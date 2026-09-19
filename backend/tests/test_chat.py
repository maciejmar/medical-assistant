import json

from src.api import chat as chat_module


class FakeGraph:
    def __init__(self):
        self.states = []

    async def astream(self, state, stream_mode):
        assert stream_mode == "custom"
        self.states.append(state)
        yield {"type": "status", "stage": "rewrite"}
        yield {"type": "sources", "sources": [{"index": 1, "title": "Rotacyzm"}]}
        yield {"type": "token", "text": "Odpo"}
        yield {"type": "token", "text": "wiedź [1]"}
        yield {"type": "usage", "prompt_tokens": 20, "completion_tokens": 8, "total_tokens": 28}


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_chat_streams_events_and_persists(client, make_headers, monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(chat_module, "rag_graph", fake)
    headers = await make_headers("a@example.com")

    response = await client.post("/api/chat", json={"message": "Jak ćwiczyć r?"}, headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [e for e, _ in events] == [
        "meta",
        "status",
        "sources",
        "token",
        "token",
        "usage",
        "done",
    ]
    conversation_id = events[0][1]["conversation_id"]
    assert fake.states[0]["question"] == "Jak ćwiczyć r?"

    history = await client.get(f"/api/chat/conversations/{conversation_id}", headers=headers)
    messages = history.json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["content"] == "Odpowiedź [1]"
    assert messages[1]["total_tokens"] == 28
    assert messages[1]["sources"][0]["title"] == "Rotacyzm"

    listing = (await client.get("/api/chat/conversations", headers=headers)).json()
    assert listing[0]["conversation_id"] == conversation_id and listing[0]["message_count"] == 2

    follow_up = await client.post(
        "/api/chat",
        json={"message": "A u dorosłych?", "conversation_id": conversation_id},
        headers=headers,
    )
    assert follow_up.status_code == 200
    assert [m["role"] for m in fake.states[1]["history"]] == ["user", "assistant"]


async def test_chat_isolated_between_doctors(client, make_headers, monkeypatch):
    monkeypatch.setattr(chat_module, "rag_graph", FakeGraph())
    headers_x = await make_headers("x@example.com")
    headers_y = await make_headers("y@example.com")
    events = parse_sse(
        (await client.post("/api/chat", json={"message": "Pytanie"}, headers=headers_x)).text
    )
    conversation_id = events[0][1]["conversation_id"]

    assert (
        await client.get(f"/api/chat/conversations/{conversation_id}", headers=headers_y)
    ).status_code == 404
    assert (await client.get("/api/chat/conversations", headers=headers_y)).json() == []
    hijack = await client.post(
        "/api/chat",
        json={"message": "x", "conversation_id": conversation_id},
        headers=headers_y,
    )
    assert hijack.status_code == 404


async def test_chat_rejects_foreign_patient(client, make_headers, monkeypatch):
    monkeypatch.setattr(chat_module, "rag_graph", FakeGraph())
    headers_x = await make_headers("x@example.com")
    headers_y = await make_headers("y@example.com")
    pid = (
        await client.post(
            "/api/patients", json={"first_name": "A", "last_name": "B"}, headers=headers_x
        )
    ).json()["id"]
    response = await client.post(
        "/api/chat", json={"message": "Pytanie", "patient_id": pid}, headers=headers_y
    )
    assert response.status_code == 404
