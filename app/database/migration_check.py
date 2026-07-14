"""Validate that a process only starts against the schema it was built for."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import AsyncEngine


class DatabaseSchemaMismatchError(RuntimeError):
    """Raised when the database revision does not match this runtime image."""


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def expected_database_revision() -> str:
    """Return the only Alembic head bundled with the running application."""
    project_root = _project_root()
    config = Config(str(project_root / "alembic.ini"))
    config.set_main_option("script_location", str(project_root / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()
    if len(heads) != 1:
        raise DatabaseSchemaMismatchError(
            f"Runtime image must contain exactly one Alembic head, found: {', '.join(heads) or 'none'}"
        )
    return heads[0]


def _current_database_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


async def require_current_database_revision(engine: AsyncEngine) -> None:
    """Fail fast with an actionable message when code and database schemas diverge."""
    expected_revision = expected_database_revision()
    async with engine.connect() as connection:
        current_revision = await connection.run_sync(_current_database_revision)
    if current_revision != expected_revision:
        raise DatabaseSchemaMismatchError(
            "Database Alembic revision mismatch: "
            f"database={current_revision or 'none'}, runtime={expected_revision}. "
            "Run 'alembic upgrade head' from this runtime image before starting services."
        )
