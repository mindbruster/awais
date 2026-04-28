from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import TimestampedRead


class CustomerBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    address: str | None = None
    notes: str | None = None


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    address: str | None = None
    notes: str | None = None


class CustomerRead(TimestampedRead, CustomerBase):
    pass
