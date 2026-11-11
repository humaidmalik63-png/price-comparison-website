"""Phase 16.5.2 regression tests for SQLite migration compatibility.

Covers the SQLite limitation that rejected:

    ALTER TABLE products ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

The fix adds the column without a non-constant default, backfills only NULL
values, and installs idempotent triggers. These tests use isolated temporary
databases only — never the real application database.
"""

import os
import tempfile
from pathlib import Path

import pytest

from src.config import SCHEMA_PATH
from src.database.connection import get_connection, init_db, migrate_db


@pytest.fixture
def temp_db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


def _make_legacy_phase6_db(path: str) -> None:
    """Create a schema-complete database whose products table lacks updated_at.

    This reproduces the pre-Phase-16 shape of the products table without
    duplicating the whole schema by hand.
    """
    schema = Path(SCHEMA_PATH).read_text(encoding="utf-8")
    products_block = (
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,\n"
        "    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
        ");"
    )
    legacy_products_block = (
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n"
        ");"
    )
    assert products_block in schema, "schema did not match expected products block"
    legacy_schema = schema.replace(products_block, legacy_products_block, 1)

    with get_connection(path) as conn:
        conn.executescript(legacy_schema)
        conn.execute(
            """
            INSERT INTO products (id, sku, title, brand, category, description, specs_json)
            VALUES (1, 'LEGACY-001', 'Legacy Product', 'BrandX', 'Laptops',
                    'Legacy description', '{"Size": "30ml"}')
            """
        )
        conn.execute(
            "INSERT INTO stores (id, name, domain, rating) VALUES (1, 'LegacyStore', 'legacy.example', 4.2)"
        )
        conn.execute(
            """
            INSERT INTO offers (id, product_id, store_id, current_price, original_price, currency)
            VALUES (10, 1, 1, 950.0, 1200.0, 'USD')
            """
        )
        conn.execute(
            "INSERT INTO price_history (id, offer_id, price, currency) VALUES (100, 10, 950.0, 'USD')"
        )

    # Confirm the legacy shape really has no updated_at column.
    with get_connection(path) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
    assert "updated_at" not in cols


# ── Fresh database ───────────────────────────────────────────────────────────

def test_fresh_database_has_updated_at_and_triggers(temp_db_path):
    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "updated_at" in cols

        triggers = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='products'"
            )
        }
        assert "trg_products_updated_at_insert" in triggers
        assert "trg_products_updated_at_update" in triggers


def test_fresh_database_insert_and_update_receive_timestamps(temp_db_path):
    init_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        conn.execute(
            "INSERT INTO products (sku, title, brand, category) VALUES ('FRESH-1', 'Fresh', 'B', 'C')"
        )
        pid = conn.execute("SELECT id FROM products WHERE sku='FRESH-1'").fetchone()["id"]
        inserted_ts = conn.execute(
            "SELECT updated_at FROM products WHERE id=?", (pid,)
        ).fetchone()["updated_at"]
        assert inserted_ts is not None

        # Force an old timestamp, then update another column: the trigger must
        # refresh updated_at without any application-level code doing it.
        conn.execute(
            "UPDATE products SET updated_at='2020-01-01 00:00:00' WHERE id=?", (pid,)
        )
        conn.execute("UPDATE products SET title='Fresh Renamed' WHERE id=?", (pid,))
        refreshed = conn.execute(
            "SELECT updated_at FROM products WHERE id=?", (pid,)
        ).fetchone()["updated_at"]
        assert refreshed != "2020-01-01 00:00:00"


# ── Existing Phase 6 database ────────────────────────────────────────────────

def test_legacy_db_migration_adds_column_and_preserves_records(temp_db_path):
    _make_legacy_phase6_db(temp_db_path)

    migrate_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "updated_at" in cols

        product = conn.execute(
            "SELECT id, sku, title, brand, category, description FROM products WHERE id=1"
        ).fetchone()
        assert product is not None
        assert product["sku"] == "LEGACY-001"
        assert product["title"] == "Legacy Product"
        assert product["brand"] == "BrandX"

        offer = conn.execute(
            "SELECT id, product_id, store_id, current_price FROM offers WHERE id=10"
        ).fetchone()
        assert offer["product_id"] == 1
        assert offer["store_id"] == 1
        assert offer["current_price"] == 950.0

        assert conn.execute(
            "SELECT COUNT(*) FROM price_history WHERE offer_id=10"
        ).fetchone()[0] == 1


def test_legacy_db_timestamps_are_backfilled(temp_db_path):
    _make_legacy_phase6_db(temp_db_path)

    # The legacy column does not exist at all before the migration.
    with get_connection(temp_db_path) as conn:
        cols = {row["name"] for row in conn.execute("PRAGMA table_info(products)")}
        assert "updated_at" not in cols

    migrate_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        rows = conn.execute("SELECT id, updated_at FROM products").fetchall()
        assert rows
        assert all(row["updated_at"] is not None for row in rows)


def test_migration_preserves_foreign_keys_and_indexes(temp_db_path):
    _make_legacy_phase6_db(temp_db_path)

    migrate_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert violations == []

        indexes = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='products'"
            )
        }
        assert "idx_products_brand" in indexes

        # Relationship still resolvable through a join.
        joined = conn.execute(
            """
            SELECT p.id, o.id AS offer_id
            FROM products p
            JOIN offers o ON o.product_id = p.id
            WHERE p.id = 1 AND o.id = 10
            """
        ).fetchone()
        assert joined is not None


# ── Idempotency ──────────────────────────────────────────────────────────────

def test_migration_is_idempotent(temp_db_path):
    _make_legacy_phase6_db(temp_db_path)

    migrate_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        cols_after_first = [row["name"] for row in conn.execute("PRAGMA table_info(products)")]
        counts_after_first = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in ("products", "stores", "offers", "price_history")
        }

    migrate_db(temp_db_path)  # must not raise or duplicate anything
    migrate_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        cols_after_second = [row["name"] for row in conn.execute("PRAGMA table_info(products)")]
        assert cols_after_second == cols_after_first
        for table, expected in counts_after_first.items():
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == expected


def test_migration_does_not_overwrite_existing_timestamps(temp_db_path):
    _make_legacy_phase6_db(temp_db_path)
    migrate_db(temp_db_path)

    fixed = "2021-06-15 12:34:56"
    with get_connection(temp_db_path) as conn:
        conn.execute("UPDATE products SET updated_at=? WHERE id=1", (fixed,))

    migrate_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        assert conn.execute(
            "SELECT updated_at FROM products WHERE id=1"
        ).fetchone()["updated_at"] == fixed


def test_legacy_insert_after_migration_gets_timestamp(temp_db_path):
    _make_legacy_phase6_db(temp_db_path)
    migrate_db(temp_db_path)

    with get_connection(temp_db_path) as conn:
        conn.execute(
            "INSERT INTO products (sku, title, brand, category) VALUES ('LEGACY-002', 'New', 'B', 'C')"
        )
        ts = conn.execute(
            "SELECT updated_at FROM products WHERE sku='LEGACY-002'"
        ).fetchone()["updated_at"]
        assert ts is not None
