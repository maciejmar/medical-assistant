import json
from types import SimpleNamespace

import pytest
from sqlmodel import select

from src import llm, plan_advisor
from src.database import LlmCall, session_factory
from src.llm import Completion, Usage

PATIENT = {
    "first_name": "Zofia",
    "last_name": "Wiśniewska",
    "diagnosis": "Rotacyzm",
    "icd_code": "F80.0",
}
DOCS = [
    {
        "id": "a",
        "title": "Rotacyzm – etapy terapii",
        "text": "Po pionizacji języka – wibracja.",
        "score": 0.9,
    },
    {
        "id": "b",
        "title": "Badanie słuchu u dzieci",
        "text": "Audiometria przy infekcjach uszu.",
        "score": 0.5,
    },
]


def test_parse_suggestion_tolerates_code_fence_and_filters_sources():
    raw = 'Oto propozycja:\n```json\n{"kind": "diagnostics", "title": "Badanie słuchu", "description": "Audiometria.", "rationale": "Częste infekcje.", "sources": [2, 9, "x", 2]}\n```'
    parsed = plan_advisor.parse_suggestion(raw, sources_count=2)
    assert parsed == {
        "kind": "diagnostics",
        "title": "Badanie słuchu",
        "description": "Audiometria.",
        "rationale": "Częste infekcje.",
        "sources": [2],
    }
    assert plan_advisor.parse_suggestion('{"kind": "inne", "title": "X"}', 0)["kind"] == "therapy"
    with pytest.raises(ValueError):
        plan_advisor.parse_suggestion('{"kind": "therapy", "title": ""}', 0)


@pytest.fixture
def fake_rag(monkeypatch):
    calls: dict = {}

    async def fake_embed(texts, *, user_id, operation):
        calls["query"] = texts[0]
        return [[0.1, 0.2]], Usage()

    async def fake_search(query, vector, filters=None, user_id=None):
        calls["search_user"] = user_id
        return DOCS

    async def fake_rerank(query, docs, top_n=None):
        return docs

    async def fake_chat(messages, *, user_id, operation, temperature=0.0, max_tokens=400):
        calls["messages"] = messages
        calls["operation"] = operation
        return Completion(text=calls.get("answer", ""), usage=Usage(10, 5, 15))

    monkeypatch.setattr(llm, "embed", fake_embed)
    monkeypatch.setattr(plan_advisor.vector_store, "hybrid_search", fake_search)
    monkeypatch.setattr(plan_advisor.reranker, "rerank", fake_rerank)
    monkeypatch.setattr(llm, "chat_complete", fake_chat)
    return calls


async def test_suggestion_uses_patient_context_plan_notes_and_knowledge(
    client, make_headers, fake_rag
):
    doctor = await make_headers("doc@example.com")
    pid = (await client.post("/api/patients", json=PATIENT, headers=doctor)).json()["id"]
    await client.post(
        f"/api/patients/{pid}/plan/steps",
        json={"title": "Pionizacja języka", "status": "completed"},
        headers=doctor,
    )
    await client.post(
        f"/api/patients/{pid}/notes", json={"content": "Pionizacja opanowana."}, headers=doctor
    )
    fake_rag["answer"] = json.dumps(
        {
            "kind": "therapy",
            "title": "Wywoływanie wibracji",
            "description": "Ćwiczenia wibracji 3× dziennie [1].",
            "rationale": "Pionizacja zakończona.",
            "sources": [1],
        }
    )

    response = await client.post(f"/api/patients/{pid}/plan/suggest", headers=doctor)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["kind"] == "therapy" and body["title"] == "Wywoływanie wibracji"
    assert body["sources"] == [
        {"index": 1, "title": "Rotacyzm – etapy terapii", "snippet": DOCS[0]["text"]}
    ]
    assert body["grounded"] is True

    prompt = fake_rag["messages"][1]["content"]
    assert "Rozpoznanie: Rotacyzm" in prompt
    assert "1. Pionizacja języka – status: zakończony" in prompt
    assert "Pionizacja opanowana." in prompt
    assert "[1] Rotacyzm – etapy terapii" in prompt
    assert "Rotacyzm" in fake_rag["query"] and "Pionizacja języka" in fake_rag["query"]
    assert fake_rag["operation"] == "plan_suggestion"

    # Propozycja niczego nie zapisuje w planie.
    steps = (await client.get(f"/api/patients/{pid}/plan", headers=doctor)).json()["steps"]
    assert [s["title"] for s in steps] == ["Pionizacja języka"]


async def test_suggestion_errors_and_isolation(client, make_headers, fake_rag):
    doctor = await make_headers("doc@example.com")
    other = await make_headers("other@example.com")
    pid = (await client.post("/api/patients", json=PATIENT, headers=doctor)).json()["id"]

    assert (
        await client.post(f"/api/patients/{pid}/plan/suggest", headers=other)
    ).status_code == 404
    fake_rag["answer"] = "Nie wiem, co zaproponować."
    garbled = await client.post(f"/api/patients/{pid}/plan/suggest", headers=doctor)
    assert garbled.status_code == 502 and "nieczytelną" in garbled.json()["detail"]


async def test_suggestion_prompt_and_search_are_anonymized(client, make_headers, monkeypatch):
    """Prawdziwe llm.chat_complete i llm.embed – podstawiony tylko klient API: do modelu i do
    wyszukiwania nie trafia imię, nazwisko, PESEL ani telefon pacjenta (także z notatek i planu)."""
    sent: dict = {}

    async def fake_chat_create(**kwargs):
        sent["chat"] = kwargs["messages"]
        answer = {
            "kind": "therapy",
            "title": "Krok",
            "description": "Opis",
            "rationale": "",
            "sources": [],
        }
        return SimpleNamespace(
            model="m",
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(answer)))],
        )

    async def fake_embed_create(**kwargs):
        sent["embed"] = kwargs["input"]
        return SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[0.1, 0.2])], usage=None)

    async def fake_search(query, vector, filters=None, user_id=None):
        return []

    async def fake_rerank(query, docs, top_n=None):
        return []

    monkeypatch.setattr(llm.client.chat.completions, "create", fake_chat_create)
    monkeypatch.setattr(llm.client.embeddings, "create", fake_embed_create)
    monkeypatch.setattr(plan_advisor.vector_store, "hybrid_search", fake_search)
    monkeypatch.setattr(plan_advisor.reranker, "rerank", fake_rerank)

    doctor = await make_headers("doc@example.com")
    pid = (
        await client.post(
            "/api/patients",
            json={
                **PATIENT,
                "description": "Zofia Wiśniewska, tel. 600 700 800, PESEL 12345678901",
            },
            headers=doctor,
        )
    ).json()["id"]
    await client.post(
        f"/api/patients/{pid}/plan/steps",
        json={"title": "Ćwiczenia z Zofią", "description": "Mama Zofii dzwoni: 600700800"},
        headers=doctor,
    )
    await client.post(
        f"/api/patients/{pid}/notes",
        json={"content": "Zofia Wiśniewska ćwiczy pionizację, PESEL 12345678901."},
        headers=doctor,
    )

    response = await client.post(f"/api/patients/{pid}/plan/suggest", headers=doctor)
    assert response.status_code == 200, response.text
    await llm.drain_background_tasks()

    outgoing = json.dumps(sent["chat"], ensure_ascii=False) + json.dumps(
        sent["embed"], ensure_ascii=False
    )
    for secret in ("Zofi", "Wiśniewsk", "12345678901", "600 700 800", "600700800"):
        assert secret not in outgoing, f"{secret!r} wyciekło do LLM"
    assert "[IMIĘ PACJENTKI]" in outgoing and "[PESEL]" in outgoing and "[TELEFON]" in outgoing
    assert "Rozpoznanie: Rotacyzm" in outgoing, "treść kliniczna zostaje"

    async with session_factory() as session:
        logged = (await session.exec(select(LlmCall))).all()
    assert logged and all("Zofi" not in str(c.request) for c in logged), (
        "log admina też zanonimizowany"
    )
