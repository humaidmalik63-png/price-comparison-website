"""Phase 6A Foundation Tests: FastAPI Bridge, Gemini Service, Browser Manager & Security Policy.

Verifies:
1. FastAPI endpoints (/api/health, /api/products, /api/products/{slug}).
2. GeminiService entity parsing, offline heuristic fallback, and no-price-prediction guarantee.
3. Security navigation policy (HTTPS-only, retailer allowlist, SSRF/private IP blocking).
4. BrowserManager headless Chromium lifecycle, resource blocking, and safe navigation.
5. SQLite database preservation and record integrity.
"""

import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
from starlette.testclient import TestClient

from src.api.main import app
from src.services.gemini_service import GeminiService, GeminiSKUExtractionResult
from src.workers.security_policy import validate_browser_url, ALLOWED_RETAILER_DOMAINS
from src.workers.browser_manager import BrowserManager, BrowserSecurityError
from src.database.connection import get_connection
from src.database.seed import (
    DEMO_BEAUTY_PRODUCTS,
    DEMO_BEAUTY_STORES,
    DEMO_OBF_PRODUCTS,
    DEMO_PRODUCTS,
    DEMO_STORES,
)


class TestFastApiBridge(unittest.TestCase):
    """Test suite for Phase 6A FastAPI Bridge."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)

    def test_health_endpoint(self):
        """Verify /api/health returns 200, valid status, and database record count."""
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["database"], "sqlite")
        self.assertGreater(data["record_count"], 0)
        self.assertIn("PriceWise", data["app_name"])

    def test_list_products_endpoint(self):
        """Verify /api/products returns products list."""
        response = self.client.get("/api/products")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertGreater(len(data), 0)

        first = data[0]
        self.assertIn("id", first)
        self.assertIn("title", first)
        self.assertIn("brand", first)
        self.assertIn("category", first)
        self.assertIn("lowest_price", first)

    def test_list_products_filtering(self):
        """Verify /api/products filtering by category and search keyword."""
        # Category filter
        res_cat = self.client.get("/api/products?category=sunscreen")
        self.assertEqual(res_cat.status_code, 200)
        cat_items = res_cat.json()
        self.assertGreater(len(cat_items), 0)
        for item in cat_items:
            self.assertIn("sunscreen", item["category"].lower())

        # Search filter
        res_search = self.client.get("/api/products?search=Dot")
        self.assertEqual(res_search.status_code, 200)
        search_items = res_search.json()
        self.assertGreater(len(search_items), 0)
        for item in search_items:
            self.assertTrue("dot" in item["title"].lower() or "dot" in item["brand"].lower())

    def test_get_product_by_slug_or_id(self):
        """Verify /api/products/{slug_or_id} returns detailed product with offers."""
        # Fetch by slug
        response = self.client.get("/api/products/watermelon-cooling-sunscreen-spf-50")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("watermelon", data["slug"])
        self.assertIn("offers", data)
        self.assertIsInstance(data["offers"], list)
        self.assertGreater(len(data["offers"]), 0)

        # Fetch by ID — resolve the id from the seeded database instead of
        # relying on a developer-local AUTOINCREMENT value.
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM products WHERE title LIKE '%Watermelon Cooling Sunscreen%'"
            ).fetchone()
        self.assertIsNotNone(row)
        product_id = row["id"]

        res_id = self.client.get(f"/api/products/{product_id}")
        self.assertEqual(res_id.status_code, 200)
        self.assertEqual(res_id.json()["id"], product_id)

    def test_get_product_not_found(self):
        """Verify 404 is returned for non-existent product slug."""
        response = self.client.get("/api/products/non-existent-product-99999")
        self.assertEqual(response.status_code, 404)


class TestGeminiServiceFoundation(unittest.TestCase):
    """Test suite for Phase 6A Gemini Service."""

    def test_unconfigured_initialization(self):
        """Verify service behaves safely when GEMINI_API_KEY is not set."""
        with patch.dict(os.environ, {}, clear=True):
            service = GeminiService()
            self.assertFalse(service.is_configured)
            
            # Heuristic fallback parsing works cleanly offline
            parsed = service.parse_sku_entities("Dot & Key Watermelon Cooling Sunscreen Gel SPF 50+ PA++++ 50g")
            self.assertIsInstance(parsed, GeminiSKUExtractionResult)
            self.assertIn("50", parsed.size_volume or "")
            self.assertEqual(parsed.formulation, "Gel")
            self.assertEqual(parsed.extraction_source, "heuristic_fallback")

    def test_no_price_prediction_guarantee(self):
        """Verify that GeminiService has NO price prediction capabilities."""
        service = GeminiService()
        self.assertFalse(hasattr(service, "predict_price"))
        self.assertFalse(hasattr(service, "estimate_price"))
        self.assertFalse(hasattr(service, "generate_deal"))

    def test_mocked_gemini_api_parsing(self):
        """Verify parsing when Gemini API is configured and responds."""
        with patch.dict(os.environ, {"GEMINI_API_KEY": "test_key_12345"}):
            mock_client = MagicMock()
            mock_response = MagicMock()
            mock_response.text = '{"brand": "Plum", "product_name": "Green Tea Renewed Clarity Night Gel", "size_volume": "50ml", "shade": null, "formulation": "Night Gel"}'
            mock_client.models.generate_content.return_value = mock_response

            service = GeminiService()
            service._client = mock_client
            self.assertTrue(service.is_configured)

            parsed = service.parse_sku_entities("Plum Green Tea Renewed Clarity Night Gel 50ml")
            self.assertEqual(parsed.brand, "Plum")
            self.assertEqual(parsed.size_volume, "50ml")
            self.assertEqual(parsed.formulation, "Night Gel")
            self.assertEqual(parsed.extraction_source, "gemini_model")


class TestBrowserSecurityPolicy(unittest.TestCase):
    """Test suite for browser URL validation and SSRF prevention."""

    def test_allowed_retailers(self):
        """Verify valid HTTPS URLs for allowed retailers are accepted."""
        valid_urls = [
            "https://www.nykaa.com/dot-key-watermelon-sunscreen/p/123",
            "https://tirabeauty.com/product/plum-night-gel",
            "https://www.purplle.com/product/minimalist-niacinamide",
            "https://www.amazon.in/dp/B08XYZ123",
            "https://www.myntra.com/skin-care/minimalist/serum/12345",
        ]
        for url in valid_urls:
            is_valid, reason = validate_browser_url(url)
            self.assertTrue(is_valid, f"Expected {url} to be valid, got: {reason}")
            self.assertIsNone(reason)

    def test_reject_insecure_scheme(self):
        """Verify non-HTTPS schemes are rejected."""
        invalids = [
            "http://www.nykaa.com/product",
            "ftp://tirabeauty.com",
            "file:///C:/Users/tannu/pricewise.db",
            "javascript:alert(1)",
        ]
        for url in invalids:
            is_valid, reason = validate_browser_url(url)
            self.assertFalse(is_valid)
            self.assertIn("Only HTTPS is permitted", reason or "")

    def test_reject_unapproved_domains(self):
        """Verify unapproved domains are rejected."""
        unapproved = [
            "https://google.com",
            "https://evil-hacker.com/nykaa",
            "https://fakestore.in",
            "https://facebook.com",
        ]
        for url in unapproved:
            is_valid, reason = validate_browser_url(url)
            self.assertFalse(is_valid)
            self.assertIn("not in the approved retailer allowlist", reason or "")

    def test_reject_localhost_and_internal_ips(self):
        """Verify localhost, private IPs, and cloud metadata are blocked."""
        blocked = [
            "http://localhost:8000",
            "http://127.0.0.1:8501",
            "https://127.0.0.1",
            "http://169.254.169.254/latest/meta-data/",
            "https://169.254.169.254",
            "https://10.0.0.1",
            "https://192.168.1.1",
        ]
        for url in blocked:
            is_valid, reason = validate_browser_url(url)
            self.assertFalse(is_valid)


class TestBrowserManagerLifecycle(unittest.TestCase):
    """Test suite for Playwright browser manager."""

    def test_browser_lifecycle_and_test_navigation(self):
        """Verify browser starts, navigates safely to about:blank, and terminates cleanly."""
        bm = BrowserManager(headless=True, timeout_ms=8000)
        self.assertFalse(bm.is_running)

        with bm:
            self.assertTrue(bm.is_running)
            with bm.page_session(allow_test_urls=True) as page:
                success = bm.safe_navigate(page, "about:blank", allow_test_urls=True)
                self.assertTrue(success)
                self.assertEqual(page.title(), "")

        self.assertFalse(bm.is_running)

    def test_safe_navigate_blocks_disallowed_urls(self):
        """Verify safe_navigate raises BrowserSecurityError on forbidden destinations."""
        with BrowserManager(headless=True, timeout_ms=5000) as bm:
            with bm.page_session() as page:
                with self.assertRaises(BrowserSecurityError):
                    bm.safe_navigate(page, "http://127.0.0.1:8000")

                with self.assertRaises(BrowserSecurityError):
                    bm.safe_navigate(page, "https://unauthorized-domain.com")


class TestDatabaseIntegrity(unittest.TestCase):
    """Verify SQLite database integrity and record preservation."""

    def test_database_counts(self):
        """Ensure all tables exist and counts match a fresh deterministic seed."""
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}

            expected_tables = {
                "products", "stores", "offers", "price_history",
                "price_alerts", "users", "wishlist", "user_preferences", "price_tracking"
            }
            self.assertTrue(expected_tables.issubset(tables))

            expected_products = (
                len(DEMO_PRODUCTS) + len(DEMO_BEAUTY_PRODUCTS) + len(DEMO_OBF_PRODUCTS)
            )
            expected_stores = len(DEMO_STORES) + len(DEMO_BEAUTY_STORES)

            cur.execute("SELECT count(*) FROM products")
            self.assertEqual(cur.fetchone()[0], expected_products)

            cur.execute("SELECT count(*) FROM stores")
            self.assertEqual(cur.fetchone()[0], expected_stores)

            cur.execute("SELECT count(*) FROM offers")
            self.assertGreater(cur.fetchone()[0], 0)

            cur.execute("SELECT count(*) FROM price_history")
            self.assertGreater(cur.fetchone()[0], 0)

    def test_database_backup_is_valid(self):
        """Verify a genuine SQLite backup of the isolated DB is self-contained.

        The previous test asserted that a developer-local artifact
        (``data/pricewise.db.backup_phase6a``) existed, which is not part of the
        repository or the application. Instead, exercise SQLite's backup API and
        verify the resulting file is a valid, populated database.
        """
        source = Path(os.environ["PRICEWISE_DB_PATH"])
        self.assertTrue(source.exists(), "isolated test database must exist")

        with tempfile.TemporaryDirectory() as tmp_dir:
            backup_path = Path(tmp_dir) / "pricewise.db.backup"
            src_conn = sqlite3.connect(str(source))
            dst_conn = sqlite3.connect(str(backup_path))
            try:
                src_conn.backup(dst_conn)
            finally:
                dst_conn.close()
                src_conn.close()

            self.assertTrue(backup_path.exists())
            self.assertGreater(backup_path.stat().st_size, 0)

            check = sqlite3.connect(str(backup_path))
            try:
                count = check.execute("SELECT COUNT(*) FROM products").fetchone()[0]
                integrity = check.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                check.close()
            self.assertGreater(count, 0)
            self.assertEqual(integrity, "ok")


if __name__ == "__main__":
    unittest.main()
