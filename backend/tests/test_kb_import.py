import io
import os
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

from sqlmodel import select

from src import kb_import, knowledge, ocr
from src.database import KbDocument, OcrPage, Role, session_factory
from src.kb_import import (
    ImportReport,
    SourceFile,
    import_directory,
    plan_units,
    split_sessions,
    title_from_text,
)
from src.knowledge import extract_text
from src.ocr import OcrResult, lines_from_data


def _odt(paragraphs: list[str], heading: str) -> bytes:
    ns = 'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"'
    body = f"<text:h>{heading}</text:h>" + "".join(
        f'<text:p>{p}<text:s text:c="2"/>koniec<text:line-break/>linia</text:p>' for p in paragraphs
    )
    xml = f'<office:document-content xmlns:office="urn:x" {ns}><office:body>{body}</office:body></office:document-content>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("content.xml", xml)
    return buffer.getvalue()


def test_odt_extraction_keeps_headings_and_spacing():
    text = extract_text(_odt(["Ćwiczenia warg"], "Mioterapia"), ".odt")
    assert text == "# Mioterapia\n\nĆwiczenia warg  koniec\nlinia"


def test_ocr_keeps_confident_printed_lines_only():
    data = {
        "text": ["Jak", "budować", "plan", "", "bazgroł", "xq", "ok", "Zasada:", "mięśnie"],
        "conf": [95, 91, 88, -1, 20, 15, 70, 90, 85],
        "block_num": [1, 1, 1, 1, 1, 1, 1, 2, 2],
        "par_num": [1, 1, 1, 1, 1, 1, 1, 1, 1],
        "line_num": [1, 1, 1, 1, 2, 2, 2, 1, 1],
    }
    result = lines_from_data(data, min_confidence=60)
    assert result.text == "Jak budować plan\n\nZasada: mięśnie"
    assert result.words == 5 and result.confidence > 85


def test_best_rotation_picks_most_confident_orientation(monkeypatch):
    class FakeImage:
        def __init__(self, angle=0):
            self.angle = angle

        def rotate(self, angle, expand):
            return FakeImage((self.angle + angle) % 360)

    def fake_read(image):
        good = image.angle == 270
        return OcrResult("tekst", 90.0 if good else 30.0, 40 if good else 3)

    monkeypatch.setattr(ocr, "_read", fake_read)
    assert ocr.best_rotation(FakeImage()) == 270


def test_sessions_split_on_time_gaps():
    start = datetime(2026, 9, 7, 9, 0)
    files = [
        SourceFile(Path(f"{i}.jpg"), f"{i}.jpg", str(i), start + timedelta(minutes=m))
        for i, m in enumerate([0, 2, 5, 50, 52, 200])
    ]
    sessions = split_sessions(files, timedelta(minutes=30))
    assert [len(s) for s in sessions] == [3, 2, 1]


def test_title_from_text():
    assert title_from_text("12\nREHABILITACJA DYSFUNKCJI JĘZYKA\n...", "x") == (
        "Rehabilitacja dysfunkcji języka"
    )
    assert title_from_text("1 2 3", "Zapasowy") == "Zapasowy"


def _write_image(path: Path, payload: bytes, minute: int) -> None:
    path.write_bytes(payload)
    stamp = datetime(2026, 9, 7, 9, minute).timestamp()
    os.utime(path, (stamp, stamp))


def _build_tree(root: Path) -> None:
    (root / "book").mkdir(parents=True)
    (root / "notatki.md").write_text("# Notatki\n\nĆwiczenia oddechowe dla dzieci.", "utf-8")
    (root / "notatki-kopia.md").write_text("# Notatki\n\nĆwiczenia oddechowe dla dzieci.", "utf-8")
    _write_image(root / "book" / "a.jpg", b"strona-1", 0)
    _write_image(root / "book" / "b.jpg", b"strona-2", 1)
    _write_image(root / "a-duplikat.jpg", b"strona-1", 0)
    _write_image(root / "luzem-1.jpg", b"luzem-1", 10)
    _write_image(root / "luzem-2.jpg", b"luzem-2", 59)


def test_plan_groups_folders_sessions_and_skips_duplicates(tmp_path):
    _build_tree(tmp_path)
    report = ImportReport()
    units = plan_units(tmp_path, report)
    by_path = {u.source_path: u for u in units}
    assert set(by_path) == {"book/", "notatki-kopia.md", "#luzem-1.jpg", "#luzem-2.jpg"}
    assert [f.relative for f in by_path["book/"].files] == ["book/a.jpg", "book/b.jpg"]
    assert report.duplicates == 2  # kopia .md i zdjęcie z katalogu głównego


async def test_import_is_idempotent_and_reacts_to_changes(tmp_path, fake_index, monkeypatch):
    _build_tree(tmp_path)
    calls: list[bytes] = []

    def fake_ocr(data: bytes) -> OcrResult:
        calls.append(data)
        text = (
            "REHABILITACJA DYSFUNKCJI JĘZYKA\n\nĆwiczenia pionizacji języka."
            if data == b"strona-1"
            else "Ćwiczenia warg i mięśni okrężnych ust."
        )
        return OcrResult(text, 90.0, 10)

    monkeypatch.setattr(kb_import, "ocr_image", fake_ocr)
    first = await import_directory(tmp_path)
    assert len(first.created) == 4 and not first.failed, first.failed
    assert len(calls) == 4  # każde unikalne zdjęcie raz

    async with session_factory() as session:
        book = (
            await session.exec(select(KbDocument).where(KbDocument.source_path == "book/"))
        ).one()
        cached = (await session.exec(select(OcrPage))).all()
    assert book.title == "Rehabilitacja dysfunkcji języka" and book.pages == 2
    assert "# Strona 2" in book.text and book.status == "indexed"
    assert len(cached) == 4
    assert any(p["kb_document_id"] == book.id for p in fake_index.values())

    second = await import_directory(tmp_path)
    assert len(second.unchanged) == 4 and not second.created and len(calls) == 4

    _write_image(tmp_path / "book" / "c.jpg", b"strona-3", 2)
    third = await import_directory(tmp_path)
    assert third.updated == ["book/"] and len(calls) == 5  # OCR tylko nowej strony


async def test_admin_edits_metadata_and_import_endpoint(
    client, make_headers, fake_index, tmp_path, monkeypatch
):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    created = await client.post(
        "/api/admin/knowledge",
        data={"title": "Stary tytuł", "category": "technique"},
        files={"file": ("a.md", "Treść dokumentu o terapii.".encode(), "text/markdown")},
        headers=admin,
    )
    doc_id = created.json()["id"]
    patched = await client.patch(
        f"/api/admin/knowledge/{doc_id}",
        json={"title": "Nowy tytuł", "category": "disorder", "audience": "children", "tags": "x"},
        headers=admin,
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Nowy tytuł" and patched.json()["audience"] == "children"
    assert all(p["title"] == "Nowy tytuł" for p in fake_index.values())

    monkeypatch.setattr(knowledge.settings, "kb_source_dir", str(tmp_path / "brak"))
    status = (await client.get("/api/admin/knowledge/import", headers=admin)).json()
    assert status["source_available"] is False and status["running"] is False
    assert (await client.post("/api/admin/knowledge/import", headers=admin)).status_code == 409


def test_safe_target_rejects_paths_outside_directory(tmp_path):
    from src.kb_import import UnsafePathError, safe_target

    ok = safe_target(tmp_path, "Logopeda-17-10-2026/IMG_5936.jpeg")
    assert ok == tmp_path / "Logopeda-17-10-2026" / "IMG_5936.jpeg"
    assert safe_target(tmp_path, "Materiały (ąę)\slajd 1.png").name == "slajd 1.png"
    for bad in (
        "../etc/passwd.txt",
        "a/../../x.md",
        "/abs.md",
        ".ukryty/x.md",
        "a/b/c/d/e.md",
        "skrypt.sh",
        "x|y.md",
    ):
        try:
            safe_target(tmp_path, bad)
        except UnsafePathError:
            continue
        raise AssertionError(f"ścieżka przepuszczona: {bad}")


def test_store_file_is_atomic_and_detects_unchanged(tmp_path):
    from src.kb_import import store_file

    assert store_file(tmp_path, "Nowy/a.md", b"tresc") == ("Nowy/a.md", True)
    assert store_file(tmp_path, "Nowy/a.md", b"tresc") == ("Nowy/a.md", False)
    assert store_file(tmp_path, "Nowy/a.md", b"nowa tresc") == ("Nowy/a.md", True)
    assert (tmp_path / "Nowy" / "a.md").read_bytes() == b"nowa tresc"
    assert [p.name for p in (tmp_path / "Nowy").iterdir()] == ["a.md"], "bez plików tymczasowych"


def test_text_duplicates_keep_shallowest_copy_and_hidden_files_are_ignored(tmp_path):
    (tmp_path / "Logopeda-18").mkdir()
    (tmp_path / "artykul.md").write_text("Treść artykułu o mioterapii.", "utf-8")
    (tmp_path / "Logopeda-18" / "artykul.md").write_text("Treść artykułu o mioterapii.", "utf-8")
    (tmp_path / "Logopeda-18" / ".upload-123.part").write_bytes(b"w trakcie")
    report = ImportReport()
    units = plan_units(tmp_path, report)
    assert [u.source_path for u in units] == ["artykul.md"] and report.duplicates == 1


def test_auto_import_waits_for_stable_directory(tmp_path):
    from src.kb_import import directory_fingerprint, should_auto_import

    first = directory_fingerprint(tmp_path)
    (tmp_path / "nowy.md").write_text("Nowy materiał.", "utf-8")
    second = directory_fingerprint(tmp_path)
    assert first != second
    assert not should_auto_import(second, first, imported=first)  # pliki jeszcze się kopiują
    assert should_auto_import(second, second, imported=first)  # stabilny i zmieniony
    assert not should_auto_import(second, second, imported=second)  # już zaimportowany


async def test_folder_upload_endpoint(client, make_headers, tmp_path, monkeypatch):
    monkeypatch.setattr(knowledge.settings, "kb_source_dir", str(tmp_path))
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await make_headers("doc@example.com")

    def upload(headers, path, data=b"\x89PNG obraz"):
        return client.post(
            "/api/admin/knowledge/files",
            data={"relative_path": path},
            files={"file": ("x", data, "application/octet-stream")},
            headers=headers,
        )

    saved = await upload(admin, "Logopeda-17-10-2026/IMG_1.png")
    assert saved.status_code == 201 and saved.json() == {
        "path": "Logopeda-17-10-2026/IMG_1.png",
        "changed": True,
    }
    assert (tmp_path / "Logopeda-17-10-2026" / "IMG_1.png").read_bytes() == b"\x89PNG obraz"
    assert (await upload(admin, "Logopeda-17-10-2026/IMG_1.png")).json()["changed"] is False
    assert (await upload(admin, "../poza.png")).status_code == 422
    assert (await upload(doctor, "Logopeda/IMG_2.png")).status_code == 403
