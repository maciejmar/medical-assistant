import json

from src import exercises, llm
from src.database import KbDocument, Role, session_factory
from src.llm import Completion, Usage

BOOK = """# Strona 125
21 „Grot - deska” POTRZEBNE NARZĘDZIA: - CEL: precyzja ruchów celowych, poprawa wydolności
OPIS TECHNIKI: Naprzemiennie wykonywać językiem pozycję „grotu” i „deski”.
22 „Deska na dźwigu” OTRZEBNE NARZĘDZIA: - CEL: precyzja ruchów celowych
# Strona 126
OPIS TECHNIKI: Szeroki język unoszony powoli do podniebienia i opuszczany.
"""


def test_normalize_and_match_names():
    assert exercises.normalize_name("„Deska na dźwigu”") == "deska na dzwigu"
    assert exercises.normalize_name("Huśtawka 2,") == "hustawka 2"
    keys = ["deska na dzwigu", "grot deska", "glonojad", "cwiczenia oporowe dol"]
    assert exercises.best_match("„glonojad” – zassanie języka jak najdłużej", keys) == (
        "glonojad",
        1.0,
    )
    assert exercises.best_match("deska na dzwiqu", keys)[0] == "deska na dzwigu"  # błąd OCR
    assert exercises.best_match("ćwiczenia oporowe – dół", keys) == ("cwiczenia oporowe dol", 1.0)
    assert exercises.best_match("kołyska", keys) == (None, 0.0)


def test_names_from_pasted_list_skip_headings():
    text = "ROZGRZEWKA JĘZYKA\n•\t„liczenie” zębów,\n•\thuśtawka 2,\nTerapia ruchem – czynna:\n"
    assert exercises.names_from_text(text) == ["„liczenie” zębów", "huśtawka 2"]


def test_windows_overlap_so_no_exercise_is_cut():
    text = "\n".join(f"wiersz {i:04d} " + "x" * 40 for i in range(400))
    parts = exercises.windows(text, size=6000, overlap=1500)
    assert len(parts) > 2 and all(len(p) <= 6000 for p in parts)
    for previous, current in zip(parts, parts[1:], strict=False):
        assert previous[-500:] in current, "kolejne okno zaczyna się przed końcem poprzedniego"


def test_parse_and_merge_prefer_complete_description():
    raw = json.dumps(
        {
            "exercises": [
                {
                    "number": "22",
                    "name": "„Deska na dźwigu”",
                    "page": 125,
                    "goal": "precyzja",
                    "description": "",
                    "complete": False,
                },
                {"name": "", "description": "bez nazwy"},
            ]
        }
    )
    cut = exercises.parse_extraction("tekst " + raw)
    assert [e["name"] for e in cut] == ["Deska na dźwigu"]
    full = exercises.parse_extraction(
        json.dumps(
            {
                "exercises": [
                    {
                        "name": "Deska na dźwigu",
                        "page": None,
                        "goal": "precyzja",
                        "description": "Szeroki język unoszony.",
                        "complete": True,
                    }
                ]
            }
        )
    )
    merged = exercises.merge_exercises(cut + full)
    assert len(merged) == 1
    assert merged[0]["description"] == "Szeroki język unoszony."
    assert merged[0]["page"] == 125, "numer strony z uciętej wersji, gdy pełna go nie ma"
    assert exercises.parse_extraction("brak json") == []


async def _book() -> int:
    async with session_factory() as session:
        doc = KbDocument(
            title="Rehabilitacja dysfunkcji języka",
            filename="r.pdf",
            category="technique",
            audience="all",
            text=BOOK,
            status="indexed",
        )
        session.add(doc)
        await session.commit()
        await session.refresh(doc)
        return doc.id  # type: ignore[return-value]


async def test_extraction_review_and_match(client, make_headers, monkeypatch):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await make_headers("doc@example.com")
    doc_id = await _book()
    assert (await client.get("/api/admin/exercises", headers=doctor)).status_code == 403

    async def fake_llm(messages, *, user_id, operation, temperature=0.0, max_tokens=400):
        assert operation == "exercise_extraction"
        assert "# Strona 125" in messages[1]["content"]
        found = [
            {
                "number": "21",
                "name": "Grot - deska",
                "page": 125,
                "goal": "precyzja",
                "description": "Naprzemiennie grot i deska.",
                "complete": True,
            },
            {
                "number": "22",
                "name": "Deska na dźwigu",
                "page": 126,
                "goal": "precyzja",
                "description": "Szeroki język unoszony powoli do podniebienia.",
                "complete": True,
            },
        ]
        return Completion(text=json.dumps({"exercises": found}), usage=Usage(100, 50, 150))

    monkeypatch.setattr(llm, "chat_complete", fake_llm)

    candidates = (await client.get("/api/admin/exercises/candidates", headers=admin)).json()
    assert candidates[0]["document_id"] == doc_id and candidates[0]["markers"] >= 4

    started = await client.post(
        "/api/admin/exercises/extract", json={"document_ids": [doc_id]}, headers=admin
    )
    assert started.status_code == 202, started.text
    await exercises._task
    status = (await client.get("/api/admin/exercises/extract", headers=admin)).json()
    assert status["status"] == "done" and status["found"] == 2 and status["tokens"] == 150

    listing = (await client.get("/api/admin/exercises", headers=admin)).json()
    assert [e["name"] for e in listing] == ["Grot - deska", "Deska na dźwigu"]
    assert listing[1]["document_title"] == "Rehabilitacja dysfunkcji języka"

    # Poprawka administratora (sprawdzone) przetrwa ponowne wyodrębnianie.
    deska = listing[1]
    edited = await client.put(
        f"/api/admin/exercises/{deska['id']}",
        json={**deska, "description": "Opis poprawiony ręcznie.", "verified": True},
        headers=admin,
    )
    assert edited.json()["verified"] is True
    await client.post(
        "/api/admin/exercises/extract", json={"document_ids": [doc_id]}, headers=admin
    )
    await exercises._task
    listing = (await client.get("/api/admin/exercises", headers=admin)).json()
    assert len(listing) == 2
    assert next(e for e in listing if e["name"] == "Deska na dźwigu")["description"] == (
        "Opis poprawiony ręcznie."
    )

    matched = (
        await client.post(
            "/api/admin/exercises/match",
            json={"text": "•\t„deska na dźwigu”,\n•\tkołyska,"},
            headers=admin,
        )
    ).json()
    assert matched[0]["exercise"]["description"] == "Opis poprawiony ręcznie."
    assert matched[1] == {"name": "kołyska", "score": 0.0, "exercise": None}

    other = listing[0]
    assert (
        await client.delete(f"/api/admin/exercises/{other['id']}", headers=admin)
    ).status_code == 204
    assert len((await client.get("/api/admin/exercises", headers=admin)).json()) == 1
