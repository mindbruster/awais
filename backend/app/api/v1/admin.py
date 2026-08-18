"""
The super admin panel: which modules this shop uses, and what each role may do.

Both live behind `superadmin` rather than behind a permission, and that is the
point of the tier. A permission that could be granted to widen who may grant
permissions is not a control, it is a formality — so the two things that decide
what everybody else can reach are held by somebody who is not also running the
counter.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select

from app.api.deps import CurrentUser, DbSession, require_password_confirm
from app.core.permissions import SUPERADMIN, all_permissions
from app.models.module import Module
from app.models.role import Role, RolePermission
from app.models.user import User
from app.schemas.admin import (
    BlockerRead,
    ModuleRead,
    ModuleUpdate,
    PermissionInfo,
    RoleCreate,
    RoleRead,
    RoleUpdate,
)
from app.services import modules as modules_svc
from app.services.audit import changes, log_action, snapshot

router = APIRouter()


async def require_superadmin(current: CurrentUser) -> User:
    """
    The one check in this system that is a role name rather than a permission.

    Everything else asks "does this user hold `invoice:write`", which is right
    because those permissions are meant to be handed out. These two are not:
    the ability to change what anybody may do has to sit outside the thing it
    governs, or an admin can simply grant it to themselves and the whole
    arrangement means nothing.
    """
    if current.role is None or current.role.name != SUPERADMIN:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Only a super admin can change modules or role permissions. This is "
            "deliberate: an admin who could widen their own permissions would not "
            "really be limited by them.",
        )
    return current


superadmin = Depends(require_superadmin)
confirm = Depends(require_password_confirm)


# --------------------------------------------------------------------------
# Modules
# --------------------------------------------------------------------------
async def _module_read(db: DbSession, module: Module) -> ModuleRead:
    state = await modules_svc.state_of(db, module)
    return ModuleRead(
        id=module.id,
        created_at=module.created_at,
        updated_at=module.updated_at,
        key=module.key,
        label=module.label,
        sort_order=module.sort_order,
        enabled=module.enabled,
        can_disable=module.can_disable,
        notes=module.notes,
        blockers=[BlockerRead(what=b.what, where=b.where) for b in state.blockers],
        can_switch_off=state.can_switch_off,
    )


@router.get("/modules", response_model=list[ModuleRead], dependencies=[superadmin])
async def list_modules(db: DbSession) -> list[ModuleRead]:
    """
    Every module, with what stands in the way of switching each one off.

    The blockers are computed here rather than when somebody clicks, so the
    screen can grey a switch and say why instead of letting a person try and
    meet a refusal.
    """
    rows = (
        (await db.execute(select(Module).order_by(Module.sort_order, Module.key)))
        .scalars()
        .all()
    )
    return [await _module_read(db, m) for m in rows]


@router.patch(
    "/modules/{key}", response_model=ModuleRead, dependencies=[superadmin, confirm]
)
async def set_module(
    key: str, payload: ModuleUpdate, db: DbSession, current: CurrentUser
) -> ModuleRead:
    """
    Switch a module on or off.

    Switching **on** is always allowed — nothing is put at risk by making a
    screen reachable. Switching **off** is refused while the module still holds
    live work, and the refusal names it: turning off Manufacturing with metal at
    a karigar would make the screen that receives it unreachable and strand real
    gold in a state nothing could move it out of.
    """
    module = await modules_svc.get_module(db, key)
    if module is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Module not found")

    was = snapshot(module)
    if payload.enabled is False and module.enabled:
        if not module.can_disable:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{module.label} cannot be switched off. Without it there would be no "
                "way to switch anything back on.",
            )
        blockers = await modules_svc.blockers_for(db, key)
        if blockers:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{module.label} still holds live work and cannot be switched off yet: "
                + "; ".join(b.what for b in blockers)
                + ". Settle or cancel these first.",
            )

    module.enabled = payload.enabled
    if payload.notes is not None:
        module.notes = payload.notes
    before, after = changes(was, snapshot(module))
    if before or after:
        await log_action(
            db,
            user=current,
            action="admin.module.set",
            resource_type="module",
            resource_id=module.id,
            before=before,
            after=after,
            reason=payload.notes,
        )
    await db.commit()
    await db.refresh(module)
    return await _module_read(db, module)


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
@router.get("/permissions", response_model=list[PermissionInfo], dependencies=[superadmin])
async def list_permissions() -> list[PermissionInfo]:
    """
    Every permission that exists, from the catalogue in code.

    Read from the code rather than from what roles happen to hold, so a
    permission no role has yet can still be granted — and so a typo cannot
    invent one that no endpoint will ever check, which would look like a grant
    and be nothing.
    """
    out: list[PermissionInfo] = []
    for key in sorted(all_permissions()):
        resource, _, action = key.partition(":")
        out.append(PermissionInfo(key=key, resource=resource, action=action))
    return out


async def _role_read(db: DbSession, role: Role) -> RoleRead:
    users = (
        await db.execute(select(func.count(User.id)).where(User.role_id == role.id))
    ).scalar_one()
    return RoleRead(
        id=role.id,
        created_at=role.created_at,
        updated_at=role.updated_at,
        name=role.name,
        description=role.description,
        is_system=role.is_system,
        permissions=sorted(role.permission_names),
        users=int(users or 0),
    )


@router.get("/roles", response_model=list[RoleRead], dependencies=[superadmin])
async def list_roles(db: DbSession) -> list[RoleRead]:
    rows = (await db.execute(select(Role).order_by(Role.name))).unique().scalars().all()
    return [await _role_read(db, r) for r in rows]


def _validate(perms: list[str]) -> set[str]:
    """
    Refuse anything not in the catalogue.

    A permission nothing checks is worse than no permission: it appears on the
    role, reads as a grant, and confers exactly nothing. Better a 422 at the
    moment somebody types it.
    """
    catalogue = all_permissions()
    unknown = sorted(set(perms) - catalogue)
    if unknown:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"No such permission: {', '.join(unknown)}. Nothing in the system checks "
            "these, so granting them would confer nothing while looking like it did.",
        )
    return set(perms)


@router.post(
    "/roles",
    response_model=RoleRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[superadmin],
)
async def create_role(payload: RoleCreate, db: DbSession, current: CurrentUser) -> RoleRead:
    """Create a role. It starts with exactly what is asked for, and nothing else."""
    wanted = _validate(payload.permissions)
    if payload.name == SUPERADMIN:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "There is already a super admin role."
        )
    existing = (
        await db.execute(select(Role).where(Role.name == payload.name))
    ).unique().scalar_one_or_none()
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "A role with that name exists.")

    role = Role(name=payload.name, description=payload.description, is_system=False)
    db.add(role)
    await db.flush()
    for perm in sorted(wanted):
        db.add(RolePermission(role_id=role.id, permission=perm))
    await db.flush()
    await log_action(
        db,
        user=current,
        action="admin.role.create",
        resource_type="role",
        resource_id=role.id,
        after={"name": role.name, "permissions": sorted(wanted)},
    )
    await db.commit()
    role = (
        await db.execute(select(Role).where(Role.id == role.id))
    ).unique().scalar_one()
    return await _role_read(db, role)


@router.patch("/roles/{role_id}", response_model=RoleRead, dependencies=[superadmin, confirm])
async def update_role(
    role_id: int, payload: RoleUpdate, db: DbSession, current: CurrentUser
) -> RoleRead:
    """
    Rename a role, or replace what it holds.

    The super admin role is not editable from in here, and that is the whole
    arrangement holding together: if it could be edited, somebody could strip it
    of the ability to edit roles and leave the installation with no way back.
    """
    role = (
        await db.execute(select(Role).where(Role.id == role_id))
    ).unique().scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.name == SUPERADMIN:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The super admin role cannot be edited. Stripping it would leave nobody "
            "able to grant anything, with no way back in.",
        )

    before_perms = sorted(role.permission_names)
    if payload.name is not None:
        if role.is_system and payload.name != role.name:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"'{role.name}' is a system role and cannot be renamed — the seed and "
                "the migrations look it up by name.",
            )
        role.name = payload.name
    if payload.description is not None:
        role.description = payload.description

    if payload.permissions is not None:
        wanted = _validate(payload.permissions)
        for existing in list(role.permissions):
            if existing.permission not in wanted:
                await db.delete(existing)
        held = role.permission_names
        for perm in sorted(wanted - held):
            db.add(RolePermission(role_id=role.id, permission=perm))

    await db.flush()
    # `populate_existing` because the role is already in the identity map with
    # the collection it had before the grants were touched. Without it a
    # revocation reads back as though it never happened — the rows are gone and
    # the object still lists them.
    role = (
        await db.execute(
            select(Role).where(Role.id == role.id).execution_options(populate_existing=True)
        )
    ).unique().scalar_one()
    after_perms = sorted(role.permission_names)
    if before_perms != after_perms:
        await log_action(
            db,
            user=current,
            action="admin.role.permissions",
            resource_type="role",
            resource_id=role.id,
            before={"permissions": before_perms},
            after={"permissions": after_perms},
        )
    await db.commit()
    role = (
        await db.execute(
            select(Role).where(Role.id == role.id).execution_options(populate_existing=True)
        )
    ).unique().scalar_one()
    return await _role_read(db, role)


@router.delete(
    "/roles/{role_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[superadmin, confirm],
)
async def delete_role(role_id: int, db: DbSession, current: CurrentUser) -> None:
    """
    Remove a role nobody holds.

    Refused while anybody is on it — deleting it would leave a user account
    pointing at nothing, which locks that person out with no message that
    explains it.
    """
    role = (
        await db.execute(select(Role).where(Role.id == role_id))
    ).unique().scalar_one_or_none()
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    if role.is_system:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"'{role.name}' is a system role and cannot be deleted.",
        )
    users = (
        await db.execute(select(func.count(User.id)).where(User.role_id == role.id))
    ).scalar_one()
    if users:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{users} user(s) hold '{role.name}'. Move them to another role first — "
            "deleting it would leave their accounts pointing at nothing.",
        )
    await log_action(
        db,
        user=current,
        action="admin.role.delete",
        resource_type="role",
        resource_id=role.id,
        before={"name": role.name, "permissions": sorted(role.permission_names)},
    )
    await db.delete(role)
    await db.commit()


# --------------------------------------------------------------------------
# What every signed-in user may see
# --------------------------------------------------------------------------
public_router = APIRouter()


@public_router.get("", response_model=list[ModuleRead])
async def my_modules(db: DbSession, current: CurrentUser) -> list[ModuleRead]:
    """
    Which modules are on, for the sidebar.

    Readable by anybody signed in, because every user's navigation depends on
    it — and it discloses nothing: a person can already tell a module is off by
    clicking one of its links. Only *changing* a module is restricted.

    Blockers are not computed here. They are a super admin's concern and each
    one costs a query, so the sidebar does not pay for them on every page load.
    """
    rows = (
        (await db.execute(select(Module).order_by(Module.sort_order, Module.key)))
        .scalars()
        .all()
    )
    return [
        ModuleRead(
            id=m.id,
            created_at=m.created_at,
            updated_at=m.updated_at,
            key=m.key,
            label=m.label,
            sort_order=m.sort_order,
            enabled=m.enabled,
            can_disable=m.can_disable,
            notes=m.notes,
            blockers=[],
            can_switch_off=m.can_disable,
        )
        for m in rows
    ]
