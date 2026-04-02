"""
Database engine, session factory, and declarative base.

Uses DATABASE_URL from environment (.env). Defaults to SQLite for local dev.
PostgreSQL for staging/production (set DATABASE_URL in .env or environment).

Usage:
    from app.data.database import SessionLocal, engine, Base

    # In a request or job:
    db = SessionLocal()
    try:
        ...
    finally:
        db.close()
"""

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "sqlite:///./optiroute.db",
)

# SQLite requires check_same_thread=False for use with FastAPI's async
connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    # Increase busy timeout to wait for locks rather than failing immediately
    # and enable WAL mode for better concurrency with readers/writers.
    connect_args["timeout"] = 30

engine = create_engine(DATABASE_URL, connect_args=connect_args, echo=False)
# If using SQLite, enable WAL mode to reduce locking contention
if DATABASE_URL.startswith("sqlite"):
    try:
        from sqlalchemy import text

        with engine.connect() as conn:
            conn.execute(text("PRAGMA journal_mode=WAL"))
            conn.commit()
    except Exception:
        # Non-fatal: if PRAGMA fails, continue with default settings
        pass
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def init_db():
    """Create all tables from ORM models. For dev/testing quick-start.
    In production, use Alembic migrations instead."""
    from app.data import models  # noqa: F401 — registers models with Base

    # For SQLite: only attempt to create tables when the DB file does not
    # already exist. Running DDL (CREATE TABLE) while another process has
    # the DB open can raise 'database is locked'. We assume migrations or
    # prior initialization have created tables if the file exists.
    if DATABASE_URL.startswith("sqlite"):
        # Handle in-memory DB explicitly
        if DATABASE_URL == "sqlite:///:memory:":
            Base.metadata.create_all(bind=engine)
            return

        # Extract filesystem path from URL like sqlite:///./optiroute.db
        prefix = "sqlite:///"
        db_path = DATABASE_URL[len(prefix) :] if DATABASE_URL.startswith(prefix) else None
        if db_path:
            db_file = Path(db_path)
            # If the DB file already exists, skip create_all to avoid locking
            if db_file.exists():
                return

    # Default: attempt to create tables (Postgres, new SQLite file, etc.)
    Base.metadata.create_all(bind=engine)
