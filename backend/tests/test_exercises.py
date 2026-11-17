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
        0.95,
    )
    assert exercises.best_match("deska na dzwiqu", keys)[0] == "deska na dzwigu"  # błąd OCR
    assert exercises.best_match("ćwiczenia oporowe – dół", keys) == ("cwiczenia oporowe dol", 1.0)
    assert exercises.best_match("kołyska", keys) == (None, 0.0)


def test_match_prefers_full_name_and_rejects_generic_hits():
    """Przypadki z pierwszego przebiegu na prawdziwym katalogu."""
    catalog = [
        "Ćwiczenia oporowe",  # nadgnykowe – nie dla „czubka języka”
        "Ćwiczenia oporowe - dół",
        "Dzióbek",
        "Dzióbek z oporem horyzontalnie",
        "Huśtawka",
        "Grot",
        "Ćwiczenie Shakera",
        "Ćwiczenie Shakera (wersja pierwsza)",
        "Ćwiczenie Shakera (wersja druga)",
        "Stymulacja punktowa (zewnętrzna)",
        "Rozluznienie podstawy czaszki z rozciągnięciem odcinka szyjnego",
        "Koparka",
    ]
    keys = [exercises.normalize_name(exercises.clean_name(c)) for c in catalog]

    def hit(name: str) -> str | None:
        key = exercises.best_match(name, keys)[0]
        return catalog[keys.index(key)] if key else None

    assert hit("„dzióbek” z oporem horyzontalnym") == "Dzióbek z oporem horyzontalnie"
    assert hit("ćwiczenie Shakera – wersja 2") == "Ćwiczenie Shakera (wersja druga)"
    assert hit("ćwiczenie Shakera – wersja 1") == "Ćwiczenie Shakera (wersja pierwsza)"
    assert hit("rozluźnienie podstawy czaszki z delikatnym rozciągnięciem odcinka szyjnego") == (
        "Rozluznienie podstawy czaszki z rozciągnięciem odcinka szyjnego"
    )
    assert hit("„koparka” – ruch wymiatająco-rozcierający w kierunku dolnym") == "Koparka"
    # Lepiej „brak” niż błędne ćwiczenie:
    assert hit("ćwiczenia oporowe – czubek języka") is None
    assert hit("huśtawka 2") is None
    assert hit("„grot” na boki") is None
    assert hit("stymulacja punktowa zewnętrzna mięśni żwaczy") is None


def test_clean_name_from_ocr():
    assert exercises.clean_name("Połykanie z cienką s. Połykanie z cienką słomką") == (
        "Połykanie z cienką słomką"
    )
    assert exercises.clean_name("Pionizacja - „winda") == "Pionizacja - winda"
    assert exercises.clean_name("Pompka. Pompka") == "Pompka"


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
    assert matched[1] == {"name": "kołyska", "score": 0.0, "alias": False, "exercise": None}

    # Nazwa z promptu lekarza przypisana ręcznie do ćwiczenia z katalogu (alias).
    grot = next(e for e in listing if e["name"] == "Grot - deska")
    aliased = await client.post(
        f"/api/admin/exercises/{grot['id']}/aliases",
        json={"name": "naprzemienny grot"},
        headers=admin,
    )
    assert aliased.status_code == 200, aliased.text
    assert aliased.json()["verified"] is True
    assert [a["alias"] for a in aliased.json()["aliases"]] == ["naprzemienny grot"]
    hit = (
        await client.post(
            "/api/admin/exercises/match", json={"text": "• „naprzemienny grot”"}, headers=admin
        )
    ).json()[0]
    assert (
        hit["alias"] is True and hit["score"] == 1.0 and hit["exercise"]["name"] == "Grot - deska"
    )
    # Ćwiczenie z aliasem przetrwa ponowne wyodrębnianie (jest sprawdzone).
    await client.post(
        "/api/admin/exercises/extract", json={"document_ids": [doc_id]}, headers=admin
    )
    await exercises._task
    listing = (await client.get("/api/admin/exercises", headers=admin)).json()
    assert next(e for e in listing if e["name"] == "Grot - deska")["aliases"]
    alias_id = aliased.json()["aliases"][0]["id"]
    assert (
        await client.delete(f"/api/admin/exercises/aliases/{alias_id}", headers=admin)
    ).status_code == 204

    assert (
        await client.delete(f"/api/admin/exercises/{grot['id']}", headers=admin)
    ).status_code == 204
    assert len((await client.get("/api/admin/exercises", headers=admin)).json()) == 1
