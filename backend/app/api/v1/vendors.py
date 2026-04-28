from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import DbSession, require_perm
from app.models.vendor import Vendor, VendorType
from app.schemas.vendor import VendorCreate, VendorRead, VendorUpdate

router = APIRouter()
read = Depends(require_perm("vendor:read"))
write = Depends(require_perm("vendor:write"))
delete = Depends(require_perm("vendor:delete"))


@router.get("", response_model=list[VendorRead], dependencies=[read])
async def list_vendors(
    db: DbSession,
    q: str | None = Query(default=None),
    type: VendorType | None = Query(default=None),
    limit: int = Query(default=200, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Vendor]:
    stmt = select(Vendor).order_by(Vendor.name).limit(limit).offset(offset)
    if type:
        stmt = stmt.where(Vendor.type == type)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Vendor.name.ilike(like), Vendor.phone.ilike(like)))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=VendorRead, status_code=status.HTTP_201_CREATED, dependencies=[write])
async def create_vendor(payload: VendorCreate, db: DbSession) -> Vendor:
    vendor = Vendor(**payload.model_dump())
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
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(vendor, k, v)
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
