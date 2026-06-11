"""
Initialize the database: create schema and (optionally) load seed data.

SQLite (default, local dev):
    python db/init_db.py [--seed] [--db path/to/file.db]

Postgres (set DATABASE_URL env var):
    DATABASE_URL=postgresql://user:pass@host/dbname python db/init_db.py [--seed]
"""

import argparse
import os
import sys
from pathlib import Path

DB_DIR = Path(__file__).parent
SCHEMA_SQL = DB_DIR / "schema.sql"
SEED_SQL = DB_DIR / "seed.sql"
DEFAULT_SQLITE_PATH = DB_DIR.parent / "dental.db"


def get_sqlite_connection(db_path: str):
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def get_postgres_connection(url: str):
    try:
        import psycopg2
    except ImportError:
        print("psycopg2 not installed. Run: pip install psycopg2-binary", file=sys.stderr)
        sys.exit(1)
    return psycopg2.connect(url)


def run_sql_file(conn, path: Path, provider: str) -> None:
    sql = path.read_text()
    if provider == "postgres":
        # Translate SQLite-isms to Postgres
        sql = sql.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        sql = sql.replace("datetime('now')", "NOW()")
        # sqlite3 executes the whole script; psycopg2 needs it split
        import psycopg2
        with conn.cursor() as cur:
            cur.execute(sql)
    else:
        conn.executescript(sql)


def init(db_path: str | None, with_seed: bool) -> None:
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        provider = "postgres"
        conn = get_postgres_connection(database_url)
        print(f"Connected to Postgres: {database_url.split('@')[-1]}")
    else:
        provider = "sqlite"
        path = db_path or str(DEFAULT_SQLITE_PATH)
        conn = get_sqlite_connection(path)
        print(f"Using SQLite: {path}")

    try:
        print("Applying schema...")
        run_sql_file(conn, SCHEMA_SQL, provider)
        conn.commit()
        print("  schema OK")

        if with_seed:
            print("Loading seed data...")
            run_sql_file(conn, SEED_SQL, provider)
            conn.commit()
            print("  seed OK")

        print("Done.")
    except Exception as exc:
        conn.rollback()
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialise the dental assistant DB")
    parser.add_argument("--seed", action="store_true", help="Load seed data after schema")
    parser.add_argument("--db", metavar="PATH", help="SQLite file path (ignored if DATABASE_URL set)")
    parser.add_argument("--reset", action="store_true", help="Delete existing SQLite file before init")
    args = parser.parse_args()

    if args.reset and not os.getenv("DATABASE_URL"):
        target = args.db or str(DEFAULT_SQLITE_PATH)
        if Path(target).exists():
            Path(target).unlink()
            print(f"Deleted {target}")

    init(db_path=args.db, with_seed=args.seed)
