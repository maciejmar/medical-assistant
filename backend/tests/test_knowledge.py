import io
import zipfile

import pytest
from pypdf import PdfWriter

from src import knowledge
from src.database import Role
from src.knowledge import ExtractionError, chunk_text, extract_text


def _docx(paragraphs: list[str]) -> bytes:
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    xml = (
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


def _text_pdf(text: str) -> bytes:
    """Minimalny PDF z warstwą tekstową (czcionka Helvetica, jedna linia)."""
    content = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    )
    return out.getvalue()


def test_extracts_supported_formats():
    assert extract_text("Ćwiczenia oddechowe dla dzieci.\r\n".encode(), ".md") == (
        "Ćwiczenia oddechowe dla dzieci."
    )
    assert "Pionizacja" in extract_text("Pionizacja języka – ćwiczenia".encode("cp1250"), ".txt")
    docx = extract_text(_docx(["Terapia miofunkcjonalna", "Ćwiczenia warg i języka"]), ".docx")
    assert docx == "Terapia miofunkcjonalna\n\nĆwiczenia warg i języka"
    pdf = extract_text(_text_pdf("Terapia rotacyzmu u dzieci w wieku przedszkolnym"), ".pdf")
    assert "Terapia rotacyzmu" in pdf


def test_rejects_scans_and_unsupported_files():
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    with pytest.raises(ExtractionError, match="skan"):
        extract_text(buffer.getvalue(), ".pdf")
    with pytest.raises(ExtractionError, match="formaty"):
        extract_text(b"abc", ".exe")
    with pytest.raises(ExtractionError):
        extract_text(b"not a zip", ".docx")


def test_chunking_respects_size_headings_and_overlap():
    text = "\n\n".join(
        [
            "# Strona 1",
            "A" * 900,
            "Krótki akapit łączący.",
            "B" * 900,
            "# Strona 2",
            "C" * 300,
            "Zdanie pierwsze. " * 120,
        ]
    )
    chunks = chunk_text(text, 1500)
    assert all(len(c) <= 1500 for c in chunks)
    assert chunks[0].startswith("# Strona 1")
    assert any(c.startswith("# Strona 2") for c in chunks), "nagłówek zaczyna nowy fragment"
    joined = "\n\n".join(chunks)
    for marker in ("A" * 900, "B" * 900, "C" * 300, "Zdanie pierwsze."):
        assert marker in joined
    assert chunks[1].startswith("Krótki akapit łączący."), "zakładka kontekstu"


async def test_admin_uploads_lists_reindexes_and_deletes(client, make_headers, fake_index):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    text = "\n\n".join(f"# Strona {i}\n\n" + "Ćwiczenia miofunkcjonalne. " * 60 for i in range(3))
    response = await client.post(
        "/api/admin/knowledge",
        data={"title": "Notatki – terapia miofunkcjonalna", "category": "technique"},
        files={"file": ("transkrypcja.md", text.encode(), "text/markdown")},
        headers=admin,
    )
    assert response.status_code == 201, response.text
    doc = response.json()
    assert doc["status"] == "indexed" and doc["chunks"] >= 3
    assert doc["audience"] == "all" and doc["filename"] == "transkrypcja.md"
    assert len(fake_index) == doc["chunks"]
    payload = next(iter(fake_index.values()))
    assert payload["title"].startswith("Notatki – terapia miofunkcjonalna (cz. ")
    assert payload["category"] == "technique"

    listing = (await client.get("/api/admin/knowledge", headers=admin)).json()
    assert listing["builtin_documents"] > 0 and listing["documents"][0]["id"] == doc["id"]

    reindexed = await client.post(f"/api/admin/knowledge/{doc['id']}/reindex", headers=admin)
    assert reindexed.json()["status"] == "indexed" and len(fake_index) == doc["chunks"]

    assert (
        await client.delete(f"/api/admin/knowledge/{doc['id']}", headers=admin)
    ).status_code == 204
    assert fake_index == {}
    assert (await client.get("/api/admin/knowledge", headers=admin)).json()["documents"] == []


async def test_upload_validation_and_permissions(client, make_headers, fake_index):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await make_headers("doc@example.com")
    form = {"title": "Tytuł", "category": "technique"}
    file = {"file": ("a.md", "Treść dokumentu o terapii.".encode(), "text/markdown")}

    assert (
        await client.post("/api/admin/knowledge", data=form, files=file, headers=doctor)
    ).status_code == 403
    bad_category = await client.post(
        "/api/admin/knowledge", data={**form, "category": "x"}, files=file, headers=admin
    )
    assert bad_category.status_code == 422
    scan = PdfWriter()
    scan.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    scan.write(buffer)
    rejected = await client.post(
        "/api/admin/knowledge",
        data=form,
        files={"file": ("skan.pdf", buffer.getvalue(), "application/pdf")},
        headers=admin,
    )
    assert rejected.status_code == 422 and "skan" in rejected.json()["detail"]


async def test_indexing_failure_keeps_document_for_retry(
    client, make_headers, fake_index, monkeypatch
):
    async def broken_embed(texts, *, user_id, operation):
        raise RuntimeError("vLLM niedostępny")

    monkeypatch.setattr(knowledge, "embed", broken_embed)
    admin = await make_headers("admin@example.com", Role.ADMIN)
    response = await client.post(
        "/api/admin/knowledge",
        data={"title": "Tytuł", "category": "technique"},
        files={"file": ("a.md", "Treść dokumentu o terapii.".encode(), "text/markdown")},
        headers=admin,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "error" and "vLLM" in response.json()["error"]
