import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mcq.db")
TURSO_DATABASE_URL = os.getenv("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.getenv("TURSO_AUTH_TOKEN")


def _build_engine():
    if TURSO_DATABASE_URL:
        if not TURSO_AUTH_TOKEN:
            raise RuntimeError("TURSO_AUTH_TOKEN is required when TURSO_DATABASE_URL is set")
        if not TURSO_DATABASE_URL.startswith("libsql://"):
            raise RuntimeError("TURSO_DATABASE_URL must start with libsql://")
        return create_engine(
            f"sqlite+{TURSO_DATABASE_URL}?secure=true",
            connect_args={"auth_token": TURSO_AUTH_TOKEN},
        )

    connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
    return create_engine(DATABASE_URL, connect_args=connect_args)


engine = _build_engine()
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def run_migrations():
    """Add columns introduced after initial schema without wiping data."""
    if TURSO_DATABASE_URL or not DATABASE_URL.startswith("sqlite"):
        return  # use Alembic for non-SQLite
    migrations = [
        "ALTER TABLE questions ADD COLUMN images TEXT",
    ]
    with engine.connect() as conn:
        for sql in migrations:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
