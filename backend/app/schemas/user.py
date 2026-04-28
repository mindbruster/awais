from pydantic import BaseModel, EmailStr, Field

from app.schemas.common import TimestampedRead
from app.schemas.role import RoleRead


class UserBase(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=150)
    is_active: bool = True


class UserCreate(UserBase):
    password: str = Field(min_length=6, max_length=100)
    role_id: int


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=150)
    is_active: bool | None = None
    role_id: int | None = None
    password: str | None = Field(default=None, min_length=6, max_length=100)


class UserRead(TimestampedRead, UserBase):
    role: RoleRead
