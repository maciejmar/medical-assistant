from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlmodel import select

from src import billing, llm
from src.config import settings
from src.database import CreditTopUp, Role, TokenUsage, User, session_factory, utcnow

from .conftest import create_user, login_headers


def test_window_is_monthly_anniversary_without_drift():
    start = datetime(2026, 1, 31, 10, 0, tzinfo=UTC)
    assert billing.current_window(start, datetime(2026, 2, 15, tzinfo=UTC)) == (
        start,
        datetime(2026, 2, 28, 10, 0, tzinfo=UTC),
    )
    # Po krótkim lutym okno wraca na 31. (liczone od daty startu, nie od poprzedniego okna).
    assert billing.current_window(start, datetime(2026, 3, 31, 11, tzinfo=UTC)) == (
        datetime(2026, 3, 31, 10, 0, tzinfo=UTC),
        datetime(2026, 4, 30, 10, 0, tzinfo=UTC),
    )
    assert billing.current_window(start, datetime(2026, 3, 31, 9, tzinfo=UTC))[0] == datetime(
        2026, 2, 28, 10, 0, tzinfo=UTC
    )


def test_cost_uses_provider_prices_and_exchange_rate(monkeypatch):
    monkeypatch.setattr(settings, "billing_usd_pln_rate", 4.0)
    # gpt-4o-mini: 0,15 USD / 1 mln wejścia, 0,60 USD / 1 mln wyjścia
    assert billing.cost_pln("gpt-4o-mini-2024-07-18", 1_000_000, 1_000_000) == pytest.approx(3.0)
    assert billing.cost_pln("text-embedding-3-small", 1_000_000, 0) == pytest.approx(0.08)
    assert billing.cost_pln("whisper-1", 60, 0) == pytest.approx(0.024)  # minuta nagrania
    assert billing.cost_pln("gemma4:12b", 10_000_000, 10_000_000) == 0.0


async def _usage(user_id: int, model: str, prompt: int, completion: int, when: datetime) -> None:
    async with session_factory() as session:
        session.add(
            TokenUsage(
                user_id=user_id,
                model_name=model,
                operation="chat_answer",
                prompt_tokens=prompt,
                completion_tokens=completion,
                total_tokens=prompt + completion,
                timestamp=when,
            )
        )
        await session.commit()


async def _doctor(client, email="doc@example.com") -> tuple[User, dict]:
    user = await create_user(email, "Password123!")
    return user, await login_headers(client, email, "Password123!")


async def test_status_counts_only_current_window(client, monkeypatch):
    monkeypatch.setattr(settings, "billing_usd_pln_rate", 4.0)
    user, headers = await _doctor(client)
    now = utcnow()
    await _usage(user.id, "gpt-4o-mini", 2_000_000, 1_000_000, now)  # 0,30 + 0,60 USD = 3,60 zł
    await _usage(user.id, "gpt-4o-mini", 9_000_000, 9_000_000, now - timedelta(days=40))

    body = (await client.get("/api/billing/me", headers=headers)).json()
    status = body["status"]
    assert status["limit_pln"] == 20.0 and status["used_pln"] == pytest.approx(3.6)
    assert status["remaining_pln"] == pytest.approx(16.4) and status["exhausted"] is False
    assert body["payment"]["amounts"] == [20.0, 50.0, 100.0]


async def test_topup_order_confirmation_and_admin_controls(client, make_headers):
    user, headers = await _doctor(client)
    admin = await make_headers("admin@example.com", Role.ADMIN)
    patient = await make_headers("pat@example.com", Role.PATIENT)
    assert (await client.get("/api/billing/me", headers=patient)).status_code == 403

    assert (
        await client.post("/api/billing/topups", json={"amount_pln": 33}, headers=headers)
    ).status_code == 400
    order = await client.post("/api/billing/topups", json={"amount_pln": 50}, headers=headers)
    assert order.status_code == 201
    assert order.json()["status"] == "pending"
    assert order.json()["reference"] == f"LOGOPED-{user.id}-{order.json()['id']}"
    me = (await client.get("/api/billing/me", headers=headers)).json()
    assert me["status"]["available_pln"] == 20.0, "oczekujące doładowanie jeszcze nie liczy się"

    pending = (await client.get("/api/admin/billing/topups", headers=admin)).json()
    assert [t["id"] for t in pending] == [order.json()["id"]]
    assert (
        await client.post(f"/api/admin/billing/topups/{order.json()['id']}/confirm", headers=admin)
    ).json()["status"] == "confirmed"
    assert (
        await client.post(f"/api/admin/billing/topups/{order.json()['id']}/confirm", headers=admin)
    ).status_code == 409
    me = (await client.get("/api/billing/me", headers=headers)).json()
    assert me["status"]["available_pln"] == 70.0

    patched = await client.patch(
        f"/api/admin/billing/users/{user.id}", json={"monthly_limit_pln": 5}, headers=admin
    )
    assert patched.json()["limit_pln"] == 5.0 and patched.json()["available_pln"] == 55.0
    manual = await client.post(
        f"/api/admin/billing/users/{user.id}/topups",
        json={"amount_pln": 10, "note": "rekompensata"},
        headers=admin,
    )
    assert manual.json()["status"] == "confirmed"

    listing = (await client.get("/api/admin/billing/users", headers=admin)).json()
    roles = {row["email"]: row for row in listing}
    assert "pat@example.com" not in roles, "pacjenci nie mają wskaźnika kredytów"
    assert roles["doc@example.com"]["status"]["available_pln"] == 65.0
    assert (await client.get("/api/admin/billing/users", headers=headers)).status_code == 403

    second = await client.post("/api/billing/topups", json={"amount_pln": 20}, headers=headers)
    assert (
        await client.delete(f"/api/billing/topups/{second.json()['id']}", headers=headers)
    ).status_code == 204

    assert (await client.delete(f"/api/admin/users/{user.id}", headers=admin)).status_code == 204
    async with session_factory() as session:
        assert (await session.exec(select(CreditTopUp))).all() == []


class FakeCompletions:
    def __init__(self, name: str, fail: bool = False):
        self.name, self.fail, self.calls = name, fail, []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise ConnectionError("local down")
        return SimpleNamespace(
            model=kwargs["model"],
            usage=None,
            choices=[SimpleNamespace(message=SimpleNamespace(content=f"od {self.name}"))],
        )


def _fake_client(completions: FakeCompletions):
    return SimpleNamespace(chat=SimpleNamespace(completions=completions))


async def test_exhausted_credits_switch_chat_to_local_model(client, monkeypatch):
    monkeypatch.setattr(settings, "local_llm_base_url", "http://gemma4:11434/v1")
    monkeypatch.setattr(settings, "billing_usd_pln_rate", 4.0)
    billing.invalidate()
    paid, local = FakeCompletions("paid"), FakeCompletions("local")
    monkeypatch.setattr(llm, "client", _fake_client(paid))
    monkeypatch.setattr(llm, "local_client", lambda: _fake_client(local))
    user, _ = await _doctor(client)

    answer = await llm.chat_complete(
        [{"role": "user", "content": "x"}], user_id=user.id, operation="test"
    )
    assert answer.text == "od paid"

    await _usage(user.id, "gpt-4o-mini", 0, 10_000_000, utcnow())  # 6 USD = 24 zł > 20 zł
    billing.invalidate(user.id)
    answer = await llm.chat_complete(
        [{"role": "user", "content": "x"}], user_id=user.id, operation="test"
    )
    assert answer.text == "od local"
    assert local.calls[-1]["model"] == settings.local_llm_model

    # Model lokalny niedostępny → awaryjnie model podstawowy (usługa działa dalej).
    monkeypatch.setattr(llm, "local_client", lambda: _fake_client(FakeCompletions("x", fail=True)))
    answer = await llm.chat_complete(
        [{"role": "user", "content": "x"}], user_id=user.id, operation="test"
    )
    assert answer.text == "od paid"
    billing.invalidate()
