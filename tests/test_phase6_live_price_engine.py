"""Comprehensive Test Suite for Phase 6: Automatic Live Retailer Price Comparison Engine.

Tests:
1. Gemini Product Identification & Query Generation.
2. Exact Variant Matching (30ml != 50ml, shade clashes, formulation mismatches).
3. Price Extraction across all 5 Indian Retailers (Nykaa, Myntra, Purplle, Tira, Amazon).
4. Bot Protection / CAPTCHA / Access Restriction Detection.
5. Lowest Listed Price vs Lowest Total Purchase Cost (Unknown Shipping Handling).
6. Request Deduplication & 10-Minute Caching.
7. Manual Retailer URL Checking & Security Validation.
8. Audit Logging in price_check_logs table.
9. FastAPI Bridge Endpoints (/api/compare/auto, /api/compare/url).
"""

import os
import unittest
from unittest.mock import patch
from starlette.testclient import TestClient

from src.api.main import app
from src.adapters.base_adapter import CapabilityStatus, ExtractedPriceResult
from src.adapters.nykaa_adapter import NykaaAdapter
from src.adapters.myntra_adapter import MyntraAdapter
from src.adapters.purplle_adapter import PurplleAdapter
from src.adapters.tira_adapter import TiraAdapter
from src.adapters.amazon_adapter import AmazonIndiaAdapter
from src.adapters.registry import get_adapter_registry
from src.services.gemini_service import get_gemini_service
from src.services.live_comparison_engine import (
    get_live_comparison_engine,
    LiveRetailerOfferItem,
    LiveComparisonEngine,
    LiveComparisonResult,
    LiveComparisonSummary,
)
from src.services.product_matching_service import evaluate_product_match, MatchClassification
from src.database.connection import get_connection


# =============================================================================
# Realistic Mock HTML Fixtures for 5 Indian Retailers
# =============================================================================

NYKAA_SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ (50g)",
    "image": "https://images-static.nykaa.com/media/catalog/product/dk_sun_50.jpg",
    "brand": {"@type": "Brand", "name": "Dot & Key"},
    "offers": {
      "@type": "Offer",
      "price": "465",
      "priceCurrency": "INR",
      "highPrice": "595",
      "availability": "https://schema.org/InStock"
    }
  }
  </script>
</head>
<body>
  <h1 class="product-title">Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ (50g)</h1>
  <div class="css-1d0jf8e">₹465</div>
  <div class="css-1jczs19">MRP: ₹595</div>
</body>
</html>
"""

MYNTRA_SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <script>
    window.__myx = {
      "pdpData": {
        "id": 123456,
        "name": "Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
        "brand": {"name": "Dot & Key"},
        "price": {
          "mrp": 595,
          "discounted": 489
        },
        "inStock": true
      }
    };
  </script>
</head>
<body>
  <h1 class="pdp-title">Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g</h1>
  <span class="pdp-price"><strong>₹489</strong></span>
  <span class="pdp-mrp">₹595</span>
</body>
</html>
"""

PURPLLE_SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <title>Dot & Key Sunscreen on Purplle</title>
</head>
<body>
  <h1 class="product-title">Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g</h1>
  <div class="product-detail-price">₹475</div>
  <div class="mrp-price">MRP: ₹595</div>
  <span class="stock-status">In Stock</span>
</body>
</html>
"""

TIRA_SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head>
  <script id="__NEXT_DATA__" type="application/json">
  {
    "props": {
      "pageProps": {
        "product": {
          "name": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
          "price": 495,
          "mrp": 595,
          "inStock": true
        }
      }
    }
  }
  </script>
</head>
<body>
  <h1 data-testid="product-title">Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g</h1>
  <div data-testid="product-price">₹495</div>
</body>
</html>
"""

AMAZON_SAMPLE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Amazon.in: Dot & Key Watermelon Sunscreen</title></head>
<body>
  <span id="productTitle">Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g</span>
  <span class="a-price a-text-price"><span class="a-offscreen">₹595.00</span></span>
  <span class="a-price"><span class="a-offscreen">₹470.00</span></span>
  <div id="availability"><span>In stock</span></div>
</body>
</html>
"""

AMAZON_CAPTCHA_HTML = """
<!DOCTYPE html>
<html>
<head><title>Robot Check</title></head>
<body>
  <h4>Enter the characters you see below</h4>
  <p>Sorry, we just need to make sure you're not a robot.</p>
  <form action="/errors/validateCaptcha">
    <input type="text" name="field-keywords">
  </form>
</body>
</html>
"""

CLOUDFLARE_CHALLENGE_HTML = """
<!DOCTYPE html>
<html>
<head><title>Just a moment...</title></head>
<body>
  <div class="cf-turnstile"></div>
  <p>Checking your browser before accessing the retailer...</p>
</body>
</html>
"""


class TestPhase6LivePriceEngine(unittest.TestCase):
    """Test suite covering the Phase 6 Live Price Engine."""

    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.engine = get_live_comparison_engine()
        cls.registry = get_adapter_registry()
        cls.gemini = get_gemini_service()

    @staticmethod
    def _sample_fixtures():
        return {
            "nykaa": NYKAA_SAMPLE_HTML,
            "myntra": MYNTRA_SAMPLE_HTML,
            "purplle": PURPLLE_SAMPLE_HTML,
            "tira": TIRA_SAMPLE_HTML,
            "amazon": AMAZON_SAMPLE_HTML,
        }

    @staticmethod
    def _sample_product_id():
        """Resolve the seeded Dot & Key sunscreen matched by the HTML fixtures."""
        with get_connection() as conn:
            row = conn.execute(
                "SELECT id FROM products "
                "WHERE title LIKE '%Watermelon Cooling Sunscreen%' AND is_active = 1 "
                "ORDER BY id LIMIT 1"
            ).fetchone()
        assert row is not None, "seeded database must contain the sunscreen product"
        return row["id"]

    # -------------------------------------------------------------------------
    # 1. Gemini Identification & Query Generation
    # -------------------------------------------------------------------------
    def test_gemini_search_query_generation(self):
        """Verify query generation is deterministic and clean."""
        q = self.gemini.generate_search_query(
            brand="Dot & Key",
            product_name="Watermelon Cooling Sunscreen SPF 50",
            size_volume="50g",
        )
        self.assertIn("Dot", q)
        self.assertIn("Key", q)
        self.assertIn("Watermelon", q)
        self.assertIn("50g", q)

    # -------------------------------------------------------------------------
    # 2. Exact Variant Matching (30ml != 50ml, Shade Clashes)
    # -------------------------------------------------------------------------
    def test_variant_matching_size_mismatch(self):
        """Ensure 30ml vs 50ml is rejected as an incompatible mismatch."""
        match = evaluate_product_match(
            target_brand="Minimalist",
            target_title="Minimalist 10% Niacinamide Serum 30ml",
            target_specs={"Net Quantity": "30ml"},
            offer_brand="Minimalist",
            offer_title="Minimalist 10% Niacinamide Serum 50ml",
            offer_specs={"Net Quantity": "50ml"},
        )
        self.assertTrue(match.is_mismatch)
        self.assertFalse(match.is_comparable)
        self.assertEqual(match.match_classification, MatchClassification.INCOMPATIBLE_MISMATCH)

    def test_variant_matching_shade_mismatch(self):
        """Ensure different lipstick shades are never matched as identical."""
        match = evaluate_product_match(
            target_brand="M.A.C",
            target_title="M.A.C Retro Matte Lipstick - Ruby Woo",
            target_specs={"Shade": "Ruby Woo"},
            offer_brand="M.A.C",
            offer_title="M.A.C Matte Lipstick - Velvet Teddy",
            offer_specs={"Shade": "Velvet Teddy"},
        )
        self.assertTrue(match.is_mismatch)

    def test_variant_matching_exact_match(self):
        """Ensure exact brand, name, and size produces verified_match."""
        match = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Dot & Key Watermelon Cooling Sunscreen SPF 50 50g",
            target_specs={"Net Quantity": "50g"},
            offer_brand="Dot & Key",
            offer_title="Dot & Key Watermelon Cooling Sunscreen 50g",
            offer_specs={"Net Quantity": "50g"},
        )
        self.assertTrue(match.is_verified)
        self.assertTrue(match.is_comparable)

    # -------------------------------------------------------------------------
    # 3. HTML Price Extraction Across Retailers
    # -------------------------------------------------------------------------
    def test_nykaa_adapter_extraction(self):
        """Verify NykaaAdapter extracts price, MRP, and stock from HTML."""
        adapter = NykaaAdapter()
        res = adapter.extract_from_html(NYKAA_SAMPLE_HTML, "https://www.nykaa.com/product/123")
        self.assertEqual(res.verification_status, "retrieved")
        self.assertEqual(res.listed_price, 465.0)
        self.assertEqual(res.mrp, 595.0)
        self.assertTrue(res.in_stock)
        self.assertEqual(res.shipping_fee, 0.0)  # Free shipping on >= 299

    def test_myntra_adapter_extraction(self):
        """Verify MyntraAdapter extracts price and MRP from window.__myx."""
        adapter = MyntraAdapter()
        res = adapter.extract_from_html(MYNTRA_SAMPLE_HTML, "https://www.myntra.com/123456")
        self.assertEqual(res.verification_status, "retrieved")
        self.assertEqual(res.listed_price, 489.0)
        self.assertEqual(res.mrp, 595.0)
        self.assertTrue(res.in_stock)
        self.assertEqual(res.shipping_fee, 99.0)  # Below 799 threshold

    def test_purplle_adapter_extraction(self):
        """Verify PurplleAdapter extracts price from DOM selectors."""
        adapter = PurplleAdapter()
        res = adapter.extract_from_html(PURPLLE_SAMPLE_HTML, "https://www.purplle.com/product/xyz")
        self.assertEqual(res.verification_status, "retrieved")
        self.assertEqual(res.listed_price, 475.0)
        self.assertEqual(res.mrp, 595.0)
        self.assertTrue(res.in_stock)

    def test_tira_adapter_extraction(self):
        """Verify TiraAdapter extracts price from __NEXT_DATA__ script."""
        adapter = TiraAdapter()
        res = adapter.extract_from_html(TIRA_SAMPLE_HTML, "https://www.tirabeauty.com/product/tira-123")
        self.assertEqual(res.verification_status, "retrieved")
        self.assertEqual(res.listed_price, 495.0)
        self.assertEqual(res.mrp, 595.0)
        self.assertTrue(res.in_stock)

    def test_amazon_adapter_extraction(self):
        """Verify AmazonIndiaAdapter extracts price from standard Amazon DOM."""
        adapter = AmazonIndiaAdapter()
        res = adapter.extract_from_html(AMAZON_SAMPLE_HTML, "https://www.amazon.in/dp/B0XYZ123")
        self.assertEqual(res.verification_status, "retrieved")
        self.assertEqual(res.listed_price, 470.0)
        self.assertEqual(res.mrp, 595.0)
        self.assertTrue(res.in_stock)

    # -------------------------------------------------------------------------
    # 4. Bot Protection & CAPTCHA Detection
    # -------------------------------------------------------------------------
    def test_amazon_captcha_detection(self):
        """Ensure Amazon CAPTCHA challenge is detected and marked as restricted."""
        adapter = AmazonIndiaAdapter()
        res = adapter.extract_from_html(AMAZON_CAPTCHA_HTML, "https://www.amazon.in/dp/B0XYZ123")
        self.assertEqual(res.verification_status, "restricted")
        self.assertIn("CAPTCHA", res.validation_notes or "")

    def test_cloudflare_bot_detection(self):
        """Ensure Cloudflare challenge is detected without crashing."""
        adapter = NykaaAdapter()
        res = adapter.extract_from_html(CLOUDFLARE_CHALLENGE_HTML, "https://www.nykaa.com/test")
        self.assertEqual(res.verification_status, "restricted")
        self.assertIn("Cloudflare", res.validation_notes or "")

    # -------------------------------------------------------------------------
    # 5. Lowest Listed Price vs Lowest Total Purchase Cost
    # -------------------------------------------------------------------------
    def test_lowest_total_cost_calculation_with_unknown_shipping(self):
        """
        Verify the distinction between lowest listed price and lowest total landed cost:
        Nykaa: ₹499 + ₹40 shipping = ₹539 total
        Myntra: ₹519 + ₹0 shipping = ₹519 total
        Tira: ₹489 + unknown shipping = total unknown
        -> Lowest listed price is Tira (489)
        -> Lowest verified total cost is Myntra (519)
        """
        offers = [
            LiveRetailerOfferItem(
                retailer_name="Nykaa",
                store_id="nykaa",
                status="retrieved",
                listed_price=499.0,
                shipping_fee=40.0,
                is_shipping_disclosed=True,
                total_cost=539.0,
                in_stock=True,
            ),
            LiveRetailerOfferItem(
                retailer_name="Myntra",
                store_id="myntra",
                status="retrieved",
                listed_price=519.0,
                shipping_fee=0.0,
                is_shipping_disclosed=True,
                total_cost=519.0,
                in_stock=True,
            ),
            LiveRetailerOfferItem(
                retailer_name="Tira",
                store_id="tira",
                status="retrieved",
                listed_price=489.0,
                shipping_fee=None,
                is_shipping_disclosed=False,
                total_cost=None,
                in_stock=True,
            ),
        ]

        summary = self.engine._compute_summary(offers)
        self.assertEqual(summary.lowest_listed_price, 489.0)
        self.assertEqual(summary.lowest_listed_retailer, "Tira")
        self.assertEqual(summary.lowest_total_cost, 519.0)
        self.assertEqual(summary.lowest_total_retailer, "Myntra")

    # -------------------------------------------------------------------------
    # 6. Automatic Comparison Execution with Fixtures & Caching
    # -------------------------------------------------------------------------
    def test_automatic_comparison_engine_with_fixtures(self):
        """Execute full engine comparison using mock HTML fixtures."""
        product_id = self._sample_product_id()

        res = self.engine.execute_live_comparison(
            product_id=product_id,
            force_refresh=True,
            mock_html_fixtures=self._sample_fixtures(),
        )

        self.assertIsNotNone(res)
        self.assertEqual(res.product_id, product_id)
        self.assertGreater(len(res.offers), 0)
        self.assertFalse(res.is_cached)

        # Verify summary
        self.assertIsNotNone(res.summary.lowest_listed_price)
        self.assertIsNotNone(res.summary.lowest_total_cost)

        # Second run without force_refresh should return cached result
        cached_res = self.engine.execute_live_comparison(
            product_id=product_id, force_refresh=False
        )
        self.assertTrue(cached_res.is_cached)
        self.assertEqual(cached_res.product_id, product_id)

    # -------------------------------------------------------------------------
    # 7. Manual Retailer URL Checking
    # -------------------------------------------------------------------------
    def test_manual_url_check_valid_nykaa(self):
        """Verify manual URL check for Nykaa URL using mock HTML."""
        url = "https://www.nykaa.com/dot-key-watermelon-cooling-sunscreen/p/123"
        res = self.engine.check_manual_url_price(url, mock_html=NYKAA_SAMPLE_HTML)
        self.assertEqual(res.verification_status, "retrieved")
        self.assertEqual(res.retailer_name, "Nykaa")
        self.assertEqual(res.listed_price, 465.0)

    def test_manual_url_check_security_rejections(self):
        """Ensure security policy blocks malicious / unapproved URLs."""
        # Localhost
        res_local = self.engine.check_manual_url_price("http://127.0.0.1:8000")
        self.assertEqual(res_local.verification_status, "unsupported")

        # Unapproved domain
        res_evil = self.engine.check_manual_url_price("https://evil-hacker.com/nykaa")
        self.assertEqual(res_evil.verification_status, "unsupported")

        # Insecure scheme
        res_http = self.engine.check_manual_url_price("http://www.nykaa.com/product/123")
        self.assertEqual(res_http.verification_status, "unsupported")

    # -------------------------------------------------------------------------
    # 8. Audit Logging in price_check_logs Table
    # -------------------------------------------------------------------------
    def test_audit_logs_persisted(self):
        """Verify that price_check_logs table logs live runs."""
        product_id = self._sample_product_id()
        # Make the test self-contained rather than relying on audit rows left
        # behind by earlier tests or a developer-local database.
        self.engine.execute_live_comparison(
            product_id=product_id,
            force_refresh=True,
            mock_html_fixtures=self._sample_fixtures(),
        )
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM price_check_logs")
            count = cur.fetchone()[0]
            self.assertGreaterEqual(count, 1)

    # -------------------------------------------------------------------------
    # 9. API Endpoints Integration (/api/compare/auto, /api/compare/url)
    # -------------------------------------------------------------------------
    @patch.object(LiveComparisonEngine, "execute_live_comparison")
    def test_api_auto_compare_endpoint(self, mock_execute):
        """Test GET /api/compare/auto endpoint."""
        mock_execute.return_value = LiveComparisonResult(
            product_id=76,
            product_title="Dot & Key Watermelon Cooling Sunscreen",
            brand="Dot & Key",
            target_variant="50g",
            is_cached=False,
            freshness_seconds=0,
            retrieval_timestamp="2026-11-01T12:00:00Z",
            offers=[
                LiveRetailerOfferItem(
                    retailer_name="Nykaa",
                    store_id="nykaa",
                    status="retrieved",
                    listed_price=465.0,
                    mrp=595.0,
                    shipping_fee=0.0,
                    is_shipping_disclosed=True,
                    total_cost=465.0,
                    in_stock=True,
                )
            ],
            summary=LiveComparisonSummary(
                lowest_listed_price=465.0,
                lowest_listed_retailer="Nykaa",
                lowest_total_cost=465.0,
                lowest_total_retailer="Nykaa",
                retailers_checked=1,
                retailers_retrieved=1,
                retailers_unavailable=0,
                retailers_unsupported=0,
                retailers_restricted=0,
                cheapest_savings_amount=130.0,
                cheapest_savings_percent=21.8,
            ),
        )
        response = self.client.get("/api/compare/auto?product_id=76")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["product_id"], 76)
        self.assertIn("offers", data)
        self.assertIn("summary", data)
        self.assertEqual(data["summary"]["lowest_listed_price"], 465.0)

    def test_api_auto_compare_missing_params(self):
        """Test GET /api/compare/auto returns 400 when params are missing."""
        response = self.client.get("/api/compare/auto")
        self.assertEqual(response.status_code, 400)

    @patch.object(LiveComparisonEngine, "check_manual_url_price")
    def test_api_manual_url_endpoint(self, mock_check):
        """Test POST /api/compare/url endpoint."""
        mock_check.return_value = ExtractedPriceResult(
            retailer_name="Nykaa",
            store_id="nykaa",
            product_name="Dot & Key Watermelon Sunscreen",
            product_url="https://www.nykaa.com/dot-key-sunscreen/p/123",
            verification_status="retrieved",
            listed_price=465.0,
            mrp=595.0,
            shipping_fee=0.0,
            is_shipping_disclosed=True,
            in_stock=True,
            stock_status="In Stock",
        )
        body = {"url": "https://www.nykaa.com/dot-key-sunscreen/p/123"}
        response = self.client.post("/api/compare/url", json=body)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["retailer_name"], "Nykaa")
        self.assertEqual(data["listed_price"], 465.0)


if __name__ == "__main__":
    unittest.main()
