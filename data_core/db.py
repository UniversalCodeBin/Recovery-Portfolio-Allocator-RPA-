"""PostgreSQL loading for the RPA data foundation.

Loads the *validated* dataset into PostgreSQL using ``psycopg`` (no ORM, no
SQLAlchemy, no ``psycopg.extras``) -- keeps the data layer lightweight. Connection
parameters are read from environment variables in :mod:`data_core.config`; no
credentials are hard-coded.

Bulk loading uses PostgreSQL ``COPY ... FROM STDIN`` (CSV) fed from an
in-memory ``StringIO``. Dict/list payloads are JSON-serialized before copy so
the ``jsonb`` columns parse correctly; booleans are normalized to ``true``/
``false`` and nulls use the ``NULL ''`` marker.

DB loading is optional: the rest of Step 1 (generation, cleaning, validation,
splitting, reporting) works entirely off the filesystem and needs no database.
"""
from __future__ import annotations

import csv
import io
import json
import re
from typing import Dict

import pandas as pd

from .config import DB_APPLICATION_NAME, DB_SCHEMA, database_url
from .schema import SCHEMA_SQL, migration_files

# Dependency order: parents before children (FK-safe for inserts/truncates).
LOAD_ORDER = [
    "customers",
    "recovery_actions",
    "resource_constraints",
    "transactions",
    "action_outcomes",
    "recovery_predictions",
    "recovery_decisions",
    "audit_logs",
]
TRUNCATE_ORDER = list(reversed(LOAD_ORDER))


def _connect():
    """Open a psycopg connection (lazy import; gives a clear error)."""
    try:
        import psycopg  # psycopg3
    except ImportError as exc:  # pragma: no cover - environment guard
        raise RuntimeError(
            "psycopg is required for DB loading. Install via "
            "`uv pip install psycopg[binary]`."
        ) from exc
    conn = psycopg.connect(database_url(), application_name=DB_APPLICATION_NAME)
    conn.autocommit = False
    return conn


def connect():
    """Open and verify a connection to the configured PostgreSQL database."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:
        conn.close()
        raise
    return conn


def _normalize_df(df: pd.DataFrame) -> pd.DataFrame:
    """Prepare a DataFrame for COPY: JSON-serialize dict/list, normalize bools."""
    out = df.copy()
    # JSON columns -> JSON strings.
    for col in out.columns:
        series = out[col]
        if series.apply(lambda v: isinstance(v, (dict, list))).any():
            out[col] = series.apply(
                lambda v: json.dumps(v) if isinstance(v, (dict, list)) else v
            )
    # Boolean columns -> text 'true'/'false'.
    for col in out.columns:
        series = out[col]
        if series.apply(lambda v: isinstance(v, bool)).any():
            out[col] = series.map({True: "true", False: "false"}).where(
                series.notna(), other=None
            )
    return out


def _frame_to_copy(df: pd.DataFrame) -> bytes:
    """Serialize a DataFrame to CSV bytes suitable for ``COPY ... FROM STDIN``."""
    out = _normalize_df(df)
    buf = io.StringIO()
    out.to_csv(
        buf,
        index=False,
        header=False,
        na_rep="",
        quoting=csv.QUOTE_MINIMAL,
        quotechar='"',
    )
    return buf.getvalue().encode("utf-8")


def _quoted_cols(cols: list[str]) -> str:
    return ", ".join(f'"{c}"' for c in cols)


class Database:
    """Manages schema lifecycle and validated-data loading for one database."""

    _IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

    def __init__(self, schema: str = DB_SCHEMA) -> None:
        if not self._IDENTIFIER.fullmatch(schema):
            raise ValueError("invalid database schema identifier")
        self.schema = schema

    def _qualified(self, table: str) -> str:
        if not self._IDENTIFIER.fullmatch(table):
            raise ValueError("invalid table identifier")
        return f'"{self.schema}"."{table}"'

    # ------------------------------------------------------------------
    def _set_search_path(self, cur) -> None:
        cur.execute(f"SET LOCAL search_path TO {self.schema}")

    def create_schema(self, conn, reset: bool = False) -> None:
        """Create the target schema and apply each migration once."""
        with conn.cursor() as cur:
            if reset:
                cur.execute(f'DROP SCHEMA IF EXISTS "{self.schema}" CASCADE')
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            self._set_search_path(cur)
            cur.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
            )
            cur.execute("SELECT version FROM schema_migrations")
            applied = {row[0] for row in cur.fetchall()}
            if not applied:
                cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.customers",))
                if cur.fetchone()[0] is not None:
                    applied.add("V001__create_rpa_schema")
                cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.recovery_runs",))
                if cur.fetchone()[0] is not None:
                    applied.add("V002__add_rpa_backend")
                cur.execute("SELECT to_regclass(%s)", (f"{self.schema}.tenants",))
                if cur.fetchone()[0] is not None:
                    applied.add("V003__production_runtime_foundation")
            for mig in migration_files():
                if mig.stem in applied:
                    continue
                cur.execute(mig.read_text(encoding="utf-8"))
                cur.execute("INSERT INTO schema_migrations(version) VALUES (%s)", (mig.stem,))
        conn.commit()

    def create_schema_from_inline(self, conn, reset: bool = False) -> None:
        """Variant using the in-process SCHEMA_SQL constant (no file I/O)."""
        with conn.cursor() as cur:
            if reset:
                cur.execute(f"DROP SCHEMA IF EXISTS {self.schema} CASCADE")
            cur.execute(f"CREATE SCHEMA IF NOT EXISTS {self.schema}")
            self._set_search_path(cur)
            cur.execute(SCHEMA_SQL)
        conn.commit()

    # ------------------------------------------------------------------
    def load_frame(self, conn, table: str, df: pd.DataFrame, reset_table: bool = False, *, commit: bool = True) -> int:
        """Copy all rows of a validated DataFrame into ``<schema>.<table>``."""
        if df.empty:
            return 0
        qualified = self._qualified(table)
        cols = list(df.columns)
        data = _frame_to_copy(df)
        with conn.cursor() as cur:
            self._set_search_path(cur)
            if reset_table:
                cur.execute(f'TRUNCATE TABLE {qualified} RESTART IDENTITY CASCADE')
            stmt = (
                f'COPY {qualified} ({_quoted_cols(cols)}) '
                f"FROM STDIN WITH (FORMAT csv, NULL '')"
            )
            with cur.copy(stmt) as copy:
                copy.write(data)
        if commit:
            conn.commit()
        return len(df)

    def truncate_all(self, conn) -> None:
        with conn.cursor() as cur:
            self._set_search_path(cur)
            for table in TRUNCATE_ORDER:
                cur.execute(f'TRUNCATE TABLE {self._qualified(table)} RESTART IDENTITY CASCADE')
        conn.commit()

    def load_dataset(self, conn, frames: Dict[str, pd.DataFrame], reset: bool = False) -> Dict[str, int]:
        """Load all validated entity frames in dependency order."""
        if reset:
            self.truncate_all(conn)
        counts: Dict[str, int] = {}
        for table in LOAD_ORDER:
            df = frames.get(table, pd.DataFrame(columns=[]))
            counts[table] = self.load_frame(conn, table, df)
        return counts

    # ------------------------------------------------------------------
    def row_counts(self, conn) -> Dict[str, int]:
        with conn.cursor() as cur:
            self._set_search_path(cur)
            out: Dict[str, int] = {}
            for table in LOAD_ORDER:
                cur.execute(f'SELECT COUNT(*) FROM {self._qualified(table)}')
                out[table] = int(cur.fetchone()[0])
        return out


def drop_schema(conn, schema: str = DB_SCHEMA) -> None:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", schema):
        raise ValueError("invalid database schema identifier")
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
    conn.commit()


def table_names() -> list[str]:
    return list(LOAD_ORDER)


__all__ = ["Database", "connect", "drop_schema", "table_names", "LOAD_ORDER"]
