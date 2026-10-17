from datetime import date
from types import SimpleNamespace

from sqlmodel import select

from src import llm
from src.anonymizer import Anonymizer, is_female_name
from src.api.chat import describe_patient, format_age
from src.database import LlmCall, Patient, session_factory

from .conftest import create_user


def test_patient_names_are_removed_with_inflection_and_gender():
    anonymize = Anonymizer.for_names([("Jan", "Kowalski"), ("Anna", "Nowak")])
    text = (
        "Jan Kowalski ma rotacyzm. Rozmawiałam z mamą Kowalskiego, a u Anny Nowak "
        "oraz Annie Nowakowej poprawa. jan kowalski ćwiczy."
    )
    result = anonymize(text)
    for leaked in ("Jan ", "Kowalsk", "Ann", "Nowak", "jan", "kowalski"):
        assert leaked not in result, result
    assert "[IMIĘ PACJENTA] [NAZWISKO] ma rotacyzm" in result
    assert "u [IMIĘ PACJENTKI] [NAZWISKO]" in result
    assert "mamą [NAZWISKO]" in result


def test_gender_heuristic():
    assert is_female_name("Anna") and is_female_name("Zofia Maria")
    assert not is_female_name("Jan") and not is_female_name("Kuba")


def test_pesel_phone_and_address_are_removed():
    anonymize = Anonymizer()
    text = (
        "PESEL 90010112345, tel. +48 600 123 456 lub 600-123-456, "
        "mieszka przy ul. Kwiatowej 5/12 w mieście 00-950."
    )
    assert anonymize(text) == (
        "PESEL [PESEL], tel. [TELEFON] lub [TELEFON], mieszka przy [ADRES] w mieście [ADRES]."
    )


def test_clinical_content_and_dates_are_preserved():
    anonymize = Anonymizer.for_names([("Ala", "Lis")])
    text = (
        "Wiek: 6 lat. Płeć: żeńska. Kod ICD: F80.0, ICD-11 6A01.0. Terapia od 15.03.2026, "
        "kontrola 2026-11-14. Ćwiczenia 2x dziennie po 10-15 min, 3 sesje w tygodniu. "
        "Cechy szczególne: rozszczep podniebienia operowany w wieku 14 mies., wędzidełko "
        "podcięte, ale nowa metoda działa."
    )
    assert anonymize(text) == text


def test_search_text_has_no_markers():
    anonymize = Anonymizer.for_names([("Jan", "Kowalski")])
    assert anonymize.for_search("ćwiczenia dla Jana Kowalskiego tel. 600123456 rotacyzm") == (
        "ćwiczenia dla tel. rotacyzm"
    )


def test_age_includes_months_for_children():
    assert format_age(date(2020, 6, 20), date(2026, 10, 17)) == "6 lat 3 mies. (6;3)"
    assert format_age(date(2022, 10, 17), date(2026, 10, 17)) == "4 lat 0 mies. (4;0)"
    assert format_age(date(1980, 1, 1), date(2026, 10, 17)) == "46 lat"


def test_patient_context_is_complete_but_nameless():
    description = "Cechy szczególne: " + "obniżone napięcie mięśni orofacjalnych. " * 40
    patient = Patient(
        user_id=1,
        first_name="Zofia",
        last_name="Wiśniewska",
        diagnosis="Rotacyzm",
        icd_code="F80.0",
        birth_date=date(2020, 1, 1),
        description=description,
    )
    context = describe_patient(patient)
    assert "Płeć: żeńska" in context and "Rozpoznanie: Rotacyzm" in context
    assert "Kod ICD: F80.0" in context and "Wiek: " in context
    assert description in context, "opis nie może być obcinany"
    assert "Zofia" not in context and "Wiśniewska" not in context


async def test_llm_receives_and_logs_only_anonymized_text(monkeypatch):
    doctor = await create_user("doc@example.com", "Password123!")
    other = await create_user("other@example.com", "Password123!")
    async with session_factory() as session:
        session.add(Patient(user_id=doctor.id, first_name="Zofia", last_name="Wiśniewska"))
        session.add(Patient(user_id=other.id, first_name="Obcy", last_name="Pacjentowski"))
        await session.commit()

    sent = {}

    async def fake_create(**kwargs):
        sent.update(kwargs)
        return SimpleNamespace(
            model="m",
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        )

    monkeypatch.setattr(llm.client.chat.completions, "create", fake_create)
    await llm.chat_complete(
        [{"role": "user", "content": "Co z Zofią Wiśniewską (6 lat)? PESEL 12345678901"}],
        user_id=doctor.id,
        operation="query_rewriting",
    )
    await llm.drain_background_tasks()

    content = sent["messages"][0]["content"]
    assert content == "Co z [IMIĘ PACJENTKI] [NAZWISKO] (6 lat)? PESEL [PESEL]"

    async with session_factory() as session:
        logged = (await session.exec(select(LlmCall))).one()
    assert "Zofi" not in str(logged.request) and "12345678901" not in str(logged.request)
