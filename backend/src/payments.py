"""Stripe Checkout (BLIK, karta, Przelewy24) – REST API przez httpx, bez SDK.

Przepływ: sesja Checkout → klient płaci na stronie Stripe → webhook `checkout.session.completed`
(podpisany STRIPE_WEBHOOK_SECRET) → doładowanie potwierdzone automatycznie. Po powrocie na /kredyty
frontend prosi też o synchronizację (odczyt sesji z API), gdyby webhook się spóźniał. Potwierdzenie
jest idempotentne – jedna sesja dolicza kredyty najwyżej raz.
"""

import hashlib
import hmac
import logging
import time
from typing import Any

import httpx

from .config import settings

logger = logging.getLogger(__name__)

SIGNATURE_TOLERANCE_SECONDS = 300


class PaymentError(Exception):
    pass


def is_configured() -> bool:
    return bool(settings.stripe_secret_key)


def payment_methods() -> list[str]:
    """Metody pokazywane użytkownikowi w opisie przycisku. Same metody płatności Stripe wybiera
    według ustawień w panelu (Settings → Payment methods) – API od wersji 2026-10 nie przyjmuje
    już `payment_method_types` przy tworzeniu sesji Checkout."""
    return [m.strip() for m in settings.stripe_payment_methods.split(",") if m.strip()]


async def _request(method: str, path: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=30.0) as http:
            response = await http.request(
                method,
                f"{settings.stripe_api_url}{path}",
                data=data,
                headers={"Authorization": f"Bearer {settings.stripe_secret_key}"},
            )
    except httpx.HTTPError as exc:
        logger.exception("Brak połączenia ze Stripe")
        raise PaymentError("Operator płatności jest chwilowo niedostępny") from exc
    payload = response.json() if response.content else {}
    if response.status_code >= 400:
        message = (payload.get("error") or {}).get("message", response.text[:300])
        logger.error("Stripe zwrócił %s: %s", response.status_code, message)
        raise PaymentError("Operator płatności odrzucił żądanie")
    return payload


async def create_checkout(
    *, amount_pln: float, reference: str, topup_id: int, email: str
) -> dict[str, Any]:
    """Tworzy sesję Checkout w PLN; zwraca obiekt sesji (m.in. `id`, `url`)."""
    base = settings.app_public_url.rstrip("/")
    data: dict[str, Any] = {
        "mode": "payment",
        "locale": "pl",
        "customer_email": email,
        "client_reference_id": reference,
        "metadata[topup_id]": str(topup_id),
        "metadata[reference]": reference,
        "line_items[0][quantity]": "1",
        "line_items[0][price_data][currency]": "pln",
        "line_items[0][price_data][unit_amount]": str(round(amount_pln * 100)),
        "line_items[0][price_data][product_data][name]": (
            f"Logoped Assistant – {round(amount_pln * settings.billing_credits_per_pln)} kredytów"
        ),
        "success_url": f"{base}/kredyty?payment=success&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/kredyty?payment=cancelled",
        # Porzucona płatność wygasa po 30 min (minimum Stripe) – zamówienie zostaje anulowane.
        "expires_at": str(int(time.time()) + 31 * 60),
    }
    return await _request("POST", "/checkout/sessions", data)


async def retrieve_checkout(session_id: str) -> dict[str, Any]:
    return await _request(
        "GET", f"/checkout/sessions/{session_id}?expand[]=payment_intent.payment_method"
    )


def verify_signature(payload: bytes, header: str, secret: str, now: float | None = None) -> bool:
    """Weryfikacja nagłówka Stripe-Signature (`t=…,v1=…`): HMAC-SHA256 z `t.payload`."""
    parts: dict[str, list[str]] = {}
    for item in header.split(","):
        key, _, value = item.strip().partition("=")
        parts.setdefault(key, []).append(value)
    try:
        timestamp = int(parts["t"][0])
    except (KeyError, ValueError, IndexError):
        return False
    if abs((now or time.time()) - timestamp) > SIGNATURE_TOLERANCE_SECONDS:
        return False
    expected = hmac.new(
        secret.encode(), f"{timestamp}.".encode() + payload, hashlib.sha256
    ).hexdigest()
    return any(hmac.compare_digest(expected, candidate) for candidate in parts.get("v1", []))


def method_of(session: dict[str, Any]) -> str:
    """Metoda płatności z rozwiniętej sesji (blik/card/p24) – informacyjnie dla administratora."""
    intent = session.get("payment_intent")
    if isinstance(intent, dict):
        method = intent.get("payment_method")
        if isinstance(method, dict):
            return str(method.get("type", ""))
        types = intent.get("payment_method_types") or []
        if len(types) == 1:
            return str(types[0])
    return ""
