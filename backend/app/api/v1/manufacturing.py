from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, require_password_confirm, require_perm
from app.models.inventory import InventoryItem, InventoryType
from app.models.manufacturing import JobStage, ManufacturingJob
from app.models.product import Product, ProductStatus
from app.models.stock_movement import MovementType
from app.models.user import User
from app.models.vendor import Vendor, VendorType
from app.schemas.manufacturing import (
    AssignKarigar,
    AssignPolish,
    AssignStoneFixer,
    CancelJob,
    CompleteJob,
    ManufacturingJobCreate,
    ManufacturingJobRead,
    ReceiveFromKarigar,
    ReceiveFromPolish,
    ReceiveFromStoneFixer,
    SetJobCosts,
)
from app.services.audit import log_action
from app.services.inventory import post_movement
from app.services.product_cost import recompute_material_cost
from app.services.serial import next_job_no, next_product_serial

router = APIRouter()
read = Depends(require_perm("manufacturing:read"))
write = Depends(require_perm("manufacturing:write"))


def _expect_stage(job: ManufacturingJob, *allowed: JobStage) -> None:
    if job.stage not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Action not allowed for stage '{job.stage.value}'",
        )


async def _get_vendor(db, vendor_id: int, expected: VendorType) -> Vendor:
    vendor = await db.get(Vendor, vendor_id)
    if vendor is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vendor not found")
    if vendor.type != expected:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Vendor #{vendor_id} is type '{vendor.type.value}', expected '{expected.value}'",
        )
    return vendor


async def _get_inventory(db, item_id: int) -> InventoryItem:
    item = await db.get(InventoryItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Inventory item #{item_id} not found")
    return item


@router.get("", response_model=list[ManufacturingJobRead], dependencies=[read])
async def list_jobs(
    db: DbSession,
    stage: JobStage | None = Query(default=None),
    limit: int = Query(default=100, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ManufacturingJob]:
    stmt = (
        select(ManufacturingJob)
        .order_by(ManufacturingJob.id.desc())
        .limit(limit)
        .offset(offset)
    )
    if stage:
        stmt = stmt.where(ManufacturingJob.stage == stage)
    return list((await db.execute(stmt)).scalars().all())


@router.post(
    "",
    response_model=ManufacturingJobRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=[write],
)
async def open_job(
    payload: ManufacturingJobCreate, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = ManufacturingJob(
        job_no=await next_job_no(db),
        stage=JobStage.draft,
        notes=payload.notes,
    )

    if payload.karigar_id and payload.gold_assigned_g and payload.gold_assigned_g > 0:
        if payload.gold_source_inventory_id is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "gold_source_inventory_id is required when assigning gold to a karigar.",
            )
        karigar = await _get_vendor(db, payload.karigar_id, VendorType.karigar)
        source = await _get_inventory(db, payload.gold_source_inventory_id)
        job.karigar_id = karigar.id
        job.gold_assigned_g = payload.gold_assigned_g
        job.gold_assigned_purity = payload.gold_assigned_purity
        job.gold_assigned_at = datetime.now(timezone.utc)
        job.gold_source_inventory_id = source.id
        job.stage = JobStage.karigar_assigned

        db.add(job)
        await db.flush()
        await post_movement(
            db,
            item=source,
            type=MovementType.manufacturing_out,
            weight_g_delta=-payload.gold_assigned_g,
            reference_type="manufacturing_job",
            reference_id=job.id,
            notes=f"Assigned to karigar {karigar.name} (job {job.job_no})",
            user_id=current.id,
        )
    else:
        db.add(job)

    await db.commit()
    await db.refresh(job)
    return job


@router.get("/{job_id}", response_model=ManufacturingJobRead, dependencies=[read])
async def get_job(job_id: int, db: DbSession) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.post("/{job_id}/assign-karigar", response_model=ManufacturingJobRead, dependencies=[write])
async def assign_karigar(
    job_id: int, payload: AssignKarigar, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _expect_stage(job, JobStage.draft)

    karigar = await _get_vendor(db, payload.karigar_id, VendorType.karigar)
    source = await _get_inventory(db, payload.gold_source_inventory_id)

    job.karigar_id = karigar.id
    job.gold_assigned_g = payload.gold_assigned_g
    job.gold_assigned_purity = payload.gold_assigned_purity
    job.gold_assigned_at = datetime.now(timezone.utc)
    job.gold_source_inventory_id = source.id
    job.stage = JobStage.karigar_assigned
    if payload.notes:
        job.notes = (job.notes + "\n" if job.notes else "") + payload.notes

    await post_movement(
        db,
        item=source,
        type=MovementType.manufacturing_out,
        weight_g_delta=-payload.gold_assigned_g,
        reference_type="manufacturing_job",
        reference_id=job.id,
        notes=f"Assigned to karigar {karigar.name}",
        user_id=current.id,
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/receive-karigar", response_model=ManufacturingJobRead, dependencies=[write])
async def receive_karigar(
    job_id: int, payload: ReceiveFromKarigar, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _expect_stage(job, JobStage.karigar_assigned)

    received = Decimal(str(payload.jewelry_received_g))
    assigned = Decimal(str(job.gold_assigned_g))
    # A gain is legitimate: karigars add solder, alloy and findings while
    # working, so the piece regularly returns heavier than the gold issued.
    # The difference is stored signed — negative loss means weight was added.
    job.jewelry_received_g = received
    job.karigar_loss_g = assigned - received
    job.stage = JobStage.karigar_received
    if payload.notes:
        job.notes = (job.notes + "\n" if job.notes else "") + payload.notes

    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/assign-stone-fixer", response_model=ManufacturingJobRead, dependencies=[write])
async def assign_stone_fixer(
    job_id: int, payload: AssignStoneFixer, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _expect_stage(job, JobStage.karigar_received)

    fixer = await _get_vendor(db, payload.stone_fixer_id, VendorType.stone_fixer)
    source = await _get_inventory(db, payload.stone_source_inventory_id)

    job.stone_fixer_id = fixer.id
    job.stones_assigned_ct = payload.stones_assigned_ct
    job.stone_source_inventory_id = source.id
    job.stage = JobStage.stone_fixer_assigned
    if payload.notes:
        job.notes = (job.notes + "\n" if job.notes else "") + payload.notes

    await post_movement(
        db,
        item=source,
        type=MovementType.manufacturing_out,
        weight_ct_delta=-payload.stones_assigned_ct,
        reference_type="manufacturing_job",
        reference_id=job.id,
        notes=f"Stones to {fixer.name}",
        user_id=current.id,
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/receive-stone-fixer", response_model=ManufacturingJobRead, dependencies=[write])
async def receive_stone_fixer(
    job_id: int, payload: ReceiveFromStoneFixer, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _expect_stage(job, JobStage.stone_fixer_assigned)

    used = Decimal(str(payload.stones_used_ct))
    returned = Decimal(str(payload.stones_returned_ct))
    assigned = Decimal(str(job.stones_assigned_ct))
    if used + returned > assigned:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "stones_used + stones_returned cannot exceed assigned.",
        )
    job.stones_used_ct = used
    job.stones_returned_ct = returned
    job.stage = JobStage.stone_fixer_received
    if payload.notes:
        job.notes = (job.notes + "\n" if job.notes else "") + payload.notes

    # Stones handed back by the fixer must go back into stock. Without this the
    # carats deducted at assign time are only ever partly accounted for (the
    # used portion lands on the product) and the returned portion vanishes,
    # walking stone inventory down on every single job.
    if returned > 0 and job.stone_source_inventory_id is not None:
        source = await _get_inventory(db, job.stone_source_inventory_id)
        await post_movement(
            db,
            item=source,
            type=MovementType.manufacturing_in,
            weight_ct_delta=returned,
            reference_type="manufacturing_job",
            reference_id=job.id,
            notes=f"Stones returned unused from fixer (job {job.job_no})",
            user_id=current.id,
        )

    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/assign-polish", response_model=ManufacturingJobRead, dependencies=[write])
async def assign_polish(
    job_id: int, payload: AssignPolish, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _expect_stage(job, JobStage.stone_fixer_received, JobStage.karigar_received)

    polisher = await _get_vendor(db, payload.polish_vendor_id, VendorType.polish)

    job.polish_vendor_id = polisher.id
    job.weight_before_polish_g = payload.weight_before_polish_g
    job.stage = JobStage.polish_assigned
    if payload.notes:
        job.notes = (job.notes + "\n" if job.notes else "") + payload.notes

    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/receive-polish", response_model=ManufacturingJobRead, dependencies=[write])
async def receive_polish(
    job_id: int, payload: ReceiveFromPolish, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _expect_stage(job, JobStage.polish_assigned)

    after = Decimal(str(payload.weight_after_polish_g))
    before = Decimal(str(job.weight_before_polish_g))
    # Polishing usually removes metal, but rhodium and plating add a little,
    # so a gain is allowed and recorded as a negative loss.
    job.weight_after_polish_g = after
    job.polish_loss_g = before - after
    job.stage = JobStage.polish_received
    if payload.notes:
        job.notes = (job.notes + "\n" if job.notes else "") + payload.notes

    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/costs", response_model=ManufacturingJobRead, dependencies=[write])
async def set_costs(
    job_id: int, payload: SetJobCosts, db: DbSession
) -> ManufacturingJob:
    """Set/override one or more cost fields on a job. Only allowed before completion."""
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.stage in (JobStage.completed, JobStage.cancelled):
        raise HTTPException(status.HTTP_409_CONFLICT, "Cannot edit costs on a finalised job")
    for k, v in payload.model_dump(exclude_unset=True).items():
        setattr(job, k, v)
    await db.commit()
    await db.refresh(job)
    return job


@router.post(
    "/{job_id}/complete",
    response_model=ManufacturingJobRead,
    # Completing a job mints a new product and posts manufacturing_in stock
    # movements — irreversible without manual reversals, so password-confirm.
    dependencies=[write, Depends(require_password_confirm)],
)
async def complete_job(
    job_id: int, payload: CompleteJob, db: DbSession, current: CurrentUser
) -> ManufacturingJob:
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    _expect_stage(job, JobStage.polish_received, JobStage.stone_fixer_received, JobStage.karigar_received)

    final_gold_g = (
        Decimal(str(job.weight_after_polish_g))
        if job.weight_after_polish_g and Decimal(str(job.weight_after_polish_g)) > 0
        else Decimal(str(job.jewelry_received_g))
    )
    final_stones_ct = Decimal(str(job.stones_used_ct))

    total_cost = (
        Decimal(str(job.karigar_cost))
        + Decimal(str(job.stone_fixing_cost))
        + Decimal(str(job.polish_cost))
        + Decimal(str(job.other_cost))
    )

    product = Product(
        serial_no=await next_product_serial(db),
        name=payload.product_name,
        category=payload.category,
        gold_weight_g=final_gold_g,
        gold_purity=job.gold_assigned_purity,
        stone_weight_ct=final_stones_ct,
        total_cost=total_cost,
        status=ProductStatus.in_stock,
    )
    db.add(product)
    await db.flush()
    # Snapshot the gold value into material_cost using the current PKR rate.
    # Stones added later via /products/{id}/stones trigger a recompute.
    await recompute_material_cost(db, product)

    inv = InventoryItem(
        type=InventoryType.finished_product,
        label=payload.product_name,
        location=payload.finished_inventory_location,
        quantity=0,
        weight_g=Decimal("0"),
        weight_ct=Decimal("0"),
        purity=job.gold_assigned_purity,
        product_id=product.id,
    )
    db.add(inv)
    await db.flush()
    await post_movement(
        db,
        item=inv,
        type=MovementType.manufacturing_in,
        quantity_delta=1,
        weight_g_delta=final_gold_g,
        weight_ct_delta=final_stones_ct,
        reference_type="manufacturing_job",
        reference_id=job.id,
        notes=f"Job {job.job_no} completed",
        user_id=current.id,
    )

    job.product_id = product.id
    job.stage = JobStage.completed

    await log_action(
        db, user=current,
        action="manufacturing.complete",
        resource_type="manufacturing_job", resource_id=job.id,
        details={
            "product_id": product.id,
            "product_serial": product.serial_no,
            "gold_g": str(final_gold_g),
            "stones_ct": str(final_stones_ct),
            "labor_cost": str(total_cost),
            "material_cost": str(product.material_cost),
        },
    )
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/cancel", response_model=ManufacturingJobRead, dependencies=[write])
async def cancel_job(
    job_id: int,
    payload: CancelJob,
    db: DbSession,
    # Once a job has assigned material, cancelling it is destructive (costs/loss
    # left in the books, materials already moved). Require password confirmation
    # except for jobs still in draft.
    current: User = Depends(require_password_confirm),
) -> ManufacturingJob:
    """
    Cancel a job and settle its outstanding material.

    Gold and stones issued against the job were deducted from stock and are
    only credited back when the job completes. Cancelling therefore has to say
    what happened to them: whatever the shop physically recovers is returned to
    the source inventory rows, and the rest is written off on the job so it can
    be raised against the worker rather than quietly disappearing from stock.
    """
    job = await db.get(ManufacturingJob, job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    if job.stage in (JobStage.completed, JobStage.cancelled):
        raise HTTPException(status.HTTP_409_CONFLICT, "Job already finalised")

    # Outstanding = issued minus anything already credited back. Stones handed
    # back at receive-stone-fixer time have already returned to stock.
    gold_outstanding = Decimal(str(job.gold_assigned_g))
    stones_outstanding = Decimal(str(job.stones_assigned_ct)) - Decimal(str(job.stones_returned_ct))

    gold_recovered = Decimal(str(payload.gold_recovered_g))
    stones_recovered = Decimal(str(payload.stones_recovered_ct))

    if gold_recovered > gold_outstanding:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot recover {gold_recovered}g — only {gold_outstanding}g is outstanding on this job.",
        )
    if stones_recovered > stones_outstanding:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot recover {stones_recovered}ct — only {stones_outstanding}ct is outstanding on this job.",
        )

    if gold_recovered > 0:
        if job.gold_source_inventory_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This job has no recorded gold source, so recovered gold cannot be returned to stock.",
            )
        await post_movement(
            db,
            item=await _get_inventory(db, job.gold_source_inventory_id),
            type=MovementType.manufacturing_in,
            weight_g_delta=gold_recovered,
            reference_type="manufacturing_job",
            reference_id=job.id,
            notes=f"Gold recovered on cancellation of job {job.job_no}",
            user_id=current.id,
        )
    if stones_recovered > 0:
        if job.stone_source_inventory_id is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "This job has no recorded stone source, so recovered stones cannot be returned to stock.",
            )
        await post_movement(
            db,
            item=await _get_inventory(db, job.stone_source_inventory_id),
            type=MovementType.manufacturing_in,
            weight_ct_delta=stones_recovered,
            reference_type="manufacturing_job",
            reference_id=job.id,
            notes=f"Stones recovered on cancellation of job {job.job_no}",
            user_id=current.id,
        )

    prev_stage = job.stage
    job.gold_written_off_g = gold_outstanding - gold_recovered
    job.stones_written_off_ct = stones_outstanding - stones_recovered
    job.cancel_reason = payload.reason
    job.stage = JobStage.cancelled

    await log_action(
        db, user=current,
        action="manufacturing.cancel",
        resource_type="manufacturing_job", resource_id=job.id,
        details={
            "previous_stage": prev_stage.value,
            "reason": payload.reason,
            "gold_recovered_g": str(gold_recovered),
            "stones_recovered_ct": str(stones_recovered),
            "gold_written_off_g": str(job.gold_written_off_g),
            "stones_written_off_ct": str(job.stones_written_off_ct),
        },
    )
    await db.commit()
    await db.refresh(job)
    return job
