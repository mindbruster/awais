from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import DbSession, require_perm
from app.models.department import Department
from app.models.vendor import Vendor, VendorType, legacy_type_for
from app.schemas.vendor import VendorCreate, VendorRead, VendorUpdate

router = APIRouter()
read = Depends(require_perm("vendor:read"))
write = Depends(require_perm("vendor:write"))
delete = Depends(require_perm("vendor:delete"))


@router.get("", response_model=list[VendorRead], dependencies=[read])
async def list_vendors(
    db: DbSession,
    q: str | None = Query(default=None),
    department_id: int | None = Query(default=None),
    # The stage a worker handles is what anyone actually filters by. `type` is
    # kept because the legacy loss report links here with it.
    type: VendorType | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Vendor]:
    stmt = select(Vendor).order_by(Vendor.name).limit(limit).offset(offset)
    if department_id is not None:
        stmt = stmt.where(Vendor.department_id == department_id)
    if type:
        stmt = stmt.where(Vendor.type == type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Vendor.name.ilike(like), Vendor.phone.ilike(like)))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def _department(db: DbSession, department_id: int) -> Department:
    department = await db.get(Department, department_id)
    if department is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Department not found")
    return department


@router.post("", response_model=VendorRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_vendor(payload: VendorCreate, db: DbSession) -> Vendor:
    department = await _department(db, payload.department_id)
    vendor = Vendor(**payload.model_dump(), type=legacy_type_for(department))
    db.add(vendor)
    await db.commit()
    await db.refresh(vendor)
    return vendor


@router.get("/{vendor_id}", response_model=VendorRead, dependencies=[read])
async def get_vendor(vendor_id: int, db: DbSession) -> Vendor:
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    return vendor


@router.patch("/{vendor_id}", response_model=VendorRead, dependencies=[write])
async def update_vendor(
    vendor_id: int, payload: VendorUpdate, db: DbSession
) -> Vendor:
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    fields = payload.model_dump(exclude_unset=True)
    for k, v in fields.items():
        setattr(vendor, k, v)
    # Moving a worker to another stage moves his legacy role with him.
    if fields.get("department_id") is not None:
        vendor.type = legacy_type_for(await _department(db, fields["department_id"]))
    await db.commit()
    await db.refresh(vendor)
    return vendor


@router.delete("/{vendor_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[delete])
async def delete_vendor(vendor_id: int, db: DbSession) -> None:
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    await db.delete(vendor)
    await db.commit()
