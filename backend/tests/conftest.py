import os
import tempfile
from pathlib import Path

_tmp = Path(tempfile.mkdtemp(prefix="logoped-tests-"))
os.environ.update(
    {
        "DB_URL": f"sqlite+aiosqlite:///{(_tmp / 'test.db').as_posix()}",
        "VLLM_BASE_URL": "http://vllm.invalid/v1",
        "VLLM_API_KEY": "test-key",
        "VLLM_CHAT_MODEL": "test-chat-model",
        "VLLM_EMBEDDING_MODEL": "test-embedding-model",
        "WHISPER_API_URL": "http://whisper.invalid/v1/audio/transcriptions",
        "JWT_SECRET": "test-secret-test-secret-test-secret-123",
        "ADMIN_PASSWORD": "AdminPassword123!",
        "QDRANT_URL": "http://qdrant.invalid:6333",
    }
)

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlmodel import SQLModel  # noqa: E402

from src.auth import hash_password  # noqa: E402
from src.database import Role, User, engine, session_factory  # noqa: E402
from src.main import create_app  # noqa: E402


@pytest_asyncio.fixture(autouse=True)
async def _database():
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
        await conn.run_sync(SQLModel.metadata.create_all)
    yield


@pytest_asyncio.fixture
async def client():
    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def create_user(email: str, password: str, role: Role = Role.DOCTOR) -> User:
    async with session_factory() as session:
        user = User(
            email=email,
            full_name=f"Test {email}",
            hashed_password=await hash_password(password),
            role=role.value,
        )
        session.add(user)
        await session.commit()
        await session.refresh(user)
        return user


async def login_headers(client: httpx.AsyncClient, email: str, password: str) -> dict[str, str]:
    response = await client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def make_headers(client):
    async def factory(email: str, role: Role = Role.DOCTOR) -> dict[str, str]:
        await create_user(email, "Password123!", role)
        return await login_headers(client, email, "Password123!")

    return factory
