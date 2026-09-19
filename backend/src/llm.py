"""Klient zewnętrznego vLLM (oficjalne async SDK OpenAI) z rejestrowaniem zużycia tokenów."""

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

from openai import AsyncOpenAI

from .config import settings
from .database import TokenUsage, session_factory

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


def track_usage(user_id: int | None, model: str, operation: str, usage: Usage) -> None:
    """Zapisuje metryki w tle, bez blokowania odpowiedzi dla użytkownika."""
    task = asyncio.create_task(_persist_usage(user_id, model, operation, usage))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


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
    response = await client.chat.completions.create(
        model=settings.vllm_chat_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
    )
    usage = _usage_from(response.usage)
    track_usage(user_id, response.model or settings.vllm_chat_model, operation, usage)
    text = response.choices[0].message.content if response.choices else ""
    return Completion(text=text or "", usage=usage)


async def chat_stream(
    messages: list[dict[str, str]],
    *,
    user_id: int | None,
    operation: str,
    temperature: float = 0.2,
    max_tokens: int = 1200,
) -> AsyncIterator[str | Usage]:
    """Zwraca kolejne fragmenty tekstu, a na końcu obiekt Usage z metrykami ze streamu vLLM."""
    stream = await client.chat.completions.create(
        model=settings.vllm_chat_model,
        messages=messages,  # type: ignore[arg-type]
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        stream_options={"include_usage": True},
    )
    model_name = settings.vllm_chat_model
    raw_usage = None
    collected: list[str] = []
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
    yield usage


async def embed(
    texts: list[str], *, user_id: int | None, operation: str
) -> tuple[list[list[float]], Usage]:
    response = await client.embeddings.create(model=settings.vllm_embedding_model, input=texts)
    ordered = sorted(response.data, key=lambda item: item.index)
    usage = _usage_from(response.usage)
    track_usage(user_id, settings.vllm_embedding_model, operation, usage)
    return [item.embedding for item in ordered], usage
