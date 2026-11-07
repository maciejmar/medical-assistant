import os
from datetime import datetime
from pathlib import Path

import pytest
from sqlmodel import select

from src import kb_import, knowledge, ocr
from src.database import KbDocument, OcrCacheEntry, OcrPage, Role, session_factory
from src.kb_import import SourceFile, _ocr_cached, import_directory, reprocess
from src.ocr import LEGACY_TESSERACT_KEY, OcrResult, get_engine


class FakeEngine:
    """Silnik OCR do testów: liczy wywołania i zwraca tekst z nazwą silnika."""

    def __init__(self, name: str):
        self.name = name
        self.label = f"Silnik {name}"
        self.calls: list[bytes] = []

    def key(self) -> str:
        return f"{self.name}:v1"

    def read(self, data: bytes) -> OcrResult:
        self.calls.append(data)
        return OcrResult(f"Tekst ze strony odczytany silnikiem {self.name}.", 95.0, 8)


@pytest.fixture
def engines(monkeypatch):
    tesseract, vision = FakeEngine("tesseract"), FakeEngine("wizja")
    monkeypatch.setitem(ocr.ENGINES, "tesseract", tesseract)
    monkeypatch.setitem(ocr.ENGINES, "wizja", vision)
    return tesseract, vision


def _photo_tree(root: Path) -> None:
    (root / "Kurs").mkdir()
    for i, minute in enumerate((0, 1, 2)):
        path = root / "Kurs" / f"s{i}.jpg"
        path.write_bytes(f"strona-{i}".encode())
        stamp = datetime(2026, 9, 7, 9, minute).timestamp()
        os.utime(path, (stamp, stamp))
    (root / "notatki.md").write_text("Ćwiczenia oddechowe i artykulacyjne dla dzieci.", "utf-8")


def test_engine_registry():
    assert get_engine().name == "tesseract"
    assert ocr.TesseractEngine().key() == LEGACY_TESSERACT_KEY  # domyślne parametry
    with pytest.raises(ValueError, match="Nieznany silnik"):
        get_engine("nie-ma-takiego")


async def test_ocr_cache_is_per_engine_and_reuses_legacy_results(tmp_path, engines):
    tesseract, vision = engines
    image = tmp_path / "a.jpg"
    image.write_bytes(b"obraz")
    source = SourceFile(image, "a.jpg", "sha-a", datetime.min)
    async with session_factory() as session:
        session.add(OcrPage(sha256="sha-a", text="Wynik starego Tesseracta.", confidence=80))
        await session.commit()

    legacy_engine = ocr.TesseractEngine()
    legacy = await _ocr_cached(source, legacy_engine)
    assert legacy.text == "Wynik starego Tesseracta.", "stary odczyt użyty bez ponownego OCR"

    first = await _ocr_cached(source, vision)
    again = await _ocr_cached(source, vision)
    assert first.text == again.text and len(vision.calls) == 1, "drugi raz z pamięci podręcznej"
    await _ocr_cached(source, vision, force=True)
    assert len(vision.calls) == 2, "force = OCR od nowa"

    async with session_factory() as session:
        rows = (await session.exec(select(OcrCacheEntry))).all()
    assert {r.engine for r in rows} == {LEGACY_TESSERACT_KEY, "wizja:v1"}


async def test_reprocess_all_reocrs_with_new_engine_and_keeps_titles(tmp_path, fake_index, engines):
    tesseract, vision = engines
    _photo_tree(tmp_path)
    await import_directory(tmp_path)
    assert len(tesseract.calls) == 3

    async with session_factory() as session:
        course = (
            await session.exec(select(KbDocument).where(KbDocument.source_path == "Kurs/"))
        ).one()
        course.title = "Tytuł nadany w panelu"
        session.add(course)
        await session.commit()

    report = await reprocess(tmp_path, engine_name="wizja", force_ocr=True)
    assert sorted(report.updated) == ["Kurs/", "notatki.md"] and not report.failed
    assert len(vision.calls) == 3 and len(tesseract.calls) == 3

    async with session_factory() as session:
        course = (
            await session.exec(select(KbDocument).where(KbDocument.source_path == "Kurs/"))
        ).one()
    assert course.title == "Tytuł nadany w panelu"
    assert "silnikiem wizja" in course.text and course.status == "indexed"

    cached = await reprocess(tmp_path, engine_name="wizja", force_ocr=False)
    assert len(cached.updated) == 2 and len(vision.calls) == 3, "bez force – pamięć podręczna"


async def test_reprocess_single_document(tmp_path, fake_index, engines):
    tesseract, _ = engines
    _photo_tree(tmp_path)
    await import_directory(tmp_path)
    report = await reprocess(tmp_path, force_ocr=True, only={"Kurs/"})
    assert report.updated == ["Kurs/"] and len(tesseract.calls) == 6


async def test_rebuild_index_recreates_collection_and_keeps_documents_without_original(
    tmp_path, fake_index, engines, monkeypatch
):
    _photo_tree(tmp_path)
    await import_directory(tmp_path)
    async with session_factory() as session:
        session.add(
            KbDocument(
                title="Stary plik bez oryginału",
                filename="stary.md",
                category="technique",
                audience="all",
                text="Treść zapisana tylko w bazie danych.",
            )
        )
        await session.commit()

    events: list[str] = []

    async def drop_collection():
        events.append("drop")
        fake_index.clear()

    async def seed_builtin():
        events.append("seed")
        return 23

    monkeypatch.setattr(kb_import.vector_store, "drop_collection", drop_collection)
    monkeypatch.setattr(kb_import, "seed_builtin", seed_builtin)
    report = await reprocess(tmp_path, force_ocr=False, rebuild_index=True)
    assert events == ["drop", "seed"] and not report.failed
    titles = {p["title"].split(" (cz.")[0] for p in fake_index.values()}
    assert "Stary plik bez oryginału" in titles, "dokument bez oryginału odtworzony z tekstu"
    assert len({p["kb_document_id"] for p in fake_index.values()}) == 3


async def test_single_upload_keeps_original_and_import_treats_it_as_unchanged(
    client, make_headers, fake_index, tmp_path, monkeypatch
):
    monkeypatch.setattr(knowledge.settings, "kb_source_dir", str(tmp_path))
    admin = await make_headers("admin@example.com", Role.ADMIN)
    response = await client.post(
        "/api/admin/knowledge",
        data={"title": "Poradnik", "category": "technique"},
        files={
            "file": (
                "Poradnik ćwiczeń?.md",
                "Ćwiczenia języka i warg dla dzieci.".encode(),
                "text/markdown",
            )
        },
        headers=admin,
    )
    doc = response.json()
    assert response.status_code == 201, response.text
    assert doc["source_path"].startswith("pojedyncze/Poradnik ćwiczeń_-")
    assert doc["source_path"].endswith("/Poradnik ćwiczeń_.md")
    assert (tmp_path / doc["source_path"]).read_text(
        "utf-8"
    ) == "Ćwiczenia języka i warg dla dzieci."

    report = await import_directory(tmp_path)
    assert report.unchanged == [doc["source_path"]] and not report.created


async def test_reprocess_endpoints(client, make_headers, fake_index, tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge.settings, "kb_source_dir", str(tmp_path))
    started: list[dict] = []

    def fake_start(root, **options):
        started.append(options)
        return True

    from src.api import knowledge as api

    monkeypatch.setattr(api, "start_background_reprocess", fake_start)
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await make_headers("doc@example.com")

    ok = await client.post(
        "/api/admin/knowledge/reprocess",
        json={"force_ocr": True, "rebuild_index": True},
        headers=admin,
    )
    assert ok.status_code == 202
    assert started[-1]["rebuild_index"] is True and "przebudowa indeksu" in started[-1]["label"]
    assert ok.json()["ocr_engines"][0]["name"] == "tesseract"

    bad = await client.post(
        "/api/admin/knowledge/reprocess", json={"engine": "nie-ma"}, headers=admin
    )
    assert bad.status_code == 422
    assert (
        await client.post("/api/admin/knowledge/reprocess", json={}, headers=doctor)
    ).status_code == 403

    async with session_factory() as session:
        orphan = KbDocument(
            title="Bez oryginału", filename="x.md", category="technique", audience="all", text="T"
        )
        session.add(orphan)
        await session.commit()
        await session.refresh(orphan)
    no_original = await client.post(
        f"/api/admin/knowledge/{orphan.id}/reprocess", json={}, headers=admin
    )
    assert no_original.status_code == 409
