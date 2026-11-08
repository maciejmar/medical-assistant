import hashlib
import hmac
import json
import time

import pytest

from src import payments
from src.config import settings
from src.database import Role

from .conftest import create_user, login_headers

SECRET = "whsec_test"


def _signed(event: dict, secret: str = SECRET, at: int | None = None) -> tuple[bytes, str]:
    body = json.dumps(event).encode()
    timestamp = at or int(time.time())
    digest = hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()
    return body, f"t={timestamp},v1={digest}"


def test_signature_verification():
    body, header = _signed({"a": 1})
    assert payments.verify_signature(body, header, SECRET)
    assert not payments.verify_signature(body + b" ", header, SECRET)
    assert not payments.verify_signature(body, header, "inny-sekret")
    old_body, old_header = _signed({"a": 1}, at=int(time.time()) - 3600)
    assert not payments.verify_signature(old_body, old_header, SECRET), "stary podpis = replay"
    assert not payments.verify_signature(body, "garbage", SECRET)


@pytest.fixture
def stripe(monkeypatch):
    """Podstawiony Stripe: zapisuje żądania, sesje trzyma w słowniku."""
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", SECRET)
    state: dict = {"requests": [], "sessions": {}}

    async def fake_request(method, path, data=None):
        state["requests"].append((method, path, data))
        if method == "POST" and path == "/checkout/sessions":
            sid = f"cs_test_{len(state['sessions']) + 1}"
            session = {
                "id": sid,
                "url": f"https://checkout.stripe.com/c/pay/{sid}",
                "amount_total": int(data["line_items[0][price_data][unit_amount]"]),
                "payment_status": "unpaid",
                "status": "open",
            }
            state["sessions"][sid] = session
            return session
        sid = path.split("/")[-1].split("?")[0]
        return state["sessions"][sid]

    monkeypatch.setattr(payments, "_request", fake_request)
    return state


async def _doctor(client):
    await create_user("doc@example.com", "Password123!")
    return await login_headers(client, "doc@example.com", "Password123!")


async def _webhook(client, event, secret=SECRET):
    body, header = _signed(event, secret)
    return await client.post(
        "/api/payments/stripe/webhook",
        content=body,
        headers={"Stripe-Signature": header, "Content-Type": "application/json"},
    )


def _completed(session: dict, **overrides) -> dict:
    obj = {**session, "payment_status": "paid", "status": "complete", **overrides}
    return {"type": "checkout.session.completed", "data": {"object": obj}}


async def test_blik_payment_confirms_credits_automatically(client, stripe, make_headers):
    doctor = await _doctor(client)
    admin = await make_headers("admin@example.com", Role.ADMIN)
    details = (await client.get("/api/billing/me", headers=doctor)).json()["payment"]
    assert details["online_enabled"] is True and details["online_methods"] == [
        "blik",
        "card",
        "p24",
    ]

    started = await client.post("/api/billing/checkout", json={"amount_pln": 50}, headers=doctor)
    assert started.status_code == 201, started.text
    assert started.json()["url"].startswith("https://checkout.stripe.com/")
    _, _, data = stripe["requests"][0]
    assert data["line_items[0][price_data][unit_amount]"] == "5000"
    assert data["line_items[0][price_data][currency]"] == "pln"
    assert not any(k.startswith("payment_method_types") for k in data), (
        "metody wybiera panel Stripe"
    )
    assert "session_id={CHECKOUT_SESSION_ID}" in data["success_url"]

    # Oczekująca płatność online nie trafia do listy przelewów admina.
    assert (await client.get("/api/admin/billing/topups", headers=admin)).json() == []

    session = stripe["sessions"]["cs_test_1"]
    assert (await _webhook(client, _completed(session), secret="zly")).status_code == 400
    assert (await _webhook(client, _completed(session))).status_code == 200
    assert (await _webhook(client, _completed(session))).status_code == 200  # ponowienie
    me = (await client.get("/api/billing/me", headers=doctor)).json()
    assert me["status"]["available_pln"] == 70.0, "doliczone dokładnie raz"
    assert me["topups"][0]["status"] == "confirmed"


async def test_amount_mismatch_and_expiry_do_not_add_credits(client, stripe):
    doctor = await _doctor(client)
    await client.post("/api/billing/checkout", json={"amount_pln": 20}, headers=doctor)
    await client.post("/api/billing/checkout", json={"amount_pln": 100}, headers=doctor)
    first, second = stripe["sessions"]["cs_test_1"], stripe["sessions"]["cs_test_2"]

    await _webhook(client, _completed(first, amount_total=100))
    expired = {
        "type": "checkout.session.expired",
        "data": {"object": {**second, "status": "expired"}},
    }
    await _webhook(client, expired)

    me = (await client.get("/api/billing/me", headers=doctor)).json()
    assert me["status"]["available_pln"] == 20.0
    statuses = {t["amount_pln"]: t["status"] for t in me["topups"]}
    assert statuses == {20.0: "pending", 100.0: "cancelled"}


async def test_sync_after_return_confirms_when_webhook_is_late(client, stripe):
    doctor = await _doctor(client)
    await client.post("/api/billing/checkout", json={"amount_pln": 20}, headers=doctor)
    stripe["sessions"]["cs_test_1"].update(payment_status="paid", status="complete")

    synced = await client.post(
        "/api/billing/checkout/sync", json={"session_id": "cs_test_1"}, headers=doctor
    )
    assert synced.status_code == 200 and synced.json()["status"] == "confirmed"
    other = await create_user("other@example.com", "Password123!")
    assert other.id
    other_headers = await login_headers(client, "other@example.com", "Password123!")
    foreign = await client.post(
        "/api/billing/checkout/sync", json={"session_id": "cs_test_1"}, headers=other_headers
    )
    assert foreign.status_code == 404


async def test_online_payments_disabled_without_keys(client):
    doctor = await _doctor(client)
    me = (await client.get("/api/billing/me", headers=doctor)).json()
    assert me["payment"]["online_enabled"] is False
    response = await client.post("/api/billing/checkout", json={"amount_pln": 20}, headers=doctor)
    assert response.status_code == 503
