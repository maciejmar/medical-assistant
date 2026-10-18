"""Baza wiedzy w panelu administratora: wgrywanie plików, import katalogu, edycja, usuwanie."""

import asyncio
from pathlib import Path, PurePath
from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlmodel import col, select

from ..auth import CurrentAdmin, SessionDep
from ..config import settings
from ..database import KbDocument
from ..kb_import import UnsafePathError, job, start_background_import, store_file
from ..knowledge import ExtractionError, extract_text, index_and_record
from ..ocr import OcrUnavailableError
from ..seed_data import DOCUMENTS
from ..vector_store import vector_store
from .schemas import (
    KbDocumentOut,
    KbDocumentPatch,
    KbImportProgressOut,
    KbImportStatusOut,
    KbStoredFileOut,
    KnowledgeBaseOut,
)

router = APIRouter(prefix="/admin/knowledge", tags=["admin"])

Category = Literal["disorder", "icd", "technique", "diagnostics"]
Audience = Literal["children", "adults", "all"]


def _out(doc: KbDocument) -> KbDocumentOut:
    return KbDocumentOut.model_validate(
        {
            **doc.model_dump(exclude={"text"}),
            "characters": len(doc.text),
            "preview": doc.text[:400],
        }
    )


async def _get(session: SessionDep, document_id: int) -> KbDocument:
    doc = (await session.exec(select(KbDocument).where(KbDocument.id == document_id))).first()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono dokumentu")
    return doc


@router.get("", response_model=KnowledgeBaseOut)
async def list_documents(session: SessionDep, admin: CurrentAdmin) -> KnowledgeBaseOut:
    docs = await session.exec(select(KbDocument).order_by(col(KbDocument.created_at).desc()))
    return KnowledgeBaseOut(
        builtin_documents=len(DOCUMENTS), documents=[_out(d) for d in docs.all()]
    )


@router.post("", response_model=KbDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    session: SessionDep,
    admin: CurrentAdmin,
    file: Annotated[UploadFile, File(description="PDF (z tekstem), DOCX, MD lub TXT")],
    title: Annotated[str, Form(min_length=2, max_length=300)],
    category: Annotated[Category, Form()],
    audience: Annotated[Audience, Form()] = "all",
    icd10: Annotated[str, Form(max_length=50)] = "",
    icd11: Annotated[str, Form(max_length=50)] = "",
    tags: Annotated[str, Form(max_length=500)] = "",
) -> KbDocumentOut:
    filename = PurePath(file.filename or "dokument.txt").name
    data = await file.read(settings.kb_max_upload_bytes + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plik jest pusty")
    if len(data) > settings.kb_max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Plik jest zbyt duży")
    try:
        # Zdjęcia przechodzą przez OCR (kilka sekund CPU) – poza pętlą zdarzeń.
        text = await asyncio.to_thread(extract_text, data, PurePath(filename).suffix.lower())
    except ExtractionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except OcrUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    doc = KbDocument(
        title=title.strip(),
        filename=filename,
        category=category,
        audience=audience,
        icd10=icd10.strip(),
        icd11=icd11.strip(),
        tags=tags.strip(),
        text=text,
        uploaded_by=admin.id,
    )
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return _out(await index_and_record(doc))


def _import_status() -> KbImportStatusOut:
    p = job.progress
    progress = KbImportProgressOut(
        phase=p.phase,  # type: ignore[arg-type]
        fraction=round(p.fraction, 4),
        elapsed_seconds=p.elapsed_seconds,
        eta_seconds=p.eta_seconds,
        units_total=p.units_total,
        units_done=p.units_done,
        unchanged=p.unchanged,
        created=p.created,
        updated=p.updated,
        failed=p.failed,
        unit_title=p.unit_title,
        unit_path=p.unit_path,
        unit_kind=p.unit_kind,
        step_done=p.step_done,
        step_total=p.step_total,
        recent=p.recent,  # type: ignore[arg-type]
    )
    return KbImportStatusOut(
        source_dir=settings.kb_source_dir,
        source_available=Path(settings.kb_source_dir).is_dir(),
        running=job.running,
        started_at=job.started_at,
        finished_at=job.finished_at,
        progress=progress,
        summary=job.summary,
        failed=job.failed,
        error=job.error,
        trigger=job.trigger,
        auto_scan_seconds=settings.kb_scan_interval_seconds,
    )


@router.post("/files", response_model=KbStoredFileOut, status_code=status.HTTP_201_CREATED)
async def store_source_file(
    admin: CurrentAdmin,
    file: Annotated[UploadFile, File()],
    relative_path: Annotated[str, Form(min_length=1, max_length=600)],
) -> KbStoredFileOut:
    """Zapisuje plik (np. z wgrywanego folderu) w katalogu bazy wiedzy na serwerze.
    Indeksowanie wykonuje import katalogu (uruchamiany po wgraniu lub automatycznie)."""
    root = Path(settings.kb_source_dir)
    if not root.is_dir():
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Katalog {settings.kb_source_dir} jest niedostępny."
        )
    data = await file.read(settings.kb_max_upload_bytes + 1)
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Plik jest pusty")
    if len(data) > settings.kb_max_upload_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Plik jest zbyt duży")
    try:
        path, changed = await asyncio.to_thread(store_file, root, relative_path, data)
    except UnsafePathError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, f"Nie udało się zapisać pliku: {exc}"
        ) from exc
    return KbStoredFileOut(path=path, changed=changed)


@router.get("/import", response_model=KbImportStatusOut)
async def import_status(admin: CurrentAdmin) -> KbImportStatusOut:
    return _import_status()


@router.post("/import", response_model=KbImportStatusOut, status_code=status.HTTP_202_ACCEPTED)
async def start_import(admin: CurrentAdmin) -> KbImportStatusOut:
    """Synchronizuje katalog KB_SOURCE_DIR w tle: dodaje nowe i zmienione materiały."""
    if not Path(settings.kb_source_dir).is_dir():
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Katalog {settings.kb_source_dir} jest niedostępny – sprawdź wolumen /kb.",
        )
    if not start_background_import(Path(settings.kb_source_dir)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Import już trwa")
    return _import_status()


@router.patch("/{document_id}", response_model=KbDocumentOut)
async def update_document(
    document_id: int, body: KbDocumentPatch, session: SessionDep, admin: CurrentAdmin
) -> KbDocumentOut:
    """Zmiana tytułu/metadanych – fragmenty w Qdrant są indeksowane ponownie (tytuł w źródłach)."""
    doc = await _get(session, document_id)
    for name, value in body.model_dump().items():
        setattr(doc, name, value.strip() if isinstance(value, str) else value)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return _out(await index_and_record(doc))


@router.post("/{document_id}/reindex", response_model=KbDocumentOut)
async def reindex_document(
    document_id: int, session: SessionDep, admin: CurrentAdmin
) -> KbDocumentOut:
    return _out(await index_and_record(await _get(session, document_id)))


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: int, session: SessionDep, admin: CurrentAdmin) -> Response:
    doc = await _get(session, document_id)
    try:
        await vector_store.delete_kb_document(document_id)
    except Exception as exc:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Nie udało się usunąć fragmentów z Qdrant – dokument pozostawiono, spróbuj ponownie.",
        ) from exc
    await session.delete(doc)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
