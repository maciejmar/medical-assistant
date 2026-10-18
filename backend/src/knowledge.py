"""Materiały bazy wiedzy (wgrane w panelu lub zaimportowane z katalogu): odczyt tekstu, podział
na fragmenty, indeksowanie w Qdrant (te same wektory gęste + rzadkie co dokumenty wbudowane).

Obsługiwane formaty: .pdf (z warstwą tekstową), .docx, .odt, .md, .txt oraz zdjęcia stron
(.jpg/.png… – OCR druku, src.ocr). Skany PDF bez tekstu są odrzucane – zdjęcia stron należy
wgrać jako obrazy (import katalogu) albo wcześniej wykonać transkrypcję do .md.
"""

import asyncio
import io
import logging
import re
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlmodel import col, select

from .config import settings
from .database import KbDocument, session_factory, utcnow
from .llm import embed
from .ocr import IMAGE_EXTENSIONS, ocr_image
from .seed import document_id, embedding_text
from .vector_store import vector_store

logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {".pdf", ".docx", ".odt", ".md", ".txt"}
SUPPORTED_EXTENSIONS = TEXT_EXTENSIONS | IMAGE_EXTENSIONS
_BATCH = 16
_MIN_CHARS_PER_PDF_PAGE = 40
_MAX_XML_BYTES = 50 * 1024 * 1024
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_ODT_TEXT = "{urn:oasis:names:tc:opendocument:xmlns:text:1.0}"


class ExtractionError(ValueError):
    pass


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("PDF jest zaszyfrowany – zdejmij hasło i wgraj ponownie.")
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except PdfReadError as exc:
        raise ExtractionError(f"Nie udało się odczytać pliku PDF: {exc}") from exc
    text = "\n\n".join(p for p in pages if p)
    if len(text) < _MIN_CHARS_PER_PDF_PAGE * max(1, len(pages)):
        raise ExtractionError(
            "PDF nie zawiera warstwy tekstowej (to prawdopodobnie skan). Wykonaj transkrypcję "
            "(np. skryptem logop.py) i wgraj wynikowy plik .md."
        )
    return text


def _zipped_xml(data: bytes, member: str, label: str) -> ElementTree.Element:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            info = archive.getinfo(member)
            if info.file_size > _MAX_XML_BYTES:
                raise ExtractionError(f"Dokument {label} jest zbyt duży.")
            return ElementTree.fromstring(archive.read(info))
    except (zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ExtractionError(f"Nie udało się odczytać pliku {label}.") from exc


def _odt_inline(element: ElementTree.Element) -> str:
    parts = [element.text or ""]
    for child in element:
        if child.tag == f"{_ODT_TEXT}tab":
            parts.append("\t")
        elif child.tag == f"{_ODT_TEXT}line-break":
            parts.append("\n")
        elif child.tag == f"{_ODT_TEXT}s":  # ciąg spacji
            parts.append(" " * int(child.get(f"{_ODT_TEXT}c", "1")))
        else:
            parts.append(_odt_inline(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _odt_text(data: bytes) -> str:
    root = _zipped_xml(data, "content.xml", "ODT")
    blocks = []
    for node in root.iter():
        if node.tag in (f"{_ODT_TEXT}p", f"{_ODT_TEXT}h"):
            text = _odt_inline(node).strip()
            if text:
                blocks.append(f"# {text}" if node.tag == f"{_ODT_TEXT}h" else text)
    return "\n\n".join(blocks)


def _image_text(data: bytes) -> str:
    result = ocr_image(data)
    if len(result.text) < 20:
        raise ExtractionError("Na zdjęciu nie rozpoznano drukowanego tekstu.")
    return result.text


def _docx_text(data: bytes) -> str:
    root = _zipped_xml(data, "word/document.xml", "DOCX")
    paragraphs = []
    for paragraph in root.iter(f"{_W}p"):
        parts = []
        for node in paragraph.iter():
            if node.tag == f"{_W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                parts.append("\n")
        paragraphs.append("".join(parts))
    # Pusty akapit w Wordzie = odstęp; zachowujemy go, bo wyznacza granice fragmentów.
    return "\n\n".join(p for p in paragraphs if p.strip())


def _plain_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1250"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ExtractionError("Nie rozpoznano kodowania pliku tekstowego (zapisz go jako UTF-8).")


def extract_text(data: bytes, extension: str) -> str:
    """Tekst z pliku. Dla zdjęć uruchamia OCR (blokujące) – w kodzie async wołać w wątku."""
    if extension not in SUPPORTED_EXTENSIONS:
        raise ExtractionError("Obsługiwane formaty: PDF (z tekstem), DOCX, ODT, MD, TXT, JPG, PNG.")
    if extension == ".pdf":
        text = _pdf_text(data)
    elif extension == ".docx":
        text = _docx_text(data)
    elif extension == ".odt":
        text = _odt_text(data)
    elif extension in IMAGE_EXTENSIONS:
        text = _image_text(data)
    else:
        text = _plain_text(data)
    text = re.sub(r"[ \t]+\n", "\n", text.replace("\r\n", "\n"))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 20:
        raise ExtractionError("Plik nie zawiera tekstu do zaindeksowania.")
    return text


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?…])\s+", paragraph)
    pieces: list[str] = []
    current = ""
    for sentence in sentences:
        while len(sentence) > max_chars:  # zdanie dłuższe niż fragment – cięcie twarde
            if current:
                pieces.append(current)
                current = ""
            pieces.append(sentence[:max_chars])
            sentence = sentence[max_chars:]
        if current and len(current) + 1 + len(sentence) > max_chars:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


def chunk_text(text: str, max_chars: int) -> list[str]:
    """Fragmenty do ~max_chars znaków, cięte po akapitach; nagłówek (#) zaczyna nowy fragment,
    a krótki ostatni akapit poprzedniego fragmentu jest powtarzany jako zakładka kontekstu."""
    pieces: list[str] = []
    for paragraph in re.split(r"\n\s*\n", text):
        paragraph = paragraph.strip()
        if paragraph:
            pieces.extend(
                _split_long(paragraph, max_chars) if len(paragraph) > max_chars else [paragraph]
            )

    chunks: list[str] = []
    current: list[str] = []
    for piece in pieces:
        size = sum(len(p) + 2 for p in current)
        starts_section = piece.startswith("#") and size > max_chars // 2
        if current and (size + len(piece) > max_chars or starts_section):
            chunks.append("\n\n".join(current))
            last = current[-1]
            overlap = (
                not starts_section
                and len(last) <= max_chars // 4
                and len(last) + 2 + len(piece) <= max_chars
            )
            current = [last] if overlap else []
        current.append(piece)
    if current:
        chunks.append("\n\n".join(current))
    return chunks


def _payload(doc: KbDocument, chunk: str, index: int, total: int) -> dict:
    title = doc.title if total == 1 else f"{doc.title} (cz. {index}/{total})"
    return {
        "key": f"kb-{doc.id}-{index}",
        "title": title,
        "text": chunk,
        "category": doc.category,
        "audience": doc.audience,
        "icd10": doc.icd10,
        "icd11": doc.icd11,
        "tags": doc.tags,
        "kb_document_id": doc.id,
        "filename": doc.filename,
    }


async def index_document(doc: KbDocument) -> int:
    """(Re)indeksuje dokument w Qdrant; zwraca liczbę fragmentów."""
    chunks = chunk_text(doc.text, settings.kb_chunk_chars)
    await vector_store.delete_kb_document(doc.id)  # type: ignore[arg-type]
    total = len(chunks)
    for start in range(0, total, _BATCH):
        payloads = [
            _payload(doc, chunk, start + i + 1, total)
            for i, chunk in enumerate(chunks[start : start + _BATCH])
        ]
        texts = [embedding_text(p) for p in payloads]
        vectors, _ = await embed(texts, user_id=None, operation="kb_embedding")
        await vector_store.ensure_collection(len(vectors[0]))
        await vector_store.upsert(
            [
                (document_id(p["key"]), vector, text, p)
                for p, vector, text in zip(payloads, vectors, texts, strict=True)
            ]
        )
    return total


async def index_and_record(doc: KbDocument) -> KbDocument:
    """Indeksuje i zapisuje wynik (status/błąd) w bazie – błąd vLLM/Qdrant nie gubi pliku."""
    try:
        doc.chunks = await index_document(doc)
        doc.status, doc.error, doc.indexed_at = "indexed", None, utcnow()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("Indeksowanie dokumentu bazy wiedzy #%s nie powiodło się", doc.id)
        doc.status, doc.error = "error", f"{type(exc).__name__}: {exc}"[:1000]
    async with session_factory() as session:
        merged = await session.merge(doc)  # doc może pochodzić z sesji żądania HTTP
        await session.commit()
        await session.refresh(merged)
    return merged


async def reindex_uploaded() -> int:
    """Odtwarza w Qdrant wszystkie wgrane pliki (po zasileniu pustej bazy lub --force)."""
    async with session_factory() as session:
        docs = list((await session.exec(select(KbDocument).order_by(col(KbDocument.id)))).all())
    for doc in docs:
        await index_and_record(doc)
    if docs:
        logger.info("Odtworzono w indeksie %d wgranych plików bazy wiedzy", len(docs))
    return len(docs)
