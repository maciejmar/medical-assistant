from sqlmodel import select

from src.api import chat as chat_module
from src.database import PatientPlan, PlanStep, session_factory

from .test_chat import FakeGraph

PATIENT = {"first_name": "Jan", "last_name": "Kowalski", "diagnosis": "Rotacyzm"}


async def _patient(client, headers) -> int:
    return (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]


async def test_steps_crud_order_and_isolation(client, make_headers):
    doctor = await make_headers("doc@example.com")
    other = await make_headers("other@example.com")
    pid = await _patient(client, doctor)
    base = f"/api/patients/{pid}/plan"

    empty = await client.get(base, headers=doctor)
    assert empty.json() == {"include_in_context": False, "steps": []}

    first = await client.post(
        f"{base}/steps", json={"title": " Diagnoza ", "description": "Badanie"}, headers=doctor
    )
    assert first.status_code == 201
    assert first.json()["title"] == "Diagnoza" and first.json()["status"] == "planned"
    second = (
        await client.post(f"{base}/steps", json={"title": "Pionizacja"}, headers=doctor)
    ).json()
    assert second["position"] == 1

    updated = await client.put(
        f"{base}/steps/{first.json()['id']}",
        json={"title": "Diagnoza wstępna", "description": "Opis", "status": "completed"},
        headers=doctor,
    )
    assert updated.json()["status"] == "completed" and updated.json()["title"] == "Diagnoza wstępna"
    bad_status = await client.put(
        f"{base}/steps/{second['id']}", json={"title": "x", "status": "done"}, headers=doctor
    )
    assert bad_status.status_code == 422

    order = await client.put(
        f"{base}/order", json={"step_ids": [second["id"], first.json()["id"]]}, headers=doctor
    )
    assert [s["title"] for s in order.json()] == ["Pionizacja", "Diagnoza wstępna"]
    incomplete = await client.put(
        f"{base}/order", json={"step_ids": [second["id"]]}, headers=doctor
    )
    assert incomplete.status_code == 400

    assert (await client.get(base, headers=other)).status_code == 404
    foreign = await client.put(f"{base}/steps/{second['id']}", json={"title": "x"}, headers=other)
    assert foreign.status_code == 404

    deleted = await client.delete(f"{base}/steps/{second['id']}", headers=doctor)
    assert deleted.status_code == 204
    assert [s["title"] for s in (await client.get(base, headers=doctor)).json()["steps"]] == [
        "Diagnoza wstępna"
    ]


async def test_plan_enters_llm_context_only_when_enabled(client, make_headers, monkeypatch):
    fake = FakeGraph()
    monkeypatch.setattr(chat_module, "rag_graph", fake)
    doctor = await make_headers("doc@example.com")
    pid = await _patient(client, doctor)
    base = f"/api/patients/{pid}/plan"
    await client.post(
        f"{base}/steps",
        json={"title": "Ćwiczenia wibracji", "description": "3x w tygodniu", "status": "suspended"},
        headers=doctor,
    )

    async def ask() -> str:
        await client.post(
            "/api/chat", json={"message": "Co dalej?", "patient_id": pid}, headers=doctor
        )
        return fake.states[-1]["patient_context"]

    assert "Plan działania" not in await ask()

    enabled = await client.put(
        f"{base}/settings", json={"include_in_context": True}, headers=doctor
    )
    assert enabled.json() == {"include_in_context": True}
    context = await ask()
    assert "Plan działania" in context
    assert "1. Ćwiczenia wibracji – status: zawieszony\n   3x w tygodniu" in context

    await client.put(f"{base}/settings", json={"include_in_context": False}, headers=doctor)
    assert "Plan działania" not in await ask()


async def test_deleting_patient_removes_plan(client, make_headers):
    doctor = await make_headers("doc@example.com")
    pid = await _patient(client, doctor)
    await client.post(f"/api/patients/{pid}/plan/steps", json={"title": "Krok"}, headers=doctor)
    await client.put(
        f"/api/patients/{pid}/plan/settings", json={"include_in_context": True}, headers=doctor
    )
    assert (await client.delete(f"/api/patients/{pid}", headers=doctor)).status_code == 204
    async with session_factory() as session:
        for model in (PlanStep, PatientPlan):
            assert (await session.exec(select(model))).all() == []
