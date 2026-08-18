"""
Every picture the database points at — is the file actually still there?

An image URL on a record is not a promise the file exists. Files get moved when
storage changes, deleted when somebody prunes a folder, and orphaned by a
restore that brought the database back without `uploads/`. Nothing notices,
because nothing reads an image until somebody opens the screen — and then it
shows as a broken frame in front of a customer.

This walks every record that carries an image and checks the file behind it.

**Two directions, and both are worth knowing.** A *missing* file is a record
pointing at nothing — that is the broken frame. An *orphan* is a file on disk no
record points at — harmless to the shop, but it is what a folder fills up with,
and after a migration a pile of them usually means URLs were rewritten and the
old ones left behind.

Local disk only. On S3 the same check needs a HEAD per object and a bill to go
with it; when the shop moves to object storage this grows a `--remote` flag
rather than pretending it already covered it.

Run: `python -m tools.check_images`   (or `npm run check:images`)

Exits 0 when every referenced file is present, 1 when any is missing.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

from sqlalchemy import select

# This prints a short report a person reads; SQL echo would bury it.
logging.disable(logging.INFO)

from app.core.database import SessionLocal
from app.models.branch import Branch
from app.models.design import Design
from app.models.product import Product

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
PREFIX = "/static/"


def local_path(url: str) -> Path | None:
    """The file a `/static/...` URL means, or None if it is not ours to check."""
    if not url.startswith(PREFIX):
        return None
    return UPLOAD_DIR / url.removeprefix(PREFIX)


async def main() -> int:
    referenced: set[str] = set()
    missing: list[tuple[str, str, str]] = []
    remote = 0

    async with SessionLocal() as db:
        for model, column, label, name_col in (
            (Product, Product.image_url, "product", Product.serial_no),
            (Design, Design.image_url, "design", Design.design_no),
            (Branch, Branch.logo_url, "branch logo", Branch.name),
        ):
            rows = (
                await db.execute(
                    select(name_col, column).where(column.is_not(None), column != "")
                )
            ).all()
            for who, url in rows:
                path = local_path(url)
                if path is None:
                    # An absolute URL — object storage or a CDN. Counted so the
                    # summary cannot imply everything was checked when it wasn't.
                    remote += 1
                    continue
                referenced.add(path.name)
                if not path.exists():
                    missing.append((label, str(who), url))

    on_disk = {p.name for p in UPLOAD_DIR.iterdir() if p.is_file()} if UPLOAD_DIR.exists() else set()
    orphans = sorted(on_disk - referenced)

    if missing:
        print(f"{len(missing)} image(s) referenced by a record but not on disk:\n")
        for label, who, url in missing:
            print(f"  • {label} {who}: {url}")
        print(
            "\nEach of these renders as a missing picture on screen. Either the file "
            "was deleted, or the database was restored without its uploads folder."
        )
    else:
        print(f"All {len(referenced)} referenced image(s) are present.")

    if remote:
        print(f"\n{remote} image(s) live in object storage and were not checked — "
              "this tool reads the local disk only.")
    if orphans:
        print(f"\n{len(orphans)} file(s) on disk that no record points at:")
        for o in orphans[:10]:
            print(f"  · {o}")
        if len(orphans) > 10:
            print(f"  · … and {len(orphans) - 10} more")
        print("Harmless, but this is what fills a folder up. Safe to delete once "
              "you are sure no backup depends on them.")

    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
