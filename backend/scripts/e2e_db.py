"""A fresh database of demo data for the Playwright tests.

  python scripts/e2e_db.py --url     print the e2e database URL (your DATABASE_URL, renamed)
  python scripts/e2e_db.py --reset   drop everything in it, migrate, and load the demo data

It refuses any database whose name doesn't contain "e2e", so it can't wipe real data.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, make_url, text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def e2e_url() -> str:
    from app.core.config import settings

    url = os.environ.get("E2E_DATABASE_URL") or str(
        make_url(settings.DATABASE_URL).set(database="dealflow_e2e").render_as_string(False)
    )
    return url


def reset(url: str) -> None:
    parsed = make_url(url)
    if "e2e" not in (parsed.database or ""):
        raise SystemExit(f"Refusing to reset {parsed.database!r}: its name must contain 'e2e'")

    # create the database on first use
    admin = create_engine(parsed.set(database="postgres"), isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": parsed.database}
        ).first()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{parsed.database}"'))
    admin.dispose()

    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()

    env = {**os.environ, "DATABASE_URL": url}
    for cmd in (
        ["alembic", "upgrade", "head"],
        [sys.executable, "-m", "app.initial_data"],
        [sys.executable, "-m", "app.demo_data"],
    ):
        subprocess.run(cmd, cwd=ROOT, env=env, check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--url", action="store_true")
    group.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    if args.url:
        print(e2e_url())
    else:
        reset(e2e_url())
        print(f"Reset {make_url(e2e_url()).database} with the demo data")
