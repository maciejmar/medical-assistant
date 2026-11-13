"""Kredyty użytkowników: wskaźnik wykorzystania, doładowania (płatność online Stripe – BLIK, karta,
Przelewy24 – albo przelew tradycyjny potwierdzany ręcznie) i panel administratora."""

import json
import logging

from fastapi import APIRouter, HTTPException, Request, status
from sqlmodel import col, select

from .. import billing, mailer, payments
from ..auth import CurrentAdmin, CurrentDoctor, SessionDep
from ..config import settings
from ..database import CreditTopUp, PaymentSession, Role, User, utcnow
from ..llm import _in_background
from .schemas import (
    CheckoutOut,
    CheckoutSyncIn,
    CreditStatusOut,
    ManualTopUpIn,
    MyCreditsOut,
    PaymentDetailsOut,
    SubscriptionPatch,
    TopUpIn,
    TopUpOut,
    UserCreditsOut,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["billing"])

ONLINE_NOTE = "online"


def topup_amounts() -> list[float]:
    amounts = []
    for part in settings.billing_topup_amounts.split(","):
        try:
            amounts.append(float(part))
        except ValueError:
            continue
    return amounts or [20.0, 50.0, 100.0]


def _status_out(s: billing.CreditStatus) -> CreditStatusOut:
    return CreditStatusOut(
        started_at=s.started_at,
        window_start=s.window_start,
        window_end=s.window_end,
        limit_pln=round(s.limit_pln, 2),
        topups_pln=round(s.topups_pln, 2),
        available_pln=round(s.available_pln, 2),
        used_pln=round(s.used_pln, 2),
        remaining_pln=round(s.remaining_pln, 2),
        limit_credits=billing.to_credits(s.limit_pln),
        topups_credits=billing.to_credits(s.topups_pln),
        available_credits=s.available_credits,
        used_credits=s.used_credits,
        remaining_credits=s.remaining_credits,
        percent=round(s.percent, 1),
        exhausted=s.exhausted,
    )


async def _topups(session: SessionDep, user_id: int, limit: int = 20) -> list[CreditTopUp]:
    rows = await session.exec(
        select(CreditTopUp)
        .where(CreditTopUp.user_id == user_id)
        .order_by(col(CreditTopUp.created_at).desc())
        .limit(limit)
    )
    return list(rows.all())


def _payment() -> PaymentDetailsOut:
    return PaymentDetailsOut(
        recipient=settings.topup_recipient,
        bank_account=settings.topup_bank_account,
        amounts=topup_amounts(),
        credits_per_pln=settings.billing_credits_per_pln,
        online_enabled=payments.is_configured(),
        online_methods=payments.payment_methods() if payments.is_configured() else [],
    )


@router.get("/billing/me", response_model=MyCreditsOut)
async def my_credits(session: SessionDep, user: CurrentDoctor) -> MyCreditsOut:
    status_ = await billing.credit_status(session, user)
    return MyCreditsOut(
        status=_status_out(status_),
        topups=[TopUpOut.model_validate(t) for t in await _topups(session, user.id)],  # type: ignore[arg-type]
        payment=_payment(),
    )


async def _notify_admin(user: User, topup: CreditTopUp) -> None:
    try:
        await mailer.send_email(
            settings.admin_email,
            f"Zamówienie doładowania {topup.amount_pln:.0f} zł – {user.full_name}",
            f"Użytkownik {user.full_name} ({user.email}) zamówił doładowanie kredytów "
            f"{topup.amount_pln:.2f} zł.\nTytuł przelewu: {topup.reference}\n\n"
            f"Po zaksięgowaniu wpłaty potwierdź doładowanie w panelu administratora: "
            f"{settings.app_public_url}/admin",
        )
    except Exception:
        logger.warning("Nie wysłano powiadomienia o doładowaniu %s do administratora", topup.id)


@router.post("/billing/topups", response_model=TopUpOut, status_code=status.HTTP_201_CREATED)
async def order_topup(body: TopUpIn, session: SessionDep, user: CurrentDoctor) -> CreditTopUp:
    """Zamówienie doładowania – kredyty dochodzą po potwierdzeniu wpłaty przez administratora."""
    if body.amount_pln not in topup_amounts():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Wybierz jedną z dostępnych kwot doładowania"
        )
    pending = (
        await session.exec(
            select(CreditTopUp).where(
                CreditTopUp.user_id == user.id,
                CreditTopUp.status == "pending",
                CreditTopUp.note != ONLINE_NOTE,
            )
        )
    ).all()
    if len(pending) >= 3:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Masz już 3 oczekujące doładowania – poczekaj na ich zaksięgowanie",
        )
    topup = CreditTopUp(user_id=user.id, amount_pln=body.amount_pln)  # type: ignore[arg-type]
    session.add(topup)
    await session.flush()
    topup.reference = f"LOGOPED-{user.id}-{topup.id}"
    await session.commit()
    await session.refresh(topup)
    _in_background(_notify_admin(user, topup))
    return topup


@router.delete("/billing/topups/{topup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_topup(topup_id: int, session: SessionDep, user: CurrentDoctor) -> None:
    topup = await session.get(CreditTopUp, topup_id)
    if topup is None or topup.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono zamówienia")
    if topup.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Można anulować tylko oczekujące zamówienie")
    topup.status = "cancelled"
    session.add(topup)
    await session.commit()


# --- administrator --------------------------------------------------------------------------


@router.get("/admin/billing/users", response_model=list[UserCreditsOut])
async def users_credits(session: SessionDep, admin: CurrentAdmin) -> list[UserCreditsOut]:
    """Wskaźnik kredytów lekarzy i administratorów (pacjenci nie korzystają z LLM)."""
    users = await session.exec(
        select(User)
        .where(col(User.role).in_([Role.DOCTOR.value, Role.ADMIN.value]))
        .order_by(col(User.full_name))
    )
    result = []
    for user in users.all():
        result.append(
            UserCreditsOut(
                user_id=user.id,  # type: ignore[arg-type]
                email=user.email,
                full_name=user.full_name,
                role=user.role,
                status=_status_out(await billing.credit_status(session, user)),
            )
        )
    return result


async def _user(session: SessionDep, user_id: int) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono użytkownika")
    return user


@router.patch("/admin/billing/users/{user_id}", response_model=CreditStatusOut)
async def update_subscription(
    user_id: int, body: SubscriptionPatch, session: SessionDep, admin: CurrentAdmin
) -> CreditStatusOut:
    """Zmiana limitu miesięcznego i/lub daty startu subskrypcji (wyznacza okna rozliczeniowe)."""
    user = await _user(session, user_id)
    subscription = await billing.subscription_for(session, user)
    if body.monthly_limit_pln is not None:
        subscription.monthly_limit_pln = body.monthly_limit_pln
    if body.started_at is not None:
        subscription.started_at = body.started_at
    subscription.updated_at = utcnow()
    session.add(subscription)
    await session.commit()
    billing.invalidate(user.id)
    return _status_out(await billing.credit_status(session, user))


@router.get("/admin/billing/topups", response_model=list[TopUpOut])
async def list_topups(
    session: SessionDep, admin: CurrentAdmin, status_filter: str | None = "pending"
) -> list[CreditTopUp]:
    query = select(CreditTopUp).order_by(col(CreditTopUp.created_at).desc()).limit(200)
    if status_filter:
        query = query.where(CreditTopUp.status == status_filter)
    if status_filter == "pending":
        # Płatności online potwierdza operator – admin rozpatruje tylko przelewy tradycyjne.
        query = query.where(CreditTopUp.note != ONLINE_NOTE)
    return list((await session.exec(query)).all())


async def _decide(session: SessionDep, topup_id: int, admin: User, new_status: str) -> CreditTopUp:
    topup = await session.get(CreditTopUp, topup_id)
    if topup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono zamówienia")
    if topup.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Zamówienie zostało już rozpatrzone")
    topup.status = new_status
    topup.confirmed_at = utcnow()
    topup.confirmed_by = admin.id
    session.add(topup)
    await session.commit()
    await session.refresh(topup)
    billing.invalidate(topup.user_id)
    return topup


@router.post("/admin/billing/topups/{topup_id}/confirm", response_model=TopUpOut)
async def confirm_topup(topup_id: int, session: SessionDep, admin: CurrentAdmin) -> CreditTopUp:
    """Wpłata zaksięgowana – kwota powiększa limit bieżącego okna użytkownika."""
    return await _decide(session, topup_id, admin, "confirmed")


@router.post("/admin/billing/topups/{topup_id}/reject", response_model=TopUpOut)
async def reject_topup(topup_id: int, session: SessionDep, admin: CurrentAdmin) -> CreditTopUp:
    return await _decide(session, topup_id, admin, "rejected")


@router.post(
    "/admin/billing/users/{user_id}/topups",
    response_model=TopUpOut,
    status_code=status.HTTP_201_CREATED,
)
async def manual_topup(
    user_id: int, body: ManualTopUpIn, session: SessionDep, admin: CurrentAdmin
) -> CreditTopUp:
    """Doładowanie przyznane przez administratora (np. wpłata poza systemem, rekompensata)."""
    user = await _user(session, user_id)
    now = utcnow()
    topup = CreditTopUp(
        user_id=user.id,  # type: ignore[arg-type]
        amount_pln=body.amount_pln,
        status="confirmed",
        note=body.note.strip(),
        confirmed_at=now,
        confirmed_by=admin.id,
    )
    session.add(topup)
    await session.flush()
    topup.reference = f"RECZNE-{user.id}-{topup.id}"
    await session.commit()
    await session.refresh(topup)
    billing.invalidate(user.id)
    return topup


# --- płatności online (Stripe Checkout) -------------------------------------------------------


@router.post("/billing/checkout", response_model=CheckoutOut, status_code=status.HTTP_201_CREATED)
async def start_checkout(body: TopUpIn, session: SessionDep, user: CurrentDoctor) -> CheckoutOut:
    """Tworzy zamówienie i sesję płatności; frontend przekierowuje na zwrócony adres Stripe."""
    if not payments.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Płatności online są wyłączone")
    if body.amount_pln not in topup_amounts():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Wybierz jedną z dostępnych kwot doładowania"
        )
    topup = CreditTopUp(user_id=user.id, amount_pln=body.amount_pln, note=ONLINE_NOTE)  # type: ignore[arg-type]
    session.add(topup)
    await session.flush()
    topup.reference = f"LOGOPED-{user.id}-{topup.id}"
    try:
        checkout = await payments.create_checkout(
            amount_pln=body.amount_pln,
            reference=topup.reference,
            topup_id=topup.id,  # type: ignore[arg-type]
            email=user.email,
        )
    except payments.PaymentError as exc:
        await session.rollback()
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    session.add(
        PaymentSession(
            topup_id=topup.id,  # type: ignore[arg-type]
            user_id=user.id,  # type: ignore[arg-type]
            session_id=str(checkout["id"]),
            amount_pln=body.amount_pln,
        )
    )
    await session.commit()
    return CheckoutOut(topup_id=topup.id, url=str(checkout["url"]))  # type: ignore[arg-type]


async def _payment_for(session: SessionDep, session_id: str) -> PaymentSession | None:
    return (
        await session.exec(select(PaymentSession).where(PaymentSession.session_id == session_id))
    ).first()


async def _settle(session: SessionDep, checkout: dict) -> CreditTopUp | None:
    """Przenosi stan sesji Stripe na zamówienie (idempotentnie). Zwraca zamówienie albo None."""
    payment = await _payment_for(session, str(checkout.get("id")))
    if payment is None:
        logger.warning("Nieznana sesja płatności %s", checkout.get("id"))
        return None
    topup = await session.get(CreditTopUp, payment.topup_id)
    if topup is None:
        return None
    if payment.status != "open":
        return topup  # już rozliczona
    paid = checkout.get("payment_status") == "paid"
    now = utcnow()
    if paid:
        if int(checkout.get("amount_total") or 0) != round(payment.amount_pln * 100):
            logger.error("Kwota sesji %s nie zgadza się z zamówieniem", payment.session_id)
            return topup
        payment.status = "paid"
        payment.payment_method = payments.method_of(checkout)
        if topup.status == "pending":
            topup.status = "confirmed"
            topup.confirmed_at = now
    elif checkout.get("status") == "expired":
        payment.status = "expired"
        if topup.status == "pending":
            topup.status = "cancelled"
    else:
        return topup  # płatność w toku (np. Przelewy24 – rozliczenie asynchroniczne)
    payment.completed_at = now
    session.add(payment)
    session.add(topup)
    await session.commit()
    await session.refresh(topup)
    billing.invalidate(topup.user_id)
    return topup


@router.post("/billing/checkout/sync", response_model=TopUpOut)
async def sync_checkout(
    body: CheckoutSyncIn, session: SessionDep, user: CurrentDoctor
) -> CreditTopUp:
    """Po powrocie ze Stripe: odczyt stanu sesji z API (na wypadek opóźnionego webhooka)."""
    payment = await _payment_for(session, body.session_id)
    if payment is None or payment.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono płatności")
    try:
        checkout = await payments.retrieve_checkout(body.session_id)
    except payments.PaymentError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    topup = await _settle(session, checkout)
    if topup is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono zamówienia")
    return topup


@router.post("/payments/stripe/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, session: SessionDep) -> dict[str, bool]:
    """Powiadomienia Stripe – podpis weryfikowany sekretem STRIPE_WEBHOOK_SECRET."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    secret = settings.stripe_webhook_secret
    if not secret or not payments.verify_signature(payload, signature, secret):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nieprawidłowy podpis")
    event = json.loads(payload)
    kind = event.get("type", "")
    checkout = (event.get("data") or {}).get("object") or {}
    if kind in {
        "checkout.session.completed",
        "checkout.session.async_payment_succeeded",
        "checkout.session.expired",
    }:
        await _settle(session, checkout)
    elif kind == "checkout.session.async_payment_failed":
        payment = await _payment_for(session, str(checkout.get("id")))
        if payment is not None and payment.status == "open":
            payment.status = "failed"
            payment.completed_at = utcnow()
            topup = await session.get(CreditTopUp, payment.topup_id)
            if topup is not None and topup.status == "pending":
                topup.status = "rejected"
                session.add(topup)
            session.add(payment)
            await session.commit()
    return {"received": True}
