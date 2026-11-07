from sqlmodel import select

from src.api import chat as chat_module
from src.api import interview as interview_module
from src.database import InterviewAudio, InterviewItem, PatientInterview, Role, session_factory
from src.stt import TranscriptionError

from .test_chat import FakeGraph

PATIENT = {"first_name": "Zofia", "last_name": "Wiśniewska", "diagnosis": "Rotacyzm"}


async def _patient(client, headers) -> int:
    return (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]


def _payload(items, **answers):
    """Lista do zapisu: odpowiedzi podane jako {indeks: tekst}."""
    return {
        "items": [
            {"id": i["id"], "question": i["question"], "answer": answers.get(f"a{n}", i["answer"])}
            for n, i in enumerate(items)
        ]
    }


async def test_interview_starts_from_template_and_is_owner_scoped(client, make_headers):
    doctor = await make_headers("doc@example.com")
    other = await make_headers("other@example.com")
    pid = await _patient(client, doctor)

    response = await client.get(f"/api/patients/{pid}/interview", headers=doctor)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "draft" and body["approved_at"] is None
    assert [i["question"] for i in body["items"]] == interview_module.DEFAULT_QUESTIONS
    assert all(i["answer"] == "" and not i["has_audio"] for i in body["items"])

    assert (await client.get(f"/api/patients/{pid}/interview", headers=other)).status_code == 404
    item_id = body["items"][0]["id"]
    foreign = await client.get(
        f"/api/patients/{pid}/interview/items/{item_id}/audio", headers=other
    )
    assert foreign.status_code == 404


async def test_approval_snapshot_feeds_llm_context(client, make_headers, monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(chat_module, "rag_graph", fake)
    doctor = await make_headers("doc@example.com")
    pid = await _patient(client, doctor)
    items = (await client.get(f"/api/patients/{pid}/interview", headers=doctor)).json()["items"]

    draft = await client.put(
        f"/api/patients/{pid}/interview",
        json=_payload(items, a0="Nie wymawia głoski r"),
        headers=doctor,
    )
    assert draft.status_code == 200 and draft.json()["status"] == "draft"
    await client.post("/api/chat", json={"message": "Co dalej?", "patient_id": pid}, headers=doctor)
    assert "Wywiad" not in (fake.states[-1]["patient_context"] or ""), "szkic nie trafia do LLM"

    approved = await client.post(
        f"/api/patients/{pid}/interview/approve",
        json=_payload(items, a0="Nie wymawia głoski r", a3="Chodzenie w 11. miesiącu"),
        headers=doctor,
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved" and approved.json()["approved_at"]

    await client.post("/api/chat", json={"message": "Co dalej?", "patient_id": pid}, headers=doctor)
    context = fake.states[-1]["patient_context"]
    assert "Wywiad z pacjentem" in context
    assert f"- {items[0]['question']}\n  Odpowiedź: Nie wymawia głoski r" in context
    assert "Chodzenie w 11. miesiącu" in context
    assert items[1]["question"] not in context, "pytania bez odpowiedzi są pomijane"

    # Poprawka po zatwierdzeniu: status wraca do szkicu, LLM widzi nadal zatwierdzoną wersję.
    edited = (await client.get(f"/api/patients/{pid}/interview", headers=doctor)).json()["items"]
    changed = await client.put(
        f"/api/patients/{pid}/interview", json=_payload(edited, a0="ZMIANA"), headers=doctor
    )
    assert changed.json()["status"] == "draft"
    await client.post("/api/chat", json={"message": "Co dalej?", "patient_id": pid}, headers=doctor)
    assert "ZMIANA" not in fake.states[-1]["patient_context"]

    # Cofnięcie zmiany = treść znów zgodna z zatwierdzoną migawką.
    restored = await client.put(
        f"/api/patients/{pid}/interview",
        json=_payload(edited, a0="Nie wymawia głoski r"),
        headers=doctor,
    )
    assert restored.json()["status"] == "approved"


async def test_custom_questions_and_recordings(client, make_headers, monkeypatch):
    calls = []

    async def fake_transcribe(data, **kwargs):
        calls.append((data, kwargs))
        return "Mówi od drugiego roku życia"

    monkeypatch.setattr(interview_module, "transcribe_audio", fake_transcribe)
    doctor = await make_headers("doc@example.com")
    pid = await _patient(client, doctor)
    initial = (await client.get(f"/api/patients/{pid}/interview", headers=doctor)).json()["items"]

    added = await client.post(
        f"/api/patients/{pid}/interview/items",
        json={"question": "Czy dziecko lubi śpiewać?"},
        headers=doctor,
    )
    assert added.status_code == 201
    custom = added.json()
    assert custom["position"] == len(initial)

    url = f"/api/patients/{pid}/interview/items/{custom['id']}/audio"
    uploaded = await client.put(
        url, files={"audio": ("odp.webm", b"AUDIO-1", "audio/webm")}, headers=doctor
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["transcript"] == "Mówi od drugiego roku życia"
    assert uploaded.json()["item"]["has_audio"] is True
    assert uploaded.json()["item"]["answer"] == "", "transkrypcja nie nadpisuje odpowiedzi"
    assert calls[0][0] == b"AUDIO-1" and calls[0][1]["language"] == "pl"

    played = await client.get(url, headers=doctor)
    assert played.status_code == 200 and played.content == b"AUDIO-1"
    assert played.headers["content-type"].startswith("audio/webm")

    async def failing(*args, **kwargs):
        raise TranscriptionError("Usługa transkrypcji jest niedostępna")

    monkeypatch.setattr(interview_module, "transcribe_audio", failing)
    replaced = await client.put(
        url, files={"audio": ("odp.webm", b"AUDIO-2", "audio/webm")}, headers=doctor
    )
    assert replaced.json()["transcript"] is None and "niedostępna" in replaced.json()["error"]
    assert (await client.get(url, headers=doctor)).content == b"AUDIO-2", "nagranie zachowane"

    assert (await client.delete(url, headers=doctor)).status_code == 204
    assert (await client.get(url, headers=doctor)).status_code == 404

    removed = await client.delete(
        f"/api/patients/{pid}/interview/items/{initial[0]['id']}", headers=doctor
    )
    assert removed.status_code == 204
    questions = [
        i["question"]
        for i in (await client.get(f"/api/patients/{pid}/interview", headers=doctor)).json()[
            "items"
        ]
    ]
    assert initial[0]["question"] not in questions and questions[-1] == "Czy dziecko lubi śpiewać?"

    bad = await client.put(
        f"/api/patients/{pid}/interview",
        json={"items": [{"id": 999999, "question": "x", "answer": ""}]},
        headers=doctor,
    )
    assert bad.status_code == 404


async def test_admin_edits_template_for_new_interviews(client, make_headers):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await make_headers("doc@example.com")
    assert (await client.get("/api/admin/interview-template", headers=doctor)).status_code == 403

    first = await _patient(client, doctor)
    await client.get(f"/api/patients/{first}/interview", headers=doctor)

    saved = await client.put(
        "/api/admin/interview-template",
        json={"questions": ["  Powód   zgłoszenia? ", "", "Rozwój mowy?"]},
        headers=admin,
    )
    assert saved.status_code == 200
    assert saved.json() == {
        "questions": ["Powód zgłoszenia?", "Rozwój mowy?"],
        "is_default": False,
        "updated_at": saved.json()["updated_at"],
    }

    second = await _patient(client, doctor)
    new_items = (await client.get(f"/api/patients/{second}/interview", headers=doctor)).json()
    assert [i["question"] for i in new_items["items"]] == ["Powód zgłoszenia?", "Rozwój mowy?"]
    old_items = (await client.get(f"/api/patients/{first}/interview", headers=doctor)).json()
    assert len(old_items["items"]) == len(interview_module.DEFAULT_QUESTIONS)

    reset = await client.delete("/api/admin/interview-template", headers=admin)
    assert reset.json()["is_default"] is True
    assert reset.json()["questions"] == interview_module.DEFAULT_QUESTIONS


async def test_deleting_patient_removes_interview(client, make_headers, monkeypatch):
    async def fake_transcribe(data, **kwargs):
        return "tekst"

    monkeypatch.setattr(interview_module, "transcribe_audio", fake_transcribe)
    doctor = await make_headers("doc@example.com")
    pid = await _patient(client, doctor)
    items = (await client.get(f"/api/patients/{pid}/interview", headers=doctor)).json()["items"]
    await client.put(
        f"/api/patients/{pid}/interview/items/{items[0]['id']}/audio",
        files={"audio": ("odp.webm", b"A", "audio/webm")},
        headers=doctor,
    )
    await client.post(
        f"/api/patients/{pid}/interview/approve", json=_payload(items, a0="x"), headers=doctor
    )

    assert (await client.delete(f"/api/patients/{pid}", headers=doctor)).status_code == 204
    async with session_factory() as session:
        for model in (InterviewAudio, InterviewItem, PatientInterview):
            assert (await session.exec(select(model))).all() == []
