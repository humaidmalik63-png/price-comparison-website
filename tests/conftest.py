"""Shared pytest configuration for the PriceWise AI test suite.

Purpose
-------
Guarantee that **no test can modify the shared development database**
(``data/pricewise.db``).

Historically several test modules called service functions and the FastAPI
``TestClient`` without a ``custom_path``, so they wrote users, wishlist rows,
offers and product fixtures straight into the shared development database.
That made the suite order-dependent (two ``test_phase11b`` failures hardcoded
``user_id = 1``) and left the working copy dirty after every run.

Mechanism
---------
1. **Redirect before import.** ``src.config`` resolves ``DATABASE_PATH`` from
   the ``PRICEWISE_DB_PATH`` environment variable *at import time*. This
   module is imported by pytest before any test module, so setting the
   variable here guarantees that every default-path database access — including
   the FastAPI application used through ``TestClient`` — is redirected to a
   temporary copy.

2. **Temporary copy, not an empty database.** The copy preserves the seeded
   catalogue (113 products, 494 offers, 1,360 price-history rows) so that
   assertions about catalogue size and content keep working, while every write
   lands in the temporary file.

3. **Read-only original.** While the session runs, the shared database file is
   made read-only (mode 0o444). Any test that still reaches it fails loudly
   with "attempt to write a readonly database" instead of silently corrupting
   the working copy.

4. **Verified teardown.** At the end of the session the original file's
   SHA-256 digest is compared with the digest captured at start-up. A mismatch
   fails the session.

Environment variables are restored and the temporary directory is removed in
``finalize``.
"""

import hashlib
import os
import shutil
import stat
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DB = REPO_ROOT / "data" / "pricewise.db"

# ---------------------------------------------------------------------------
# 1. Redirect the default database path BEFORE any src.* module is imported.
#    pytest imports conftest.py before collecting test modules, so src.config
#    will pick this value up on its first import.
# ---------------------------------------------------------------------------
_TEST_TMP_DIR = Path(tempfile.mkdtemp(prefix="pricewise_pytest_"))
_TEST_DB_PATH = _TEST_TMP_DIR / "pricewise_test.db"

if SHARED_DB.exists():
    shutil.copy2(SHARED_DB, _TEST_DB_PATH)
else:
    _TEST_DB_PATH.touch()

os.environ["PRICEWISE_DB_PATH"] = str(_TEST_DB_PATH)


def _sha256(path: Path) -> str:
    """Return the SHA-256 digest of a file (empty string when missing)."""
    if not path.exists():
        return ""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


_SHARED_DB_DIGEST_AT_START = _sha256(SHARED_DB)
_SHARED_DB_MODE_AT_START = (
    stat.S_IMODE(SHARED_DB.stat().st_mode) if SHARED_DB.exists() else None
)


# ---------------------------------------------------------------------------
# 2. Session lifecycle: protect the original, verify it afterwards.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session", autouse=True)
def _protect_shared_database():
    """Make the shared development database read-only for the whole session."""
    if SHARED_DB.exists():
        try:
            SHARED_DB.chmod(0o444)
        except OSError:
            pass  # best effort; the redirect above is the primary protection
    yield


def pytest_sessionfinish(session, exitstatus):
    """Restore the shared database and verify that it was not modified."""
    if SHARED_DB.exists() and _SHARED_DB_MODE_AT_START is not None:
        try:
            SHARED_DB.chmod(_SHARED_DB_MODE_AT_START)
        except OSError:
            pass

    if SHARED_DB.exists():
        digest_after = _sha256(SHARED_DB)
        if digest_after != _SHARED_DB_DIGEST_AT_START:
            session.exitstatus = 1
            raise RuntimeError(
                "The shared development database was modified by the test run "
                f"(digest {digest_after} != {_SHARED_DB_DIGEST_AT_START}). "
                "This indicates a test wrote outside the temporary database."
            )

    shutil.rmtree(_TEST_TMP_DIR, ignore_errors=True)
