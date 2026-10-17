from src import mailer
from src.database import Role

from .conftest import create_user, login_headers

PATIENT = {"first_name": "Jan", "last_name": "Kowalski", "diagnosis": "Rotacyzm"}


async def _patient_with_account(client, doctor_headers) -> int:
    pid = (await client.post("/api/patients", json=PATIENT, headers=doctor_headers)).json()["id"]
    linked = await client.put(
        f"/api/patients/{pid}/account",
        json={"email": "Jan@Example.com", "password": "Pacjent123!"},
        headers=doctor_headers,
    )
    assert linked.status_code == 200, linked.text
    assert linked.json()["email"] == "jan@example.com"
    return pid


async def test_doctor_creates_account_and_patient_sees_portal(client, make_headers, monkeypatch):
    sent: list[tuple[str, str, str]] = []

    async def fake_send(recipient, subject, body):
        sent.append((recipient, subject, body))

    monkeypatch.setattr(mailer, "send_email", fake_send)
    doctor = await make_headers("doc@example.com")
    pid = await _patient_with_account(client, doctor)
    await client.post(
        f"/api/patients/{pid}/notes", json={"content": "NOTATKA LEKARZA"}, headers=doctor
    )

    rec = await client.post(
        f"/api/patients/{pid}/recommendations",
        json={"title": "Ćwiczenia", "content": "Pionizacja języka 2x dziennie", "notify": True},
        headers=doctor,
    )
    assert rec.status_code == 201
    assert sent and sent[0][0] == "jan@example.com" and "Ćwiczenia" in sent[0][1]

    patient = await login_headers(client, "jan@example.com", "Pacjent123!")
    portal = await client.get("/api/portal/me", headers=patient)
    assert portal.status_code == 200
    body = portal.json()
    assert body["diagnosis"] == "Rotacyzm"
    assert body["doctor_email"] == "doc@example.com"
    assert body["recommendations"][0]["title"] == "Ćwiczenia"
    assert body["notifications"][0]["status"] == "sent"
    assert "NOTATKA LEKARZA" not in portal.text

    assert (await client.get("/api/patients", headers=patient)).status_code == 403


async def test_notification_failure_is_recorded(client, make_headers, monkeypatch):
    async def failing_send(recipient, subject, body):
        raise mailer.MailNotConfiguredError("brak SMTP")

    monkeypatch.setattr(mailer, "send_email", failing_send)
    doctor = await make_headers("doc@example.com")
    pid = await _patient_with_account(client, doctor)

    response = await client.post(
        f"/api/patients/{pid}/notifications",
        json={"subject": "Wizyta", "body": "Przypominam o wizycie."},
        headers=doctor,
    )
    assert response.status_code == 201
    assert response.json()["status"] == "failed" and "SMTP" in response.json()["error"]
    listing = (await client.get(f"/api/patients/{pid}/notifications", headers=doctor)).json()
    assert len(listing) == 1


async def test_account_linking_rules(client, make_headers):
    doctor = await make_headers("doc@example.com")
    other_doctor = await make_headers("other@example.com")
    pid = (await client.post("/api/patients", json=PATIENT, headers=doctor)).json()["id"]

    missing_password = await client.put(
        f"/api/patients/{pid}/account", json={"email": "new@example.com"}, headers=doctor
    )
    assert missing_password.status_code == 400

    not_patient = await client.put(
        f"/api/patients/{pid}/account", json={"email": "other@example.com"}, headers=doctor
    )
    assert not_patient.status_code == 409

    await create_user("pat@example.com", "Password123!", Role.PATIENT)
    linked = await client.put(
        f"/api/patients/{pid}/account", json={"email": "pat@example.com"}, headers=doctor
    )
    assert linked.status_code == 200

    pid2 = (await client.post("/api/patients", json=PATIENT, headers=doctor)).json()["id"]
    taken = await client.put(
        f"/api/patients/{pid2}/account", json={"email": "pat@example.com"}, headers=doctor
    )
    assert taken.status_code == 409

    assert (
        await client.get(f"/api/patients/{pid}/account", headers=other_doctor)
    ).status_code == 404
    assert (
        await client.get(f"/api/patients/{pid}/recommendations", headers=other_doctor)
    ).status_code == 404

    assert (await client.delete(f"/api/patients/{pid}/account", headers=doctor)).status_code == 204
    assert (await client.get(f"/api/patients/{pid}/account", headers=doctor)).json() is None


async def test_portal_without_link_returns_404(client, make_headers):
    patient = await make_headers("lonely@example.com", Role.PATIENT)
    assert (await client.get("/api/portal/me", headers=patient)).status_code == 404


async def test_deleting_patient_removes_dependent_data(client, make_headers, monkeypatch):
    async def fake_send(*_):
        return None

    monkeypatch.setattr(mailer, "send_email", fake_send)
    doctor = await make_headers("doc@example.com")
    pid = await _patient_with_account(client, doctor)
    await client.post(
        f"/api/patients/{pid}/recommendations",
        json={"title": "T", "content": "C", "notify": True},
        headers=doctor,
    )
    assert (await client.delete(f"/api/patients/{pid}", headers=doctor)).status_code == 204

    patient = await login_headers(client, "jan@example.com", "Pacjent123!")
    assert (await client.get("/api/portal/me", headers=patient)).status_code == 404
