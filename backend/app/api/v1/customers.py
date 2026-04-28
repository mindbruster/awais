from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import DbSession, require_perm
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate, CustomerRead, CustomerUpdate

router = APIRouter()
read = Depends(require_perm("customer:read"))
write = Depends(require_perm("customer:write"))
delete = Depends(require_perm("customer:delete"))


@router.get("", response_model=list[CustomerRead], dependencies=[read])
async def list_customers(
    db: DbSession,
    q: str | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[Customer]:
    stmt = select(Customer).order_by(Customer.id.desc()).limit(limit).offset(offset)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(
            or_(Customer.name.ilike(like), Customer.phone.ilike(like), Customer.email.ilike(like))
        )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post(
    "",
    response_model=CustomerRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def create_customer(payload: CustomerCreate, db: DbSession) -> Customer:
    customer = Customer(**payload.model_dump())
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.get("/{customer_id}", response_model=CustomerRead, dependencies=[read])
async def get_customer(customer_id: int, db: DbSession) -> Customer:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return customer


@router.patch("/{customer_id}", response_model=CustomerRead, dependencies=[write])
async def update_customer(
    customer_id: int, payload: CustomerUpdate, db: DbSession
) -> Customer:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(customer, k, v)
    await db.commit()
    await db.refresh(customer)
    return customer


@router.delete(
    "/{customer_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[delete]
)
async def delete_customer(customer_id: int, db: DbSession) -> None:
    customer = await db.get(Customer, customer_id)
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    await db.delete(customer)
    await db.commit()
