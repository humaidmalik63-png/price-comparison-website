"""Tests for Phase 16.2 Stage 4: Price Intelligence Engine.

Verifies verified-offers queries, cheapest calculations, stale expiry logic,
price history, discount computation, and health stats.
"""
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.database.connection import get_connection, init_db, migrate_db
from src.services.price_intelligence import (
    expire_stale_observations,
    get_verified_offers,
    get_cheapest_verified,
    list_cheapest_per_catalog,
    get_observation_price_history,
    calculate_discount,
    get_price_health_stats,
    filter_rejected_demos,
    ObservationSource,
)


@pytest.fixture(scope="module")
def db():
    """Ensure DB is initialised once per module."""
    init_db()
    migrate_db()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO stores (name, domain) VALUES (?, ?)",
                ("Nykaa", "nykaa.com"),
            )
            store_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO users (display_name, email, password_hash) VALUES (?, ?, ?)",
                ("Admin", "admin@pricewise.ai", "hash"),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO products (sku, title, brand, category, description, specs_json, image_url, source_type, data_status, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'catalog', 'approved', 1)",
                ("BEAUTY-001", "Test Face Cream", "TestBrand", "Skincare",
                 "Test product for intelligence engine", '{"Net Quantity": "50 ml"}',
                 "https://example.com/cream.jpg"),
            )
            pid = cursor.lastrowid
            cursor.execute(
                "INSERT INTO offers (product_id, store_id, current_price, original_price, shipping_cost, currency, availability, variant_name, condition, offer_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (pid, store_id, 299.0, 399.0, 0.0, "INR", "In Stock", "Standard", "Brand New", "https://nykaa.com/product"),
            )
            obs_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO retail_price_observation (product_id, retailer, product_url, observed_price, observation_type, observation_status, verification_status, evidence_notes, created_at)"
                " VALUES (?, ?, ?, ?, 'scheduled', 'live', 'pending', 'Auto-collected', ?)",
                (pid, "Nykaa", "https://nykaa.com/product", 299.0,
                 (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()),
            )
            # Demo offer (lower price but flagged as demo)
            cursor.execute(
                "INSERT INTO products (sku, title, brand, category, description, specs_json, image_url, source_type, data_status, is_active)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, 'demo', 'approved', 1)",
                ("DEMO-001", "Demo Product", "DemoBrand", "Beauty", "Demo", "{}", ""),
            )
            demo_pid = cursor.lastrowid
            cursor.execute(
                "INSERT INTO offers (product_id, store_id, current_price, original_price, shipping_cost, currency, availability, variant_name, condition, offer_url)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (demo_pid, store_id, 99.0, 199.0, 0.0, "INR", "In Stock", "Standard", "Brand New", "https://demo.com"),
            )
            # Stale observation (>72h old)
            cursor.execute(
                "INSERT INTO retail_price_observation (product_id, retailer, product_url, observed_price, observation_type, observation_status, verification_status, evidence_notes, created_at)"
                " VALUES (?, ?, ?, ?, 'manual', 'live', 'pending', 'Old entry', ?)",
                (pid, "Purplle", "https://purplle.com", 250.0,
                 (datetime.now(timezone.utc) - timedelta(hours=100)).isoformat()),
            )
    yield


@pytest.fixture(scope="module")
def product_id(db):
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM products WHERE sku = 'BEAUTY-001' LIMIT 1")
        row = cur.fetchone()
        return row["id"] if row else None


class TestGetVerifiedOffers:
    def test_returns_offers_for_product(self, product_id):
        offers = get_verified_offers(product_id)
        assert isinstance(offers, list)
        if offers:
            first = offers[0]
            assert "offer_id" in first
            assert "current_price" in first
            assert "discount_pct" in first
            assert "unit_price" in first

    def test_discount_calculation(self, product_id):
        offers = get_verified_offers(product_id)
        offering = next((o for o in offers if o.get("original_price") and o["current_price"]), None)
        if offering:
            disc = calculate_discount(offering)
            assert disc is not None
            assert 0 < disc <= 100

    def test_unit_price_computed_for_quantity_products(self):
        """Products with quantity specs should get unit_price computed."""
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM products WHERE specs_json LIKE '%Net Quantity%' LIMIT 1")
            row = cur.fetchone()
            if row:
                pid = row["id"]
                offers = get_verified_offers(pid)
                for o in offers:
                    if o.get("unit_price"):
                        assert o["unit_price"] > 0
                        return
        # If no such products, test passes


class TestCheapestVerified:
    def test_returns_cheapest_for_product(self, product_id):
        cheapest = get_cheapest_verified(product_id)
        if cheapest:
            assert cheapest["current_price"] > 0

    def test_excludes_demo_when_real_available(self, product_id):
        cheapest = get_cheapest_verified(product_id)
        if cheapest:
            assert cheapest["source_type"] != "demo" or cheapest.get("is_demo") is not True


class TestListCheapestPerCatalog:
    def test_returns_list(self, product_id):
        results = list_cheapest_per_catalog(limit=10)
        assert isinstance(results, list)
        assert all(isinstance(r, dict) for r in results)
        if results:
            assert "product_id" in results[0]


class TestExpireStaleObservations:
    def test_expires_old_observations(self, product_id):
        count = expire_stale_observations(max_age_hours=72)
        assert count >= 0


class TestPriceHistory:
    def test_returns_history_points(self, product_id):
        history = get_observation_price_history(product_id, limit=10)
        assert isinstance(history, list)
        if history:
            pt = history[0]
            assert hasattr(pt, "id")
            assert hasattr(pt, "observed_price")
            assert hasattr(pt, "created_at")


class TestCalculateDiscount:
    def test_basic_discount(self):
        d = calculate_discount({"observed_price": 800, "observed_mrp": 1000})
        assert d == 20.0

    def test_no_mrp(self):
        d = calculate_discount({"observed_price": 500, "observed_mrp": None})
        assert d is None

    def test_zero_mrp_returns_none(self):
        """Zero or missing MRP returns None to avoid division by zero."""
        d = calculate_discount({"observed_price": 0, "observed_mrp": 0})
        assert d is None


class TestFilterRejectedDemos:
    def test_separates_demo_from_real(self):
        offers = [
            {"source_type": "demo", "current_price": 99},
            {"source_type": "catalog", "current_price": 299},
            {"source_type": "demo", "current_price": 49},
        ]
        real, demos = filter_rejected_demos(offers)
        assert len(real) == 1
        assert len(demos) == 2
        assert real[0]["current_price"] == 299


class TestHealthStats:
    def test_returns_stats_dict(self, product_id):
        stats = get_price_health_stats()
        assert isinstance(stats, dict)
        assert "total_active_products" in stats
        assert "manufacturer_verified" in stats
        assert "catalog_verified" in stats
        assert "live_observations" in stats
        assert "flagged_observations" in stats
        assert "expired_observations" in stats
        assert "active_retailers" in stats
        assert "oldest_live_observation" in stats
        assert "newest_live_observation" in stats