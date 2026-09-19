"""Qdrant (wyszukiwanie hybrydowe: gęste + rzadkie, fuzja RRF) oraz reranking Cross-Encoderem."""

import asyncio
import logging
import math
import re
import zlib
from collections import Counter
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from .config import settings

logger = logging.getLogger(__name__)

DENSE = "dense"
SPARSE = "sparse"

ALLOWED_CATEGORIES = {"disorder", "icd", "technique", "diagnostics"}
ALLOWED_AUDIENCES = {"children", "adults"}

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_STEM_LEN = 6


def sparse_vector(text: str) -> models.SparseVector:
    """Rzadki wektor leksykalny (hash tokenów po przycięciu do prefiksu ~ prosty stemming).

    IDF jest naliczany po stronie Qdrant (modifier=IDF), więc wartości to tylko TF.
    """
    tokens = [t[:_STEM_LEN] for t in _TOKEN_RE.findall(text.lower()) if len(t) > 1]
    counts = Counter(zlib.crc32(t.encode("utf-8")) for t in tokens)
    indices = sorted(counts)
    values = [1.0 + math.log(counts[i]) for i in indices]
    return models.SparseVector(indices=indices, values=values)


def build_filter(filters: dict[str, str] | None) -> models.Filter | None:
    if not filters:
        return None
    must: list[models.Condition] = []
    category = filters.get("category")
    if category in ALLOWED_CATEGORIES:
        must.append(models.FieldCondition(key="category", match=models.MatchValue(value=category)))
    audience = filters.get("audience")
    if audience in ALLOWED_AUDIENCES:
        must.append(
            models.FieldCondition(key="audience", match=models.MatchAny(any=[audience, "all"]))
        )
    return models.Filter(must=must) if must else None


class VectorStore:
    def __init__(self) -> None:
        self.client = AsyncQdrantClient(url=settings.qdrant_url, timeout=30)
        self.collection = settings.qdrant_collection

    async def ensure_collection(self, dimension: int) -> None:
        if await self.client.collection_exists(self.collection):
            return
        await self.client.create_collection(
            collection_name=self.collection,
            vectors_config={
                DENSE: models.VectorParams(size=dimension, distance=models.Distance.COSINE)
            },
            sparse_vectors_config={SPARSE: models.SparseVectorParams(modifier=models.Modifier.IDF)},
        )
        for field in ("category", "audience", "icd10"):
            await self.client.create_payload_index(
                self.collection, field_name=field, field_schema=models.PayloadSchemaType.KEYWORD
            )

    async def count(self) -> int:
        if not await self.client.collection_exists(self.collection):
            return 0
        return (await self.client.count(self.collection, exact=True)).count

    async def upsert(self, points: list[tuple[str, list[float], str, dict[str, Any]]]) -> None:
        """points: (id, wektor gęsty, tekst do wektora rzadkiego, payload)."""
        await self.client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(
                    id=point_id,
                    vector={DENSE: dense, SPARSE: sparse_vector(text)},
                    payload=payload,
                )
                for point_id, dense, text, payload in points
            ],
            wait=True,
        )

    async def hybrid_search(
        self,
        query: str,
        dense: list[float],
        *,
        filters: dict[str, str] | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        limit = limit or settings.retrieval_top_k
        flt = build_filter(filters)
        result = await self.client.query_points(
            collection_name=self.collection,
            prefetch=[
                models.Prefetch(query=dense, using=DENSE, limit=limit * 2, filter=flt),
                models.Prefetch(
                    query=sparse_vector(query), using=SPARSE, limit=limit * 2, filter=flt
                ),
            ],
            query=models.FusionQuery(fusion=models.Fusion.RRF),
            limit=limit,
            with_payload=True,
        )
        return [
            {**(p.payload or {}), "id": str(p.id), "fusion_score": p.score} for p in result.points
        ]

    async def close(self) -> None:
        await self.client.close()


class Reranker:
    """Lokalny Cross-Encoder (sentence-transformers) odfiltrowujący szum przed generacją."""

    def __init__(self) -> None:
        self._model = None
        self._failed = False
        self._lock = asyncio.Lock()

    async def _get_model(self):
        if self._model is not None or self._failed:
            return self._model
        async with self._lock:
            if self._model is None and not self._failed:
                try:
                    self._model = await asyncio.to_thread(self._load)
                except Exception:
                    logger.exception("Nie udało się załadować rerankera – używam kolejności RRF")
                    self._failed = True
        return self._model

    @staticmethod
    def _load():
        from sentence_transformers import CrossEncoder

        return CrossEncoder(settings.reranker_model, max_length=512)

    async def warmup(self) -> None:
        await self._get_model()

    async def rerank(
        self, query: str, docs: list[dict[str, Any]], top_n: int | None = None
    ) -> list[dict[str, Any]]:
        top_n = top_n or settings.rerank_top_n
        if not docs:
            return []
        model = await self._get_model()
        if model is None:
            return [{**d, "score": d.get("fusion_score", 0.0)} for d in docs[:top_n]]

        pairs = [(query, f"{d['title']}. {d['text']}") for d in docs]
        raw_scores = await asyncio.to_thread(lambda: model.predict(pairs, show_progress_bar=False))
        scored = []
        for doc, raw in zip(docs, raw_scores, strict=True):
            score = 1.0 / (1.0 + math.exp(-float(raw)))
            scored.append({**doc, "score": score})
        scored.sort(key=lambda d: d["score"], reverse=True)
        return [d for d in scored[:top_n] if d["score"] >= settings.rerank_min_score]


vector_store = VectorStore()
reranker = Reranker()
