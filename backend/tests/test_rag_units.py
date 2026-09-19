from src.api import audio as audio_module
from src.graph.edges import build_graph, route_after_rerank, route_after_rewrite
from src.graph.nodes import build_answer_messages, parse_rewrite_output
from src.graph.state import merge_usage
from src.seed import document_id, embedding_text
from src.seed_data import DOCUMENTS
from src.vector_store import build_filter, sparse_vector


def test_parse_rewrite_output_valid_and_sanitised():
    raw = (
        'Oto wynik: {"query": "terapia rotacyzmu u dzieci F80.0", "needs_retrieval": true, '
        '"filters": {"category": "technique", "audience": "hacker"}}'
    )
    parsed = parse_rewrite_output(raw, "jak leczyć r?")
    assert parsed["query"] == "terapia rotacyzmu u dzieci F80.0"
    assert parsed["filters"] == {"category": "technique"}
    assert parsed["needs_retrieval"] is True


def test_parse_rewrite_output_falls_back_on_garbage():
    for raw in ("", "nie json", "{zły json}", "[1, 2]"):
        parsed = parse_rewrite_output(raw, "pytanie")
        assert parsed == {"query": "pytanie", "needs_retrieval": True, "filters": {}}


def test_sparse_vector_is_deterministic_and_stemmed():
    a = sparse_vector("Rotacyzm u dzieci")
    b = sparse_vector("rotacyzmu dziecka")
    assert a.indices == sorted(a.indices)
    assert len(a.indices) == len(a.values)
    assert set(a.indices) & set(b.indices), "prefiksowy stemming powinien łączyć odmiany"
    assert sparse_vector("Rotacyzm").indices == sparse_vector("rotacyzm").indices


def test_build_filter_only_accepts_known_values():
    assert build_filter(None) is None
    assert build_filter({"category": "x", "audience": "y"}) is None
    flt = build_filter({"category": "technique", "audience": "adults"})
    assert flt is not None and len(flt.must) == 2


def test_routing_and_usage_reducer():
    assert route_after_rewrite({"needs_retrieval": False}) == "generate_without_context"
    assert route_after_rewrite({"needs_retrieval": True}) == "retrieve"
    assert route_after_rerank({"documents": []}) == "generate_without_context"
    assert route_after_rerank({"documents": [{"title": "t"}]}) == "generate"
    merged = merge_usage(
        {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30},
    )
    assert merged == {"prompt_tokens": 11, "completion_tokens": 22, "total_tokens": 33}
    assert build_graph() is not None


def test_answer_messages_contain_sources_and_no_patient_name():
    state = {
        "question": "Jak ćwiczyć?",
        "history": [{"role": "user", "content": "wcześniej"}],
        "documents": [{"title": "Rotacyzm", "text": "Opis", "icd10": "F80.0", "icd11": "6A01.0"}],
        "patient_context": "Wiek: 6 lat",
        "needs_retrieval": True,
    }
    messages = build_answer_messages(state, grounded=True)
    assert messages[0]["role"] == "system" and messages[-1]["role"] == "user"
    assert "[1] Rotacyzm (ICD-10: F80.0, ICD-11: 6A01.0)" in messages[-1]["content"]
    assert "Wiek: 6 lat" in messages[-1]["content"]
    ungrounded = build_answer_messages({**state, "documents": []}, grounded=False)
    assert "Nie znaleziono w bazie wiedzy" in ungrounded[0]["content"]


def test_seed_dataset_is_complete_and_unique():
    keys = [d["key"] for d in DOCUMENTS]
    assert len(keys) == len(set(keys))
    assert len({document_id(k) for k in keys}) == len(keys)
    text = " ".join(d["title"].lower() for d in DOCUMENTS)
    for term in ("rotacyzm", "afazja", "dyzartria", "jąkanie"):
        assert term in text
    assert {"disorder", "icd", "technique"} <= {d["category"] for d in DOCUMENTS}
    assert {"children", "adults"} <= {d["audience"] for d in DOCUMENTS}
    assert any(d["icd10"] == "F80.0" and d["icd11"] == "6A01.0" for d in DOCUMENTS)
    assert "F80.0" in embedding_text(DOCUMENTS[0])


async def test_transcribe_endpoint(client, make_headers, monkeypatch):
    captured = {}

    async def fake_transcribe(data, *, filename, content_type, language, user_id):
        captured.update(size=len(data), filename=filename, language=language, user_id=user_id)
        return "Pacjent poprawnie wymawia głoskę r."

    monkeypatch.setattr(audio_module, "transcribe_audio", fake_transcribe)
    headers = await make_headers("a@example.com")

    ok = await client.post(
        "/api/audio/transcribe",
        files={"audio": ("nagranie.webm", b"\x1aE\xdf\xa3dane", "audio/webm")},
        headers=headers,
    )
    assert ok.status_code == 200
    assert ok.json() == {"text": "Pacjent poprawnie wymawia głoskę r."}
    assert captured["filename"] == "nagranie.webm" and captured["language"] == "pl"

    wrong_type = await client.post(
        "/api/audio/transcribe",
        files={"audio": ("x.exe", b"MZ", "application/octet-stream")},
        headers=headers,
    )
    assert wrong_type.status_code == 415

    empty = await client.post(
        "/api/audio/transcribe", files={"audio": ("a.wav", b"", "audio/wav")}, headers=headers
    )
    assert empty.status_code == 400

    anonymous = await client.post(
        "/api/audio/transcribe", files={"audio": ("a.wav", b"abc", "audio/wav")}
    )
    assert anonymous.status_code == 401
