from types import SimpleNamespace

from src import llm
from src.anonymizer import Anonymizer
from src.database import LlmCall, Patient, session_factory

from .conftest import create_user


def test_patient_names_are_removed_with_inflection():
    anonymize = Anonymizer.for_names([("Jan", "Kowalski"), ("Anna", "Nowak")])
    text = (
        "Jan Kowalski ma rotacyzm. Rozmawiałam z mamą Kowalskiego, a u Anny Nowak "
        "oraz Annie Nowakowej poprawa. jan kowalski ćwiczy."
    )
    result = anonymize(text)
    for leaked in ("Jan", "Kowalsk", "Ann", "Nowak", "jan", "kowalski"):
        assert leaked not in result, result
    assert "[IMIĘ] [NAZWISKO] ma rotacyzm" in result
    assert "mamą [NAZWISKO]" in result


def test_identifiers_are_removed():
    anonymize = Anonymizer()
    text = (
        "PESEL 90010112345, tel. +48 600 123 456 lub 600-123-456, mail jan.k@example.com, "
        "mieszka przy ul. Kwiatowej 5/12 w mieście 00-950, dowód ABC123456, "
        "urodzony 01.01.2018, wizyta 2026-03-15, konto 61 1090 1014 0000 0712 1981 2874."
    )
    result = anonymize(text)
    for leaked in (
        "90010112345",
        "600",
        "example.com",
        "Kwiatowej",
        "00-950",
        "ABC123456",
        "01.01.2018",
        "2026-03-15",
        "1090",
    ):
        assert leaked not in result, result
    assert "w mieście" in result, "adres nie może pochłaniać dalszej części zdania"


def test_clinical_content_is_preserved():
    anonymize = Anonymizer.for_names([("Ala", "Lis")])
    text = (
        "Wiek: 6 lat. Kod ICD: F80.0, ICD-11 6A01.0. Ćwiczenia 2x dziennie po 10-15 min, "
        "ale nowa metoda działa."
    )
    assert anonymize(text) == text


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
        [{"role": "user", "content": "Co z Zofią Wiśniewską? PESEL 12345678901"}],
        user_id=doctor.id,
        operation="query_rewriting",
    )
    await llm.drain_background_tasks()

    content = sent["messages"][0]["content"]
    assert content == "Co z [IMIĘ] [NAZWISKO]? PESEL [PESEL]"

    async with session_factory() as session:
        from sqlmodel import select

        logged = (await session.exec(select(LlmCall))).one()
    assert "Zofi" not in str(logged.request) and "12345678901" not in str(logged.request)
