"""Phase 16.7C — PriceInIndia Evidence & Data Quality Tests.

Covers the 16.7C improvements with mocked inputs only (no live provider
calls; the only DB used is the temporary test database via the
``fresh_seeded_db`` fixture, which is never the application database):

1. Provider ``lastUpdated`` mapped into the observation freshness system.
2. Raw provider price precision preserved; safe INR display formatting.
3. Provider page / affiliate redirect URLs distinguished from retailer URLs.
4. Retailer URLs never invented when only a provider page URL exists.
5. Retailer attribution preserved separately from provider identity.
6. Missing-size results stay POSSIBLE / NEEDS_MANUAL_REVIEW — never
   EXACT or STRONG.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.database.connection import get_connection
from src.scripts import collect_pi_observations as cpi
from src.services import cheapest_offer_service as cos
from src.services.freshness_service import (
    FRESH,
    STALE,
    UNKNOWN,
    parse_epoch_seconds,
    provider_freshness,
)
from src.services.price_formatting import format_inr, round_inr_display
from src.services.product_matching_service import (
    MatchClassification,
    MatchStrength,
    evaluate_product_match,
)


NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=timezone.utc)


# ── 1. Provider lastUpdated → freshness system ───────────────────────────────

class TestProviderFreshnessMapping:
    def test_parse_epoch_seconds(self):
        parsed = parse_epoch_seconds(1794375906, now=NOW)
        assert parsed is not None
        assert parsed.tzinfo is not None

    def test_parse_epoch_milliseconds_auto_detected(self):
        secs = parse_epoch_seconds(1794375906, now=NOW)
        ms = parse_epoch_seconds(1794375906000, now=NOW)
        assert secs is not None and ms is not None
        assert abs((ms - secs).total_seconds()) < 1

    def test_parse_epoch_rejects_garbage(self):
        assert parse_epoch_seconds(None, now=NOW) is None
        assert parse_epoch_seconds(True, now=NOW) is None
        assert parse_epoch_seconds("", now=NOW) is None
        assert parse_epoch_seconds("not-a-number", now=NOW) is None
        assert parse_epoch_seconds(-5, now=NOW) is None
        assert parse_epoch_seconds(float("nan"), now=NOW) is None
        # implausible future timestamp (> now + 1 day) is never accepted
        future = int((NOW + timedelta(days=30)).timestamp())
        assert parse_epoch_seconds(future, now=NOW) is None

    def test_provider_freshness_buckets(self):
        recent = int((NOW - timedelta(hours=1)).timestamp())
        old = int((NOW - timedelta(days=30)).timestamp())
        assert provider_freshness(recent, now=NOW)["provider_freshness"] == FRESH
        assert provider_freshness(old, now=NOW)["provider_freshness"] == STALE
        unknown = provider_freshness(None, now=NOW)
        assert unknown["provider_freshness"] == UNKNOWN
        assert unknown["provider_last_updated_iso"] is None
        assert unknown["provider_age_hours"] is None

    def test_normalize_maps_last_updated_epoch(self):
        epoch = 1794375906
        n = cpi.normalize_pi_item({
            "title": "Minimalist 10% Niacinamide Serum",
            "store": "myntra.com",
            "price": 569,
            "currency": "INR",
            "lastUpdated": epoch,
        })
        assert n["last_updated_epoch"] == pytest.approx(float(epoch))
        # absent lastUpdated stays None — never guessed
        n2 = cpi.normalize_pi_item({
            "title": "X", "store": "myntra.com", "price": 1, "currency": "INR",
        })
        assert n2["last_updated_epoch"] is None


# ── 2. Raw price precision + safe INR display policy ─────────────────────────

class TestPricePrecisionAndDisplay:
    def test_parse_price_preserves_full_precision(self):
        assert cpi.parse_price(569.049988) == 569.049988

    def test_normalize_preserves_raw_price(self):
        n = cpi.normalize_pi_item({
            "title": "Tata Cliq serum", "store": "tatacliq.com",
            "price": 569.049988, "currency": "INR",
        })
        assert n["price"] == 569.049988
        assert n["price_raw"] == 569.049988

        n2 = cpi.normalize_pi_item({
            "title": "Formatted", "store": "nykaa.com",
            "price": "₹1,299", "currency": "INR",
        })
        assert n2["price"] == 1299.0
        assert n2["price_raw"] == "₹1,299"

    def test_display_policy_rounds_but_does_not_mutate_storage(self):
        stored = cpi.parse_price(569.049988)
        assert stored == 569.049988          # storage keeps provider precision
        assert round_inr_display(stored) == 569.05  # display rounds to paise

    def test_format_inr(self):
        assert format_inr(569) == "₹569"
        assert format_inr(1299.5) == "₹1,299.50"
        assert format_inr(569.049988) == "₹569.05"
        assert format_inr(12999999) == "₹1,29,99,999"  # Indian digit grouping
        assert format_inr(-42.5) == "-₹42.50"
        assert format_inr(None) is None
        assert format_inr(float("nan")) is None
        assert format_inr("not-a-number") is None

    def test_store_observation_keeps_precision_and_records_raw(self):
        result = cpi.store_observation(
            1,
            {"id": "p", "title": "t", "store": "tatacliq.com", "price": 569.049988,
             "productPageUrl": "https://www.priceinindia.website/products/x"},
            _comparable_match(),
            dry_run=True,
        )
        observation = result["observation"]
        assert observation["observed_price"] == 569.049988  # precision preserved
        evidence = json.loads(observation["match_result"])
        assert evidence["provider_price_raw"] == 569.049988


# ── 3. + 4. URL provenance — provider page vs retailer URL ───────────────────

class TestUrlProvenance:
    PI_PAGE = "https://www.priceinindia.website/products/niacinamide-serum"
    AFFILIATE = "https://www.priceinindia.website/external/myntra.com/abc"

    def test_provider_page_url_kind_and_flag(self):
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "productPageUrl": self.PI_PAGE,
        })
        assert n["url"] == self.PI_PAGE
        assert n["url_kind"] == "provider_page"
        assert n["provider_page_url"] == self.PI_PAGE
        assert n["affiliate_redirect_url"] is None
        assert "url_is_provider_page" in n["flags"]

    def test_affiliate_only_redirect_flagged(self):
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "productUrl": self.AFFILIATE,
        })
        assert n["url"] == self.AFFILIATE
        assert n["url_kind"] == "provider_affiliate_redirect"
        assert "url_is_affiliate_redirect" in n["flags"]

    def test_citation_prefers_provider_page_when_both_present(self):
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR",
            "productPageUrl": self.PI_PAGE, "productUrl": self.AFFILIATE,
        })
        assert n["url"] == self.PI_PAGE
        assert n["url_kind"] == "provider_page"

    def test_retailer_url_only_when_explicitly_supplied(self):
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR",
            "retailerUrl": "https://www.myntra.com/serum/1234",
        })
        assert n["retailer_product_url"] == "https://www.myntra.com/serum/1234"
        assert n["url_kind"] == "retailer"

    def test_explicit_retailer_url_does_not_override_citation(self):
        """Citation stays the provider page (documented citation link); the
        explicit retailer URL is recorded separately, never conflated."""
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "productPageUrl": self.PI_PAGE,
            "retailerUrl": "https://www.myntra.com/serum/1234",
        })
        assert n["url"] == self.PI_PAGE
        assert n["url_kind"] == "provider_page"
        assert n["retailer_product_url"] == "https://www.myntra.com/serum/1234"

    def test_retailer_url_never_invented_from_provider_page(self):
        """Requirement 4: only a PriceInIndia page URL available ⇒ the
        retailer product URL is None. Never derived, never guessed."""
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "productPageUrl": self.PI_PAGE,
        })
        assert n["retailer_product_url"] is None

    def test_store_observation_records_url_provenance(self):
        result = cpi.store_observation(
            1,
            {"id": "p", "title": "Serum", "store": "myntra.com", "price": 569,
             "currency": "INR", "productPageUrl": self.PI_PAGE},
            _comparable_match(),
            dry_run=True,
        )
        observation = result["observation"]
        assert " | url_is_provider_page" in observation["evidence_notes"]
        evidence = json.loads(observation["match_result"])
        assert evidence["url_kind"] == "provider_page"
        assert evidence["provider_page_url"] == self.PI_PAGE
        assert evidence["affiliate_redirect_url"] is None
        assert evidence["retailer_product_url"] is None  # never invented


# ── 5. Retailer attribution separate from provider identity ──────────────────

class TestRetailerAttributionSeparate:
    def test_retailer_and_provider_recorded_distinctly(self):
        result = cpi.store_observation(
            1,
            {"id": "p", "title": "Serum", "store": "myntra.com", "price": 569,
             "currency": "INR", "productPageUrl": "https://x"},
            _comparable_match(),
            dry_run=True,
        )
        obs = result["observation"]
        assert obs["retailer"] == "myntra.com"        # retailer attribution
        assert obs["retailer_domain"] == "myntra.com"
        assert obs["provider_name"] == "priceinindia"  # provider identity
        evidence = json.loads(obs["match_result"])
        assert evidence["retailer"] == "myntra.com"

    def test_plain_retailer_name_gets_no_guessed_domain(self):
        result = cpi.store_observation(
            1,
            {"id": "p", "title": "Serum", "store": "Nykaa", "price": 569,
             "currency": "INR", "productPageUrl": "https://x"},
            _comparable_match(),
            dry_run=True,
        )
        obs = result["observation"]
        assert obs["retailer"] == "Nykaa"
        assert obs["retailer_domain"] is None  # never guessed

    def test_provider_page_url_is_not_written_as_retailer_offer_url(
        self, fresh_seeded_db,
    ):
        """Requirement 4 at the offers-table level: a PriceInIndia page URL
        must never overwrite or stand in for a retailer product URL in the
        offers table."""
        with get_connection(fresh_seeded_db) as conn:
            store = conn.execute(
                "SELECT id FROM stores WHERE domain = 'myntra.com'"
            ).fetchone()
            assert store is not None
            existing = conn.execute(
                "SELECT id, offer_url FROM offers WHERE product_id = 1 AND store_id = ?",
                (store["id"],),
            ).fetchone()
            if existing is None:
                cursor = conn.execute(
                    """
                    INSERT INTO offers (product_id, store_id, current_price,
                        original_price, shipping_cost, currency, availability,
                        offer_url, last_checked)
                    VALUES (1, ?, 100.0, 120.0, 0, 'INR', 'In Stock',
                        'https://www.myntra.com/existing/1', '2026-01-01')
                    """,
                    (store["id"],),
                )
                offer_id, original_url = cursor.lastrowid, "https://www.myntra.com/existing/1"
            else:
                offer_id, original_url = existing["id"], existing["offer_url"]
            conn.commit()

        cpi.store_observation(
            1,
            {"id": "p", "title": "Serum", "store": "myntra.com", "price": 569,
             "currency": "INR",
             "productPageUrl": "https://www.priceinindia.website/products/serum"},
            _comparable_match(),
            db_path=fresh_seeded_db,
        )
        with get_connection(fresh_seeded_db) as conn:
            after = conn.execute(
                "SELECT offer_url FROM offers WHERE id = ?", (offer_id,)
            ).fetchone()
        # The provider page URL must NOT overwrite the existing retailer URL,
        # and no new retailer URL is invented.
        assert after["offer_url"] == original_url


# ── 6. Missing size stays POSSIBLE / NEEDS_MANUAL_REVIEW ─────────────────────

class TestMissingSizeNeverVerified:
    CATALOG = {
        "brand": "Minimalist",
        "title": "Minimalist 10% Niacinamide Serum",
        "specs": {"Net Quantity": "30 ml"},
    }

    def _offer_like_provider(self, title="Niacinamide Face Serum by Minimalist"):
        return {
            "brand": "minimalist",
            "title": title,
            "store": "myntra.com",
            "specs": {},  # no quantity anywhere — provider titles omit size
        }

    def test_missing_size_is_possible_match_never_verified(self):
        r = evaluate_product_match(
            target_brand=self.CATALOG["brand"],
            target_title=self.CATALOG["title"],
            target_specs=self.CATALOG["specs"],
            offer_brand=self._offer_like_provider()["brand"],
            offer_title=self._offer_like_provider()["title"],
            offer_specs=self._offer_like_provider()["specs"],
        )
        assert r.offer_size is None
        assert r.match_classification in (
            MatchClassification.POSSIBLE_MATCH,
            MatchClassification.AMBIGUOUS_MATCH,
        )
        assert r.match_strength in (MatchStrength.POSSIBLE, MatchStrength.NEEDS_MANUAL_REVIEW)
        assert r.match_strength not in (MatchStrength.EXACT, MatchStrength.STRONG)

    def test_pi_path_missing_size_requires_human_review(self):
        r = cpi.match_pi_result_to_product(
            self._offer_like_provider(), self.CATALOG,
        )
        assert r.match_classification == MatchClassification.POSSIBLE_MATCH
        assert r.match_strength == MatchStrength.POSSIBLE
        assert r.requires_human_review is True

    def test_guard_downgrades_verified_result_missing_size(self):
        """Belt-and-braces guard: even a barcode-verified evaluation with a
        missing provider size is downgraded to POSSIBLE with review."""
        # Build a verified evaluation manually (GTIN evidence bypasses the
        # quantity quality gate) and run it through the PI matcher's guard.
        verified = evaluate_product_match(
            target_brand=self.CATALOG["brand"],
            target_title=self.CATALOG["title"],
            target_specs=self.CATALOG["specs"],
            offer_brand="minimalist",
            offer_title=self._offer_like_provider()["title"],
            offer_specs=self._offer_like_provider()["specs"],
            target_barcode="8901234567890",
            offer_barcode="8901234567890",
        )
        assert verified.gtin_matched is True
        assert verified.match_classification == MatchClassification.VERIFIED_MATCH

        guarded = cpi.enforce_missing_size_identity_guard(verified)
        assert guarded.match_classification == MatchClassification.POSSIBLE_MATCH
        assert guarded.match_strength == MatchStrength.POSSIBLE
        assert guarded.requires_human_review is True
        assert any(
            "missing size" in str(x).lower() for x in guarded.reasons
        )

    def test_missing_size_can_never_reach_exact(self):
        r = evaluate_product_match(
            target_brand=self.CATALOG["brand"],
            target_title=self.CATALOG["title"],
            target_specs=self.CATALOG["specs"],
            offer_brand="Minimalist",
            offer_title="Minimalist 10% Niacinamide Serum",
            offer_specs={},
        )
        assert r.offer_size is None
        assert r.match_strength != MatchStrength.EXACT


# ── Eligibility: provider page URL cannot satisfy the purchase-link rule ─────

class TestEligibilityProviderPageUrl:
    def _observation(self, match_result: str) -> dict:
        return {
            "observed_price": 569.0,
            "currency": "INR",
            "observation_status": "live",
            "verification_status": "provider_observed",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "product_url": "https://www.priceinindia.website/products/serum",
            "match_result": match_result,
        }

    def test_provider_page_url_excluded_from_rankings(self):
        evidence = json.dumps({
            "classification": "verified_match",
            "url_kind": "provider_page",
        })
        eligible, reasons = cos.evaluate_eligibility(self._observation(evidence))
        assert not eligible
        assert "url_is_provider_page" in reasons

    def test_explicit_retailer_url_eligible(self):
        evidence = json.dumps({
            "classification": "verified_match",
            "url_kind": "retailer",
        })
        obs = self._observation(evidence)
        obs["product_url"] = "https://www.myntra.com/serum/1234"
        eligible, reasons = cos.evaluate_eligibility(obs)
        assert eligible, reasons

    def test_legacy_rows_without_url_kind_unaffected(self):
        """Backward compatibility: evidence recorded before 16.7C has no
        url_kind and keeps its previous eligibility behaviour."""
        evidence = json.dumps({"classification": "verified_match"})
        obs = self._observation(evidence)
        obs["product_url"] = "https://www.nykaa.com/serum/1234"
        eligible, reasons = cos.evaluate_eligibility(obs)
        assert eligible, reasons


# ── helpers ──────────────────────────────────────────────────────────────────

def _comparable_match():
    return cpi.ProductMatchResult(
        match_classification="possible_match",
        confidence_score=0.6,
        is_comparable=True,
        brand_match=True,
        size_match=True,
        shade_match=True,
        formulation_match=True,
        title_similarity=0.8,
        match_strength="possible",
    )
