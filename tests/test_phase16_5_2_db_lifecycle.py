"""Phase 16.5.2 regression tests for SQLite connection lifecycle and seeding.

The original failure was:

    sqlite3.ProgrammingError: Cannot operate on a closed database

caused by the Phase 16.2 OBF seed block living outside its
``with get_connection(...)`` block. These tests run entirely against isolated
temporary databases and never touch the application database.
"""

import os
import sqlite3
import tempfile

import pytest

from src.database.connection import get_connection, init_db, migrate_db
from src.database.seed import (
    DEMO_BEAUTY_PRODUCTS,
    DEMO_BEAUTY_STORES,
    DEMO_OBF_PRODUCTS,
    DEMO_PRODUCTS,
    DEMO_STORES,
    seed_database,
)

EXPECTED_PRODUCTS = len(DEMO_PRODUCTS) + len(DEMO_BEAUTY_PRODUCTS) + len(DEMO_OBF_PRODUCTS)
EXPECTED_STORES = len(DEMO_STORES) + len(DEMO_BEAUTY_STORES)


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


def _counts(path: str) -> dict[str, int]:
    with get_connection(path) as conn:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("products", "stores", "offers", "price_history")
        }


# ── Connection ownership ─────────────────────────────────────────────────────

def test_connection_is_closed_after_context_exit(db_path):
    init_db(db_path)
    with get_connection(db_path) as conn:
        conn.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_connection_rolls_back_on_exception(db_path):
    init_db(db_path)
    with pytest.raises(RuntimeError):
        with get_connection(db_path) as conn:
            conn.execute(
                "INSERT INTO stores (name, domain) VALUES ('RollbackStore', 'rollback.example')"
            )
            raise RuntimeError("boom")

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id FROM stores WHERE name='RollbackStore'"
        ).fetchone()
        assert row is None


def test_connections_are_independent(db_path):
    init_db(db_path)
    with get_connection(db_path) as first:
        first.execute(
            "INSERT INTO stores (name, domain) VALUES ('StoreA', 'a.example')"
        )
        # A second connection sees the committed data only after the first exits.
        with get_connection(db_path) as second:
            second.execute("SELECT 1")

    with get_connection(db_path) as check:
        assert check.execute(
            "SELECT COUNT(*) FROM stores WHERE name='StoreA'"
        ).fetchone()[0] == 1


# ── Repeated seeding ─────────────────────────────────────────────────────────

def test_seed_database_runs_repeatedly_without_closed_db_errors(db_path):
    counts = []
    for _ in range(3):
        seed_database(custom_path=db_path, force=True)
        counts.append(_counts(db_path))

    assert counts[0] == counts[1] == counts[2]
    assert counts[0]["products"] == EXPECTED_PRODUCTS
    assert counts[0]["stores"] == EXPECTED_STORES
    assert counts[0]["offers"] > 0
    assert counts[0]["price_history"] > 0

    with get_connection(db_path) as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_seed_without_force_is_idempotent(db_path):
    seed_database(custom_path=db_path, force=True)
    first = _counts(db_path)

    seed_database(custom_path=db_path, force=False)
    second = _counts(db_path)

    assert second == first


def test_forced_reseed_succeeds_when_dependent_rows_exist(db_path):
    seed_database(custom_path=db_path, force=True)

    with get_connection(db_path) as conn:
        product_id = conn.execute("SELECT id FROM products LIMIT 1").fetchone()["id"]
        conn.execute(
            """
            INSERT INTO retail_price_observation
                (product_id, retailer, product_url, observed_price, observation_type)
            VALUES (?, 'Nykaa', 'https://nykaa.com/p/1', 199.0, 'live')
            """,
            (product_id,),
        )

    # Forced reseed must clear dependents in FK-safe order rather than crash.
    seed_database(custom_path=db_path, force=True)
    assert _counts(db_path)["products"] == EXPECTED_PRODUCTS


def test_init_and_migrate_are_repeatable(db_path):
    for _ in range(3):
        init_db(db_path)
        migrate_db(db_path)

    with get_connection(db_path) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "updated_at" in cols
