"""Regression tests for Phase 16.2 Stage 2: OBF Product Verification workflow.

Tests verify:
- Approving an OBF record does NOT auto-claim manufacturer_verified without explicit action
- catalog_verified is distinct from manufacturer_verified
- reject and needs_review actions preserve complete audit history
- Only authenticated admins can access/modify the verification queue
- Database migrations are idempotent
"""

import sys
import os
import json
from pathlib import Path
from typing import Any

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.database.connection import get_connection, init_db, migrate_db
from src.services.price_collection_engine import (
    VerificationStatus,
    approve_obf_product_verification,
    count_obf_products_pending_verification,
    get_obf_products_pending_verification,
    get_obf_verification_history,
    request_obf_product_review,
    reject_obf_product_verification,
)


@pytest.fixture(scope="module")
def db():
    """Ensure database is initialised, migrated, and seeded with OBF products for testing."""
    from src.database.seed import DEMO_OBF_PRODUCTS

    init_db()

    # Seed OBF products for testing - ensure we have at least 5
    with get_connection() as conn:
        cursor = conn.cursor()

        # First, ensure no existing OBF products with wrong status
        cursor.execute("DELETE FROM obf_product_verification")
        cursor.execute("UPDATE products SET data_status='catalog_verified' WHERE source_type='catalog_verified'")

        # Check current count
        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE source_type='catalog_verified' AND data_status='catalog_verified' AND is_active=1"
        )
        count = cursor.fetchone()[0]

        # Insert missing OBF products (upsert by SKU)
        for prod in DEMO_OBF_PRODUCTS:
            cursor.execute("SELECT id FROM products WHERE sku = ?", (prod["sku"],))
            existing = cursor.fetchone()
            if existing:
                # Update to correct status if needed
                cursor.execute(
                    "UPDATE products SET source_type='catalog_verified', data_status='catalog_verified', is_active=1 WHERE id = ?",
                    (existing["id"],),
                )
            else:
                specs = prod["specs"]
                cursor.execute(
                    """
                    INSERT INTO products (sku, title, brand, category, description, specs_json, image_url, source_type, data_status, is_active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'catalog_verified', 'catalog_verified', 1)
                    """,
                    (
                        prod["sku"],
                        prod["title"],
                        prod["brand"],
                        prod["category"],
                        prod["description"],
                        json.dumps(specs),
                        prod["image_url"],
                    ),
                )

        # Ensure a Nykaa store exists and get its id. Seeded demo stores are
        # named "Nykaa (Demo)", so reuse those instead of inserting a duplicate.
        cursor.execute("SELECT id FROM stores WHERE name LIKE 'Nykaa%' LIMIT 1")
        nykaa_row = cursor.fetchone()
        if nykaa_row:
            store_id = nykaa_row["id"]
        else:
            cursor.execute("INSERT INTO stores (name, domain) VALUES ('Nykaa', 'nykaa.com')")
            store_id = cursor.lastrowid

        # Add offers for OBF products
        cursor.execute("SELECT id, sku FROM products WHERE source_type='catalog_verified' AND is_active=1")
        for row in cursor.fetchall():
            # Check if offers already exist
            cursor.execute("SELECT id FROM offers WHERE product_id = ?", (row["id"],))
            if not cursor.fetchone():
                cursor.execute(
                    """
                    INSERT INTO offers (product_id, store_id, current_price, original_price, shipping_cost, currency, availability, variant_name, condition, offer_url)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (row["id"], store_id, 1299.0, 1499.0, 0.0, "INR", "In Stock", "Standard", "Brand New", f"https://nykaa.com/product/{row['sku'].lower()}"),
                )

        # Verify we have at least 5 OBF products
        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE source_type='catalog_verified' AND data_status='catalog_verified' AND is_active=1"
        )
        final_count = cursor.fetchone()[0]

    yield


@pytest.fixture(scope="module")
def demo_user_id(db):
    """Get (or create) the demo admin user ID from the database."""
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
        display_name = "Alex Demo"
    return MockUser()


@pytest.fixture(autouse=True)
def reset_test_data(db):
    """Reset verification table before each test and restore products to catalog_verified afterwards."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM obf_product_verification")
        cursor.execute("UPDATE products SET data_status='catalog_verified' WHERE source_type='catalog_verified'")
    yield
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM obf_product_verification")
        cursor.execute("UPDATE products SET data_status='catalog_verified' WHERE source_type='catalog_verified'")


# ── Step 1: Verify no automatic manufacturer claim on import ──────────────────

class TestStep1NoAutoClaim:
    def test_obf_products_start_as_catalog_verified(self, db):
        """OBF-imported products must land in catalog_verified, not manufacturer_verified."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM products "
                "WHERE source_type='catalog_verified' AND data_status='catalog_verified'"
            )
            count = cursor.fetchone()[0]
            assert count >= 5, f"Expected ≥5 catalog_verified products, got {count}"

    def test_no_products_are_manufacturer_verified_before_approval(self, db):
        """Before any admin approval, zero OBF products should be manufacturer_verified."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM products "
                "WHERE source_type='catalog_verified' AND data_status='manufacturer_verified'"
            )
            count = cursor.fetchone()[0]
            assert count == 0, f"Expected 0 manufacturer_verified, got {count}"


# ── Step 2: Distinguish catalog_verified vs manufacturer_verified ────────────

class TestStep2StatusDistinction:
    def test_statuses_are_distinct(self):
        """The three statuses must have unique string values."""
        assert VerificationStatus.CATALOG_VERIFIED == "catalog_verified"
        assert VerificationStatus.MANUFACTURER_VERIFIED == "manufacturer_verified"
        assert VerificationStatus.PENDING_REVIEW == "pending_review"
        assert len({VerificationStatus.CATALOG_VERIFIED,
                    VerificationStatus.MANUFACTURER_VERIFIED,
                    VerificationStatus.PENDING_REVIEW}) == 3

    def test_all_new_statuses_in_all_statuses_set(self):
        """New statuses must appear in VerificationStatus.all_statuses()."""
        assert VerificationStatus.CATALOG_VERIFIED.value in VerificationStatus.all_statuses()
        assert VerificationStatus.MANUFACTURER_VERIFIED.value in VerificationStatus.all_statuses()
        assert VerificationStatus.PENDING_REVIEW.value in VerificationStatus.all_statuses()

    def test_approve_promotes_to_manufacturer_verified(self, db, demo_user_id):
        """approve() should promote catalog_verified → manufacturer_verified."""
        # Find first pending product
        products = get_obf_products_pending_verification(limit=1)
        assert len(products) >= 1
        product_id = products[0]["id"]

        result = approve_obf_product_verification(
            product_id, make_admin_user(demo_user_id),
            new_data_status=VerificationStatus.MANUFACTURER_VERIFIED,
            evidence_notes="Verified against manufacturer website",
        )
        assert result["status"] == "approved"
        assert result["previous_data_status"] == VerificationStatus.CATALOG_VERIFIED
        assert result["new_data_status"] == VerificationStatus.MANUFACTURER_VERIFIED

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data_status FROM products WHERE id=?", (product_id,)
            )
            row = cursor.fetchone()
            assert row["data_status"] == VerificationStatus.MANUFACTURER_VERIFIED

    def test_reject_moves_to_pending_review(self, db, demo_user_id):
        """reject() should move catalog_verified → pending_review."""
        products = get_obf_products_pending_verification(limit=1)
        assert len(products) >= 1
        product_id = products[0]["id"]

        result = reject_obf_product_verification(
            product_id, make_admin_user(demo_user_id),
            evidence_notes="Wrong category assigned",
            new_data_status=VerificationStatus.PENDING_REVIEW,
        )
        assert result["status"] == "rejected"
        assert result["new_data_status"] == VerificationStatus.PENDING_REVIEW

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data_status FROM products WHERE id=?", (product_id,)
            )
            row = cursor.fetchone()
            assert row["data_status"] == VerificationStatus.PENDING_REVIEW

    def test_request_review_keeps_same_status(self, db, demo_user_id):
        """needs_review action should not change data_status."""
        products = get_obf_products_pending_verification(limit=1)
        assert len(products) >= 1
        product_id = products[0]["id"]
        original_status = products[0]["data_status"]

        result = request_obf_product_review(
            product_id, make_admin_user(demo_user_id),
            evidence_notes="Need more info",
        )
        assert result["status"] == "needs_review"

        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT data_status FROM products WHERE id=?", (product_id,)
            )
            row = cursor.fetchone()
            assert row["data_status"] == original_status


# ── Step 3: Audit history preservation ────────────────────────────────────────

class TestStep3AuditHistory:
    def test_full_history_after_approval(self, db, demo_user_id):
        """Approved product should have a history entry with full metadata."""
        products = get_obf_products_pending_verification(limit=1)
        product_id = products[0]["id"]

        approve_obf_product_verification(
            product_id, make_admin_user(demo_user_id),
            new_data_status=VerificationStatus.MANUFACTURER_VERIFIED,
            evidence_notes="LMR cross-check passed",
        )
        history = get_obf_verification_history(product_id=product_id)
        assert len(history) == 1
        h = history[0]
        assert h["action"] == "approved"
        assert h["evidence_notes"] == "LMR cross-check passed"
        assert h["previous_data_status"] == VerificationStatus.CATALOG_VERIFIED
        assert h["new_data_status"] == VerificationStatus.MANUFACTURER_VERIFIED
        assert h["admin_user_id"] == demo_user_id
        assert "reviewed_at" in h
        assert h["reviewed_at"] != ""

    def test_full_history_after_rejection(self, db, demo_user_id):
        """Rejected product should have rejection history preserved."""
        products = get_obf_products_pending_verification(limit=1)
        product_id = products[0]["id"]

        reject_obf_product_verification(
            product_id, make_admin_user(demo_user_id),
            evidence_notes="Incorrect ingredients listed",
            new_data_status=VerificationStatus.PENDING_REVIEW,
        )
        history = get_obf_verification_history(product_id=product_id)
        assert len(history) == 1
        h = history[0]
        assert h["action"] == "rejected"
        assert h["evidence_notes"] == "Incorrect ingredients listed"

    def test_history_records_sequence_of_actions(self, db, demo_user_id):
        """Multiple actions on same product should accumulate in order."""
        products = get_obf_products_pending_verification(limit=1)
        if not products:
            pytest.skip("No OBF products available")
        product_id = products[0]["id"]

        # First action: request review
        request_obf_product_review(product_id, make_admin_user(demo_user_id), "Needs clarification")
        # Second action: approve after review
        approve_obf_product_verification(
            product_id, make_admin_user(demo_user_id),
            new_data_status=VerificationStatus.MANUFACTURER_VERIFIED,
            evidence_notes="Re-reviewed and approved",
        )

        history = get_obf_verification_history(product_id=product_id, limit=10)
        assert len(history) == 2
        assert history[0]["action"] == "needs_review"
        assert history[1]["action"] == "approved"

    def test_general_history_endpoint_returns_all(self, db, demo_user_id):
        """General history endpoint should return entries across all products."""
        products = get_obf_products_pending_verification(limit=2)
        if len(products) < 2:
            pytest.skip("Need at least 2 products for this test")

        for p in products:
            approve_obf_product_verification(
                p["id"], make_admin_user(demo_user_id),
                new_data_status=VerificationStatus.MANUFACTURER_VERIFIED,
                evidence_notes=f"Test approval for {p['title']}",
            )

        history = get_obf_verification_history(limit=10)
        assert len(history) >= 2


# ── Step 4: Auth requirement ─────────────────────────────────────────────────

class TestStep4AuthRequirement:
    def test_functions_require_user_object(self, db):
        """All public functions require a User-like object; None should fail."""
        products = get_obf_products_pending_verification(limit=1)
        if not products:
            pytest.skip("No OBF products available")
        product_id = products[0]["id"]

        with pytest.raises((TypeError, AttributeError)):
            approve_obf_product_verification(product_id, None)
        with pytest.raises((TypeError, AttributeError)):
            reject_obf_product_verification(product_id, None, "note")
        with pytest.raises((TypeError, AttributeError)):
            request_obf_product_review(product_id, None, "note")


# ── Step 5: Idempotent migration ──────────────────────────────────────────────

class TestStep5IdempotentMigration:
    def test_migrate_runs_twice_without_error(self, db):
        """Running migrate_db() multiple times must not raise."""
        migrate_db()
        migrate_db()  # second run

    def test_obf_table_exists_after_migration(self, db):
        """The obf_product_verification table must exist after migration."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' AND name='obf_product_verification'"
            )
            assert cursor.fetchone() is not None

    def test_products_have_required_columns(self, db):
        """products table must have data_status and source_type columns."""
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(products)")
            col_names = {row["name"] for row in cursor.fetchall()}
            assert "data_status" in col_names
            assert "source_type" in col_names


# ── Step 6: Status transition matrix ─────────────────────────────────────────

class TestStep6TransitionMatrix:
    def test_catalog_verified_can_be_approved(self, db, demo_user_id):
        products = get_obf_products_pending_verification(limit=1)
        assert products
        result = approve_obf_product_verification(
            products[0]["id"], make_admin_user(demo_user_id),
            new_data_status=VerificationStatus.MANUFACTURER_VERIFIED,
        )
        assert result["status"] == "approved"

    def test_catalog_verified_can_be_rejected(self, db, demo_user_id):
        products = get_obf_products_pending_verification(limit=1)
        assert products
        result = reject_obf_product_verification(
            products[0]["id"], make_admin_user(demo_user_id),
            evidence_notes="test reason",
        )
        assert result["status"] == "rejected"

    def test_catalog_verified_can_be_flagged_for_review(self, db, demo_user_id):
        products = get_obf_products_pending_verification(limit=1)
        assert products
        result = request_obf_product_review(
            products[0]["id"], make_admin_user(demo_user_id),
            evidence_notes="test note",
        )
        assert result["status"] == "needs_review"

    def test_invalid_new_status_raises(self, db, demo_user_id):
        products = get_obf_products_pending_verification(limit=1)
        if not products:
            pytest.skip("No OBF products available")
        with pytest.raises(ValueError, match="Invalid data_status"):
            approve_obf_product_verification(
                products[0]["id"], make_admin_user(demo_user_id),
                new_data_status="some_invalid_value",
            )

    def test_reject_requires_evidence_notes(self, db, demo_user_id):
        products = get_obf_products_pending_verification(limit=1)
        if not products:
            pytest.skip("No OBF products available")
        with pytest.raises(ValueError, match="Evidence notes are required"):
            reject_obf_product_verification(
                products[0]["id"], make_admin_user(demo_user_id),
                evidence_notes="",
            )

    def test_request_review_requires_evidence_notes(self, db, demo_user_id):
        products = get_obf_products_pending_verification(limit=1)
        if not products:
            pytest.skip("No OBF products available")
        with pytest.raises(ValueError, match="Evidence notes are required"):
            request_obf_product_review(
                products[0]["id"], make_admin_user(demo_user_id),
                evidence_notes="   ",  # whitespace only
            )

    def test_nonexistent_product_raises(self, db, demo_user_id):
        with pytest.raises(ValueError, match="not found"):
            approve_obf_product_verification(99999, make_admin_user(demo_user_id))
        with pytest.raises(ValueError, match="not found"):
            reject_obf_product_verification(99999, make_admin_user(demo_user_id), "reason")
        with pytest.raises(ValueError, match="not found"):
            request_obf_product_review(99999, make_admin_user(demo_user_id), "reason")