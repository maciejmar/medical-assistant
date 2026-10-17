from src.database import ChatMessage, Role, TokenUsage, session_factory

from .conftest import create_user, login_headers


async def _seed_usage(user_id: int) -> None:
    async with session_factory() as session:
        session.add(
            TokenUsage(
                user_id=user_id,
                model_name="m1",
                operation="chat_rag",
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            )
        )
        session.add(
            TokenUsage(
                user_id=user_id,
                model_name="m2",
                operation="query_rewriting",
                prompt_tokens=4,
                completion_tokens=1,
                total_tokens=5,
            )
        )
        session.add(
            TokenUsage(
                user_id=None,
                model_name="m2",
                operation="seed_embedding",
                prompt_tokens=100,
                completion_tokens=0,
                total_tokens=100,
            )
        )
        session.add(
            ChatMessage(
                user_id=user_id,
                conversation_id="c1",
                role="user",
                content="TAJNA TREŚĆ MEDYCZNA",
            )
        )
        await session.commit()


async def test_usage_is_aggregated_and_anonymised(client, make_headers):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await create_user("doctor@example.com", "Password123!")
    await _seed_usage(doctor.id)

    response = await client.get("/api/admin/usage?days=7", headers=admin)
    assert response.status_code == 200
    body = response.json()
    assert body["totals"] == {
        "prompt_tokens": 114,
        "completion_tokens": 6,
        "total_tokens": 120,
        "requests": 3,
    }
    assert {m["model_name"]: m["total_tokens"] for m in body["by_model"]} == {"m1": 15, "m2": 105}
    assert {o["operation"] for o in body["by_operation"]} == {
        "chat_rag",
        "query_rewriting",
        "seed_embedding",
    }
    assert len(body["by_day"]) == 1 and body["by_day"][0]["total_tokens"] == 120
    labels = {u["label"] for u in body["by_user"]}
    assert f"Użytkownik #{doctor.id}" in labels

    raw = response.text
    assert "doctor@example.com" not in raw
    assert "TAJNA" not in raw


async def test_admin_endpoints_forbidden_for_doctor(client, make_headers):
    doctor = await make_headers("d@example.com")
    for path in ("/api/admin/usage", "/api/admin/stats", "/api/admin/users"):
        assert (await client.get(path, headers=doctor)).status_code == 403


async def test_admin_manages_users(client, make_headers):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    doctor = await create_user("doc@example.com", "Password123!")
    await _seed_usage(doctor.id)

    users = (await client.get("/api/admin/users", headers=admin)).json()
    assert {u["email"] for u in users} == {"admin@example.com", "doc@example.com"}

    patched = await client.patch(
        f"/api/admin/users/{doctor.id}", json={"is_active": False}, headers=admin
    )
    assert patched.json()["is_active"] is False
    login = await client.post(
        "/api/auth/login", json={"email": "doc@example.com", "password": "Password123!"}
    )
    assert login.status_code == 401

    admin_id = next(u["id"] for u in users if u["email"] == "admin@example.com")
    assert (
        await client.patch(f"/api/admin/users/{admin_id}", json={"is_active": False}, headers=admin)
    ).status_code == 400

    assert (await client.delete(f"/api/admin/users/{doctor.id}", headers=admin)).status_code == 204
    usage = (await client.get("/api/admin/usage", headers=admin)).json()
    assert usage["totals"]["total_tokens"] == 120


async def test_admin_creates_users_with_roles(client, make_headers):
    admin = await make_headers("admin@example.com", Role.ADMIN)
    created = await client.post(
        "/api/admin/users",
        json={
            "email": "Pacjent@Example.com",
            "full_name": "Jan Pacjent",
            "password": "Password123!",
            "role": "ROLE_PATIENT",
        },
        headers=admin,
    )
    assert created.status_code == 201
    assert created.json()["role"] == "ROLE_PATIENT"
    assert created.json()["email"] == "pacjent@example.com"
    stats = await client.get("/api/admin/stats", headers=admin)
    assert stats.status_code == 200
    assert stats.json()["patient_accounts"] == 1 and stats.json()["admins"] == 1

    duplicate = await client.post(
        "/api/admin/users",
        json={"email": "pacjent@example.com", "full_name": "X Y", "password": "Password123!"},
        headers=admin,
    )
    assert duplicate.status_code == 409

    user_id = created.json()["id"]
    patched = await client.patch(
        f"/api/admin/users/{user_id}",
        json={"role": "ROLE_DOCTOR", "password": "NoweHaslo123!"},
        headers=admin,
    )
    assert patched.json()["role"] == "ROLE_DOCTOR"
    login = await client.post(
        "/api/auth/login", json={"email": "pacjent@example.com", "password": "NoweHaslo123!"}
    )
    assert login.status_code == 200

    doctor = await make_headers("doc2@example.com")
    forbidden = await client.post(
        "/api/admin/users",
        json={"email": "x@example.com", "full_name": "X Y", "password": "Password123!"},
        headers=doctor,
    )
    assert forbidden.status_code == 403


async def test_llm_calls_are_logged_and_visible_to_admin(client, make_headers, monkeypatch):
    from types import SimpleNamespace

    from src import llm

    doctor = await create_user("doc@example.com", "Password123!")

    async def fake_create(**kwargs):
        return SimpleNamespace(
            model="test-chat-model",
            usage=SimpleNamespace(prompt_tokens=12, completion_tokens=3, total_tokens=15),
            choices=[SimpleNamespace(message=SimpleNamespace(content="ODPOWIEDŹ MODELU"))],
        )

    monkeypatch.setattr(llm.client.chat.completions, "create", fake_create)
    await llm.chat_complete(
        [{"role": "system", "content": "SYS"}, {"role": "user", "content": "PYTANIE LEKARZA"}],
        user_id=doctor.id,
        operation="query_rewriting",
    )
    await llm.drain_background_tasks()

    admin = await make_headers("admin@example.com", Role.ADMIN)
    page = (await client.get("/api/admin/llm-calls", headers=admin)).json()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["user_email"] == "doc@example.com"
    assert item["preview"] == "PYTANIE LEKARZA"
    assert item["total_tokens"] == 15

    detail = (await client.get(f"/api/admin/llm-calls/{item['id']}", headers=admin)).json()
    assert detail["request"][0] == {"role": "system", "content": "SYS"}
    assert detail["response"] == "ODPOWIEDŹ MODELU"

    filtered = await client.get("/api/admin/llm-calls?operation=chat_rag", headers=admin)
    assert filtered.json()["total"] == 0

    doctor_headers = await login_headers(client, "doc@example.com", "Password123!")
    assert (await client.get("/api/admin/llm-calls", headers=doctor_headers)).status_code == 403
