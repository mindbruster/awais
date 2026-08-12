"""
Open psql on the database the application actually uses.

The obvious version of this command is `docker exec -it <container> psql`, and
it is wrong on any machine where something else already holds 5432 — you get a
shell on the container's database while the app talks to the other one, and
every query answers about the wrong data with no hint that it is doing so.
Resolving the connection from `DATABASE_URL` is the only version that cannot
lie to you.

Run: python -m tools.db_psql   (or `npm run db:psql`)
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from urllib.parse import unquote, urlparse

from app.core.config import settings


def main() -> int:
    raw = settings.database_url.replace("+asyncpg", "").replace("+psycopg2", "")
    u = urlparse(raw)
    name = u.path.lstrip("/")

    psql = shutil.which("psql")
    if not psql:
        print(
            "psql is not on PATH. Either install the Postgres client tools, or\n"
            "use the container's own client:\n\n"
            "    docker exec -it jewelry_erp_postgres psql -U jewelry -d jewelry_erp\n\n"
            "— but note that only reaches the container's database, which is not\n"
            f"necessarily the one this app uses ({u.hostname}:{u.port or 5432}/{name}).",
            file=sys.stderr,
        )
        return 1

    env = dict(os.environ)
    if u.password:
        env["PGPASSWORD"] = unquote(u.password)

    print(f"  {name} on {u.hostname}:{u.port or 5432} as {u.username}")
    return subprocess.call(
        [
            psql,
            "-h", u.hostname or "localhost",
            "-p", str(u.port or 5432),
            "-U", unquote(u.username or "postgres"),
            "-d", name,
        ],
        env=env,
    )


if __name__ == "__main__":
    raise SystemExit(main())
