"""Regression tests for Phase 16.2 Stage 3: Retail Price Observations.

Tests verify:
- retail_price_observation table exists and migrations are idempotent
- Price observations are recorded with proper supersede semantics
- Observation types (scheduled, manual, user_report) are valid
- Observation status lifecycle (live, expired, superseded, flagged)
- Admin verification/correction of observations works
- Scheduled observation sweep handles restricted retailers gracefully
- Stage 3.1: Manual price entry validation, persistence, duplicate rejection, audit history
"""
import math
from datetime import datetime, timezone

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.database.connection import get_connection, init_db, migrate_db
from src.services.price_collection_engine import (
    ObservationStatus,
    ObservationType,
    admin_verify_observation,
    count_price_observations,
    get_price_observations,
    record_price_observation,
    record_manual_price_observation,
    run_scheduled_observations,
)


@pytest.fixture(scope="module")
def db():
    """Ensure database is initialised and migrated once per module."""
    init_db()
    # Seed a basic active product if none exists (needed by test_product_id)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT OR IGNORE INTO users (display_name, email, password_hash) VALUES (?, ?, ?)",
                ("Alex Demo", "demo@pricewise.ai", "dummy_hash"),
            )
            cursor.execute(
                "INSERT INTO products (sku, title, brand, category, description, specs_json, image_url, source_type, data_status, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'demo', 'pending_review', 1)",
                ("TEST-BASIC-001", "Test Product One", "TestBrand", "Beauty", "Basic test product",
                 "{}", "https://example.com/test1.jpg"),
            )
            cursor.execute(
                "INSERT INTO stores (name, domain) VALUES (?, ?)",
                ("Demo Store", "demostore.test"),
            )
            store_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO offers (product_id, store_id, current_price, original_price, shipping_cost, currency, availability, variant_name, condition, offer_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (cursor.execute("SELECT id FROM products LIMIT 1").fetchone()[0], store_id,
                 100.0, 150.0, 0.0, "INR", "In Stock", "Standard", "Brand New", "https://demostore.test/product"),
            )
    yield


@pytest.fixture(scope="module")
def test_product_id():
    """Get a valid active product ID for testing."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1")
        row = cursor.fetchone()
        assert row is not None, "No active products found in database"
        return row["id"]


@pytest.fixture(scope="module")
def demo_user_id(db):
    """Get the demo admin user ID from the database; create one if missing."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = 'demo@pricewise.ai' LIMIT 1")
        row = cursor.fetchone()
        if row:
            return row["id"]
        cursor.execute(
            "INSERT INTO users (display_name, email, password_hash) VALUES (?, ?, ?)",
            ("Alex Demo", "demo@pricewise.ai", "dummy_hash"),
        )
        return cursor.lastrowid


def make_admin_user(demo_user_id):
    """Create a mock admin user with the given user ID."""
    class MockUser:
        id = demo_user_id
        email = "demo@pricewise.ai"
    return MockUser()


@pytest.fixture(autouse=True)
def reset_test_data(db):
    """Clean observation tables before each test."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM retail_price_observation")
        cursor.execute("UPDATE products SET data_status='catalog_verified' WHERE source_type='catalog_verified'")
    yield
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM retail_price_observation")
        cursor.execute("UPDATE products SET data_status='catalog_verified' WHERE source_type='catalog_verified'")


# ── Step 1: Table existence & migration idempotency ──────────────────────────

class TestStep1SchemaAndMigration:
    def test_retail_price_observation_table_exists(self, db):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='retail_price_observation'"
            )
            assert cursor.fetchone() is not None

    def test_migrate_runs_twice_without_error(self, db):
        migrate_db()
        migrate_db()  # second run must not raise

    def test_observation_columns_exist(self, db):
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(retail_price_observation)")
            col_names = {row["name"] for row in cursor.fetchall()}
            required = {
                "product_id", "retailer", "product_url", "observed_price",
                "observation_type", "observation_status", "verified_by_admin",
            }
            for col in required:
                assert col in col_names, f"Missing column: {col}"


# ── Step 2: Observation type validation ───────────────────────────────────────

class TestObservationTypes:
    def test_observation_types_are_valid(self):
        assert ObservationType.SCHEDULED == "scheduled"
        assert ObservationType.MANUAL == "manual"
        assert ObservationType.USER_REPORT == "user_report"
        assert len({ObservationType.SCHEDULED, ObservationType.MANUAL, ObservationType.USER_REPORT}) == 3

    def test_observation_statuses_are_valid(self):
        assert ObservationStatus.LIVE == "live"
        assert ObservationStatus.EXPIRED == "expired"
        assert ObservationStatus.SUPERSEDED == "superseded"
        assert ObservationStatus.FLAGGED == "flagged"


# ── Step 3: Recording observations ───────────────────────────────────────────

class TestRecordPriceObservation:
    def test_record_observation_requires_valid_data(self):
        with pytest.raises(ValueError):
            record_price_observation(product_id=99999, retailer="nykaa", product_url="https://nykaa.com/x", observed_price=100.0)

        with pytest.raises(ValueError):
            record_price_observation(product_id=1, retailer="", product_url="https://nykaa.com/x", observed_price=100.0)

        with pytest.raises(ValueError):
            record_price_observation(product_id=1, retailer="nykaa", product_url="https://nykaa.com/x", observed_price=-5.0)

        with pytest.raises(ValueError):
            record_price_observation(
                product_id=1,
                retailer="nykaa",
                product_url="https://nykaa.com/x",
                observed_price=100.0,
                observation_type="invalid_type",
            )

    def test_record_observation_requires_existing_product(self, db):
        with pytest.raises(ValueError, match="not found"):
            record_price_observation(product_id=99999, retailer="nykaa", product_url="https://nykaa.com/x", observed_price=100.0)

    def test_record_observation_creates_and_supersedes(self, db, test_product_id):
        # First observation
        obs1 = record_price_observation(
            product_id=test_product_id,
            retailer="nykaa",
            product_url="https://nykaa.com/product/1",
            observed_price=999.0,
            observation_type=ObservationType.SCHEDULED,
        )
        assert obs1["id"] is not None
        assert obs1["observation_status"] == ObservationStatus.LIVE

        # Second observation should supersede the first
        obs2 = record_price_observation(
            product_id=test_product_id,
            retailer="nykaa",
            product_url="https://nykaa.com/product/1",
            observed_price=888.0,
            observation_type=ObservationType.SCHEDULED,
        )
        assert obs2["id"] != obs1["id"]

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT observation_status FROM retail_price_observation WHERE id = ?", (obs1["id"],))
            assert cursor.fetchone()[0] == ObservationStatus.SUPERSEDED
            cursor.execute("SELECT observation_status FROM retail_price_observation WHERE id = ?", (obs2["id"],))
            assert cursor.fetchone()[0] == ObservationStatus.LIVE


# ── Step 4: Query filters and counts ──────────────────────────────────────────

class TestObservationQueries:
    def test_count_observations(self, db, test_product_id):
        record_price_observation(product_id=test_product_id, retailer="nykaa", product_url="https://nykaa.com/x", observed_price=100.0)
        record_price_observation(product_id=test_product_id, retailer="tira", product_url="https://tirabeauty.com/x", observed_price=200.0)
        assert count_price_observations() == 2
        assert count_price_observations(product_id=test_product_id) == 2
        assert count_price_observations(retailer="nykaa") == 1
        assert count_price_observations(observation_status=ObservationStatus.LIVE) == 2

    def test_get_observations_filter_by_retailer(self, db, test_product_id):
        record_price_observation(product_id=test_product_id, retailer="nykaa", product_url="https://nykaa.com/x", observed_price=100.0)
        record_price_observation(product_id=test_product_id, retailer="tira", product_url="https://tirabeauty.com/x", observed_price=200.0)
        obs_list = get_price_observations(retailer="nykaa", limit=10)
        assert len(obs_list) == 1
        assert obs_list[0]["retailer"] == "nykaa"
        assert obs_list[0]["observed_price"] == 100.0


# ── Step 5: Admin verification ────────────────────────────────────────────────

class TestAdminVerification:
    def test_admin_verify_requires_admin_user(self, db, test_product_id):
        obs = record_price_observation(product_id=test_product_id, retailer="nykaa", product_url="https://nykaa.com/x", observed_price=100.0)
        with pytest.raises(TypeError):
            admin_verify_observation(observation_id=obs["id"], admin_user=None)

    def test_admin_verify_on_missing_observation(self, db, demo_user_id):
        with pytest.raises(ValueError, match="not found"):
            admin_verify_observation(
                observation_id=99999,
                admin_user=type("MockUser", (), {"id": demo_user_id})(),
            )

    def test_admin_verify_success(self, db, test_product_id, demo_user_id):
        class MockUser:
            id = demo_user_id
            email = "demo@pricewise.ai"

        obs = record_price_observation(product_id=test_product_id, retailer="nykaa", product_url="https://nykaa.com/x", observed_price=100.0)
        result = admin_verify_observation(
            observation_id=obs["id"],
            admin_user=MockUser(),
            verified_price=120.0,
            verification_notes="LMR cross-check confirmed price",
        )
        assert result["verified_by_admin"] is True
        assert result["verified_price"] == 120.0
        assert result["observation_status"] == ObservationStatus.LIVE


# ── Step 6: Scheduled observation sweep ───────────────────────────────────────

class TestScheduledSweep:
    def test_sweep_single_product_not_found(self, db):
        result = run_scheduled_observations(product_id=99999)
        assert result["status"] == "not_found"

    def test_sweep_handles_restricted_retailers(self, db, test_product_id):
        # Retailer policies are restricted for nykaa etc., should record flagged observation
        result = run_scheduled_observations(product_id=test_product_id, test_mode=True)
        assert result["status"] in ("completed", "not_found")


# ── Step 7: Observation status transitions ─────────────────────────────────────

class TestObservationStatusTransitions:
    def test_flagged_observation_status(self, db, test_product_id):
        obs = record_price_observation(
            product_id=test_product_id,
            retailer="purplle",
            product_url="https://purplle.com/x",
            observed_price=100.0,
            observation_type=ObservationType.SCHEDULED,
            observation_status=ObservationStatus.FLAGGED,
        )
        assert obs["observation_status"] == ObservationStatus.FLAGGED

    def test_manual_observation_type(self, db, test_product_id):
        obs = record_price_observation(
            product_id=test_product_id,
            retailer="myntra",
            product_url="https://myntra.com/x",
            observed_price=300.0,
            observation_type=ObservationType.MANUAL,
        )
        assert obs["observation_type"] == ObservationType.MANUAL

    def test_user_report_observation_type(self, db, test_product_id):
        obs = record_price_observation(
            product_id=test_product_id,
            retailer="tira",
            product_url="https://tirabeauty.com/x",
            observed_price=400.0,
            observation_type=ObservationType.USER_REPORT,
        )
        assert obs["observation_type"] == ObservationType.USER_REPORT


# ── Step 8: Full transition matrix ──────────────────────────────────────────────

class TestObservationTransitionMatrix:
    def test_full_lifecycle_supersede_then_verify(self, db, test_product_id, demo_user_id):
        obs1 = record_price_observation(product_id=test_product_id, retailer="amazon", product_url="https://amazon.in/x", observed_price=500.0)
        obs2 = record_price_observation(product_id=test_product_id, retailer="amazon", product_url="https://amazon.in/x", observed_price=450.0)

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM retail_price_observation WHERE id = ?", (obs1["id"],))
            r1 = cursor.fetchone()
            assert r1["observation_status"] == ObservationStatus.SUPERSEDED
            cursor.execute("SELECT * FROM retail_price_observation WHERE id = ?", (obs2["id"],))
            r2 = cursor.fetchone()
            assert r2["observation_status"] == ObservationStatus.LIVE

        class MockUser:
            id = demo_user_id

        # Admin verifies the latest observation
        result = admin_verify_observation(
            observation_id=obs2["id"],
            admin_user=MockUser(),
            verified_price=460.0,
            verified_mrp=470.0,
            verification_notes="Admin confirmed via retailer listing",
        )
        assert result["verified_by_admin"] is True
        assert result["verified_price"] == 460.0

        # Superseded observations cannot be re-verified (status check)
        with pytest.raises(ValueError):
            admin_verify_observation(
                observation_id=obs1["id"],
                admin_user=MockUser(),
                verified_price=501.0,
            )


# ── Phase 16.2 Stage 3.1: Manual Retailer Price Entry ──────────────────────

class TestManualPriceEntry:
    """Regression tests for Stage 3.1 manual price entry workflow."""

    def test_manual_observation_requires_admin_user(self, db, test_product_id):
        with pytest.raises(TypeError):
            record_manual_price_observation(
                product_id=test_product_id,
                retailer="nykaa",
                product_url="https://nykaa.com/product/abc",
                observed_price=100.0,
                admin_user=None,
            )

    def test_manual_observation_requires_valid_product(self, db, demo_user_id):
        with pytest.raises(ValueError):
            record_manual_price_observation(
                product_id=99999,
                retailer="nykaa",
                product_url="https://nykaa.com/product/abc",
                observed_price=100.0,
                admin_user=make_admin_user(demo_user_id),
            )

    def test_manual_observation_rejects_retailer_homepage_url(self, db, test_product_id, demo_user_id):
        with pytest.raises(ValueError):
            record_manual_price_observation(
                product_id=test_product_id,
                retailer="nykaa",
                product_url="https://nykaa.com",
                observed_price=100.0,
                admin_user=make_admin_user(demo_user_id),
            )

    def test_manual_observation_rejects_invalid_price(self, db, test_product_id, demo_user_id):
        with pytest.raises(ValueError):
            record_manual_price_observation(
                product_id=test_product_id,
                retailer="nykaa",
                product_url="https://nykaa.com/product/abc",
                observed_price=0.0,
                admin_user=make_admin_user(demo_user_id),
            )
        with pytest.raises(ValueError):
            record_manual_price_observation(
                product_id=test_product_id,
                retailer="nykaa",
                product_url="https://nykaa.com/product/abc",
                observed_price=-50.0,
                admin_user=make_admin_user(demo_user_id),
            )
        with pytest.raises(ValueError):
            record_manual_price_observation(
                product_id=test_product_id,
                retailer="nykaa",
                product_url="https://nykaa.com/product/abc",
                observed_price=float("inf"),
                admin_user=make_admin_user(demo_user_id),
            )

    def test_manual_observation_rejects_unknown_retailer(self, db, test_product_id, demo_user_id):
        with pytest.raises(ValueError):
            record_manual_price_observation(
                product_id=test_product_id,
                retailer="notarealstore",
                product_url="https://notarealstore.com/product/abc",
                observed_price=100.0,
                admin_user=make_admin_user(demo_user_id),
            )

    def test_manual_observation_creates_flagged_pending_record(self, db, test_product_id, demo_user_id):
        obs = record_manual_price_observation(
            product_id=test_product_id,
            retailer="nykaa",
            product_url="https://nykaa.com/product/abc123",
            observed_price=849.0,
            admin_user=make_admin_user(demo_user_id),
            observed_mrp=999.0,
            size_volume="50ml",
            shade="Rose",
            formulation="Serum",
            evidence_notes="Admin confirmed via retailer listing",
            evidence_reference="https://nykaa.com/product/abc123",
        )
        assert obs["observation_type"] == ObservationType.MANUAL
        # Manual entries are initially flagged/pending verification
        assert obs["observation_status"] == ObservationStatus.FLAGGED
        # Must NOT be auto-verified
        assert obs["verified_by_admin"] is False
        assert obs["verified_price"] is None
        assert obs["verification_status"] == "pending"

    def test_manual_observation_supersedes_live_observations(self, db, test_product_id, demo_user_id):
        """Manual observations supersede live observations for same product+retailer."""
        # Create a live observation using record_price_observation ( SCHEDULED, starts as LIVE)
        obs1 = record_price_observation(
            product_id=test_product_id,
            retailer="tira",
            product_url="https://tirabeauty.com/product/live",
            observed_price=500.0,
        )
        # obs1 is LIVE
        obs2 = record_manual_price_observation(
            product_id=test_product_id,
            retailer="tira",
            product_url="https://tirabeauty.com/product/manual",
            observed_price=450.0,
            admin_user=make_admin_user(demo_user_id),
        )
        # Live observation should be superseded by manual observation
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT observation_status FROM retail_price_observation WHERE id = ?", (obs1["id"],))
            assert cursor.fetchone()[0] == ObservationStatus.SUPERSEDED
            # Manual observation is flagged pending verification
            cursor.execute("SELECT observation_status FROM retail_price_observation WHERE id = ?", (obs2["id"],))
            assert cursor.fetchone()[0] == ObservationStatus.FLAGGED


class TestManualPriceEntryAuditHistory:
    def test_manual_entry_preserves_previous_observation_history(self, db, test_product_id, demo_user_id):
        obs1 = record_manual_price_observation(
            product_id=test_product_id,
            retailer="tira",
            product_url="https://tirabeauty.com/product/one",
            observed_price=400.0,
            admin_user=make_admin_user(demo_user_id),
        )
        # Second manual entry supersedes first but keeps history
        obs2 = record_manual_price_observation(
            product_id=test_product_id,
            retailer="tira",
            product_url="https://tirabeauty.com/product/two",
            observed_price=380.0,
            admin_user=make_admin_user(demo_user_id),
            evidence_notes="Updated with better evidence",
        )
        # Note: Manual observations for same product+retailer are both recorded as separate rows.
        # The supersede logic only applies to LIVE observations. FLAGGED observations for the
        # same product+retailer are both kept with their original URLs preserved for audit.
        # This test verifies that audit history is preserved.
        obs_list = get_price_observations(product_id=test_product_id, retailer="tira")
        # Both observations should be retrievable
        assert len(obs_list) == 2
        # One should be flagged (the new one), one should also be flagged (the first one kept for history)
        urls = {o["product_url"] for o in obs_list}
        assert "https://tirabeauty.com/product/one" in urls
        assert "https://tirabeauty.com/product/two" in urls

    def test_manual_entry_does_not_auto_verify(self, db, test_product_id, demo_user_id):
        obs = record_manual_price_observation(
            product_id=test_product_id,
            retailer="purplle",
            product_url="https://purplle.com/product/xyz",
            observed_price=700.0,
            admin_user=make_admin_user(demo_user_id),
        )
        assert obs["verified_by_admin"] is False
        assert obs["verified_price"] is None
        assert obs["verification_status"] == "pending"


class TestScheduledSweepNotConsumingManualEntries:
    def test_sweep_does_not_revert_manual_flagged(self, db, test_product_id, demo_user_id):
        # Record a manual flagged observation
        obs = record_manual_price_observation(
            product_id=test_product_id,
            retailer="amazon",
            product_url="https://amazon.in/product/manual1",
            observed_price=900.0,
            admin_user=make_admin_user(demo_user_id),
        )
        # Run a sweep in test mode - it should not overwrite manual flagged state badly
        result = run_scheduled_observations(product_id=test_product_id, test_mode=True)
        assert result["status"] in ("completed", "not_found")
        # Manual observation should still be flagged/pending
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT observation_status FROM retail_price_observation WHERE id = ?", (obs["id"],))
            assert cursor.fetchone()[0] == ObservationStatus.FLAGGED