from pydantic import BaseModel, Field

from app.models.vendor import VendorType
from app.schemas.common import TimestampedRead


class VendorBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    type: VendorType
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    notes: str | None = None


class VendorCreate(VendorBase):
    pass


class VendorUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    type: VendorType | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = None
    notes: str | None = None


class VendorRead(TimestampedRead, VendorBase):
    pass
