"""Seed default roles and an initial admin user.

Usage:
    python -m app.seed
"""
import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.role import Role
from app.models.user import User

DEFAULT_ROLES = [
    ("admin", "Full system access"),
    ("accountant", "Sales, invoices, reports"),
    ("staff", "Day-to-day operations"),
]


async def seed() -> None:
    async with SessionLocal() as db:
        existing = {r.name for r in (await db.execute(select(Role))).scalars().all()}
        created_roles = []
        for name, desc in DEFAULT_ROLES:
            if name not in existing:
                role = Role(name=name, description=desc)
                db.add(role)
                created_roles.append(name)
        if created_roles:
            await db.commit()
            print(f"Created roles: {', '.join(created_roles)}")
        else:
            print("Roles already exist — skipping.")

        admin_role = (
            await db.execute(select(Role).where(Role.name == "admin"))
        ).scalar_one()

        admin_email = settings.seed_admin_email.lower()
        existing_admin = (
            await db.execute(select(User).where(User.email == admin_email))
        ).scalar_one_or_none()
        if existing_admin:
            print(f"Admin user already exists: {admin_email}")
            return

        admin = User(
            email=admin_email,
            full_name=settings.seed_admin_name,
            hashed_password=hash_password(settings.seed_admin_password),
            is_active=True,
            role_id=admin_role.id,
        )
        db.add(admin)
        await db.commit()
        print(f"Created admin user: {admin_email} / {settings.seed_admin_password}")
        print("WARNING: change this password after first login.")


if __name__ == "__main__":
    asyncio.run(seed())
