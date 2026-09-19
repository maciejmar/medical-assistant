from src.database import Role

PATIENT = {
    "first_name": "Jan",
    "last_name": "Kowalski",
    "icd_code": "F80.0",
    "diagnosis": "Rotacyzm",
}


async def test_doctor_crud_and_notes(client, make_headers):
    headers = await make_headers("a@example.com")
    created = await client.post("/api/patients", json=PATIENT, headers=headers)
    assert created.status_code == 201
    pid = created.json()["id"]

    updated = await client.put(
        f"/api/patients/{pid}", json={**PATIENT, "diagnosis": "Sygmatyzm"}, headers=headers
    )
    assert updated.json()["diagnosis"] == "Sygmatyzm"

    note = await client.post(
        f"/api/patients/{pid}/notes",
        json={"content": "Ćwiczenia pionizacji języka.", "source": "dictated"},
        headers=headers,
    )
    assert note.status_code == 201
    recent = await client.get("/api/patients/notes/recent", headers=headers)
    assert recent.json()[0]["patient_name"] == "Jan Kowalski"

    assert (
        await client.delete(f"/api/patients/{pid}/notes/{note.json()['id']}", headers=headers)
    ).status_code == 204
    assert (await client.delete(f"/api/patients/{pid}", headers=headers)).status_code == 204
    assert (await client.get(f"/api/patients/{pid}", headers=headers)).status_code == 404


async def test_doctor_cannot_access_other_doctors_patients(client, make_headers):
    headers_x = await make_headers("x@example.com")
    headers_y = await make_headers("y@example.com")
    pid = (await client.post("/api/patients", json=PATIENT, headers=headers_x)).json()["id"]
    note_id = (
        await client.post(
            f"/api/patients/{pid}/notes", json={"content": "Poufne"}, headers=headers_x
        )
    ).json()["id"]

    assert (await client.get("/api/patients", headers=headers_y)).json() == []
    assert (await client.get(f"/api/patients/{pid}", headers=headers_y)).status_code == 404
    assert (
        await client.put(f"/api/patients/{pid}", json=PATIENT, headers=headers_y)
    ).status_code == 404
    assert (await client.delete(f"/api/patients/{pid}", headers=headers_y)).status_code == 404
    assert (await client.get(f"/api/patients/{pid}/notes", headers=headers_y)).status_code == 404
    assert (
        await client.delete(f"/api/patients/{pid}/notes/{note_id}", headers=headers_y)
    ).status_code == 404
    assert (await client.get("/api/patients/notes/recent", headers=headers_y)).json() == []
    assert (await client.get(f"/api/patients/{pid}", headers=headers_x)).status_code == 200


async def test_admin_has_no_access_to_patient_data(client, make_headers):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    assert (await client.get("/api/patients", headers=admin)).status_code == 403
    assert (await client.get("/api/chat/conversations", headers=admin)).status_code == 403
