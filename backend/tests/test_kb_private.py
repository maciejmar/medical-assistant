from sqlmodel import select

from src import knowledge
from src.database import KbDocument, KbPrivateDocument, Role, User, session_factory
from src.kb_import import ImportReport, import_directory, plan_units

from .conftest import create_user, login_headers


async def _upload(client, headers, title, visibility):
    response = await client.post(
        "/api/admin/knowledge",
        data={"title": title, "category": "technique", "visibility": visibility},
        files={
            "file": (f"{title}.md", f"Treść: {title}. Ćwiczenia języka.".encode(), "text/markdown")
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _payloads(fake_index, document_id):
    return [p for p in fake_index.values() if p["kb_document_id"] == document_id]


async def test_private_knowledge_is_hidden_from_other_admins(client, make_headers, fake_index):
    first = await make_headers("a@example.com", Role.ADMIN)
    second = await make_headers("b@example.com", Role.ADMIN)

    private = await _upload(client, first, "Moje notatki", "private")
    shared = await _upload(client, second, "Wspólny poradnik", "shared")
    assert private["visibility"] == "private" and shared["visibility"] == "shared"

    async with session_factory() as session:
        owner = (await session.exec(select(User).where(User.email == "a@example.com"))).one()
    assert all(p["owner_id"] == owner.id for p in _payloads(fake_index, private["id"]))
    assert all("owner_id" not in p for p in _payloads(fake_index, shared["id"]))

    titles = lambda r: {d["title"] for d in r.json()["documents"]}  # noqa: E731
    assert titles(await client.get("/api/admin/knowledge", headers=first)) == {
        "Moje notatki",
        "Wspólny poradnik",
    }
    assert titles(await client.get("/api/admin/knowledge", headers=second)) == {"Wspólny poradnik"}

    doc_url = f"/api/admin/knowledge/{private['id']}"
    patch = {"title": "Przejęte", "category": "technique", "audience": "all"}
    assert (await client.patch(doc_url, json=patch, headers=second)).status_code == 404
    assert (await client.post(f"{doc_url}/reindex", headers=second)).status_code == 404
    assert (await client.delete(doc_url, headers=second)).status_code == 404
    assert (await client.delete(doc_url, headers=first)).status_code == 204
    assert _payloads(fake_index, private["id"]) == []


async def test_visibility_can_be_changed(client, make_headers, fake_index):
    admin = await make_headers("a@example.com", Role.ADMIN)
    other = await make_headers("b@example.com", Role.ADMIN)
    doc = await _upload(client, admin, "Poradnik", "shared")
    url = f"/api/admin/knowledge/{doc['id']}"
    body = {"title": "Poradnik", "category": "technique", "audience": "all"}

    made_private = await client.patch(url, json={**body, "visibility": "private"}, headers=admin)
    assert made_private.json()["visibility"] == "private"
    assert all("owner_id" in p for p in _payloads(fake_index, doc["id"]))
    assert (await client.get(url.rsplit("/", 1)[0], headers=other)).json()["documents"] == []

    unchanged = await client.patch(url, json=body, headers=admin)  # bez pola – widoczność bez zmian
    assert unchanged.json()["visibility"] == "private"

    shared_again = await client.patch(url, json={**body, "visibility": "shared"}, headers=admin)
    assert shared_again.json()["visibility"] == "shared"
    assert all("owner_id" not in p for p in _payloads(fake_index, doc["id"]))


async def test_private_folder_upload_goes_to_owner_directory(
    client, make_headers, tmp_path, monkeypatch
):
    monkeypatch.setattr(knowledge.settings, "kb_source_dir", str(tmp_path))
    admin = await make_headers("a@example.com", Role.ADMIN)
    async with session_factory() as session:
        admin_id = (await session.exec(select(User.id).where(User.email == "a@example.com"))).one()

    def upload(path, visibility):
        return client.post(
            "/api/admin/knowledge/files",
            data={"relative_path": path, "visibility": visibility},
            files={"file": ("x", b"Notatki prywatne.", "text/markdown")},
            headers=admin,
        )

    private = await upload("Moje/notatki.md", "private")
    assert private.json()["path"] == f"prywatne/{admin_id}/Moje/notatki.md"
    assert (tmp_path / "prywatne" / str(admin_id) / "Moje" / "notatki.md").is_file()
    assert (await upload("Wspólne/notatki.md", "shared")).json()["path"] == "Wspólne/notatki.md"
    reserved = await upload("prywatne/999/podszycie.md", "shared")
    assert reserved.status_code == 422


async def test_import_marks_private_directory_and_dedupes_per_scope(tmp_path, fake_index):
    owner = await create_user("owner@example.com", "Password123!", Role.ADMIN)
    (tmp_path / "prywatne" / str(owner.id) / "Kurs").mkdir(parents=True)
    (tmp_path / "prywatne" / "999").mkdir(parents=True)
    content = "Ćwiczenia pionizacji języka – materiał kursowy."
    (tmp_path / "wspolne.md").write_text(content, "utf-8")
    (tmp_path / "prywatne" / str(owner.id) / "Kurs" / "kopia.md").write_text(content, "utf-8")
    (tmp_path / "prywatne" / "999" / "sierota.md").write_text("Materiał bez konta.", "utf-8")

    units = {u.source_path: u for u in plan_units(tmp_path, ImportReport())}
    assert units["wspolne.md"].owner_id is None
    assert units[f"prywatne/{owner.id}/Kurs/kopia.md"].owner_id == owner.id

    report = await import_directory(tmp_path)
    assert sorted(report.created) == sorted(["wspolne.md", f"prywatne/{owner.id}/Kurs/kopia.md"])
    assert report.failed == ["prywatne/999/sierota.md: konto #999 nie istnieje"]

    async with session_factory() as session:
        docs = {d.source_path: d for d in (await session.exec(select(KbDocument))).all()}
        private_doc = docs[f"prywatne/{owner.id}/Kurs/kopia.md"]
        link = await session.get(KbPrivateDocument, private_doc.id)
    assert link is not None and link.owner_id == owner.id
    assert await session_get_owner(docs["wspolne.md"].id) is None


async def session_get_owner(document_id):
    async with session_factory() as session:
        row = await session.get(KbPrivateDocument, document_id)
        return row.owner_id if row else None


async def test_deleting_account_removes_its_private_knowledge(client, make_headers, fake_index):
    root = await make_headers("root@example.com", Role.ADMIN)
    leaving = await create_user("leaving@example.com", "Password123!", Role.ADMIN)
    leaving_headers = await login_headers(client, "leaving@example.com", "Password123!")
    private = await _upload(client, leaving_headers, "Prywatne", "private")
    shared = await _upload(client, leaving_headers, "Wspólne", "shared")

    assert (await client.delete(f"/api/admin/users/{leaving.id}", headers=root)).status_code == 204
    async with session_factory() as session:
        remaining = {d.id: d for d in (await session.exec(select(KbDocument))).all()}
    assert private["id"] not in remaining and _payloads(fake_index, private["id"]) == []
    assert remaining[shared["id"]].uploaded_by is None
