from src import templates
from src.api import chat as chat_module
from src.database import KbDocument, KbExercise, Role, session_factory
from src.graph.nodes import build_answer_messages

from .test_chat import FakeGraph, parse_sse

PATIENT = {"first_name": "Jan", "last_name": "Kowalski", "diagnosis": "Zaburzenia miofunkcjonalne"}


async def _catalog() -> None:
    """Katalog z dwoma ćwiczeniami z bazy etapu 2."""
    async with session_factory() as session:
        doc = KbDocument(
            title="Rehabilitacja dysfunkcji języka",
            filename="r.pdf",
            category="technique",
            audience="all",
            text="x",
            status="indexed",
        )
        session.add(doc)
        await session.flush()
        for name, page in (("Glonojad", 100), ("Huśtawka", 98)):
            session.add(
                KbExercise(
                    document_id=doc.id,
                    name=name,
                    key=name.lower().replace("ś", "s"),
                    page=page,
                    goal="sprawność języka",
                    description=f"Opis ćwiczenia {name}.",
                )
            )
        await session.commit()


def test_exercise_names_are_bullet_lines():
    names = templates.template_exercise_names(templates.STAGE_2)
    assert names[0] == "„liczenie” zębów"
    assert "huśtawka 2" in names and "„dzióbek w kółko”" in names
    assert not any(n.startswith(("Cel", "Organizacja", "Pola")) for n in names)
    assert len(templates.template_exercise_names(templates.STAGE_4)) == 38


async def test_seed_is_idempotent_and_permissions(client, make_headers):
    assert await templates.seed_templates() == 4
    assert await templates.seed_templates() == 0
    doctor = await make_headers("doc@example.com")
    other = await make_headers("other@example.com")
    admin = await make_headers("admin@example.com", Role.ADMIN)

    shared = (await client.get("/api/templates", headers=doctor)).json()
    assert [t["name"] for t in shared] == [
        "Etap 1 · Napięcie",
        "Etap 2 · Wydolność",
        "Etap 3 · Siła",
        "Etap 4 · Funkcja",
    ]
    assert all(t["shared"] and not t["editable"] for t in shared)
    stage2 = shared[1]

    body = {"name": "Mój etap", "body": "• glonojad", "requires_patient": True}
    assert (
        await client.put(f"/api/templates/{stage2['id']}", json=body, headers=doctor)
    ).status_code == 403
    assert (
        await client.post("/api/templates", json={**body, "shared": True}, headers=doctor)
    ).status_code == 403

    own = (await client.post("/api/templates", json=body, headers=doctor)).json()
    assert own["shared"] is False and own["editable"] is True
    copy = (await client.post(f"/api/templates/{stage2['id']}/copy", headers=doctor)).json()
    assert copy["name"] == "Etap 2 · Wydolność (moja)" and copy["body"] == stage2["body"]
    names = [t["name"] for t in (await client.get("/api/templates", headers=doctor)).json()]
    assert names[-2:] == ["Etap 2 · Wydolność (moja)", "Mój etap"] or set(names[-2:]) == {
        "Etap 2 · Wydolność (moja)",
        "Mój etap",
    }
    assert len((await client.get("/api/templates", headers=other)).json()) == 4, "prywatne"

    # Administrator edytuje wspólne; usunięcie startowego tylko je ukrywa.
    edited = await client.put(
        f"/api/templates/{stage2['id']}", json={**body, "name": "Etap 2 · Wydolność"}, headers=admin
    )
    assert edited.status_code == 200 and edited.json()["body"] == "• glonojad"
    assert (
        await client.delete(f"/api/templates/{shared[0]['id']}", headers=admin)
    ).status_code == 204
    assert len((await client.get("/api/templates", headers=other)).json()) == 3
    assert await templates.seed_templates() == 0, "ukryty szablon startowy nie wraca"


async def test_coverage_and_chat_with_template(client, make_headers, monkeypatch):
    await templates.seed_templates()
    await _catalog()
    doctor = await make_headers("doc@example.com")
    stage2 = (await client.get("/api/templates", headers=doctor)).json()[1]

    coverage = (
        await client.post(
            "/api/templates/coverage",
            json={
                "body": "Rozgrzewka:\n• „glonojad” (zassanie języka jak najdłużej przy odwiedzionej żuchwie)\n• niania"
            },
            headers=doctor,
        )
    ).json()
    assert coverage[0]["found"] is True and coverage[0]["exercise_name"] == "Glonojad"
    assert coverage[0]["source"] == "Rehabilitacja dysfunkcji języka, s. 100"
    assert coverage[1] == {"name": "niania", "found": False, "exercise_name": "", "source": ""}

    fake = FakeGraph()
    monkeypatch.setattr(chat_module, "rag_graph", fake)
    message = {"message": "Przygotuj plan: Etap 2 · Wydolność", "template_id": stage2["id"]}
    no_patient = await client.post("/api/chat", json=message, headers=doctor)
    assert no_patient.status_code == 422
    assert "wymaga wybrania pacjenta" in no_patient.json()["detail"]

    patient_id = (await client.post("/api/patients", json=PATIENT, headers=doctor)).json()["id"]
    response = await client.post(
        "/api/chat", json={**message, "patient_id": patient_id}, headers=doctor
    )
    assert response.status_code == 200
    state = fake.states[0]
    assert state["template"]["name"] == "Etap 2 · Wydolność" and state["template"]["long_answer"]
    titles = [d["title"] for d in state["template_documents"]]
    assert titles == [
        "Ćwiczenie: Huśtawka (Rehabilitacja dysfunkcji języka, s. 98)",
        "Ćwiczenie: Glonojad (Rehabilitacja dysfunkcji języka, s. 100)",
    ]
    assert (
        "„niania” (żuchwa w odwiedzeniu, język szeroki, sylaba „ńia”)" in state["template_missing"]
    )

    # Kontekst modelu: zasady szablonu, treść szablonu, lista ćwiczeń bez opisu.
    messages = build_answer_messages(
        {**state, "documents": state["template_documents"]}, grounded=True
    )
    assert "WYŁĄCZNIE ćwiczenia/techniki z bazy podanej w szablonie" in messages[0]["content"]
    assert "Szablon „Etap 2 · Wydolność”" in messages[-1]["content"]
    assert "bez opisu w bazie wiedzy" in messages[-1]["content"]
    assert "[1] Ćwiczenie: Huśtawka" in messages[-1]["content"]

    conversation_id = parse_sse(response.text)[0][1]["conversation_id"]
    history = (
        await client.get(f"/api/chat/conversations/{conversation_id}", headers=doctor)
    ).json()
    assert history[0]["template_name"] == "Etap 2 · Wydolność"
    assert history[1]["template_name"] is None
    assert (
        await client.delete(f"/api/chat/conversations/{conversation_id}", headers=doctor)
    ).status_code == 204
