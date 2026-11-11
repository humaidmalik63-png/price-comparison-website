"""Shared pytest fixtures for the PriceWise AI test suite.

The suite must be reproducible on a clean checkout and must never depend on a
developer's local ``data/pricewise.db``. We therefore point
``PRICEWISE_DB_PATH`` at an isolated, freshly seeded temporary database *before*
``src.config`` is imported anywhere.

Module-scoped fixtures in the existing suite intentionally share a database for
the duration of a module, so the default database is seeded once per session
rather than reset per test. Tests that need a pristine copy can request the
``fresh_seeded_db`` fixture. Tests that pass ``custom_path=...`` are unaffected.
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TMP_ROOT = Path(tempfile.mkdtemp(prefix="pricewise-pytest-"))
_TEMPLATE_DB = _TMP_ROOT / "template.db"
_ACTIVE_DB = _TMP_ROOT / "active.db"

# Must be set before importing src.config (which captures DATABASE_PATH).
os.environ["PRICEWISE_DB_PATH"] = str(_ACTIVE_DB)

from src.database.seed import seed_database  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def seeded_template_db():
    """Seed a template database, then activate an identical session copy."""
    seed_database(custom_path=str(_TEMPLATE_DB), force=True)
    shutil.copyfile(_TEMPLATE_DB, _ACTIVE_DB)
    yield str(_TEMPLATE_DB)
    shutil.rmtree(_TMP_ROOT, ignore_errors=True)


@pytest.fixture(scope="session")
def seeded_db_path(seeded_template_db):
    """Path to the session-scoped seeded template database (read-only)."""
    return seeded_template_db


@pytest.fixture
def fresh_seeded_db(seeded_template_db):
    """Function-scoped pristine seeded database copy."""
    handle = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    path = handle.name
    handle.close()
    os.remove(path)
    try:
        shutil.copyfile(seeded_template_db, path)
        yield path
    finally:
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(path + suffix)
            if candidate.exists():
                candidate.unlink()
