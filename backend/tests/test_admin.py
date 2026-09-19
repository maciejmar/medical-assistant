from src.database import ChatMessage, Role, TokenUsage, session_factory

from .conftest import create_user


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
