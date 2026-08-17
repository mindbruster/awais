"""
CRUD over the shop's reference data.

The seven resources here (departments, items, attribute options, countries,
cities, banks, bank accounts) differ only in their model, their schemas and
which columns a text search should look at — so they're generated from one
factory rather than written out seven times. The factory owns the behaviour
that's easy to get subtly wrong per-copy: translating a unique-constraint
breach into a 409 rather than a 500, and refusing a delete that would orphan
rows pointing at it.
"""
from typing import Any, Callable, Sequence

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.attribute_option import AttributeKind, AttributeOption
from app.models.bank import Bank, BankAccount
from app.models.department import Department
from app.models.item import Item
from app.models.location import City, Country
from app.schemas.masters import (
    AttributeOptionCreate,
    AttributeOptionRead,
    AttributeOptionUpdate,
    BankAccountCreate,
    BankAccountRead,
    BankAccountUpdate,
    BankCreate,
    BankRead,
    BankUpdate,
    CityCreate,
    CityRead,
    CityUpdate,
    CountryCreate,
    CountryRead,
    CountryUpdate,
    DepartmentCreate,
    DepartmentRead,
    DepartmentUpdate,
    ItemCreate,
    ItemRead,
    ItemUpdate,
)
from app.services.audit import changes, log_action, snapshot

read_perm = Depends(require_perm("master:read"))
write_perm = Depends(require_perm("master:write"))
delete_perm = Depends(require_perm("master:delete"))


def _integrity_error(exc: IntegrityError, label: str) -> HTTPException:
    """
    Turn a constraint breach into something the user can act on.

    Unique breaches are the common case and mean "you already have one of
    these"; foreign-key breaches on delete mean the row is referenced and
    removing it would orphan real records.
    """
    detail = str(getattr(exc, "orig", exc))
    if "unique" in detail.lower() or "duplicate key" in detail.lower():
        return HTTPException(
            status.HTTP_409_CONFLICT,
            f"A {label} with these details already exists.",
        )
    if "foreign key" in detail.lower():
        return HTTPException(
            status.HTTP_409_CONFLICT,
            f"This {label} is still referenced by other records and cannot be removed. "
            "Deactivate it instead.",
        )
    return HTTPException(status.HTTP_409_CONFLICT, f"Could not save {label}: {detail}")


def make_master_router(
    *,
    model: Any,
    create_schema: Any,
    update_schema: Any,
    read_schema: Any,
    label: str,
    search_fields: Sequence[Any] = (),
    order_by: Sequence[Any] = (),
    to_read: Callable[[Any], Any] | None = None,
) -> APIRouter:
    router = APIRouter()
    serialise = to_read or (lambda obj: read_schema.model_validate(obj, from_attributes=True))

    @router.get("", response_model=list[read_schema], dependencies=[read_perm])
    async def list_rows(
        db: DbSession,
        q: str | None = Query(default=None, description=f"Search {label}s"),
        is_active: bool | None = Query(default=None),
        limit: int = Query(default=200, le=500),
        offset: int = Query(default=0, ge=0),
    ) -> list[Any]:
        stmt = select(model).limit(limit).offset(offset)
        if order_by:
            stmt = stmt.order_by(*order_by)
        if is_active is not None and hasattr(model, "is_active"):
            stmt = stmt.where(model.is_active == is_active)
        if q and search_fields:
            like = f"%{q}%"
            stmt = stmt.where(or_(*[f.ilike(like) for f in search_fields]))
        rows = list((await db.execute(stmt)).scalars().all())
        return [serialise(r) for r in rows]

    @router.post(
        "",
        response_model=read_schema,
        status_code=status.HTTP_201_CREATED,
        dependencies=[write_perm],
    )
    async def create_row(
        payload: create_schema, db: DbSession, current: CurrentUser  # type: ignore[valid-type]
    ) -> Any:
        row = model(**payload.model_dump())
        db.add(row)
        try:
            await db.flush()
            await log_action(
                db,
                user=current,
                action=f"{label}.create",
                resource_type=label,
                resource_id=row.id,
                after=snapshot(row),
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise _integrity_error(exc, label) from exc
        await db.refresh(row)
        return serialise(row)

    @router.get("/{row_id}", response_model=read_schema, dependencies=[read_perm])
    async def get_row(row_id: int, db: DbSession) -> Any:
        row = await db.get(model, row_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label.capitalize()} not found")
        return serialise(row)

    @router.patch("/{row_id}", response_model=read_schema, dependencies=[write_perm])
    async def update_row(
        row_id: int, payload: update_schema, db: DbSession, current: CurrentUser  # type: ignore[valid-type]
    ) -> Any:
        row = await db.get(model, row_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label.capitalize()} not found")
        # Captured before the setattr loop, or "before" would be the new value.
        was = snapshot(row)
        for k, v in payload.model_dump(exclude_unset=True).items():
            setattr(row, k, v)
        before, after = changes(was, snapshot(row))
        try:
            # An edit that altered nothing writes no line. "Somebody opened this
            # and changed nothing" is a row that only makes the real edits
            # harder to find.
            if before or after:
                await log_action(
                    db,
                    user=current,
                    action=f"{label}.update",
                    resource_type=label,
                    resource_id=row.id,
                    before=before,
                    after=after,
                )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise _integrity_error(exc, label) from exc
        await db.refresh(row)
        return serialise(row)

    @router.delete(
        "/{row_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[delete_perm, Depends(require_password_confirm)],
    )
    async def delete_row(row_id: int, db: DbSession, current: CurrentUser) -> None:
        row = await db.get(model, row_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label.capitalize()} not found")
        # The whole row, because after this there is nothing left to compare
        # against. This is the one case where a full snapshot is the point.
        was = snapshot(row)
        await db.delete(row)
        try:
            await log_action(
                db,
                user=current,
                action=f"{label}.delete",
                resource_type=label,
                resource_id=row_id,
                before=was,
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise _integrity_error(exc, label) from exc

    return router


departments_router = make_master_router(
    model=Department,
    create_schema=DepartmentCreate,
    update_schema=DepartmentUpdate,
    read_schema=DepartmentRead,
    label="department",
    search_fields=(Department.name, Department.code),
    order_by=(Department.sequence, Department.name),
)

items_router = make_master_router(
    model=Item,
    create_schema=ItemCreate,
    update_schema=ItemUpdate,
    read_schema=ItemRead,
    label="item",
    search_fields=(Item.name, Item.abbreviation, Item.category),
    order_by=(Item.name,),
)

attribute_options_router = make_master_router(
    model=AttributeOption,
    create_schema=AttributeOptionCreate,
    update_schema=AttributeOptionUpdate,
    read_schema=AttributeOptionRead,
    label="attribute option",
    search_fields=(AttributeOption.value,),
    order_by=(AttributeOption.kind, AttributeOption.sort_order, AttributeOption.value),
)


@attribute_options_router.get(
    "/by-kind/{kind}", response_model=list[AttributeOptionRead], dependencies=[read_perm]
)
async def options_by_kind(kind: AttributeKind, db: DbSession) -> list[AttributeOption]:
    """Active options of one kind, ordered for direct use as a dropdown."""
    stmt = (
        select(AttributeOption)
        .where(AttributeOption.kind == kind, AttributeOption.is_active.is_(True))
        .order_by(AttributeOption.sort_order, AttributeOption.value)
    )
    return list((await db.execute(stmt)).scalars().all())


countries_router = make_master_router(
    model=Country,
    create_schema=CountryCreate,
    update_schema=CountryUpdate,
    read_schema=CountryRead,
    label="country",
    search_fields=(Country.name, Country.iso_code),
    order_by=(Country.name,),
)

cities_router = make_master_router(
    model=City,
    create_schema=CityCreate,
    update_schema=CityUpdate,
    read_schema=CityRead,
    label="city",
    search_fields=(City.name,),
    order_by=(City.name,),
    # City rows are almost always shown next to their country, so flatten the
    # name in rather than making the UI resolve a second lookup per row.
    to_read=lambda c: CityRead(
        id=c.id,
        created_at=c.created_at,
        updated_at=c.updated_at,
        name=c.name,
        country_id=c.country_id,
        is_active=c.is_active,
        country_name=c.country.name if c.country else None,
    ),
)

banks_router = make_master_router(
    model=Bank,
    create_schema=BankCreate,
    update_schema=BankUpdate,
    read_schema=BankRead,
    label="bank",
    search_fields=(Bank.name,),
    order_by=(Bank.name,),
)

bank_accounts_router = make_master_router(
    model=BankAccount,
    create_schema=BankAccountCreate,
    update_schema=BankAccountUpdate,
    read_schema=BankAccountRead,
    label="bank account",
    search_fields=(BankAccount.account_no, BankAccount.title),
    order_by=(BankAccount.account_no,),
    to_read=lambda a: BankAccountRead(
        id=a.id,
        created_at=a.created_at,
        updated_at=a.updated_at,
        bank_id=a.bank_id,
        account_no=a.account_no,
        title=a.title,
        currency=a.currency,
        opening_balance=a.opening_balance,
        is_active=a.is_active,
        bank_name=a.bank.name if a.bank else None,
    ),
)
