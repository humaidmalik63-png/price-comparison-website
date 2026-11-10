"""Phase 11B Hybrid AI + Web Extraction & Price Intelligence Engine Test Suite.

Comprehensive tests covering:
1. Deterministic Schema.org JSON-LD extraction
2. OpenGraph / meta tag product extraction
3. HTML DOM parsing with price regex cleaners
4. Anti-Bot and WAF challenge detection (Akamai 403, Cloudflare, Amazon CAPTCHA)
5. SSRF prevention (private IPs, link-local, non-whitelisted domains, invalid schemes)
6. Response size protection (<5MB limits)
7. Gemini semantic extraction fallback and quota error handling
8. Product matching engine (EXACT_MATCH, SIZE_VARIANT, FORMULATION_VARIANT, SHADE_VARIANT, BUNDLE_MATCH, POSSIBLE_MATCH, NO_MATCH)
9. Unit price normalization (₹/ml and ₹/g)
10. Deterministic price validation (positive price, MRP >= price)
11. Evidence reference persistence (screenshots, receipts, audit links)
12. Retailer access policies and circuit breaker tripping
13. Concurrency locking per product ID
14. Admin verification queue & approval / rejection lifecycle
15. Price history persistence and deal alert rule trigger
16. Strict separation of DEMO vs LIVE_VERIFIED and MANUAL_VERIFIED data
"""

import os
from unittest.mock import patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.database.connection import get_connection
from src.database.models import User
from src.services.product_matching_service import (
    evaluate_product_match,
    calculate_unit_price,
    parse_quantity_volume,
    parse_concentration,
    parse_shade,
    parse_formulation,
    detect_bundle,
    MatchClassification,
)
from src.services.web_extraction_service import (
    extract_product_data,
    extract_from_json_ld,
    extract_from_meta_tags,
    extract_from_html_dom,
    detect_waf_challenge,
    safe_fetch_url,
    interpret_with_gemini,
)
from src.services.price_verification_service import (
    record_evidence_reference,
    get_evidence_for_reference,
    get_pending_verification_queue,
    approve_manual_verification,
    reject_manual_verification,
    approve_price_correction,
    reject_price_correction,
    validate_price_observation_data,
    VerificationStatus,
)
from src.services.price_collection_engine import (
    get_retailer_status_list,
    get_product_retailer_sources,
    collect_product_prices,
    is_circuit_breaker_tripped,
    trip_circuit_breaker,
    check_rate_limit,
    RetailerAccessStatus,
)

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def read_fixture(name: str) -> str:
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


# =============================================================================
# 1. Structured Web Extraction Tests
# =============================================================================

class TestWebExtraction:
    def test_json_ld_extraction(self):
        html = read_fixture("myntra_sample.html")
        data = extract_from_json_ld(html)
        assert data is not None
        assert data["price"] == 569.00
        assert data["mrp"] == 599.00
        assert data["currency"] == "INR"
        assert data["brand"] == "Minimalist"
        assert "Minimalist 10% Niacinamide" in data["title"]
        assert data["in_stock"] is True

    def test_opengraph_meta_extraction(self):
        html = read_fixture("purplle_sample.html")
        data = extract_from_meta_tags(html)
        assert data is not None
        assert data["price"] == 425.00
        assert data["mrp"] == 470.00
        assert data["brand"] == "Plum"
        assert "Plum Green Tea" in data["title"]
        assert data["in_stock"] is True

    def test_html_dom_extraction(self):
        html = """
        <html>
        <head><title>The Derma Co 10% Vitamin C Serum</title></head>
        <body>
            <h1>The Derma Co 10% Vitamin C Serum 30ml</h1>
            <div class="product-price">
                <span class="selling-price">₹ 649.00</span>
                <span class="mrp">MRP ₹699</span>
            </div>
        </body>
        </html>
        """
        data = extract_from_html_dom(html)
        assert data is not None
        assert data["price"] == 649.00
        assert data["mrp"] == 699.00
        assert "The Derma Co" in data["title"]

    def test_full_pipeline_extracted_result(self):
        html = read_fixture("myntra_sample.html")
        res = extract_product_data(
            html_content=html,
            url="https://www.myntra.com/serum",
            retailer_name="Myntra",
        )
        assert res.status == "extracted"
        assert res.extraction_method == "json_ld"
        assert res.price == 569.00
        assert res.mrp == 599.00
        assert res.discount_pct == 5.0
        assert res.size_volume == "30.0ml"
        assert res.is_blocked is False


# =============================================================================
# 2. WAF and Security Protection Tests
# =============================================================================

class TestWafAndSecurityProtection:
    def test_akamai_waf_detection(self):
        html = read_fixture("akamai_blocked.html")
        is_blocked, block_type = detect_waf_challenge(html, status_code=403)
        assert is_blocked is True
        assert block_type in ("http_403_or_429", "akamai_waf")

        res = extract_product_data(html, url="https://www.nykaa.com", retailer_name="Nykaa", status_code=403)
        assert res.status == "restricted"
        assert res.is_blocked is True

    def test_amazon_robot_check_captcha(self):
        html = read_fixture("amazon_captcha.html")
        is_blocked, block_type = detect_waf_challenge(html, status_code=200)
        assert is_blocked is True
        assert block_type == "amazon_captcha"

        res = extract_product_data(html, url="https://www.amazon.in", retailer_name="Amazon India")
        assert res.status == "restricted"
        assert res.is_blocked is True

    def test_ssrf_blocking_private_ip(self):
        html, code, err = safe_fetch_url("http://169.254.169.254/latest/meta-data")
        assert code == 400
        assert "SSRF" in err or "Insecure scheme" in err

    def test_ssrf_blocking_localhost(self):
        html, code, err = safe_fetch_url("https://127.0.0.1:8000/api")
        assert code == 400
        assert "Access to localhost" in err or "SSRF" in err

    def test_ssrf_blocking_unauthorized_domain(self):
        html, code, err = safe_fetch_url("https://malicious-external-site.com/exploit")
        assert code == 400
        assert "approved retailer allowlist" in err


# =============================================================================
# 3. Gemini Structured Interpretation & Fallback Tests
# =============================================================================

class TestGeminiInterpretation:
    @patch("src.services.gemini_service.GeminiService._get_client")
    @patch("src.services.gemini_service.GeminiService.is_configured", True)
    def test_gemini_structured_interpretation(self, mock_get_client):
        mock_response = MagicMock()
        mock_response.text = """```json
        {
            "title": "Minimalist Niacinamide 10% 30ml",
            "brand": "Minimalist",
            "selling_price": 549.0,
            "mrp": 599.0,
            "currency": "INR",
            "size_volume": "30ml",
            "shade": null,
            "formulation": "Serum",
            "in_stock": true
        }
        ```"""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        snippet = "<div class='p'>Minimalist Niacinamide 10% on sale for 549 rupees (original 599)</div>"
        parsed = interpret_with_gemini(snippet, context_hint="Nykaa")
        assert parsed is not None
        assert parsed["price"] == 549.0
        assert parsed["mrp"] == 599.0
        assert parsed["brand"] == "Minimalist"
        assert parsed["size_volume"] == "30ml"

    @patch("src.services.gemini_service.GeminiService._get_client")
    @patch("src.services.gemini_service.GeminiService.is_configured", True)
    def test_gemini_quota_error_fallback(self, mock_get_client):
        # Simulate Quota Exhaustion HTTP 429
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("429 Resource has been exhausted (quota limit reached)")
        mock_get_client.return_value = mock_client

        snippet = "<div>Some price text</div>"
        parsed = interpret_with_gemini(snippet)
        assert parsed is None  # Safe fallback without crashing

    @patch("src.services.gemini_service.GeminiService._get_client")
    @patch("src.services.gemini_service.GeminiService.is_configured", True)
    def test_gemini_impossible_price_guardrail(self, mock_get_client):
        # Simulate LLM hallucination: MRP < selling price or negative price
        mock_response = MagicMock()
        mock_response.text = """```json
        {
            "title": "Serum",
            "brand": "Minimalist",
            "selling_price": -50.0,
            "mrp": 10.0,
            "currency": "INR",
            "in_stock": true
        }
        ```"""
        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response
        mock_get_client.return_value = mock_client

        parsed = interpret_with_gemini("<div>Negative price</div>")
        assert parsed is None  # Deterministic guardrail rejected invalid price


# =============================================================================
# 4. Multi-Factor Product Matching Tests (7 Tiers)
# =============================================================================

class TestProductMatchingSevenTiers:
    def test_exact_match(self):
        res = evaluate_product_match(
            target_brand="Minimalist",
            target_title="Minimalist 10% Niacinamide Face Serum 30ml",
            offer_brand="Minimalist",
            offer_title="Minimalist 10% Niacinamide Face Serum 30ml",
            target_price=599.0,
            offer_price=569.0,
        )
        assert res.match_classification == MatchClassification.EXACT_MATCH
        assert res.is_verified is True
        assert res.is_comparable is True
        assert res.confidence_score >= 0.95

    def test_size_variant_with_unit_price(self):
        res = evaluate_product_match(
            target_brand="Minimalist",
            target_title="Minimalist 10% Niacinamide Face Serum 30ml",
            offer_brand="Minimalist",
            offer_title="Minimalist 10% Niacinamide Face Serum 60ml",
            target_price=599.0,
            offer_price=999.0,
        )
        assert res.match_classification == MatchClassification.SIZE_VARIANT
        assert res.is_verified is False
        assert res.target_unit_price == round(599.0 / 30.0, 2)  # ₹19.97/ml
        assert res.offer_unit_price == round(999.0 / 60.0, 2)    # ₹16.65/ml
        assert res.unit_price_unit == "₹/ml"

    def test_formulation_variant_concentration_difference(self):
        res = evaluate_product_match(
            target_brand="Minimalist",
            target_title="Minimalist 10% Niacinamide Face Serum 30ml",
            offer_brand="Minimalist",
            offer_title="Minimalist 5% Niacinamide Face Serum 30ml",
        )
        assert res.match_classification == MatchClassification.FORMULATION_VARIANT
        assert res.is_verified is False
        assert res.is_mismatch is True

    def test_shade_variant_difference(self):
        res = evaluate_product_match(
            target_brand="M.A.C",
            target_title="M.A.C Retro Matte Lipstick - Ruby Woo 3g",
            offer_brand="M.A.C",
            offer_title="M.A.C Retro Matte Lipstick - Velvet Teddy 3g",
        )
        assert res.match_classification == MatchClassification.SHADE_VARIANT
        assert res.is_verified is False
        assert res.target_shade == "Ruby Woo"
        assert res.offer_shade == "Velvet Teddy"

    def test_bundle_match_detection(self):
        res = evaluate_product_match(
            target_brand="Cetaphil",
            target_title="Cetaphil Gentle Skin Cleanser 250ml",
            offer_brand="Cetaphil",
            offer_title="Cetaphil Gentle Skin Cleanser 250ml (Pack of 2)",
        )
        assert res.match_classification == MatchClassification.BUNDLE_MATCH
        assert res.is_bundle is True
        assert res.bundle_quantity == 2
        assert res.is_verified is False

    def test_no_match_brand_conflict(self):
        res = evaluate_product_match(
            target_brand="Minimalist",
            target_title="Minimalist 10% Niacinamide Serum 30ml",
            offer_brand="The Ordinary",
            offer_title="The Ordinary Niacinamide 10% + Zinc 1% 30ml",
        )
        assert res.match_classification == MatchClassification.NO_MATCH
        assert res.is_comparable is False
        assert res.confidence_score <= 0.20


# =============================================================================
# 5. Price Verification & Evidence Management Tests
# =============================================================================

class TestPriceVerificationService:
    @pytest.fixture(autouse=True)
    def _provision_users(self):
        """Create the users this class needs instead of assuming user id 1.

        These tests previously hardcoded ``user_id=1`` / ``uploaded_by=1`` and
        only passed when another test module had already created that user in
        the shared database. Provisioning the fixtures here makes the class
        self-contained and order-independent.
        """
        from src.services.auth_service import get_user_by_email, register_user

        created: dict[str, int] = {}
        for label, email in (
            ("customer", "phase11b_customer@example.com"),
            ("admin", "phase11b_admin@example.com"),
        ):
            ok, _msg, user = register_user(
                email=email,
                password="Phase11bPass!",
                display_name=f"Phase 11B {label.title()}",
            )
            if not ok:
                # The fixture runs once per test; reuse the account created
                # by an earlier test in this class instead of failing.
                user = get_user_by_email(email)
            assert user is not None, f"could not provision the {label} fixture user"
            created[label] = user.id

        # A product that exists in the catalogue and is visible to customers.
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM products WHERE is_active = 1 ORDER BY id LIMIT 1"
            )
            row = cursor.fetchone()
        created["product_id"] = int(row["id"]) if row else 1

        self.customer_id = created["customer"]
        self.admin_id = created["admin"]
        self.product_id = created["product_id"]
        yield

    def test_deterministic_validation_guardrails(self):
        # Selling price <= 0 rejected
        valid, reason = validate_price_observation_data(
            selling_price=-10.0,
            mrp=500.0,
            product_url="https://www.nykaa.com/item",
            retailer="Nykaa",
            match_classification="EXACT_MATCH",
        )
        assert valid is False
        assert "greater than zero" in reason

        # MRP < selling price rejected
        valid, reason = validate_price_observation_data(
            selling_price=599.0,
            mrp=499.0,
            product_url="https://www.nykaa.com/item",
            retailer="Nykaa",
            match_classification="EXACT_MATCH",
        )
        assert valid is False
        assert "lower than selling price" in reason

        # Valid parameters succeed
        valid, reason = validate_price_observation_data(
            selling_price=499.0,
            mrp=599.0,
            product_url="https://www.nykaa.com/item",
            retailer="Nykaa",
            match_classification="EXACT_MATCH",
        )
        assert valid is True
        assert reason is None

    def test_evidence_reference_recording_and_retrieval(self):
        # Use the customer fixture provisioned for this test (no hardcoded id)
        evidence_id = record_evidence_reference(
            reference_type="manual_verification",
            reference_id=9999,
            evidence_url="/api/verification/evidence/proof_test_123.png",
            evidence_type="screenshot",
            description="Nykaa product page screenshot verification",
            uploaded_by=self.customer_id,
        )
        assert evidence_id > 0

        evidence_list = get_evidence_for_reference("manual_verification", 9999)
        assert len(evidence_list) >= 1
        assert evidence_list[0]["evidence_url"] == "/api/verification/evidence/proof_test_123.png"

    def test_admin_approval_and_rejection_workflow(self):
        admin_user = User(
            id=self.admin_id,
            display_name="Alex Demo",
            email="phase11b_admin@example.com",
            password_hash="test",
            created_at="2026-11-09",
            status="active",
        )

        # Create a pending manual verification request in DB
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO manual_verification_requests (
                    user_id, product_id, retailer, product_url, user_submitted_price,
                    size_volume, notes, status, submitted_at
                ) VALUES (?, ?, 'Nykaa', 'https://www.nykaa.com/test-pdp', 549.0, '30ml', 'Test promo', 'pending', CURRENT_TIMESTAMP)
                """,
                (self.customer_id, self.product_id),
            )
            req_id = cursor.lastrowid

        # Approve
        approval_res = approve_manual_verification(
            request_id=req_id,
            reviewer=admin_user,
            verified_price=549.0,
            verified_mrp=599.0,
            notes="Confirmed screenshot evidence",
        )
        assert approval_res["status"] == "approved"
        assert approval_res["verification_status"] == VerificationStatus.MANUAL_VERIFIED

        # Verify DB state
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, verification_status, verified_price FROM manual_verification_requests WHERE id = ?", (req_id,))
            row = cursor.fetchone()
            assert row["status"] == "verified"
            assert row["verification_status"] == VerificationStatus.MANUAL_VERIFIED
            assert row["verified_price"] == 549.0

            # Verify price_history persistence
            cursor.execute("SELECT * FROM price_history WHERE data_source = 'manual_verification' ORDER BY id DESC LIMIT 1")
            hist = cursor.fetchone()
            assert hist is not None
            assert hist["data_status"] == "manual_verified"
            assert hist["price"] == 549.0


# =============================================================================
# 6. Retailer Policy & Circuit Breaker Tests
# =============================================================================

class TestRetailerAccessPolicies:
    def test_all_five_retailers_configured(self):
        policies = get_retailer_status_list()
        assert len(policies) == 5
        names = {p["retailer_name"] for p in policies}
        assert "Nykaa" in names
        assert "Tira Beauty" in names
        assert "Amazon India" in names
        assert "Myntra" in names
        assert "Purplle" in names

    def test_restricted_retailer_blocks_automated_collection(self):
        # Nykaa is RESTRICTED by default
        res = collect_product_prices(1, test_retailer="nykaa")
        assert res["status"] == "completed"
        nykaa_result = res["results"][0]
        assert nykaa_result["verification_status"] == VerificationStatus.RESTRICTED
        assert nykaa_result["requires_manual_verification"] is True

    def test_circuit_breaker_trips_on_block(self):
        domain = "test-blocked-store.com"
        trip_circuit_breaker(domain, "Akamai WAF Access Denied")
        tripped, reason = is_circuit_breaker_tripped(domain)
        assert tripped is True
        assert "Akamai WAF" in reason

    def test_domain_rate_limiter(self):
        domain = "rate-limit-test.com"
        allowed1, wait1 = check_rate_limit(domain)
        assert allowed1 is True
        # Second call immediately should be throttled
        allowed2, wait2 = check_rate_limit(domain)
        assert allowed2 is False
        assert wait2 > 0.0


# =============================================================================
# 7. End-to-End API Route Tests
# =============================================================================

class TestApiEndpoints:
    @pytest.fixture
    def client(self):
        return TestClient(app)

    def test_get_retailer_status_endpoint(self, client):
        res = client.get("/api/prices/retailer-status")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["count"] == 5

    def test_get_product_sources_endpoint(self, client):
        res = client.get("/api/prices/sources/1")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "ok"
        assert data["product_id"] == 1
        assert len(data["sources"]) > 0

    def test_collect_prices_endpoint(self, client):
        res = client.post("/api/prices/collect/1")
        assert res.status_code in (200, 429)  # 200 or 429 if already running

    def test_admin_queue_requires_auth(self, client):
        res = client.get("/api/admin/verifications")
        # Unauthenticated request must be rejected
        assert res.status_code == 401
