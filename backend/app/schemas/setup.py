from pydantic import BaseModel, Field

from app.schemas.common import ORMModel


class SetupStep(ORMModel):
    """
    One thing that still needs doing, and where to go and do it.

    `optional` separates "the shop cannot work without this" from "this would
    be nice". Mixing the two produces a checklist nobody finishes, and a
    checklist nobody finishes is a checklist nobody reads.
    """

    key: str
    title: str
    detail: str
    done: bool
    count: int
    to: str
    cta: str
    optional: bool = False


class SetupChecklist(ORMModel):
    steps: list[SetupStep] = Field(default_factory=list)
    done_count: int
    total: int
    required_done: int
    required_total: int
    # True once nothing required is outstanding. The banner hides itself on
    # this rather than nagging a shop that is already trading.
    ready: bool
    user_name: str | None = None
