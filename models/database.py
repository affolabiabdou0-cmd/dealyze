from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config.settings import settings

_is_sqlite = settings.database_url.startswith("sqlite")
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if _is_sqlite else {},
    echo=False,
)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables. Called once at app startup."""
    from models import schemas  # noqa: F401
    from models import user     # noqa: F401
    Base.metadata.create_all(bind=engine)
    _run_lightweight_migrations()


_USERS_COLUMNS_TO_ENSURE = [
    ("current_period_end",  "TIMESTAMP"),
    ("email_verified",      "BOOLEAN DEFAULT FALSE"),
    ("verification_token",  "VARCHAR"),
    ("verification_expires", "TIMESTAMP"),
    ("reset_token",          "VARCHAR"),
    ("reset_token_expires",  "TIMESTAMP"),
    ("failed_login_attempts", "INTEGER DEFAULT 0"),
    ("locked_until",          "TIMESTAMP"),
]


def _run_lightweight_migrations():
    """Add columns to already-existing tables (no Alembic in this project)."""
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        return
    existing_cols = {c["name"] for c in inspector.get_columns("users")}
    for col_name, col_type in _USERS_COLUMNS_TO_ENSURE:
        if col_name not in existing_cols:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_type}"))
