"""Klient zewnętrznego vLLM (oficjalne async SDK OpenAI) z rejestrowaniem zużycia tokenów
oraz pełnej treści żądań i odpowiedzi (tabela llm_calls, wgląd w panelu administratora)."""

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from openai import AsyncOpenAI
from sqlmodel import col, delete

from .anonymizer import anonymizer_for
from .config import settings
from .database import LlmCall, TokenUsage, session_factory, utcnow

logger = logging.getLogger(__name__)

client = AsyncOpenAI(
    base_url=settings.vllm_base_url,
    api_key=settings.vllm_api_key,
    timeout=settings.llm_timeout_seconds,
    max_retries=2,
)

_background_tasks: set[asyncio.Task] = set()


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass(frozen=True)
class Completion:
    text: str
    usage: Usage


async def _persist_usage(user_id: int | None, model: str, operation: str, usage: Usage) -> None:
    try:
        async with session_factory() as session:
            session.add(
                TokenUsage(
                    user_id=user_id,
                    model_name=model,
                    operation=operation,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                )
            )
            await session.commit()
    except Exception:
        logger.exception("Nie udało się zapisać zużycia tokenów (operacja=%s)", operation)


def _in_background(coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def track_usage(user_id: int | None, model: str, operation: str, usage: Usage) -> None:
    """Zapisuje metryki w tle, bez blokowania odpowiedzi dla użytkownika."""
    _in_background(_persist_usage(user_id, model, operation, usage))


def _clip(text: str) -> str:
    limit = settings.llm_log_max_chars
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…[obcięto {len(text) - limit} znaków]"


async def _persist_call(call: LlmCall) -> None:
    try:
        async with session_factory() as session:
            session.add(call)
            await session.commit()
    except Exception:
        logger.exception("Nie udało się zapisać logu wywołania LLM (operacja=%s)", call.operation)


def log_call(
    *,
    user_id: int | None,
    model: str,
    operation: str,
    request: list | dict,
    response: str,
    usage: Usage,
    started: float,
    error: BaseException | None = None,
) -> None:
    """Zapisuje w tle pełną treść żądania i odpowiedzi LLM."""
    if not settings.llm_log_enabled:
        return
    if isinstance(request, list):
        request = [
            {**m, "content": _clip(str(m.get("content", "")))} if isinstance(m, dict) else m
            for m in request
        ]
    call = LlmCall(
        user_id=user_id,
        model_name=model,
        operation=operation,
        request=request,
        response=_clip(response),
        status="error" if error else "ok",
        error=f"{type(error).__name__}: {error}"[:1000] if error else None,
        prompt_tokens=usage.prompt_tokens,
        completion_tokens=usage.completion_tokens,
        total_tokens=usage.total_tokens,
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    _in_background(_persist_call(call))


async def purge_old_llm_calls() -> None:
    """Usuwa logi treści wywołań LLM starsze niż LLM_LOG_RETENTION_DAYS (0 = bez limitu)."""
    if settings.llm_log_retention_days <= 0:
        return
    cutoff = utcnow() - timedelta(days=settings.llm_log_retention_days)
    try:
        async with session_factory() as session:
            await session.exec(delete(LlmCall).where(col(LlmCall.timestamp) < cutoff))
            await session.commit()
    except Exception:
        logger.exception("Nie udało się usunąć starych logów wywołań LLM")


async def drain_background_tasks() -> None:
    if _background_tasks:
        await asyncio.gather(*list(_background_tasks), return_exceptions=True)


def _usage_from(raw) -> Usage:
    if raw is None:
        return Usage()
    prompt = int(getattr(raw, "prompt_tokens", 0) or 0)
    completion = int(getattr(raw, "completion_tokens", 0) or 0)
    total = int(getattr(raw, "total_tokens", 0) or 0) or prompt + completion
    return Usage(prompt, completion, total)


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


async def chat_complete(
    messages: list[dict[str, str]],
    *,
    user_id: int | None,
    operation: str,
    temperature: float = 0.0,
    max_tokens: int = 400,
) -> Completion:
    started = time.monotonic()
    messages = (await anonymizer_for(user_id)).messages(messages)
    try:
        response = await client.chat.completions.create(
            model=settings.vllm_chat_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
        )
    except Exception as exc:
        log_call(
            user_id=user_id,
            model=settings.vllm_chat_model,
            operation=operation,
            request=messages,
            response="",
            usage=Usage(),
            started=started,
            error=exc,
        )
        raise
    usage = _usage_from(response.usage)
    model_name = response.model or settings.vllm_chat_model
    track_usage(user_id, model_name, operation, usage)
    text = (response.choices[0].message.content if response.choices else "") or ""
    log_call(
        user_id=user_id,
        model=model_name,
        operation=operation,
        request=messages,
        response=text,
        usage=usage,
        started=started,
    )
    return Completion(text=text, usage=usage)


async def chat_stream(
    messages: list[dict[str, str]],
    *,
    user_id: int | None,
    operation: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> AsyncIterator[str | Usage]:
    """Zwraca kolejne fragmenty tekstu, a na końcu obiekt Usage z metrykami ze streamu vLLM."""
    started = time.monotonic()
    messages = (await anonymizer_for(user_id)).messages(messages)
    model_name = settings.vllm_chat_model
    try:
        stream = await client.chat.completions.create(
            model=settings.vllm_chat_model,
            messages=messages,  # type: ignore[arg-type]
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
    except Exception as exc:
        log_call(
            user_id=user_id,
            model=model_name,
            operation=operation,
            request=messages,
            response="",
            usage=Usage(),
            started=started,
            error=exc,
        )
        raise
    raw_usage = None
    collected: list[str] = []
    failure: BaseException | None = None
    try:
        async for chunk in stream:
            model_name = chunk.model or model_name
            if getattr(chunk, "usage", None) is not None:
                raw_usage = chunk.usage
            if chunk.choices:
                delta = chunk.choices[0].delta.content
                if delta:
                    collected.append(delta)
                    yield delta
    except BaseException as exc:
        failure = exc
        raise
    finally:
        if raw_usage is not None:
            usage = _usage_from(raw_usage)
        else:
            # Serwer nie zwrócił statystyk – zapisujemy oszacowanie (~4 znaki na token).
            prompt_chars = sum(len(m["content"]) for m in messages)
            prompt = max(1, prompt_chars // 4)
            completion = _estimate_tokens("".join(collected)) if collected else 0
            usage = Usage(prompt, completion, prompt + completion)
        track_usage(user_id, model_name, operation, usage)
        log_call(
            user_id=user_id,
            model=model_name,
            operation=operation,
            request=messages,
            response="".join(collected),
            usage=usage,
            started=started,
            error=failure,
        )
    yield usage


async def embed(
    texts: list[str], *, user_id: int | None, operation: str
) -> tuple[list[list[float]], Usage]:
    started = time.monotonic()
    if user_id is not None:  # treści systemowe (seeding bazy wiedzy) nie zawierają danych osób
        anonymize = await anonymizer_for(user_id)
        texts = [anonymize(t) for t in texts]
    request = {"input": [_clip(t) for t in texts]}
    try:
        response = await client.embeddings.create(model=settings.vllm_embedding_model, input=texts)
    except Exception as exc:
        log_call(
            user_id=user_id,
            model=settings.vllm_embedding_model,
            operation=operation,
            request=request,
            response="",
            usage=Usage(),
            started=started,
            error=exc,
        )
        raise
    ordered = sorted(response.data, key=lambda item: item.index)
    usage = _usage_from(response.usage)
    track_usage(user_id, settings.vllm_embedding_model, operation, usage)
    dims = len(ordered[0].embedding) if ordered else 0
    log_call(
        user_id=user_id,
        model=settings.vllm_embedding_model,
        operation=operation,
        request=request,
        response=f"[{len(ordered)} wektor(y) o wymiarze {dims}]",
        usage=usage,
        started=started,
    )
    return [item.embedding for item in ordered], usage
