"""Testy jakości asystenta (goldset) – tylko administrator."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import col, delete, select

from .. import goldset
from ..auth import CurrentAdmin, SessionDep
from ..database import GoldsetItem, GoldsetResult, GoldsetRun, utcnow
from .schemas import (
    GoldsetItemIn,
    GoldsetItemOut,
    GoldsetParseIn,
    GoldsetReplaceIn,
    GoldsetResultOut,
    GoldsetRunDetailOut,
    GoldsetRunIn,
    GoldsetRunOut,
)

router = APIRouter(prefix="/admin/goldset", tags=["goldset"])

PARSE_HINT = (
    "Nie rozpoznano par pytanie–odpowiedź. Format: najpierw pytania „1. Tytuł” z treścią, "
    "potem odpowiedzi „1. Tytuł” z krokami."
)


async def _items(session: SessionDep) -> list[GoldsetItem]:
    rows = await session.exec(
        select(GoldsetItem).order_by(col(GoldsetItem.position), col(GoldsetItem.id))
    )
    return list(rows.all())


@router.get("", response_model=list[GoldsetItemOut])
async def list_items(session: SessionDep, admin: CurrentAdmin) -> list[GoldsetItem]:
    return await _items(session)


@router.post("/parse", response_model=list[GoldsetItemIn])
async def parse(body: GoldsetParseIn, admin: CurrentAdmin) -> list[dict]:
    """Podgląd: rozbija wklejony tekst na pary pytanie–odpowiedź wzorcowa (nic nie zapisuje)."""
    items = [i for i in goldset.parse_goldset(body.text) if i["question"] and i["reference_answer"]]
    if not items:
        raise HTTPException(422, PARSE_HINT)
    return [
        {"title": i["title"], "question": i["question"], "reference_answer": i["reference_answer"]}
        for i in items
    ]


@router.put("", response_model=list[GoldsetItemOut])
async def replace_items(
    body: GoldsetReplaceIn, session: SessionDep, admin: CurrentAdmin
) -> list[GoldsetItem]:
    """Zastępuje cały goldset (wyniki wcześniejszych przebiegów zostają – mają kopie pytań)."""
    await session.exec(delete(GoldsetItem))
    for position, item in enumerate(body.items):
        session.add(
            GoldsetItem(
                position=position,
                title=item.title.strip(),
                question=item.question.strip(),
                reference_answer=item.reference_answer.strip(),
            )
        )
    await session.commit()
    return await _items(session)


@router.put("/{item_id}", response_model=GoldsetItemOut)
async def update_item(
    item_id: int, body: GoldsetItemIn, session: SessionDep, admin: CurrentAdmin
) -> GoldsetItem:
    item = await session.get(GoldsetItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono pytania")
    item.title = body.title.strip()
    item.question = body.question.strip()
    item.reference_answer = body.reference_answer.strip()
    item.updated_at = utcnow()
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return item


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_item(item_id: int, session: SessionDep, admin: CurrentAdmin) -> Response:
    await session.exec(delete(GoldsetItem).where(col(GoldsetItem.id) == item_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _mark_interrupted(session: SessionDep, run: GoldsetRun) -> GoldsetRun:
    """Przebieg „running” bez aktywnego zadania (np. po restarcie serwera) → przerwany."""
    if run.status == "running" and not goldset.is_running(run.id):  # type: ignore[arg-type]
        run.status = "failed"
        run.finished_at = run.finished_at or utcnow()
        session.add(run)
        await session.commit()
        await session.refresh(run)
    return run


@router.post("/runs", response_model=GoldsetRunOut, status_code=status.HTTP_201_CREATED)
async def start_run(body: GoldsetRunIn, session: SessionDep, admin: CurrentAdmin) -> GoldsetRun:
    """Uruchamia test w tle (postęp: GET /runs/{id}); koszt LLM – w kredytach administratora."""
    if goldset.any_running():
        raise HTTPException(status.HTTP_409_CONFLICT, "Test jest już w toku – poczekaj na wynik")
    if not await _items(session):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Goldset jest pusty – najpierw zaimportuj pytania"
        )
    return await goldset.start_run(admin.id, body.item_ids, body.note)  # type: ignore[arg-type]


@router.get("/runs", response_model=list[GoldsetRunOut])
async def list_runs(session: SessionDep, admin: CurrentAdmin) -> list[GoldsetRun]:
    query = select(GoldsetRun).order_by(col(GoldsetRun.started_at).desc()).limit(100)
    return [await _mark_interrupted(session, run) for run in (await session.exec(query)).all()]


@router.get("/runs/{run_id}", response_model=GoldsetRunDetailOut)
async def run_detail(run_id: int, session: SessionDep, admin: CurrentAdmin) -> GoldsetRunDetailOut:
    run = await session.get(GoldsetRun, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono przebiegu")
    run = await _mark_interrupted(session, run)
    results = (
        await session.exec(
            select(GoldsetResult)
            .where(GoldsetResult.run_id == run_id)
            .order_by(col(GoldsetResult.score), col(GoldsetResult.id))
        )
    ).all()
    return GoldsetRunDetailOut(
        run=GoldsetRunOut.model_validate(run),
        results=[GoldsetResultOut.model_validate(r) for r in results],
    )


@router.post("/runs/{run_id}/cancel", response_model=GoldsetRunOut)
async def cancel(run_id: int, session: SessionDep, admin: CurrentAdmin) -> GoldsetRun:
    if not goldset.cancel_run(run_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Ten przebieg nie jest w toku")
    run = await session.get(GoldsetRun, run_id)
    return run  # type: ignore[return-value]


@router.delete("/runs/{run_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_run(run_id: int, session: SessionDep, admin: CurrentAdmin) -> Response:
    if goldset.is_running(run_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Najpierw zatrzymaj przebieg")
    await session.exec(delete(GoldsetResult).where(col(GoldsetResult.run_id) == run_id))
    await session.exec(delete(GoldsetRun).where(col(GoldsetRun.id) == run_id))
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
