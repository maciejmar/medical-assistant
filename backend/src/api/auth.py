from fastapi import APIRouter, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from ..auth import CurrentUser, SessionDep, create_access_token, hash_password, verify_password
from ..database import Role, User
from .schemas import LoginIn, RegisterIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenOut, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterIn, session: SessionDep) -> TokenOut:
    email = body.email.lower()
    existing = (await session.exec(select(User).where(User.email == email))).first()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Konto z tym adresem e-mail już istnieje")

    user = User(
        email=email,
        full_name=body.full_name.strip(),
        hashed_password=await hash_password(body.password),
        role=Role.DOCTOR.value,
    )
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Konto z tym adresem e-mail już istnieje"
        ) from None
    await session.refresh(user)
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.post("/login", response_model=TokenOut)
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    user = (await session.exec(select(User).where(User.email == body.email.lower()))).first()
    valid = await verify_password(body.password, user.hashed_password if user else None)
    if not user or not valid or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Nieprawidłowy e-mail lub hasło")
    return TokenOut(access_token=create_access_token(user), user=UserOut.model_validate(user))


@router.get("/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user
