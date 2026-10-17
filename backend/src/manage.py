"""Polecenia administracyjne.

python -m src.manage sole-admin [email]
    Nadaje rolę ROLE_ADMIN wskazanemu kontu (domyślnie ADMIN_EMAIL), a pozostałym
    administratorom zmienia rolę na ROLE_DOCTOR (użytkownik). Konta pacjentów bez zmian.
"""

import asyncio
import sys

from sqlalchemy import update
from sqlmodel import col, select

from .config import settings
from .database import Role, User, init_db, session_factory


async def sole_admin(email: str) -> None:
    email = email.lower()
    await init_db()
    async with session_factory() as session:
        admin = (await session.exec(select(User).where(User.email == email))).first()
        if admin is None:
            raise SystemExit(f"Nie znaleziono konta {email}")
        admin.role = Role.ADMIN.value
        session.add(admin)
        result = await session.exec(
            update(User)
            .where(col(User.role) == Role.ADMIN.value, col(User.id) != admin.id)
            .values(role=Role.DOCTOR.value)
        )
        await session.commit()
        print(f"{email}: ROLE_ADMIN; zmieniono na ROLE_DOCTOR: {result.rowcount} kont(a)")


def main(argv: list[str]) -> None:
    if not argv or argv[0] != "sole-admin":
        raise SystemExit(__doc__)
    asyncio.run(sole_admin(argv[1] if len(argv) > 1 else settings.admin_email))


if __name__ == "__main__":
    main(sys.argv[1:])
