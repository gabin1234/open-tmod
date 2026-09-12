"""P01: PostgreSQL connection + init (DDL/seed). DSN from TMOD_PG_DSN. Usage: uv run python -m tmod.product.db init [--seed] [--drop]"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent.parent
DDL = ROOT / "db" / "ddl" / "001_schema.sql"
SEED = ROOT / "db" / "seed" / "002_sample.sql"
DEFAULT_DSN = "postgresql://tmod:tmod@localhost:5434/tmod"


def dsn() -> str:
    return os.getenv("TMOD_PG_DSN", DEFAULT_DSN)


def connect(d: str | None = None) -> psycopg.Connection:
    con = psycopg.connect(d or dsn(), autocommit=False)
    con.execute("SET search_path TO tmod, public")
    return con


def init(d: str | None = None, seed: bool = False, drop: bool = False) -> dict:
    with psycopg.connect(d or dsn(), autocommit=True) as con:
        if drop:
            con.execute("DROP SCHEMA IF EXISTS tmod CASCADE")
        con.execute(DDL.read_text())
        if seed:
            con.execute(SEED.read_text())
        tables = con.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema='tmod' AND table_type='BASE TABLE'").fetchone()[0]
        enums = con.execute("SELECT count(*) FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace WHERE n.nspname='tmod' AND t.typtype='e'").fetchone()[0]
        fks = con.execute("SELECT count(*) FROM information_schema.table_constraints WHERE table_schema='tmod' AND constraint_type='FOREIGN KEY'").fetchone()[0]
    return {"tables": tables, "enums": enums, "foreign_keys": fks}


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "init":
        print(init(seed="--seed" in a, drop="--drop" in a))
    else:
        print(__doc__)
