import json

import pytest
from sqlmodel import select

from src import goldset, graph, llm
from src.database import ChatMessage, Role, session_factory
from src.llm import Completion, Usage

from .test_chat import FakeGraph

SAMPLE = """Pytania dotyczące terapii
1. Chłopiec 4,5 roku – język i połykanie
Chłopiec nie utrzymuje pozycji spoczynkowej
języka. Często oddycha przez usta.
Od czego zacząć?

2. Tyłozgryz – plan
terapii
Jak odróżnić tyłozgryz czynnościowy od szkieletowego?

Jasne. Uporządkuję to jako „najpierw → potem”.
1. Chłopiec 4,5 roku – język
1.\tSprawdzić oddychanie i drożność nosa.
2.\tPracować nad pozycją spoczynkową języka.
3.\tWprowadzić prawidłowy wzorzec połykania.
2. Tyłozgryz – czynnościowy czy morfologiczny?
Najpierw:
1.\tObserwacja żuchwy w spoczynku.
2.\tSkierować do ortodonty.
"""


def test_parser_splits_questions_and_reference_answers():
    items = goldset.parse_goldset(SAMPLE)
    assert [i["title"] for i in items] == [
        "Chłopiec 4,5 roku – język i połykanie",
        "Tyłozgryz – plan terapii",
    ]
    assert items[0]["question"] == (
        "Chłopiec nie utrzymuje pozycji spoczynkowej języka. Często oddycha przez usta. "
        "Od czego zacząć?"
    )
    assert items[0]["reference_answer"].splitlines() == [
        "1. Sprawdzić oddychanie i drożność nosa.",
        "2. Pracować nad pozycją spoczynkową języka.",
        "3. Wprowadzić prawidłowy wzorzec połykania.",
    ]
    assert items[1]["reference_answer"].startswith("Najpierw:\n1. Obserwacja żuchwy")


AD_SAMPLE = """Pytania
1. Chłopiec 4,5 roku – język
Chłopiec nie utrzymuje pozycji języka.
Od czego zacząć?
2. Kolejność nauki połykania
Jaka powinna być kolejność?

Jasne. Uporządkuję to jako „najpierw → potem”.
ad1. Chłopiec 4,5 roku – język
1.\tSprawdzić oddychanie.
2.\tPracować nad pozycją języka
ad2. Kolejność nauki połykania

Lepsza kolejność:
1.  Najpierw: przygotowanie pozycji języka.
7.  Na końcu automatyzacja wzorca,
"""


def test_parser_accepts_ad_headings_for_answers():
    items = goldset.parse_goldset(AD_SAMPLE)
    assert [i["title"] for i in items] == ["Chłopiec 4,5 roku – język", "Kolejność nauki połykania"]
    assert items[1]["question"] == "Jaka powinna być kolejność?"  # bez wstępu „Jasne…”
    assert items[0]["reference_answer"].splitlines() == [
        "1. Sprawdzić oddychanie.",
        "2. Pracować nad pozycją języka",
    ]
    assert items[1]["reference_answer"].splitlines() == [
        "Lepsza kolejność:",
        "1. Najpierw: przygotowanie pozycji języka.",
        "7. Na końcu automatyzacja wzorca,",
    ]


def test_verdict_parsing_clamps_score():
    verdict = goldset.parse_verdict('ok {"score": 7, "missing": ["a"], "order_ok": false}')
    assert verdict["score"] == 5.0 and verdict["missing"] == ["a"] and verdict["order_ok"] is False
    assert goldset.cosine([1, 0], [1, 0]) == pytest.approx(1.0)


async def test_goldset_crud_is_admin_only(client, make_headers):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await make_headers("doc@example.com")
    assert (await client.get("/api/admin/goldset", headers=doctor)).status_code == 403

    parsed = await client.post("/api/admin/goldset/parse", json={"text": SAMPLE}, headers=admin)
    assert parsed.status_code == 200 and len(parsed.json()) == 2
    bad = await client.post("/api/admin/goldset/parse", json={"text": "bez numerów"}, headers=admin)
    assert bad.status_code == 422

    saved = await client.put("/api/admin/goldset", json={"items": parsed.json()}, headers=admin)
    assert [i["position"] for i in saved.json()] == [0, 1]
    item = saved.json()[1]
    edited = await client.put(
        f"/api/admin/goldset/{item['id']}",
        json={**{k: item[k] for k in ("title", "question")}, "reference_answer": "Nowy wzorzec"},
        headers=admin,
    )
    assert edited.json()["reference_answer"] == "Nowy wzorzec"
    await client.delete(f"/api/admin/goldset/{item['id']}", headers=admin)
    assert len((await client.get("/api/admin/goldset", headers=admin)).json()) == 1


async def test_ask_assistant_uses_rag_graph_without_saving_chat(monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(graph, "rag_graph", fake)
    reply = await goldset.ask_assistant("Pytanie testowe", user_id=1)
    assert reply == {
        "answer": "Odpowiedź [1]",
        "sources": [{"index": 1, "title": "Rotacyzm"}],
        "tokens": 28,
    }
    assert fake.states[0]["patient_context"] is None
    async with session_factory() as session:
        assert (await session.exec(select(ChatMessage))).all() == []


async def test_run_scores_answers_and_summarizes(client, make_headers, monkeypatch):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    items = goldset.parse_goldset(SAMPLE)
    await client.put("/api/admin/goldset", json={"items": items}, headers=admin)

    async def fake_ask(question, user_id):
        good = question.startswith("Chłopiec")
        return {
            "answer": "Sprawdzić nos, potem język i połykanie." if good else "Nie wiem.",
            "sources": [{"index": 1, "title": "Miofunkcje"}],
            "tokens": 100,
        }

    async def fake_judge_llm(messages, *, user_id, operation, temperature=0.0, max_tokens=400):
        assert operation == "goldset_judge"
        good = "Sprawdzić nos" in messages[1]["content"]
        verdict = {
            "score": 5 if good else 1,
            "missing": [] if good else ["ortodonta"],
            "comment": "x",
        }
        return Completion(text=json.dumps(verdict), usage=Usage(50, 20, 70))

    async def fake_embed(texts, *, user_id, operation):
        return [[1.0, 0.0], [1.0, 0.0] if "Sprawdzić" in texts[0] else [0.0, 1.0]], Usage()

    monkeypatch.setattr(goldset, "ask_assistant", fake_ask)
    monkeypatch.setattr(llm, "chat_complete", fake_judge_llm)
    monkeypatch.setattr(llm, "embed", fake_embed)

    started = await client.post("/api/admin/goldset/runs", json={"note": "test"}, headers=admin)
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    await goldset._active[run_id]
    assert (await client.post("/api/admin/goldset/runs", json={}, headers=admin)).status_code == 201

    detail = (await client.get(f"/api/admin/goldset/runs/{run_id}", headers=admin)).json()
    run = detail["run"]
    assert run["status"] == "done" and run["done"] == 2 and run["errors"] == 0
    assert run["avg_score"] == 3.0 and run["avg_similarity"] == 0.5
    assert run["total_tokens"] == 2 * (100 + 70)
    assert run["settings"]["chat_model"]
    assert [r["score"] for r in detail["results"]] == [1.0, 5.0], "najsłabsze na górze"
    assert detail["results"][0]["verdict"]["missing"] == ["ortodonta"]
    for task in list(goldset._active.values()):
        await task
