"""
Drop and recreate the database `DATABASE_URL` points at.

The E2E suite needs a database nobody has used yet — it mints serial numbers
and asserts on running balances, so a second run against the same data reports
failures that look like product bugs and are not. This is how you give it one.

Deliberately keyed off `DATABASE_URL` rather than the Docker container. On a
machine where a native Postgres and the container both claim 5432, the native
one wins for `127.0.0.1` connections, so `docker compose down -v` cheerfully
wipes a database the application was never talking to and leaves the real one
exactly as dirty as it was. Resolving the target the same way the app resolves
it is the only way to be sure the right database is the one that gets rebuilt.

Run: python -m tools.db_fresh   (or `npm run db:fresh`, which also migrates and
seeds)
"""
from __future__ import annotations

import asyncio
import sys
from urllib.parse import urlparse, urlunparse

import asyncpg

from app.core.config import settings

# Environments where dropping the database is a normal thing to want. Anything
# else — staging, production, or a name nobody anticipated — is refused. A
# --force is deliberately not offered: the cost of being wrong here is the
# shop's books, and typing the SQL by hand is a reasonable thing to have to do.
SAFE_ENVIRONMENTS = {"development", "test", "ci", "local"}


def _target() -> tuple[str, str]:
    """The maintenance URL to connect on, and the database name to rebuild."""
    raw = settings.database_url.replace("+asyncpg", "").replace("+psycopg2", "")
    parsed = urlparse(raw)
    name = parsed.path.lstrip("/")
    if not name:
        sys.exit("DATABASE_URL has no database name in it.")
    # Postgres will not drop the database you are connected to, so the work is
    # done from `postgres`, which always exists.
    return urlunparse(parsed._replace(path="/postgres")), name


async def main() -> int:
    env = settings.environment.lower()
    if env not in SAFE_ENVIRONMENTS:
        sys.exit(
            f"Refusing to drop a database in environment '{settings.environment}'.\n"
            "This is only for development databases."
        )

    admin_url, name = _target()
    conn = await asyncpg.connect(admin_url)
    try:
        # Anything still holding a connection — a running API, an open psql, a
        # pgAdmin tab — blocks the drop. Closing them is the whole reason this
        # is a script and not a one-liner people paste.
        closed = await conn.fetch(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            name,
        )
        if closed:
            print(f"  closed {len(closed)} open connection(s) to {name}")
        await conn.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await conn.execute(f'CREATE DATABASE "{name}"')
    finally:
        await conn.close()

    host = urlparse(admin_url).hostname
    print(f"  {name} recreated on {host} — empty, unmigrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
