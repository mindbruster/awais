"""Seed default roles and an initial admin user.

Usage:
    python -m app.seed
"""
import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logging_setup import configure_logging, get_logger
from app.core.security import hash_password
# Imported for its side effect: importing the routers is what fills the
# permission catalogue, and seeding grants against an empty catalogue would
# create roles that hold nothing.
import app.api.v1  # noqa: F401
from app.core.permissions import SUPERADMIN, default_permissions
from app.models.role import Role, RolePermission
from app.models.user import User

DEFAULT_ROLES = [
    # The tier above admin. It owns feature flags and role permissions and
    # nothing else, because an admin who can widen their own permissions is not
    # really constrained by them.
    (SUPERADMIN, "Owns feature flags and role permissions", True),
    ("admin", "Full system access", True),
    ("accountant", "Sales, invoices, reports", True),
    ("staff", "Day-to-day operations", True),
]

configure_logging()
log = get_logger("app.seed")


async def seed() -> None:
    async with SessionLocal() as db:
        existing = {r.name: r for r in (await db.execute(select(Role))).unique().scalars().all()}
        created_roles = []
        for name, desc, is_system in DEFAULT_ROLES:
            if name not in existing:
                role = Role(name=name, description=desc, is_system=is_system)
                db.add(role)
                created_roles.append(name)
        if created_roles:
            await db.flush()
            log.info("seeded roles", extra={"role_names": created_roles})

        # Grant each seeded role what the catalogue says it should hold.
        #
        # This has to happen here and not only in the migration. Migrations run
        # against an empty database on a fresh install — the roles do not exist
        # yet — so a backfill there covers an upgrade and nothing else. Without
        # this, a new installation came up with every role holding zero
        # permissions and nobody able to do anything, which fails no test and
        # looks exactly like a broken login.
        #
        # Additive on purpose: a role whose grants the shop has since edited
        # keeps its edits, and only permissions added to the catalogue since
        # are filled in. Re-seeding must never quietly restore something an
        # owner deliberately revoked.
        granted = 0
        for name, _desc, _sys in DEFAULT_ROLES:
            role = (
                await db.execute(select(Role).where(Role.name == name))
            ).unique().scalar_one()
            if name == SUPERADMIN:
                # Holds nothing. Its authority is its name, checked directly,
                # so that no grant can be taken away from it by accident.
                continue
            held = role.permission_names
            for perm in sorted(default_permissions(name) - held):
                db.add(RolePermission(role_id=role.id, permission=perm))
                granted += 1
        if granted:
            log.info("granted permissions", extra={"grants": granted})
        await db.commit()

        admin_role = (
            await db.execute(select(Role).where(Role.name == "admin"))
        ).scalar_one()

        admin_email = settings.seed_admin_email.lower()
        existing_admin = (
            await db.execute(select(User).where(User.email == admin_email))
        ).scalar_one_or_none()
        if existing_admin:
            log.info("admin already exists", extra={"email": admin_email})
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
        log.warning(
            "admin created — change password on first login",
            extra={"email": admin_email},
        )


if __name__ == "__main__":
    asyncio.run(seed())
