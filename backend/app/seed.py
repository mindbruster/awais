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
from app.core.permissions import (
    EXTRA_ROLES,
    SUPERADMIN,
    all_permissions,
    default_permissions,
)
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
    # The rest of the roles §11 of the specification asks for. Not system
    # roles: the shop is meant to rename, re-scope or delete these, and marking
    # them system would stop it. They start life holding nobody.
    *((name, desc, False) for name, (desc, _perms) in EXTRA_ROLES.items()),
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
            # The super admin holds the whole catalogue *as well as* being
            # recognised by name. Two mechanisms rather than one, and they fail
            # in opposite directions: the grants make the role honest — the
            # panel can show 60 of 60 rather than an empty role that mysteriously
            # works — while the name check means that even if every grant were
            # somehow removed, whoever holds it can still get back in and put
            # them back. A role whose power is invisible is one somebody
            # eventually "tidies up".
            if name == SUPERADMIN:
                wanted = all_permissions()
            elif name in EXTRA_ROLES:
                wanted = EXTRA_ROLES[name][1]
            else:
                wanted = default_permissions(name)
            held = role.permission_names
            for perm in sorted(wanted - held):
                db.add(RolePermission(role_id=role.id, permission=perm))
                granted += 1
        if granted:
            log.info("granted permissions", extra={"grants": granted})
        await db.commit()

        admin_role = (
            await db.execute(select(Role).where(Role.name == "admin"))
        ).scalar_one()

        # Each account is guarded on its own rather than the whole block
        # returning early on the first one found. An existing installation
        # already has an admin, and bailing there would mean the super admin
        # this release introduces never got created — the tier would exist in
        # the schema with nobody able to reach it.
        superadmin_role = (
            await db.execute(select(Role).where(Role.name == SUPERADMIN))
        ).unique().scalar_one()

        for email, name, password, role, note in (
            (
                settings.seed_superadmin_email,
                settings.seed_superadmin_name,
                settings.seed_superadmin_password,
                superadmin_role,
                "owns feature flags and role permissions",
            ),
            (
                settings.seed_admin_email,
                settings.seed_admin_name,
                settings.seed_admin_password,
                admin_role,
                "runs the shop",
            ),
        ):
            addr = email.lower()
            found = (
                await db.execute(select(User).where(User.email == addr))
            ).scalar_one_or_none()
            if found is not None:
                log.info("user already exists", extra={"email": addr})
                continue
            db.add(
                User(
                    email=addr,
                    full_name=name,
                    hashed_password=hash_password(password),
                    is_active=True,
                    role_id=role.id,
                )
            )
            await db.commit()
            log.warning(
                "account created — change the password on first login",
                extra={"email": addr, "role": role.name, "note": note},
            )


if __name__ == "__main__":
    asyncio.run(seed())
