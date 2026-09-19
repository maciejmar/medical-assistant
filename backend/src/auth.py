import asyncio
from collections.abc import Callable
from datetime import timedelta
from typing import Annotated

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from .config import settings
from .database import Role, User, get_session, utcnow

_bearer = HTTPBearer(auto_error=False)

_DUMMY_HASH = bcrypt.hashpw(b"dummy-password", bcrypt.gensalt()).decode()


def _hash_sync(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def _verify_sync(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


async def hash_password(password: str) -> str:
    return await asyncio.to_thread(_hash_sync, password)


async def verify_password(password: str, hashed: str | None) -> bool:
    """Sprawdza hasło. Dla nieistniejącego konta wykonuje pozorne porównanie (ten sam czas)."""
    matches = await asyncio.to_thread(_verify_sync, password, hashed or _DUMMY_HASH)
    return matches and hashed is not None


def create_access_token(user: User) -> str:
    now = utcnow()
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "sub"]},
    )


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nieprawidłowe lub wygasłe dane uwierzytelniające",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None:
        raise unauthorized
    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise unauthorized from None

    user = (await session.exec(select(User).where(User.id == user_id))).first()
    if user is None or not user.is_active:
        raise unauthorized
    return user


def require_roles(*roles: Role) -> Callable[..., User]:
    allowed = {r.value for r in roles}

    async def dependency(user: Annotated[User, Depends(get_current_user)]) -> User:
        if user.role not in allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Brak uprawnień do tego zasobu")
        return user

    return dependency


CurrentUser = Annotated[User, Depends(get_current_user)]
CurrentDoctor = Annotated[User, Depends(require_roles(Role.DOCTOR))]
CurrentAdmin = Annotated[User, Depends(require_roles(Role.ADMIN))]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
