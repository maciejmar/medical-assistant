"""Automatyczne zasilanie bazy Qdrant danymi logopedycznymi (idempotentne).

Uruchomienie ręczne: python -m src.seed [--force]
"""

import asyncio
import logging
import sys
import uuid

from .config import settings
from .llm import drain_background_tasks, embed
from .seed_data import DOCUMENTS
from .vector_store import vector_store

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("6f1c7a52-3b7e-4d0a-9f0e-3c2f8b6a1d10")
_BATCH = 16


def document_id(key: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, key))


def embedding_text(doc: dict[str, str]) -> str:
    codes = " ".join(c for c in (doc["icd10"], doc["icd11"]) if c)
    return f"{doc['title']}\n{doc['text']}\nKody: {codes}\nSłowa kluczowe: {doc['tags']}"


async def seed_knowledge_base(force: bool = False) -> int:
    """Zwraca liczbę wczytanych dokumentów (0, gdy baza jest już zasilona)."""
    if not force and await vector_store.count() >= len(DOCUMENTS):
        logger.info("Baza wiedzy Qdrant jest już zasilona – pomijam seeding")
        return 0

    inserted = 0
    for start in range(0, len(DOCUMENTS), _BATCH):
        batch = DOCUMENTS[start : start + _BATCH]
        vectors, _ = await embed(
            [embedding_text(d) for d in batch], user_id=None, operation="seed_embedding"
        )
        if start == 0:
            await vector_store.ensure_collection(len(vectors[0]))
        await vector_store.upsert(
            [
                (
                    document_id(doc["key"]),
                    vector,
                    embedding_text(doc),
                    {
                        "key": doc["key"],
                        "title": doc["title"],
                        "text": doc["text"],
                        "category": doc["category"],
                        "audience": doc["audience"],
                        "icd10": doc["icd10"],
                        "icd11": doc["icd11"],
                        "tags": doc["tags"],
                    },
                )
                for doc, vector in zip(batch, vectors, strict=True)
            ]
        )
        inserted += len(batch)
    logger.info("Zasilono bazę wiedzy: %d dokumentów", inserted)
    return inserted


async def seed_with_retries() -> None:
    """Start aplikacji nie może zależeć od chwilowej dostępności vLLM/Qdrant – ponawiamy próby."""
    for attempt in range(1, settings.seed_max_attempts + 1):
        try:
            await seed_knowledge_base()
            return
        except asyncio.CancelledError:
            raise
        except Exception:
            delay = min(60, 5 * attempt)
            logger.exception(
                "Seeding nieudany (próba %d/%d), ponowię za %ds",
                attempt,
                settings.seed_max_attempts,
                delay,
            )
            await asyncio.sleep(delay)
    logger.error("Seeding bazy wiedzy nie powiódł się – uruchom ręcznie: python -m src.seed")


async def _main() -> None:
    logging.basicConfig(level=logging.INFO)
    await seed_knowledge_base(force="--force" in sys.argv)
    await drain_background_tasks()
    await vector_store.close()


if __name__ == "__main__":
    asyncio.run(_main())
