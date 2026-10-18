import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlmodel import select

from .api.router import api_router
from .auth import hash_password
from .config import settings
from .database import Role, User, init_db, session_factory
from .kb_import import job as import_job
from .kb_import import watch_directory
from .llm import drain_background_tasks, purge_old_llm_calls
from .seed import seed_with_retries
from .vector_store import reranker, vector_store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def ensure_admin() -> None:
    email = settings.admin_email.lower()
    async with session_factory() as session:
        existing = (await session.exec(select(User).where(User.email == email))).first()
        if existing:
            if existing.role != Role.ADMIN.value:
                existing.role = Role.ADMIN.value
                session.add(existing)
                await session.commit()
                logger.info("Nadano rolę administratora istniejącemu kontu %s", email)
            return
        session.add(
            User(
                email=email,
                full_name="Administrator",
                hashed_password=await hash_password(settings.admin_password),
                role=Role.ADMIN.value,
            )
        )
        await session.commit()
        logger.info("Utworzono konto administratora %s", email)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await init_db()
    await ensure_admin()
    await purge_old_llm_calls()
    background: list[asyncio.Task] = [asyncio.create_task(reranker.warmup())]
    if settings.seed_on_startup:
        background.append(asyncio.create_task(seed_with_retries()))
    if settings.kb_scan_interval_seconds > 0:
        background.append(
            asyncio.create_task(
                watch_directory(Path(settings.kb_source_dir), settings.kb_scan_interval_seconds)
            )
        )
    try:
        yield
    finally:
        if import_job.task is not None:
            background.append(import_job.task)
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        await drain_background_tasks()
        await vector_store.close()


def create_app() -> FastAPI:
    app = FastAPI(title=settings.app_name, version="1.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/api/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
