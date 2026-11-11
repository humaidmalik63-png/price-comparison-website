"""Phase 16.7B — PriceInIndia Provider Investigation Mocked Tests.

Stage 8 of the safe-provider investigation plan. These tests document and
verify — with mocked data only — how the existing PriceInIndia adapter and
observation-validation pipeline behaves for the exact edge cases the
investigation plan enumerates (missing fields, duplicates, wrong size/brand/
variant, stale provider metadata, citation-link preference).

Overlaps with existing suites are intentionally NOT duplicated here; the
investigation report records which existing tests already cover which case.
Cases that the CURRENT implementation does not handle (e.g. provider
``outOfStock`` / ``lastUpdated`` fields are ignored) are tested against
current behaviour and explicitly labelled as known limitations — they must
not silently disappear in a future change.

None of these tests call the PriceInIndia provider or any retailer website,
and none of them touch a database.
"""

from src.scripts import collect_pi_observations as cpi
from src.adapters.mcp_adapters.priceinindia_adapter import normalize_search_query
from src.services.product_matching_service import (
    MatchClassification,
    MatchStrength,
    evaluate_product_match,
)


# ── Missing-field validation (Stage 6 rules) ─────────────────────────────────

class TestMissingFieldValidation:
    def test_missing_retailer_rejected(self):
        """A result without a retailer must never be accepted as a verified
        retailer offer (plan Stage 6)."""
        n = cpi.normalize_pi_item({
            "title": "Minimalist 10% Niacinamide Serum 30 ml",
            "price": 549,
            "currency": "INR",
        })
        assert n["rejection_reason"] == "missing_retailer"

    def test_missing_product_url_flagged_not_rejected(self):
        """A missing URL is flagged for honesty but the item itself is not
        silently confirmed as a verified offer (Stage 3 rule 7)."""
        n = cpi.normalize_pi_item({
            "title": "Pharmacis Sunscreen SPF 50+ Gel Cream 30 ml",
            "store": "nykaa.com",
            "price": 465,
            "currency": "INR",
        })
        assert n["rejection_reason"] is None
        assert "missing_product_url" in n["flags"]
        assert n["url"] == ""

    def test_citation_url_preferred_over_affiliate_redirect(self):
        """Provider docs: ``productPageUrl`` is the citation link, while
        ``productUrl`` is an affiliate redirect. The normaliser must prefer
        the citation URL when both are present."""
        n = cpi.normalize_pi_item({
            "title": "Kay Beauty Matte Lipstick - Reconstruct",
            "store": "nykaa.com",
            "price": 645,
            "currency": "INR",
            "productUrl": "https://affiliate.example/redirect?id=1",
            "productPageUrl": "https://www.nykaa.com/kay-beauty-lipstick/p/1002",
        })
        assert n["url"] == "https://www.nykaa.com/kay-beauty-lipstick/p/1002"


# ── Duplicate results within one provider response ───────────────────────────

class TestDuplicateResults:
    def test_identical_items_share_dedupe_key(self):
        base = {
            "title": "Minimalist 10% Niacinamide Serum 30 ml",
            "store": "nykaa.com",
            "price": 549,
            "currency": "INR",
            "productPageUrl": "https://www.nykaa.com/minimalist-niacinamide/p/1003",
        }
        a = cpi.normalize_pi_item(dict(base))
        b = cpi.normalize_pi_item(dict(base))
        assert a["dedupe_key"] == b["dedupe_key"]

    def test_different_retailer_or_price_changes_dedupe_key(self):
        base = {
            "title": "Minimalist 10% Niacinamide Serum 30 ml",
            "price": 549,
            "currency": "INR",
            "productPageUrl": "https://www.nykaa.com/minimalist-niacinamide/p/1003",
        }
        nykaa = cpi.normalize_pi_item({**base, "store": "nykaa.com"})
        amazon = cpi.normalize_pi_item({**base, "store": "amazon.in"})
        cheaper = cpi.normalize_pi_item({**base, "store": "nykaa.com", "price": 539})
        assert nykaa["dedupe_key"] != amazon["dedupe_key"]
        assert nykaa["dedupe_key"] != cheaper["dedupe_key"]


# ── Wrong size / wrong brand / incorrect variant (Stage 6 classification) ────

class TestVariantMismatchClassification:
    CATALOG_SUNSCREEN = {
        "brand": "Pharmacis",
        "title": "Pharmacis Sunscreen SPF 50+ Gel Cream",
        "specs": {"Product Type": "Gel Cream Sunscreen", "Net Quantity": "30 ml", "SPF": "50+"},
    }
    CATALOG_LIPSTICK = {
        "brand": "Kay Beauty",
        "title": "Kay Beauty Matte Lipstick - Reconstruct",
        "specs": {"Product Type": "Bullet Lipstick", "Net Quantity": "3.5 g", "Shade": "Reconstruct"},
    }

    def test_wrong_size_is_not_compared(self):
        """Same product line, different size (30 ml vs 50 ml) is an identity
        conflict — never treated as an identical SKU (plan Stage 6)."""
        r = evaluate_product_match(
            target_brand=self.CATALOG_SUNSCREEN["brand"],
            target_title=self.CATALOG_SUNSCREEN["title"],
            target_specs=self.CATALOG_SUNSCREEN["specs"],
            offer_brand="Pharmacis",
            offer_title="Pharmacis Sunscreen SPF 50+ Gel Cream 50 ml",
            offer_specs={},
        )
        assert r.size_match is False
        assert r.is_comparable is False
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert r.match_strength == MatchStrength.REJECTED

    def test_wrong_brand_rejected(self):
        r = evaluate_product_match(
            target_brand=self.CATALOG_SUNSCREEN["brand"],
            target_title=self.CATALOG_SUNSCREEN["title"],
            target_specs=self.CATALOG_SUNSCREEN["specs"],
            offer_brand="Maybelline",
            offer_title="Pharmacis Sunscreen SPF 50+ Gel Cream 30 ml",
            offer_specs={},
        )
        assert r.brand_match is False
        assert r.is_comparable is False
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert r.match_strength == MatchStrength.REJECTED

    def test_incorrect_shade_is_not_compared(self):
        """A different recognised shade is a different SKU; the offer must be
        rejected rather than compared at unit-price level. (An offer shade
        the matcher does NOT recognise is treated honestly as
        `possible_match` + 'unconfirmed shade' — a separate, softer rule.)"""
        r = evaluate_product_match(
            target_brand=self.CATALOG_LIPSTICK["brand"],
            target_title=self.CATALOG_LIPSTICK["title"],
            target_specs=self.CATALOG_LIPSTICK["specs"],
            offer_brand="Kay Beauty",
            offer_title="Kay Beauty Matte Lipstick - Velvet Teddy",
            offer_specs={},
        )
        assert r.shade_match is False
        assert r.is_comparable is False
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert r.match_strength == MatchStrength.REJECTED

    def test_unrecognised_shade_stays_possible_but_flagged(self):
        """Honesty rule: an unrecognised shade name is not confirmed as a
        mismatch, but the item can never count as a verified offer."""
        r = evaluate_product_match(
            target_brand=self.CATALOG_LIPSTICK["brand"],
            target_title=self.CATALOG_LIPSTICK["title"],
            target_specs=self.CATALOG_LIPSTICK["specs"],
            offer_brand="Kay Beauty",
            offer_title="Kay Beauty Matte Lipstick - Blossom",
            offer_specs={},
        )
        assert r.shade_match is True
        assert r.match_classification == MatchClassification.POSSIBLE_MATCH
        assert r.match_strength == MatchStrength.POSSIBLE
        assert any(
            "shade" in str(x).lower() and "not found" in str(x).lower()
            for x in r.flagged_reasons
        )


# ── Stale provider metadata (current-behaviour limitation) ───────────────────

class TestStaleProviderMetadataCurrentBehaviour:
    def test_out_of_stock_and_last_updated_are_not_currently_used(self):
        """KNOWN LIMITATION (recorded in the investigation report): the
        provider exposes ``outOfStock`` and ``lastUpdated`` (unix seconds),
        but ``normalize_pi_item`` does not consume either field. An
        out-of-stock result is therefore NOT rejected or flagged today.

        This test documents that current behaviour honestly. If the
        implementation later starts honouring these fields, this test must
        be updated deliberately — not deleted.
        """
        n = cpi.normalize_pi_item({
            "title": "Minimalist 10% Niacinamide Serum 30 ml",
            "store": "nykaa.com",
            "price": 549,
            "currency": "INR",
            "productPageUrl": "https://www.nykaa.com/minimalist-niacinamide/p/1003",
            "outOfStock": True,
            "lastUpdated": 1600000000,  # Sept 2020 — very stale
        })
        assert n["rejection_reason"] is None
        assert "out_of_stock" not in n["flags"]
        assert "stale_last_updated" not in n["flags"]


# ── Planned Stage 5 queries are derived from real catalogue records ──────────

class TestPlannedQueriesFromCatalogue:
    """The exact three queries presented for approval, built with the
    production ``build_search_query`` from real catalogue records (no
    invented products)."""

    PHARMACIS = {
        "title": "Pharmacis Sunscreen SPF 50+ Gel Cream",
        "brand": "Pharmacis",
        "specs": {"Net Quantity": "30 ml"},
    }
    MINIMALIST = {
        "title": "Minimalist 10% Niacinamide Serum",
        "brand": "Minimalist",
        "specs": {"Net Quantity": "30 ml"},
    }
    KAY_BEAUTY = {
        "title": "Kay Beauty Matte Lipstick - Reconstruct",
        "brand": "Kay Beauty",
        "specs": {"Net Quantity": "3.5 g"},
    }

    def test_query_length_within_provider_schema(self):
        """Provider schema: query must be 2–200 chars."""
        for product in (self.PHARMACIS, self.MINIMALIST, self.KAY_BEAUTY):
            q = normalize_search_query(cpi.build_search_query(product))
            assert 2 <= len(q) <= 200, q

    def test_brand_and_size_present_exactly_once(self):
        q = normalize_search_query(cpi.build_search_query(self.PHARMACIS))
        assert q.lower().count("pharmacis") == 1
        assert q.count("30 ml") == 1

    def test_normalisation_is_stable(self):
        """The same catalogue record must always produce the identical
        provider query (restartability / dedup requirement)."""
        for product in (self.PHARMACIS, self.MINIMALIST, self.KAY_BEAUTY):
            first = normalize_search_query(cpi.build_search_query(product))
            second = normalize_search_query(cpi.build_search_query(product))
            assert first == second
