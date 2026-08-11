import enum
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.mixins import TimestampMixin
from app.models.product import Product
from app.models.vendor import Vendor


class JobStage(str, enum.Enum):
    draft = "draft"
    karigar_assigned = "karigar_assigned"
    karigar_received = "karigar_received"
    stone_fixer_assigned = "stone_fixer_assigned"
    stone_fixer_received = "stone_fixer_received"
    polish_assigned = "polish_assigned"
    polish_received = "polish_received"
    completed = "completed"
    cancelled = "cancelled"


class ManufacturingJob(Base, TimestampMixin):
    __tablename__ = "manufacturing_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_no: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)
    stage: Mapped[JobStage] = mapped_column(
        Enum(JobStage, name="manufacturing_stage"),
        default=JobStage.draft,
        nullable=False,
        index=True,
    )

    # Karigar (gold work)
    karigar_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"))
    karigar: Mapped[Vendor | None] = relationship(foreign_keys=[karigar_id], lazy="selectin")
    gold_assigned_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    gold_assigned_purity: Mapped[int | None] = mapped_column(Integer)
    gold_assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    jewelry_received_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    # Signed: positive = metal lost in working, negative = weight gained (solder,
    # alloy top-up, findings added by the karigar). Both happen in practice.
    karigar_loss_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    # Inventory row the gold was drawn from. Needed to credit material back when
    # a job is cancelled — without it a cancellation silently destroys stock.
    gold_source_inventory_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )

    # Stone fixer
    stone_fixer_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"))
    stone_fixer: Mapped[Vendor | None] = relationship(foreign_keys=[stone_fixer_id], lazy="selectin")
    stones_assigned_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stones_used_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stones_returned_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    # Same purpose as gold_source_inventory_id, and additionally the destination
    # for stones the fixer hands back at receive time.
    stone_source_inventory_id: Mapped[int | None] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="SET NULL")
    )

    # Polish
    polish_vendor_id: Mapped[int | None] = mapped_column(ForeignKey("vendors.id", ondelete="SET NULL"))
    polish_vendor: Mapped[Vendor | None] = relationship(foreign_keys=[polish_vendor_id], lazy="selectin")
    weight_before_polish_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    weight_after_polish_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    polish_loss_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)

    # Phase 7 — costs charged to this job. Rolled into the resulting product
    # when the job is completed.
    karigar_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    stone_fixing_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    polish_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    other_cost: Mapped[float] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    # Resulting product (created when stage becomes completed)
    product_id: Mapped[int | None] = mapped_column(ForeignKey("products.id", ondelete="SET NULL"))
    product: Mapped[Product | None] = relationship(lazy="selectin")

    # Cancellation. Material still held by a worker when a job is cancelled is
    # not returned to stock — it is written off here and becomes that worker's
    # liability. Recording it keeps inventory honest and gives the ledger work
    # (phase 3) the numbers it needs to raise the corresponding debit.
    gold_written_off_g: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    stones_written_off_ct: Mapped[float] = mapped_column(Numeric(14, 4), default=0, nullable=False)
    cancel_reason: Mapped[str | None] = mapped_column(Text)

    notes: Mapped[str | None] = mapped_column(Text)
