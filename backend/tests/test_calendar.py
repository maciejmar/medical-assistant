from sqlmodel import select

from src.database import PatientEvent, session_factory

from .conftest import login_headers

PATIENT = {"first_name": "Jan", "last_name": "Kowalski", "diagnosis": "Rotacyzm"}


async def _patient_with_account(client, doctor, email="jan@example.com") -> tuple[int, dict]:
    pid = (await client.post("/api/patients", json=PATIENT, headers=doctor)).json()["id"]
    linked = await client.put(
        f"/api/patients/{pid}/account",
        json={"email": email, "password": "Pacjent123!"},
        headers=doctor,
    )
    assert linked.status_code == 200, linked.text
    return pid, await login_headers(client, email, "Pacjent123!")


def _event(**overrides):
    return {
        "type": "visit",
        "title": "Wizyta kontrolna",
        "starts_at": "2026-11-12T10:00:00+01:00",
        "ends_at": "2026-11-12T10:45:00+01:00",
        "location": "Gabinet 2",
        **overrides,
    }


async def test_doctor_and_patient_share_one_calendar(client, make_headers):
    doctor = await make_headers("doc@example.com")
    pid, patient = await _patient_with_account(client, doctor)

    created = await client.post(f"/api/patients/{pid}/events", json=_event(), headers=doctor)
    assert created.status_code == 201, created.text
    visit = created.json()
    assert visit["created_by_role"] == "doctor" and visit["editable"] is True

    seen = (await client.get("/api/portal/events", headers=patient)).json()
    assert [e["title"] for e in seen] == ["Wizyta kontrolna"]
    assert seen[0]["editable"] is False, "pacjent nie edytuje wpisów logopedy"

    consult = await client.post(
        "/api/portal/events",
        json=_event(
            type="consultation", title="Laryngolog", starts_at="2026-11-20T08:00:00Z", ends_at=None
        ),
        headers=patient,
    )
    assert consult.status_code == 201 and consult.json()["editable"] is True

    doctor_view = (await client.get(f"/api/patients/{pid}/events", headers=doctor)).json()
    assert [(e["title"], e["created_by_role"]) for e in doctor_view] == [
        ("Wizyta kontrolna", "doctor"),
        ("Laryngolog", "patient"),
    ]
    assert all(e["editable"] for e in doctor_view), "lekarz edytuje wszystkie wpisy pacjenta"

    forbidden = await client.put(
        f"/api/portal/events/{visit['id']}", json=_event(title="Zmiana"), headers=patient
    )
    assert forbidden.status_code == 403
    assert (
        await client.delete(f"/api/portal/events/{visit['id']}", headers=patient)
    ).status_code == 403
    wrong_type = await client.post(
        "/api/portal/events", json=_event(type="stage_start"), headers=patient
    )
    assert wrong_type.status_code == 403

    moved = await client.put(
        f"/api/patients/{pid}/events/{consult.json()['id']}",
        json=_event(
            type="consultation",
            title="Laryngolog – kontrola",
            starts_at="2026-11-21T08:00:00Z",
            ends_at=None,
        ),
        headers=doctor,
    )
    assert moved.status_code == 200
    mine = (await client.get("/api/portal/events", headers=patient)).json()
    assert mine[1]["title"] == "Laryngolog – kontrola"

    assert (
        await client.delete(f"/api/portal/events/{consult.json()['id']}", headers=patient)
    ).status_code == 204


async def test_range_filter_validation_and_plan_link(client, make_headers):
    doctor = await make_headers("doc@example.com")
    pid, _ = await _patient_with_account(client, doctor)
    base = f"/api/patients/{pid}/events"
    step = (
        await client.post(
            f"/api/patients/{pid}/plan/steps", json={"title": "Pionizacja"}, headers=doctor
        )
    ).json()

    stage = await client.post(
        base,
        json=_event(
            type="stage_start",
            title="Start etapu",
            starts_at="2026-12-01T00:00:00Z",
            ends_at=None,
            all_day=True,
            plan_step_id=step["id"],
        ),
        headers=doctor,
    )
    assert stage.status_code == 201
    assert stage.json()["plan_step_title"] == "Pionizacja"
    await client.post(base, json=_event(), headers=doctor)

    december = await client.get(
        base,
        params={"start": "2026-12-01T00:00:00Z", "end": "2027-01-01T00:00:00Z"},
        headers=doctor,
    )
    assert [e["title"] for e in december.json()] == ["Start etapu"]

    backwards = await client.post(
        base, json=_event(ends_at="2026-11-12T09:00:00+01:00"), headers=doctor
    )
    assert backwards.status_code == 422
    foreign_step = await client.post(base, json=_event(plan_step_id=999), headers=doctor)
    assert foreign_step.status_code == 404

    # Usunięcie kroku planu zostawia wydarzenie bez powiązania.
    await client.delete(f"/api/patients/{pid}/plan/steps/{step['id']}", headers=doctor)
    after = (await client.get(base, headers=doctor)).json()
    assert after[-1]["title"] == "Start etapu" and after[-1]["plan_step_id"] is None


async def test_calendars_are_isolated_between_doctors_and_patients(client, make_headers):
    doctor_a = await make_headers("a@example.com")
    doctor_b = await make_headers("b@example.com")
    pid_a, patient_a = await _patient_with_account(client, doctor_a, "pa@example.com")
    pid_b, patient_b = await _patient_with_account(client, doctor_b, "pb@example.com")
    event_a = (
        await client.post(f"/api/patients/{pid_a}/events", json=_event(title="A"), headers=doctor_a)
    ).json()
    await client.post(f"/api/patients/{pid_b}/events", json=_event(title="B"), headers=doctor_b)

    assert (await client.get(f"/api/patients/{pid_a}/events", headers=doctor_b)).status_code == 404
    assert (
        await client.put(
            f"/api/patients/{pid_b}/events/{event_a['id']}", json=_event(), headers=doctor_b
        )
    ).status_code == 404
    assert [
        e["title"] for e in (await client.get("/api/portal/events", headers=patient_a)).json()
    ] == ["A"]
    assert [
        e["title"] for e in (await client.get("/api/portal/events", headers=patient_b)).json()
    ] == ["B"]
    assert (
        await client.delete(f"/api/portal/events/{event_a['id']}", headers=patient_b)
    ).status_code == 404
    assert (await client.get("/api/portal/events", headers=doctor_a)).status_code == 403

    await client.delete(f"/api/patients/{pid_a}", headers=doctor_a)
    async with session_factory() as session:
        titles = [e.title for e in (await session.exec(select(PatientEvent))).all()]
    assert titles == ["B"]


async def test_doctor_sees_all_own_patients_in_one_calendar(client, make_headers):
    doctor = await make_headers("doc@example.com")
    other = await make_headers("other@example.com")
    first = (
        await client.post("/api/patients", json={**PATIENT, "first_name": "Ala"}, headers=doctor)
    ).json()["id"]
    second = (
        await client.post("/api/patients", json={**PATIENT, "first_name": "Ola"}, headers=doctor)
    ).json()["id"]
    foreign = (await client.post("/api/patients", json=PATIENT, headers=other)).json()["id"]
    await client.post(
        f"/api/patients/{second}/events",
        json=_event(title="Wizyta B", starts_at="2026-11-12T12:00:00Z", ends_at=None),
        headers=doctor,
    )
    await client.post(
        f"/api/patients/{first}/events",
        json=_event(title="Wizyta A", starts_at="2026-11-12T09:00:00Z", ends_at=None),
        headers=doctor,
    )
    await client.post(
        f"/api/patients/{first}/events",
        json=_event(title="Za tydzień", starts_at="2026-11-20T09:00:00Z", ends_at=None),
        headers=doctor,
    )
    await client.post(f"/api/patients/{foreign}/events", json=_event(title="Obcy"), headers=other)

    week = await client.get(
        "/api/calendar/events",
        params={"start": "2026-11-09T00:00:00Z", "end": "2026-11-16T00:00:00Z"},
        headers=doctor,
    )
    assert week.status_code == 200
    assert [(e["title"], e["patient_name"], e["patient_id"]) for e in week.json()] == [
        ("Wizyta A", "Ala Kowalski", first),
        ("Wizyta B", "Ola Kowalski", second),
    ]
    assert all(e["editable"] for e in week.json())
    everything = (await client.get("/api/calendar/events", headers=other)).json()
    assert [e["title"] for e in everything] == ["Obcy"], "lekarz widzi tylko swoich pacjentów"


async def test_overlapping_visit_warns_and_can_be_confirmed(client, make_headers):
    doctor = await make_headers("doc@example.com")
    other_doctor = await make_headers("other@example.com")
    pid_a, patient_a = await _patient_with_account(client, doctor, "a@example.com")
    pid_b = (await client.post("/api/patients", json=PATIENT, headers=doctor)).json()["id"]
    pid_x = (await client.post("/api/patients", json=PATIENT, headers=other_doctor)).json()["id"]
    first = (
        await client.post(
            f"/api/patients/{pid_a}/events",
            json=_event(starts_at="2026-11-12T10:00:00Z", ends_at="2026-11-12T10:45:00Z"),
            headers=doctor,
        )
    ).json()

    clash = await client.post(
        f"/api/patients/{pid_b}/events",
        json=_event(title="Nowa", starts_at="2026-11-12T10:30:00Z", ends_at="2026-11-12T11:15:00Z"),
        headers=doctor,
    )
    assert clash.status_code == 409
    detail = clash.json()["detail"]
    assert detail["code"] == "time_conflict" and "Zmień termin" in detail["message"]
    assert [c["id"] for c in detail["conflicts"]] == [first["id"]]
    assert detail["conflicts"][0]["patient_name"] == "Jan Kowalski"

    # Brak końca = 45 min → 10:00–10:45 koliduje z wizytą bez końca o 10:40.
    no_end = await client.post(
        f"/api/patients/{pid_b}/events",
        json=_event(starts_at="2026-11-12T10:40:00Z", ends_at=None),
        headers=doctor,
    )
    assert no_end.status_code == 409

    confirmed = await client.post(
        f"/api/patients/{pid_b}/events",
        json=_event(
            title="Nowa",
            starts_at="2026-11-12T10:30:00Z",
            ends_at="2026-11-12T11:15:00Z",
            allow_overlap=True,
        ),
        headers=doctor,
    )
    assert confirmed.status_code == 201

    back_to_back = await client.post(
        f"/api/patients/{pid_b}/events",
        json=_event(starts_at="2026-11-12T11:15:00Z", ends_at="2026-11-12T12:00:00Z"),
        headers=doctor,
    )
    assert back_to_back.status_code == 201, "styk końca z początkiem to nie kolizja"

    moved = await client.put(
        f"/api/patients/{pid_a}/events/{first['id']}",
        json=_event(
            title="Przesunięta", starts_at="2026-11-12T09:30:00Z", ends_at="2026-11-12T10:15:00Z"
        ),
        headers=doctor,
    )
    assert moved.status_code == 200, "wydarzenie nie koliduje samo ze sobą"

    for allowed in (
        _event(
            type="consultation", title="Laryngolog", starts_at="2026-11-12T10:30:00Z", ends_at=None
        ),
        _event(
            type="stage_start",
            title="Etap",
            starts_at="2026-11-12T00:00:00Z",
            ends_at=None,
            all_day=True,
        ),
    ):
        assert (
            await client.post(f"/api/patients/{pid_b}/events", json=allowed, headers=doctor)
        ).status_code == 201, "konsultacje i etapy nie zajmują czasu lekarza"
    assert (
        await client.post(
            "/api/portal/events",
            json=_event(type="consultation", starts_at="2026-11-12T10:30:00Z", ends_at=None),
            headers=patient_a,
        )
    ).status_code == 201, "pacjent nie jest blokowany"
    assert (
        await client.post(
            f"/api/patients/{pid_x}/events",
            json=_event(starts_at="2026-11-12T10:30:00Z", ends_at=None),
            headers=other_doctor,
        )
    ).status_code == 201, "kalendarze lekarzy są niezależne"
