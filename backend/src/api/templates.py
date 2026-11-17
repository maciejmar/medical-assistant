"""Szablony promptów (pastylki w czacie): lista wspólnych i własnych, edycja, kopiowanie,
sprawdzenie, które ćwiczenia szablonu mają opis w katalogu."""

from fastapi import APIRouter, HTTPException, Response, status
from sqlmodel import col, select

from .. import templates
from ..auth import CurrentDoctor, SessionDep
from ..database import KbDocument, PromptTemplate, Role, User, utcnow
from ..exercises import match_names
from .schemas import TemplateCoverageIn, TemplateCoverageOut, TemplateIn, TemplateOut

router = APIRouter(prefix="/templates", tags=["templates"])


def _is_admin(user: User) -> bool:
    return user.role == Role.ADMIN.value


def _can_edit(template: PromptTemplate, user: User) -> bool:
    if template.owner_id is None:
        return _is_admin(user)
    return template.owner_id == user.id


def _out(template: PromptTemplate, user: User) -> TemplateOut:
    return TemplateOut(
        id=template.id,  # type: ignore[arg-type]
        name=template.name,
        description=template.description,
        body=template.body,
        requires_patient=template.requires_patient,
        long_answer=template.long_answer,
        position=template.position,
        shared=template.owner_id is None,
        editable=_can_edit(template, user),
        updated_at=template.updated_at,
    )


async def _editable(session: SessionDep, template_id: int, user: User) -> PromptTemplate:
    template = await session.get(PromptTemplate, template_id)
    if template is None or not template.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono szablonu")
    if not _can_edit(template, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Nie możesz edytować tego szablonu")
    return template


@router.get("", response_model=list[TemplateOut])
async def list_templates(session: SessionDep, user: CurrentDoctor) -> list[TemplateOut]:
    return [_out(t, user) for t in await templates.visible_templates(session, user.id)]  # type: ignore[arg-type]


@router.post("", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    body: TemplateIn, session: SessionDep, user: CurrentDoctor
) -> TemplateOut:
    if body.shared and not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Szablony wspólne tworzy administrator")
    template = PromptTemplate(
        owner_id=None if body.shared else user.id,
        **body.model_dump(exclude={"shared"}),
    )
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return _out(template, user)


@router.put("/{template_id}", response_model=TemplateOut)
async def update_template(
    template_id: int, body: TemplateIn, session: SessionDep, user: CurrentDoctor
) -> TemplateOut:
    template = await _editable(session, template_id, user)
    for field, value in body.model_dump(exclude={"shared"}).items():
        setattr(template, field, value.strip() if isinstance(value, str) else value)
    template.updated_at = utcnow()
    session.add(template)
    await session.commit()
    await session.refresh(template)
    return _out(template, user)


@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(template_id: int, session: SessionDep, user: CurrentDoctor) -> Response:
    template = await _editable(session, template_id, user)
    if template.seed_key:
        # Szablon startowy jest tylko ukrywany – inaczej wróciłby przy kolejnym uruchomieniu.
        template.active = False
        session.add(template)
    else:
        await session.delete(template)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{template_id}/copy", response_model=TemplateOut, status_code=status.HTTP_201_CREATED)
async def copy_template(template_id: int, session: SessionDep, user: CurrentDoctor) -> TemplateOut:
    """Kopia szablonu (np. wspólnego) jako własny szablon do przerobienia."""
    source = await templates.template_for_user(session, template_id, user.id)  # type: ignore[arg-type]
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono szablonu")
    copy = PromptTemplate(
        owner_id=user.id,
        name=f"{source.name} (moja)"[:80],
        description=source.description,
        body=source.body,
        requires_patient=source.requires_patient,
        long_answer=source.long_answer,
        position=source.position,
    )
    session.add(copy)
    await session.commit()
    await session.refresh(copy)
    return _out(copy, user)


@router.post("/coverage", response_model=list[TemplateCoverageOut])
async def coverage(
    body: TemplateCoverageIn, session: SessionDep, user: CurrentDoctor
) -> list[TemplateCoverageOut]:
    """Które ćwiczenia (wiersze z punktorem) mają opis w katalogu ćwiczeń z bazy wiedzy."""
    names = templates.template_exercise_names(body.body)
    if not names:
        return []
    results = await match_names(session, names, user.id)  # type: ignore[arg-type]
    doc_ids = {r["exercise"].document_id for r in results if r["exercise"]}
    titles = dict(
        (
            await session.exec(
                select(KbDocument.id, KbDocument.title).where(col(KbDocument.id).in_(doc_ids))
            )
        ).all()
    )
    out = []
    for r in results:
        exercise = r["exercise"]
        if exercise is None:
            out.append(TemplateCoverageOut(name=r["name"], found=False))
            continue
        page = f", s. {exercise.page}" if exercise.page else ""
        out.append(
            TemplateCoverageOut(
                name=r["name"],
                found=True,
                exercise_name=exercise.name,
                source=f"{titles.get(exercise.document_id, '')}{page}",
            )
        )
    return out
