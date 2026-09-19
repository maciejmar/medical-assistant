import jwt

from src.auth import create_access_token, decode_access_token, hash_password, verify_password
from src.config import settings
from src.database import Role, User


async def test_password_hash_roundtrip():
    hashed = await hash_password("Sekret123!")
    assert hashed != "Sekret123!"
    assert await verify_password("Sekret123!", hashed)
    assert not await verify_password("inne", hashed)
    assert not await verify_password("cokolwiek", None)


def test_jwt_roundtrip_and_tamper():
    user = User(id=7, email="a@b.pl", full_name="A", hashed_password="x", role=Role.DOCTOR.value)
    token = create_access_token(user)
    assert decode_access_token(token)["sub"] == "7"
    forged = jwt.encode(
        {"sub": "7", "exp": 9999999999}, "inny-sekret-inny-sekret-inny-1234", "HS256"
    )
    try:
        decode_access_token(forged)
    except jwt.PyJWTError:
        pass
    else:
        raise AssertionError("sfałszowany token został zaakceptowany")
    assert settings.jwt_algorithm == "HS256"


async def test_register_login_me(client):
    payload = {"email": "Lekarz@Example.com", "full_name": "Anna Nowak", "password": "Haslo12345"}
    registered = await client.post("/api/auth/register", json=payload)
    assert registered.status_code == 201
    assert registered.json()["user"]["role"] == "ROLE_DOCTOR"
    assert registered.json()["user"]["email"] == "lekarz@example.com"

    duplicate = await client.post("/api/auth/register", json=payload)
    assert duplicate.status_code == 409

    login = await client.post(
        "/api/auth/login", json={"email": "lekarz@example.com", "password": "Haslo12345"}
    )
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = await client.get("/api/auth/me", headers=headers)
    assert me.status_code == 200 and me.json()["full_name"] == "Anna Nowak"


async def test_login_rejects_wrong_password_and_unknown_user(client, make_headers):
    await make_headers("x@example.com")
    bad = await client.post("/api/auth/login", json={"email": "x@example.com", "password": "zle"})
    unknown = await client.post(
        "/api/auth/login", json={"email": "no@example.com", "password": "zle"}
    )
    assert bad.status_code == unknown.status_code == 401
    assert bad.json() == unknown.json()


async def test_protected_route_requires_token(client):
    assert (await client.get("/api/patients")).status_code == 401
    bad = await client.get("/api/patients", headers={"Authorization": "Bearer nieprawidlowy"})
    assert bad.status_code == 401


async def test_deactivated_user_cannot_use_existing_token(client, make_headers):
    from sqlmodel import select

    from src.database import session_factory

    headers = await make_headers("inactive@example.com")
    async with session_factory() as session:
        user = (await session.exec(select(User).where(User.email == "inactive@example.com"))).one()
        user.is_active = False
        session.add(user)
        await session.commit()
    assert (await client.get("/api/auth/me", headers=headers)).status_code == 401
