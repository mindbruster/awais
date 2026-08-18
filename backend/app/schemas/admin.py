"""
Schemas for the super admin panel: modules, roles, and what each may hold.

Both features answer the same question from two sides — *what is this person
allowed to reach* — so they share a screen and a schema file.
"""
from pydantic import BaseModel, Field

from app.schemas.common import TimestampedRead


# --------------------------------------------------------------------------
# Modules
# --------------------------------------------------------------------------
class BlockerRead(BaseModel):
    """One reason a module cannot be switched off, in words somebody can act on."""

    what: str
    where: str | None = None


class ModuleRead(TimestampedRead):
    key: str
    label: str
    sort_order: int
    enabled: bool
    # False for Dashboard and Settings. A shop that switched off Settings could
    # never switch anything back on.
    can_disable: bool
    notes: str | None = None
    # What is still live inside it. Empty when nothing is, and only computed for
    # a module that is currently on.
    blockers: list[BlockerRead] = []
    can_switch_off: bool = True


class ModuleUpdate(BaseModel):
    # The only mutable field. Key and label are fixed after seeding: every guard
    # in the API looks a module up by its key, so a key that could be edited is
    # a permission check that can be renamed out of existence.
    enabled: bool
    notes: str | None = None


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class PermissionInfo(BaseModel):
    """One grantable permission, grouped so a screen can lay them out."""

    key: str
    # "invoice" from "invoice:read" — the thing being acted on.
    resource: str
    # "read", "write", "delete" — what may be done to it.
    action: str


class RoleRead(TimestampedRead):
    name: str
    description: str | None = None
    is_system: bool
    permissions: list[str] = []
    # How many people hold this role. Shown because deleting a role with users
    # on it is refused, and the number explains why before the attempt.
    users: int = 0


class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    # A role starts with nothing rather than with a sensible default. A default
    # that turned out to be too generous would be granted quietly to every role
    # created before anybody noticed.
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=50)
    description: str | None = Field(default=None, max_length=255)
    # Null leaves the grants alone; a list replaces them wholesale. Replacement
    # rather than merge, so revoking is possible at all — a merge-only endpoint
    # can add permissions and never take one away.
    permissions: list[str] | None = None
