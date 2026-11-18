"""Materiały bazy wiedzy (wgrane w panelu lub zaimportowane z katalogu): odczyt tekstu, podział
na fragmenty, indeksowanie w Qdrant (te same wektory gęste + rzadkie co dokumenty wbudowane).

Obsługiwane formaty: .pdf, .docx, .odt, .md, .txt oraz zdjęcia stron (.jpg/.png… – OCR druku,
src.ocr). PDF: warstwa tekstowa + OCR tekstu z osadzonych ilustracji (KB_PDF_IMAGE_OCR); PDF bez
tekstu nawet po OCR jest odrzucany.
"""

import asyncio
import hashlib
import io
import logging
import re
import zipfile
from collections.abc import Callable
from xml.etree import ElementTree

from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlmodel import col, select

from .config import settings
from .database import KbDocument, KbPrivateDocument, session_factory, utcnow
from .llm import embed
from .ocr import IMAGE_EXTENSIONS, OcrUnavailableError, get_engine, ocr_embedded_image
from .seed import document_id, embedding_text
from .vector_store import OWNER_FIELD, vector_store

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


_GLUED_WORD_CHARS = 25
_IMAGE_TEXT_MARKER = "[Tekst z ilustracji]"


def glued_ratio(text: str) -> float:
    """Udział „słów” sklejonych z kilku (≥25 liter bez spacji; adresy WWW się nie liczą) –
    objaw warstwy tekstowej PDF bez spacji między wyrazami."""
    words = text.split()
    if not words:
        return 0.0
    glued = sum(
        1 for w in words if len(w) >= _GLUED_WORD_CHARS and "/" not in w and "http" not in w.lower()
    )
    return glued / len(words)


def _page_text(page) -> str:
    """Tekst strony; gdy słowa są posklejane, próbuje trybu układu (layout) pypdf, który
    wylicza spacje z pozycji znaków – wybiera wariant z mniejszą liczbą sklejeń."""
    plain = (page.extract_text() or "").strip()
    if glued_ratio(plain) < 0.02:
        return plain
    try:
        layout = page.extract_text(extraction_mode="layout") or ""
    except Exception:  # tryb layout bywa zawodny przy nietypowych czcionkach
        return plain
    layout = re.sub(r"[ \t]{2,}", " ", layout)
    layout = "\n".join(line.strip() for line in layout.splitlines() if line.strip())
    return layout if glued_ratio(layout) < glued_ratio(plain) else plain


def _page_image_texts(page, seen: set[str], budget: list[int]) -> list[str]:
    """OCR ilustracji strony (pomija małe, powtarzające się – np. logo na każdym slajdzie –
    i te bez rozpoznanego druku)."""
    texts: list[str] = []
    try:
        images = list(page.images)
    except Exception as exc:
        logger.info("Nie udało się odczytać obrazków strony PDF: %s", exc)
        return texts
    for image in images:
        if budget[0] <= 0:
            break
        try:
            width, height = image.image.size
            data = image.data
        except Exception:
            continue
        if min(width, height) < settings.kb_pdf_image_min_px:
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        budget[0] -= 1
        try:
            result = ocr_embedded_image(data)
        except OcrUnavailableError:
            raise
        except Exception as exc:
            logger.info("OCR ilustracji w PDF nie powiódł się: %s", exc)
            continue
        if len(result.text) >= 20:
            texts.append(result.text)
    return texts


def _pdf_text(data: bytes) -> str:
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ExtractionError("PDF jest zaszyfrowany – zdejmij hasło i wgraj ponownie.")
        seen: set[str] = set()
        budget = [settings.kb_pdf_image_max]
        pages: list[str] = []
        for page in reader.pages:
            parts = [_page_text(page)]
            if settings.kb_pdf_image_ocr:
                for text in _page_image_texts(page, seen, budget):
                    parts.append(f"{_IMAGE_TEXT_MARKER}\n{text}")
            pages.append("\n\n".join(p for p in parts if p))
    except PdfReadError as exc:
        raise ExtractionError(f"Nie udało się odczytać pliku PDF: {exc}") from exc
    except OcrUnavailableError:  # brak tesseracta – sama warstwa tekstowa
        logger.warning("OCR ilustracji w PDF niedostępny – brak programu tesseract")
        pages = [_page_text(page) for page in reader.pages]
    text = "\n\n".join(p for p in pages if p)
    if len(text) < _MIN_CHARS_PER_PDF_PAGE * max(1, len(pages)):
        raise ExtractionError(
            "PDF nie zawiera tekstu do odczytania (skan, którego OCR nie rozpoznał). Wgraj zdjęcia "
            "stron jako obrazy albo wykonaj transkrypcję do pliku .md."
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
    result = get_engine().read(data)
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


async def document_owner(document_id: int) -> int | None:
    """Właściciel dokumentu prywatnego; None = wiedza wspólna."""
    async with session_factory() as session:
        row = await session.get(KbPrivateDocument, document_id)
        return row.owner_id if row else None


async def document_owners() -> dict[int, int]:
    async with session_factory() as session:
        rows = (await session.exec(select(KbPrivateDocument))).all()
        return {r.document_id: r.owner_id for r in rows}


async def set_document_owner(document_id: int, owner_id: int | None) -> None:
    """Ustawia widoczność: owner_id = prywatny dla tego konta, None = wspólny dla wszystkich."""
    async with session_factory() as session:
        row = await session.get(KbPrivateDocument, document_id)
        if owner_id is None:
            if row is not None:
                await session.delete(row)
        elif row is None:
            session.add(KbPrivateDocument(document_id=document_id, owner_id=owner_id))
        else:
            row.owner_id = owner_id
            session.add(row)
        await session.commit()


def _payload(doc: KbDocument, chunk: str, index: int, total: int, owner_id: int | None) -> dict:
    title = doc.title if total == 1 else f"{doc.title} (cz. {index}/{total})"
    payload = {
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
    if owner_id is not None:  # brak pola = fragment wspólny (filtr widoczności w wyszukiwaniu)
        payload[OWNER_FIELD] = owner_id
    return payload


ChunkProgress = Callable[[int, int], None]  # (fragmenty gotowe, fragmenty łącznie)


async def index_document(doc: KbDocument, on_progress: ChunkProgress | None = None) -> int:
    """(Re)indeksuje dokument w Qdrant; zwraca liczbę fragmentów."""
    chunks = chunk_text(doc.text, settings.kb_chunk_chars)
    owner_id = await document_owner(doc.id)  # type: ignore[arg-type]
    await vector_store.delete_kb_document(doc.id)  # type: ignore[arg-type]
    total = len(chunks)
    if on_progress:
        on_progress(0, total)
    for start in range(0, total, _BATCH):
        payloads = [
            _payload(doc, chunk, start + i + 1, total, owner_id)
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
        if on_progress:
            on_progress(min(start + _BATCH, total), total)
    return total


async def index_and_record(doc: KbDocument, on_progress: ChunkProgress | None = None) -> KbDocument:
    """Indeksuje i zapisuje wynik (status/błąd) w bazie – błąd vLLM/Qdrant nie gubi pliku."""
    try:
        doc.chunks = await index_document(doc, on_progress)
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
