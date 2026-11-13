"""Kredyty: przeliczanie tokenów na koszt, okna subskrypcji i model zastępczy.

Wewnętrznie wszystko liczone jest w złotówkach; klient widzi kredyty (BILLING_CREDITS_PER_PLN,
domyślnie 1 kredyt = 0,01 zł), a doładowania kupuje w złotówkach. Na start każdego okna klient
dostaje limit miesięczny (domyślnie 5 zł = 500 kredytów); niewykorzystane kredyty – także
z doładowań – przepadają z końcem okna.

Przelicznik (standard przy rozliczaniu API LLM): koszt = tokeny wejścia × cena wejścia
+ tokeny wyjścia × cena wyjścia (cennik dostawcy w USD za 1 mln tokenów) × kurs USD→PLN × marża.
Modele spoza cennika (np. lokalna Gemma w Ollamie) kosztują 0.

Okno subskrypcji: miesięczne, liczone od daty startu (rocznica w kolejnych miesiącach; 31. dnia
w krótszym miesiącu – ostatni dzień miesiąca). Zużycie liczy się tylko w bieżącym oknie, więc limit
„zeruje się” automatycznie w chwili rozpoczęcia nowego okna – bez zadań w tle.
Po wyczerpaniu limitu (limit + doładowania potwierdzone w tym oknie) odpowiedzi czatu generuje
model lokalny (LOCAL_LLM_*); embeddingi i transkrypcja zostają u dostawcy (liczone w kosztach).
"""

import json
import logging
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import settings
from .database import CreditTopUp, TokenUsage, User, UserSubscription, session_factory, utcnow

logger = logging.getLogger(__name__)

# Cennik dostawcy (USD za 1 mln tokenów: wejście, wyjście). Uzupełnij/nadpisz w BILLING_PRICES_JSON.
# whisper-1 rozliczany za czas nagrania: 1 „token” = 1 s (0,006 USD/min = 100 USD/1 mln s).
DEFAULT_PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "whisper-1": (100.0, 0.0),
    "gpt-4o-mini-transcribe": (1.25, 5.00),
    "gpt-4o-transcribe": (2.50, 10.00),
}


@lru_cache
def price_table() -> dict[str, tuple[float, float]]:
    prices = dict(DEFAULT_PRICES)
    if settings.billing_prices_json.strip():
        try:
            for model, pair in json.loads(settings.billing_prices_json).items():
                prices[str(model)] = (float(pair[0]), float(pair[1]))
        except (ValueError, TypeError, IndexError, AttributeError):
            logger.error("Nieprawidłowy BILLING_PRICES_JSON – używam cennika domyślnego")
    return prices


def model_price(model: str) -> tuple[float, float]:
    """Cena modelu; nazwy z datą wersji (gpt-4o-mini-2024-07-18) – najdłuższy pasujący prefiks."""
    prices = price_table()
    name = model.lower().split("/")[-1]
    if name in prices:
        return prices[name]
    matches = [key for key in prices if name.startswith(key)]
    return prices[max(matches, key=len)] if matches else (0.0, 0.0)


def cost_pln(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    price_in, price_out = model_price(model)
    usd = (prompt_tokens * price_in + completion_tokens * price_out) / 1_000_000
    return usd * settings.billing_usd_pln_rate * settings.billing_margin


def to_credits(pln: float) -> int:
    """Złotówki → kredyty (domyślnie 1 kredyt = 0,01 zł), zaokrąglone do pełnego kredytu."""
    return round(pln * settings.billing_credits_per_pln)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def add_months(value: datetime, months: int) -> datetime:
    index = value.month - 1 + months
    year, month = value.year + index // 12, index % 12 + 1
    return value.replace(year=year, month=month, day=min(value.day, monthrange(year, month)[1]))


def current_window(started_at: datetime, now: datetime) -> tuple[datetime, datetime]:
    """Bieżące okno [początek, koniec) – liczone zawsze od daty startu (bez dryfu dni)."""
    started_at, now = _aware(started_at), _aware(now)
    if now < started_at:
        return started_at, add_months(started_at, 1)
    months = (now.year - started_at.year) * 12 + now.month - started_at.month
    if add_months(started_at, months) > now:
        months -= 1
    return add_months(started_at, months), add_months(started_at, months + 1)


@dataclass(frozen=True)
class CreditStatus:
    user_id: int
    started_at: datetime
    window_start: datetime
    window_end: datetime
    limit_pln: float
    topups_pln: float
    used_pln: float

    @property
    def available_pln(self) -> float:
        return self.limit_pln + self.topups_pln

    @property
    def used_credits(self) -> int:
        return to_credits(self.used_pln)

    @property
    def available_credits(self) -> int:
        return to_credits(self.limit_pln) + to_credits(self.topups_pln)

    @property
    def remaining_credits(self) -> int:
        return max(0, self.available_credits - self.used_credits)

    @property
    def remaining_pln(self) -> float:
        return max(0.0, self.available_pln - self.used_pln)

    @property
    def percent(self) -> float:
        return (
            100.0
            if self.available_pln <= 0
            else min(100.0, 100 * self.used_pln / self.available_pln)
        )

    @property
    def exhausted(self) -> bool:
        return self.used_pln >= self.available_pln


async def subscription_for(session: AsyncSession, user: User) -> UserSubscription:
    """Subskrypcja użytkownika (domyślna – od daty założenia konta, niezapisana)."""
    row = await session.get(UserSubscription, user.id)
    if row is not None:
        return row
    return UserSubscription(
        user_id=user.id,  # type: ignore[arg-type]
        started_at=_aware(user.created_at),
        monthly_limit_pln=settings.billing_default_limit_pln,
    )


async def credit_status(
    session: AsyncSession, user: User, now: datetime | None = None
) -> CreditStatus:
    subscription = await subscription_for(session, user)
    start, end = current_window(subscription.started_at, now or utcnow())
    usage = await session.exec(
        select(
            TokenUsage.model_name,
            func.sum(TokenUsage.prompt_tokens),
            func.sum(TokenUsage.completion_tokens),
        )
        .where(
            TokenUsage.user_id == user.id,
            col(TokenUsage.timestamp) >= start,
            col(TokenUsage.timestamp) < end,
        )
        .group_by(TokenUsage.model_name)
    )
    used = sum(cost_pln(model, int(p or 0), int(c or 0)) for model, p, c in usage.all())
    topups = (
        await session.exec(
            select(func.sum(CreditTopUp.amount_pln)).where(
                CreditTopUp.user_id == user.id,
                CreditTopUp.status == "confirmed",
                col(CreditTopUp.confirmed_at) >= start,
                col(CreditTopUp.confirmed_at) < end,
            )
        )
    ).one()
    return CreditStatus(
        user_id=user.id,  # type: ignore[arg-type]
        started_at=_aware(subscription.started_at),
        window_start=start,
        window_end=end,
        limit_pln=subscription.monthly_limit_pln,
        topups_pln=float(topups or 0),
        used_pln=round(used, 4),
    )


_FALLBACK_TTL_SECONDS = 30.0
_fallback_cache: dict[int, tuple[float, bool]] = {}


def invalidate(user_id: int | None = None) -> None:
    """Czyści pamięć decyzji o modelu (np. po doładowaniu albo zmianie limitu)."""
    if user_id is None:
        _fallback_cache.clear()
    else:
        _fallback_cache.pop(user_id, None)


async def use_local_model(user_id: int | None) -> bool:
    """Czy czat użytkownika idzie do modelu lokalnego (limit wyczerpany, model skonfigurowany)."""
    if user_id is None or not settings.local_llm_base_url:
        return False
    cached = _fallback_cache.get(user_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        async with session_factory() as session:
            user = await session.get(User, user_id)
            exhausted = user is not None and (await credit_status(session, user)).exhausted
    except Exception:
        logger.exception("Nie udało się sprawdzić limitu kredytów (user=%s)", user_id)
        exhausted = False
    _fallback_cache[user_id] = (time.monotonic() + _FALLBACK_TTL_SECONDS, exhausted)
    return exhausted
