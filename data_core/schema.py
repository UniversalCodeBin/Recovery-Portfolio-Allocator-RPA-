"""PostgreSQL schema definition for the RPA data foundation.

Exposes the canonical DDL. The **single source of truth** on disk is
``database/schema/rpa_schema.sql``; this module loads it so the programmatic
schema and the human-readable file can never drift. The versioned migration
``database/migrations/V001__create_rpa_schema.sql`` is an identical, directly
executable copy (applied in lexical order by :mod:`data_core.db`).

Design notes:
* Primary keys use stable string ids (prefixed per entity: cust_*, txn_*,
  act_*, out_*, pred_*, rc_*, dec_*, aud_*).
* All foreign keys enforce referential integrity at the database level.
* Timestamps are stored as ``timestamptz`` (UTC).
* ``resource_requirements`` and ``*_metadata`` columns are ``jsonb`` so the
  schema stays flexible for future Step 2/3 fields without a migration.
"""
from __future__ import annotations

from pathlib import Path

from .config import SQL_SCHEMA_DIR, SQL_MIGRATIONS_DIR

_SCHEMA_FILE = SQL_SCHEMA_DIR / "rpa_schema.sql"


def load_schema_sql() -> str:
    """Return the canonical schema DDL, loaded from the on-disk file."""
    return _SCHEMA_FILE.read_text(encoding="utf-8")


SCHEMA_SQL: str = load_schema_sql()


def schema_statements() -> list[str]:
    """Split the schema DDL into individual executable statements (for psycopg)."""
    stmts: list[str] = []
    buf: list[str] = []
    for line in SCHEMA_SQL.splitlines():
        buf.append(line)
        if line.strip().endswith(";"):
            text = "\n".join(buf).strip()
            if text:
                stmts.append(text)
            buf = []
    if buf:
        text = "\n".join(buf).strip()
        if text:
            stmts.append(text)
    return stmts


def migration_files() -> list[Path]:
    """Ordered list of migration files in database/migrations/."""
    return sorted(SQL_MIGRATIONS_DIR.glob("V*.sql"))


def migration_text() -> str:
    """Concatenate all migration files into a single SQL script (ordered)."""
    parts = [p.read_text(encoding="utf-8") for p in migration_files()]
    return "\n\n".join(parts)


__all__ = ["SCHEMA_SQL", "schema_statements", "migration_files", "migration_text"]
