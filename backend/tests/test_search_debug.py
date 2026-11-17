from types import SimpleNamespace

from src import search_debug
from src.database import Role
from src.llm import Usage
from src.search_debug import focus_verdict


def _row(doc_id, score, *, candidate=False, selected=False, dense=None, sparse=None):
    return {
        "id": f"{doc_id}-{score}",
        "title": "x",
        "document_id": doc_id,
        "snippet": "",
        "score": score,
        "dense_rank": dense,
        "sparse_rank": sparse,
        "fusion_rank": None,
        "candidate": candidate,
        "selected": selected,
    }


def test_verdict_no_chunks():
    v = focus_verdict([_row(1, 0.9, candidate=True, selected=True)], 7, "Wędzidełko")
    assert v["chunks"] == 0 and "Indeksuj ponownie" in v["verdict"]


def test_verdict_selected():
    v = focus_verdict([_row(7, 0.9, candidate=True, selected=True)], 7, "Wędzidełko")
    assert "trafia do źródeł" in v["verdict"]


def test_verdict_outside_candidates_but_relevant():
    v = focus_verdict([_row(7, 0.95, dense=31, sparse=None)], 7, "Wędzidełko")
    assert "nie wszedł do" in v["verdict"]
    assert "miejsce 31" in v["verdict"] and "poza 50" in v["verdict"]
    assert "problem leży w wyszukiwaniu" in v["verdict"]


def test_verdict_outside_candidates_irrelevant():
    v = focus_verdict([_row(7, 0.001, dense=45)], 7, "Wędzidełko")
    assert "poniżej progu" in v["verdict"]


async def test_search_test_endpoint(client, make_headers, monkeypatch):
    headers = await make_headers("admin-search@example.com", Role.ADMIN)
    book = {
        "id": "b1",
        "title": "Książka (cz. 1/2)",
        "text": "frenuloplastyka",
        "kb_document_id": 1,
    }
    noise = {"id": "b2", "title": "Książka (cz. 2/2)", "text": "inne", "kb_document_id": 1}
    frenulum = {
        "id": "w1",
        "title": "Wędzidełko (cz. 1/1)",
        "text": "ankyloglosja",
        "kb_document_id": 2,
    }

    async def chat_complete(messages, **kwargs):
        return SimpleNamespace(text='{"query": "przygotowanie do frenuloplastyki", "filters": {}}')

    async def embed(texts, **kwargs):
        return [[0.1, 0.2]], Usage()

    async def hybrid_search(query, dense, *, filters=None, user_id=None, limit=None):
        return [book, noise]

    async def single_ranking(query, dense, *, using, user_id, limit):
        return ["b1", "b2", "w1"] if using == "dense" else ["b1"]

    async def document_chunks(document_id):
        return [frenulum] if document_id == 2 else []

    async def score(query, docs):
        scores = {"b1": 0.9, "b2": 0.001, "w1": 0.8}
        out = [{**d, "score": scores[d["id"]]} for d in docs]
        return sorted(out, key=lambda d: d["score"], reverse=True)

    monkeypatch.setattr(search_debug.llm, "chat_complete", chat_complete)
    monkeypatch.setattr(search_debug.llm, "embed", embed)
    monkeypatch.setattr(search_debug.vector_store, "hybrid_search", hybrid_search)
    monkeypatch.setattr(search_debug.vector_store, "single_ranking", single_ranking)
    monkeypatch.setattr(search_debug.vector_store, "document_chunks", document_chunks)
    monkeypatch.setattr(search_debug.reranker, "score", score)

    async def fake_get(session, document_id, admin):
        return SimpleNamespace(title="Wędzidełko"), None

    monkeypatch.setattr("src.api.knowledge._get", fake_get)

    response = await client.post(
        "/api/admin/knowledge/search-test",
        json={"question": "jak wygląda przygotowanie do zabiegu?", "document_id": 2},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["rewritten_query"] == "przygotowanie do frenuloplastyki"
    rows = {r["id"]: r for r in data["rows"]}
    assert rows["b1"]["selected"] and rows["b1"]["candidate"]
    assert not rows["b2"]["selected"]  # poniżej progu
    assert not rows["w1"]["candidate"] and rows["w1"]["dense_rank"] == 3
    assert data["focus"]["title"] == "Wędzidełko"
    assert "problem leży w wyszukiwaniu" in data["focus"]["verdict"]


async def test_search_test_requires_admin(client, make_headers):
    headers = await make_headers("doc-search@example.com")
    response = await client.post(
        "/api/admin/knowledge/search-test", json={"question": "pytanie"}, headers=headers
    )
    assert response.status_code == 403
