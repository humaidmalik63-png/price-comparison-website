"""Phase 16.7 — Live Price Coverage, Matching Strength, Trust & Validation Tests.

Covers the Phase 16.7 additions with deterministic, mocked inputs only:

- Stage 1: exact/strong/possible/rejected/needs-manual strength overlay,
  brand-alias registry, g-vs-ml unit-label tolerance, explainability contract
- Stage 2: PI search-query normalisation, variant/size extraction from titles
- Stage 3: price/currency validation, duplicate + supersede handling,
  provider error classification, MCP/SSE response parsing (malformed inputs)
- Stage 4: match-review context (side-by-side) and audit trail
- Stage 5: cheapest-offer quantity comparability guard + comparison scope
- Stage 6: coverage-audit Phase 16.7 metrics accuracy
- Stage 7: frontend trust-label mapping (deterministic unit tests of the util)
- Browser/MCP boundaries: the browser-investigation artifact is checked
  (file-level only — no test depends on a live Chrome session or a live site)

None of these tests call the PriceInIndia provider, any retailer website, or
a live Chrome session. All provider/browser behaviour is mocked.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from starlette.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]

from src.api import main
from src.adapters.mcp_adapters.base_mcp_adapter import BaseMcpAdapter, McpCallResult
from src.adapters.mcp_adapters.priceinindia_adapter import normalize_search_query
from src.database.connection import get_connection
from src.scripts import collect_pi_observations as cpi
from src.scripts import coverage_audit as ca
from src.services import cheapest_offer_service as cos
from src.services import match_review_service as mrs
from src.services.freshness_service import (
    FreshnessPolicy,
    classify_freshness,
    observation_age_hours,
)
from src.services.product_matching_service import (
    MatchClassification,
    MatchEvidenceTier,
    MatchStrength,
    compute_unit_price,
    evaluate_product_match,
    parse_quantity_volume,
)


# ── Stage 1: matching strength overlay ──────────────────────────────────────

class TestMatchStrengthOverlay:
    def test_barcode_evidence_yields_exact(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen SPF 50+ PA++++ (50 g)",
            offer_brand="Dot & Key",
            offer_title="Watermelon Cooling Sunscreen SPF 50+ PA++++ 50 g",
            target_barcode="8901234567890",
            offer_barcode="890-1234567890",
        )
        assert r.match_classification == MatchClassification.VERIFIED_MATCH
        assert r.match_strength == MatchStrength.EXACT
        assert r.evidence_tier == MatchEvidenceTier.BARCODE_GTIN_EXACT

    def test_verified_without_barcode_is_strong_not_exact(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen SPF 50 (50 g)",
            offer_brand="Dot & Key",
            offer_title="Watermelon Cooling Sunscreen SPF 50 (50 g)",
        )
        assert r.match_classification == MatchClassification.VERIFIED_MATCH
        assert r.match_strength == MatchStrength.STRONG
        assert any("not exact" in s for s in r.strength_reasons)

    def test_different_brand_is_rejected(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (50 g)",
            offer_brand="Mamaearth",
            offer_title="Watermelon Cooling Sunscreen (50 g)",
        )
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert r.match_strength == MatchStrength.REJECTED

    def test_brand_alias_match_is_flagged_and_capped_at_strong(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (50 g)",
            offer_brand="Dot and Key",
            offer_title="Watermelon Cooling Sunscreen (50 g)",
        )
        assert r.match_classification == MatchClassification.VERIFIED_MATCH
        assert r.brand_alias_applied is True
        assert r.match_strength == MatchStrength.STRONG
        assert any("alias" in s.lower() for s in r.flagged_reasons)

    def test_alias_with_unregistered_brand_string_is_rejected(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (50 g)",
            offer_brand="Totally Different Brand",
            offer_title="Watermelon Cooling Sunscreen (50 g)",
        )
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH

    def test_shade_mismatch_is_rejected(self):
        r = evaluate_product_match(
            target_brand="Lakme",
            target_title="9to5 Lipstick Ruby Woo (3.8g)",
            offer_brand="Lakme",
            offer_title="9to5 Lipstick Velvet Teddy (3.8g)",
        )
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert not r.shade_match

    def test_size_mismatch_is_rejected(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (30 g)",
            offer_brand="Dot & Key",
            offer_title="Watermelon Cooling Sunscreen (50 g)",
        )
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert not r.size_match

    def test_formulation_mismatch_is_rejected(self):
        r = evaluate_product_match(
            target_brand="Nykaa Cosmetics",
            target_title="Matte Lipstick Cream (4g)",
            offer_brand="Nykaa Cosmetics",
            offer_title="Matte Lipstick Gel (4g)",
        )
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert not r.formulation_match

    def test_g_vs_ml_equal_quantity_is_tolerated_but_never_exact(self):
        """Observed retailer labelling inconsistency: same SKU labelled 50ml on
        Nykaa and 50g on Myntra/Purplle/Amazon (Phase 16.7 browser evidence)."""
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (50 g)",
            target_specs={"Net Quantity": "50 g"},
            offer_brand="Dot & Key",
            offer_title="Watermelon Cooling Sunscreen SPF 50 (50 ml)",
            offer_specs={"Net Quantity": "50 ml"},
        )
        assert r.match_classification == MatchClassification.VERIFIED_MATCH
        assert r.size_match is True
        assert r.unit_label_tolerance is True
        assert r.match_strength == MatchStrength.STRONG
        assert any("unit-label-conflict" in s for s in r.flagged_reasons)

    def test_g_vs_ml_different_quantity_still_rejected(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (30 g)",
            target_specs={"Net Quantity": "30 g"},
            offer_brand="Dot & Key",
            offer_title="Watermelon Cooling Sunscreen (50 ml)",
            offer_specs={"Net Quantity": "50 ml"},
        )
        assert r.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH

    def test_missing_size_lowers_confidence_and_needs_review(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (50 g)",
            offer_brand="Dot & Key",
            offer_title="Dot & Key Sunscreen SPF 50 PA++++",
        )
        assert r.match_classification in (
            MatchClassification.POSSIBLE_MATCH,
            MatchClassification.AMBIGUOUS_MATCH,
        )
        assert r.confidence_score < 1.0
        if r.match_classification == MatchClassification.AMBIGUOUS_MATCH:
            assert r.match_strength == MatchStrength.NEEDS_MANUAL_REVIEW
            assert r.requires_human_review is True

    def test_explain_contract_is_complete(self):
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen (50 g)",
            offer_brand="Dot & Key",
            offer_title="Watermelon Cooling Sunscreen (50 g)",
        )
        d = r.explain()
        for key in (
            "classification", "match_strength", "confidence_score",
            "evidence_tier", "reasons", "flagged_reasons", "strength_reasons",
            "brand_alias_applied", "unit_label_tolerance",
        ):
            assert key in d

    def test_confidence_alone_never_creates_exact(self):
        """A high similarity score without identity evidence must stay strong."""
        r = evaluate_product_match(
            target_brand="Dot & Key",
            target_title="Watermelon Cooling Sunscreen SPF 50+ PA++++ In-Vivo Tested 50 g",
            offer_brand="Dot & Key",
            offer_title="Watermelon Cooling Sunscreen SPF 50+ PA++++ In-Vivo Tested 50 g",
        )
        assert r.title_similarity >= 0.99
        assert r.match_strength == MatchStrength.STRONG  # no barcode evidence

    def test_unit_price_computation(self):
        assert compute_unit_price(387.0, 50.0, "g") == pytest.approx(7.74)
        assert compute_unit_price(445.0, 50.0, "ml") == pytest.approx(8.9)
        assert compute_unit_price(None, 50.0, "g") is None
        assert compute_unit_price(100.0, None, "g") is None
        assert compute_unit_price(-5.0, 50.0, "g") is None

    def test_parse_quantity_variants(self):
        assert parse_quantity_volume("50 ml") == (50.0, "ml")
        assert parse_quantity_volume("100gm") == (100.0, "g")
        assert parse_quantity_volume("3.8g") == (3.8, "g")
        assert parse_quantity_volume("no size") == (None, None)


# ── Stage 2: query normalisation + size extraction ──────────────────────────

class TestStage2ProviderImprovements:
    def test_search_query_normalisation(self):
        assert normalize_search_query("Dot   &   Key   Watermelon") == "Dot & Key Watermelon"
        assert normalize_search_query("Brand | Product,,SPF 50") == "Brand Product SPF 50"
        assert normalize_search_query("  ") == ""

    def test_size_extraction_from_title(self):
        assert cpi.extract_size_from_title("Dot & Key Watermelon Sunscreen 50g") == "50g"
        assert cpi.extract_size_from_title("Mini Highlighter 9 g") == "9g"
        # pack configuration: rightmost quantity wins
        assert cpi.extract_size_from_title("Sunscreen 2 x 100 ml combo") == "100ml"
        assert cpi.extract_size_from_title("No size here") is None
        assert cpi.extract_size_from_title("") is None

    def test_normalize_item_extracts_size_from_title_with_flag(self):
        n = cpi.normalize_pi_item({
            "title": "Dot & Key Watermelon Sunscreen SPF 50 50 g",
            "store": "nykaa.com",
            "price": "₹387",
            "currency": "INR",
        })
        assert n["size"] == "50g"
        assert n["size_source"] == "title_extracted"
        assert "size_from_title" in n["flags"]

    def test_normalize_item_prefers_structured_size_field(self):
        n = cpi.normalize_pi_item({
            "title": "Some Sunscreen",
            "store": "nykaa.com",
            "price": "₹387",
            "currency": "INR",
            "size": "80 ml",
        })
        assert n["size"] == "80 ml"
        assert n["size_source"] == "provider_field"
        assert "size_from_title" not in n["flags"]

    def test_normalize_item_missing_size_stays_none(self):
        n = cpi.normalize_pi_item({
            "title": "Unnamed Sunscreen",
            "store": "nykaa.com",
            "price": 100,
            "currency": "INR",
        })
        assert n["size"] is None
        assert n["size_source"] is None


# ── Stage 3: observation validation ─────────────────────────────────────────

class TestStage3Validation:
    def test_missing_price_rejected(self):
        n = cpi.normalize_pi_item({"title": "X", "store": "s", "price": None, "currency": "INR"})
        assert n["rejection_reason"] == "invalid_price"

    def test_invalid_price_rejected(self):
        n = cpi.normalize_pi_item({"title": "X", "store": "s", "price": "N/A", "currency": "INR"})
        assert n["rejection_reason"] == "invalid_price"

    def test_missing_currency_rejected(self):
        n = cpi.normalize_pi_item({"title": "X", "store": "s", "price": 100, "currency": None})
        assert n["rejection_reason"] == "currency_missing"

    def test_unsupported_currency_rejected_not_converted(self):
        n = cpi.normalize_pi_item({"title": "X", "store": "s", "price": 100, "currency": "USD"})
        assert n["rejection_reason"] == "unsupported_currency"

    def test_price_above_mrp_flagged(self):
        n = cpi.normalize_pi_item({
            "title": "X", "store": "s", "price": 500, "mrp": 445, "currency": "INR",
        })
        assert "price_above_mrp" in n["flags"]

    def test_parse_price_never_invents(self):
        assert cpi.parse_price(None) is None
        assert cpi.parse_price("") is None
        assert cpi.parse_price("₹1,299") == 1299.0
        assert cpi.parse_price("Rs. 1,299.50") == 1299.5
        assert cpi.parse_price("abc") is None
        assert cpi.parse_price(True) is None  # bool is not a price

    def test_provider_error_classification(self):
        assert cpi.classify_provider_error(
            McpCallResult(success=False, tool_name="t", error_message="rate limit exceeded")
        ) == "rate_limit"
        assert cpi.classify_provider_error(
            McpCallResult(success=False, tool_name="t", error_message="Request timed out")
        ) == "timeout"
        assert cpi.classify_provider_error(
            McpCallResult(success=False, tool_name="t", error_message="HTTP 502")
        ) == "http_error"
        assert cpi.classify_provider_error(
            McpCallResult(success=False, tool_name="t", error_message="Unparseable MCP response")
        ) == "malformed_response"
        assert cpi.classify_provider_error(
            McpCallResult(success=False, tool_name="t", error_message="request error: network down")
        ) == "network_error"
        assert cpi.classify_provider_error(
            McpCallResult(success=False, tool_name="t", error_message="provider exploded")
        ) == "provider_error"

    def test_duplicate_observation_superseded(self, fresh_seeded_db, monkeypatch):
        """Same product+retailer re-observation supersedes the old live row;
        the old row is retained (history never deleted)."""
        monkeypatch.setattr(cpi, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))
        with get_connection(fresh_seeded_db) as conn:
            pid = conn.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1").fetchone()["id"]

        item = {"title": "Watermelon Sunscreen 50 g", "store": "nykaa.com",
                "price": 387, "mrp": 445, "currency": "INR",
                "productPageUrl": "https://www.nykaa.com/p/14072071"}
        match = evaluate_product_match(
            target_brand="Dot & Key", target_title="Watermelon Cooling Sunscreen (50 g)",
            offer_brand="Dot & Key", offer_title="Watermelon Sunscreen 50 g",
        )
        r1 = cpi.store_observation(pid, item, match, db_path=fresh_seeded_db)
        assert r1["status"] == "stored"
        r2 = cpi.store_observation(pid, item, match, db_path=fresh_seeded_db)
        assert r2["status"] == "stored"
        with get_connection(fresh_seeded_db) as conn:
            rows = conn.execute(
                "SELECT observation_status, COUNT(*) c FROM retail_price_observation "
                "WHERE product_id = ? GROUP BY observation_status",
                (pid,),
            ).fetchall()
            by_status = {r["observation_status"]: r["c"] for r in rows}
            total = conn.execute(
                "SELECT COUNT(*) c FROM retail_price_observation WHERE product_id = ?",
                (pid,),
            ).fetchone()["c"]
        assert by_status.get("live") == 1
        assert by_status.get("superseded", 0) >= 1
        assert total >= 2  # history retained

    def test_non_comparable_match_stored_flagged_never_syncs_offer(self, fresh_seeded_db, monkeypatch):
        monkeypatch.setattr(cpi, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))
        with get_connection(fresh_seeded_db) as conn:
            pid = conn.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1").fetchone()["id"]
            offers_before = conn.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"]
        item = {"title": "Different Brand Sunscreen 50 g", "store": "nykaa.com",
                "price": 300, "currency": "INR"}
        match = evaluate_product_match(
            target_brand="Dot & Key", target_title="Watermelon Cooling Sunscreen (50 g)",
            offer_brand="Different Brand", offer_title="Different Brand Sunscreen 50 g",
        )
        assert match.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        r = cpi.store_observation(pid, item, match, db_path=fresh_seeded_db)
        assert r["status"] == "stored"
        with get_connection(fresh_seeded_db) as conn:
            obs = conn.execute(
                "SELECT observation_status FROM retail_price_observation WHERE product_id = ?",
                (pid,),
            ).fetchone()
            offers_after = conn.execute("SELECT COUNT(*) c FROM offers").fetchone()["c"]
        assert obs["observation_status"] == "flagged"
        assert offers_after == offers_before  # offers untouched

    def test_stale_observations_excluded_from_current_rankings(self):
        policy = FreshnessPolicy(fresh_hours=1, aging_hours=2)
        now = datetime.now(timezone.utc)
        old = (now - timedelta(hours=10)).isoformat()
        age = observation_age_hours(old, now=now)
        assert classify_freshness(age, policy) == "stale"
        eligible, reasons = cos.evaluate_eligibility(
            {
                "observed_price": 387.0,
                "currency": "INR",
                "observation_status": "live",
                "verification_status": "provider_observed",
                "created_at": old,
                "product_url": "https://www.nykaa.com/x",
                "match_result": json.dumps({"classification": "verified_match"}),
            },
            policy=policy,
            now=now,
        )
        assert not eligible
        assert "stale" in reasons

    def test_unknown_age_cannot_be_claimed_stale(self):
        ok, reasons = cos.evaluate_eligibility(
            {
                "observed_price": 387.0,
                "currency": "INR",
                "observation_status": "live",
                "verification_status": "verified",
                "created_at": None,
                "product_url": "https://www.nykaa.com/x",
                "match_result": json.dumps({"classification": "verified_match"}),
            },
        )
        assert ok is True
        assert "stale" not in reasons


# ── MCP/SSE response parsing (mocked payloads, no network) ──────────────────

class _NoopAdapter(BaseMcpAdapter):
    def __init__(self):
        super().__init__(
            name="test", mcp_endpoint="http://localhost/mcp",
            timeout_seconds=1, max_retries=0, rate_limit_per_minute=1000,
        )


class TestMcpSseParsing:
    def _parse(self, text, status=200):
        return _NoopAdapter()._parse_response(text, status, 1.0)

    def test_malformed_response_is_reported_not_faked(self):
        r = self._parse("<<<not json at all>>>")
        assert r.success is False
        assert "Unparseable" in (r.error_message or "")

    def test_direct_json_payload_parsed(self):
        payload = json.dumps({
            "result": {
                "structuredContent": {
                    "products": [{"id": "1", "title": "Sunscreen", "price": 387,
                                  "currency": "INR", "store": "nykaa.com"}]
                }
            }
        })
        r = self._parse(payload)
        assert r.success is True
        assert len(r.items) == 1
        assert r.items[0]["title"] == "Sunscreen"

    def test_sse_stream_parsed(self):
        sse = (
            'data: {"jsonrpc":"2.0","result":{"structuredContent":'
            '{"products":[{"id":"2","title":"Serum","price":549,"currency":"INR",'
            '"store":"purplle.com"}]}}}\n\n'
        )
        r = self._parse(sse)
        assert r.success is True
        assert r.items and r.items[0]["title"] == "Serum"

    def test_sse_with_corrupt_lines_skips_them(self):
        sse = (
            "data: not-json\n\n"
            "data: {\"broken\": true\n\n"
            "data: {\"plain\": \"event\"}\n\n"
        )
        r = self._parse(sse)
        assert r.success is True
        assert r.items == [{"plain": "event"}]

    def test_empty_sse_fails_honestly(self):
        r = self._parse("event: ping\n\n")
        assert r.success is False
        assert "Unparseable" in (r.error_message or "")


# ── Stage 4: match review context + audit trail ─────────────────────────────

def _seed_review_obs(db, pid):
    evidence = {
        "classification": "possible_match",
        "confidence": 0.6,
        "evidence_tier": "brand_and_size",
        "reasons": ["Close match with minor descriptive differences"],
        "flagged_reasons": ["Net quantity missing on one or both sides"],
        "requires_human_review": True,
        "brand_match": True,
        "size_match": True,
        "title_similarity": 0.62,
        "target_size": "50g",
        "offer_size": None,
        "target_shade": None,
        "offer_shade": None,
        "provider_title": "PI Listing Title 50 g",
        "provider_brand": "dot & key",
        "retailer": "nykaa.com",
    }
    ts = datetime.now(timezone.utc).isoformat()
    with get_connection(db) as conn:
        cur = conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observed_mrp, currency,
             provider_name, size_volume, observation_type, observation_status,
             verified_by_admin, verification_status, created_at, updated_at,
             evidence_notes, evidence_reference, match_result)
            VALUES (?, 'nykaa.com', 'https://www.nykaa.com/p/1', 387.0, 445.0, 'INR',
                    'priceinindia', '50g', 'live', 'flagged', 0, 'pending', ?, ?, ?, ?, ?)
            """,
            (pid, ts, ts, "PI match: possible_match", "ref_1", json.dumps(evidence)),
        )
        return cur.lastrowid


class TestMatchReviewStage4:
    def test_review_context_side_by_side(self, fresh_seeded_db):
        with get_connection(fresh_seeded_db) as conn:
            pid = conn.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1").fetchone()["id"]
        obs_id = _seed_review_obs(fresh_seeded_db, pid)
        ctx = mrs.get_match_review_context(obs_id, db_path=fresh_seeded_db)
        assert ctx["catalogue_product"]["id"] == pid
        assert ctx["observation"]["retailer"] == "nykaa.com"
        assert ctx["match_evidence"]["provider_title"] == "PI Listing Title 50 g"
        fields = {c["field"] for c in ctx["comparison"]}
        assert {"brand", "title", "size", "price", "retailer_url"} <= fields
        assert ctx["decision_contract"]["approval_does_not"]

    def test_resolve_creates_audit_trail(self, fresh_seeded_db):
        with get_connection(fresh_seeded_db) as conn:
            pid = conn.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1").fetchone()["id"]
        obs_id = _seed_review_obs(fresh_seeded_db, pid)
        updated = mrs.resolve_pending_match(
            obs_id, "approve", admin_user_id=None,
            note="Confirmed identical SKU on retailer PDP", db_path=fresh_seeded_db,
        )
        assert updated["verification_status"] == "verified"
        assert updated["verified_by_admin"] == 1
        with get_connection(fresh_seeded_db) as conn:
            row = conn.execute(
                "SELECT verification_notes, match_result FROM retail_price_observation WHERE id = ?",
                (obs_id,),
            ).fetchone()
        assert "review:approve" in row["verification_notes"]
        assert "Confirmed identical SKU" in row["verification_notes"]
        # Approval does not fabricate evidence: stored match_result is untouched
        assert json.loads(row["match_result"])["classification"] == "possible_match"

    def test_reject_flags_but_retains_history(self, fresh_seeded_db):
        with get_connection(fresh_seeded_db) as conn:
            pid = conn.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1").fetchone()["id"]
        obs_id = _seed_review_obs(fresh_seeded_db, pid)
        updated = mrs.resolve_pending_match(
            obs_id, "reject", admin_user_id=1, note="Wrong size", db_path=fresh_seeded_db,
        )
        assert updated["observation_status"] == "flagged"
        with get_connection(fresh_seeded_db) as conn:
            row = conn.execute(
                "SELECT observation_status, verification_notes FROM retail_price_observation WHERE id = ?",
                (obs_id,),
            ).fetchone()
        assert row["observation_status"] == "flagged"
        assert "Wrong size" in row["verification_notes"]

    def test_invalid_decision_rejected(self, fresh_seeded_db):
        with pytest.raises(ValueError):
            mrs.resolve_pending_match(1, "maybe", db_path=fresh_seeded_db)

    def test_context_404_honest(self, fresh_seeded_db):
        with pytest.raises(LookupError):
            mrs.get_match_review_context(999999, db_path=fresh_seeded_db)


# ── Stage 5: cheapest-offer quantity guard ──────────────────────────────────

class TestCheapestOfferStage5:
    def test_quantities_comparable_rules(self):
        assert cos.quantities_comparable((50.0, "g"), (50.0, "g")) is True
        assert cos.quantities_comparable((50.0, "g"), (50.0, "ml")) is True  # tolerance
        assert cos.quantities_comparable((30.0, "g"), (50.0, "g")) is False
        assert cos.quantities_comparable((50.0, "g"), (50.0, "oz")) is False
        assert cos.quantities_comparable((None, None), (50.0, "g")) is None

    def test_rank_compatible_offers_excludes_incompatible(self):
        offers = [
            {"retailer": "A", "price": 387.0, "size_volume": "50 g"},
            {"retailer": "B", "price": 300.0, "size_volume": "30 g"},  # cheaper but different qty
            {"retailer": "C", "price": 399.0, "size_volume": "50 g"},
        ]
        ranked, excluded, disclosure = cos.rank_compatible_offers(offers)
        assert [o["retailer"] for o in ranked] == ["A", "C"]
        assert [o["retailer"] for o in excluded] == ["B"]
        assert disclosure["quantity_guard_excluded_count"] == 1

    def test_cheapest_comparison_scope_disclosure(self, fresh_seeded_db, monkeypatch):
        monkeypatch.setattr(cos, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))
        with get_connection(fresh_seeded_db) as conn:
            pid = conn.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1").fetchone()["id"]
            # Two eligible same-size offers + one different-size admin-approved offer
            for retailer, price, size in (("Nykaa", 387.0, "50 g"), ("Purplle", 399.0, "50 g")):
                conn.execute(
                    """
                    INSERT INTO retail_price_observation
                    (product_id, retailer, product_url, observed_price, observed_mrp, currency,
                     provider_name, size_volume, observation_type, observation_status,
                     verified_by_admin, verification_status, created_at, updated_at,
                     evidence_notes, match_result)
                    VALUES (?, ?, 'https://x.example/p', ?, 445.0, 'INR', 'priceinindia',
                            ?, 'live', 'live', 1, 'provider_observed', ?, ?, 'e', ?)
                    """,
                    (pid, retailer, price, size,
                     datetime.now(timezone.utc).isoformat(),
                     datetime.now(timezone.utc).isoformat(),
                     json.dumps({"classification": "verified_match"})),
                )
            conn.execute(
                """
                INSERT INTO retail_price_observation
                (product_id, retailer, product_url, observed_price, observed_mrp, currency,
                 provider_name, size_volume, observation_type, observation_status,
                 verified_by_admin, verification_status, created_at, updated_at,
                 evidence_notes, match_result)
                VALUES (?, 'Myntra', 'https://x.example/m', 300.0, 445.0, 'INR', 'priceinindia',
                        '30 g', 'live', 'live', 1, 'verified', ?, ?, 'e', ?)
                """,
                (pid, datetime.now(timezone.utc).isoformat(),
                 datetime.now(timezone.utc).isoformat(),
                 json.dumps({"classification": "possible_match"})),
            )
        cheapest = cos.get_cheapest_eligible(pid, db_path=fresh_seeded_db)
        assert cheapest is not None
        assert cheapest["price"] == 387.0  # the 300 different-qty offer must not win
        scope = cheapest["comparison_scope"]
        assert scope["retailers_with_eligible_offer"] == 3
        assert scope["retailers_ranked"] == 2
        assert scope["retailers_excluded_by_quantity"] == 1
        assert scope["excluded_by_quantity"][0]["retailer"] == "Myntra"
        assert "cheapest observed" in scope["claim"]

    def test_no_eligible_offers_returns_none(self, fresh_seeded_db, monkeypatch):
        monkeypatch.setattr(cos, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))
        with get_connection(fresh_seeded_db) as conn:
            pid = conn.execute("SELECT id FROM products WHERE is_active = 1 LIMIT 1").fetchone()["id"]
        assert cos.get_cheapest_eligible(pid, db_path=fresh_seeded_db) is None


# ── Stage 6: coverage audit metrics ─────────────────────────────────────────

class TestCoverageAuditStage6:
    def test_phase17_metrics_accuracy(self, fresh_seeded_db):
        # Beauty-only catalogue: the audit excludes legacy electronics demos.
        pids = [p["id"] for p in cpi.load_discovery_catalog(db_path=fresh_seeded_db, limit=3)]
        assert len(pids) == 3
        with get_connection(fresh_seeded_db) as conn:
            now = datetime.now(timezone.utc)
            old = (now - timedelta(hours=200)).isoformat()
            # Product 1: fresh verified observation -> 1 usable offer
            conn.execute(
                """
                INSERT INTO retail_price_observation
                (product_id, retailer, product_url, observed_price, currency,
                 provider_name, observation_status, verification_status,
                 created_at, updated_at, evidence_notes, match_result)
                VALUES (?, 'Nykaa', 'https://x.example/n', 387.0, 'INR', 'priceinindia',
                        'live', 'provider_observed', ?, ?, 'e', ?)
                """,
                (pids[0], now.isoformat(), now.isoformat(),
                 json.dumps({"classification": "verified_match", "match_strength": "strong"})),
            )
            # Product 2: rejected match only
            conn.execute(
                """
                INSERT INTO retail_price_observation
                (product_id, retailer, product_url, observed_price, currency,
                 provider_name, observation_status, verification_status,
                 created_at, updated_at, evidence_notes, match_result)
                VALUES (?, 'Myntra', 'https://x.example/m', 300.0, 'INR', 'priceinindia',
                        'flagged', 'pending', ?, ?, 'e', ?)
                """,
                (pids[1], now.isoformat(), now.isoformat(),
                 json.dumps({"classification": "incompatible_mismatch"})),
            )
            # Product 3: stale-only observation
            conn.execute(
                """
                INSERT INTO retail_price_observation
                (product_id, retailer, product_url, observed_price, currency,
                 provider_name, observation_status, verification_status,
                 created_at, updated_at, evidence_notes, match_result)
                VALUES (?, 'Purplle', 'https://x.example/p', 387.0, 'INR', 'priceinindia',
                        'live', 'provider_observed', ?, ?, 'e', ?)
                """,
                (pids[2], old, old,
                 json.dumps({"classification": "verified_match", "match_strength": "strong"})),
            )

        report = ca.audit_database(fresh_seeded_db)
        by_id = {p["id"]: p for p in report["products"]}
        assert by_id[pids[0]]["strong_matches"] == 1
        assert by_id[pids[0]]["verified_usable_offers"] == 1
        assert by_id[pids[0]]["coverage_unavailable_reason"] is None
        assert by_id[pids[1]]["rejected_matches"] == 1
        assert by_id[pids[1]]["verified_usable_offers"] == 0
        assert by_id[pids[1]]["coverage_unavailable_reason"] == "all_matches_rejected"
        assert by_id[pids[2]]["stale_observations"] == 1
        assert by_id[pids[2]]["fresh_observations"] == 0
        assert by_id[pids[2]]["coverage_unavailable_reason"] == "stale_observations_only"

        m = report["phase16_7_metrics"]
        assert m["total_exact_matches"] + m["total_strong_matches"] + \
            m["total_possible_matches"] + m["total_rejected_matches"] >= 3
        assert m["exact_match_rate"] is not None or m["verified_match_rate"] is not None
        assert m["rejection_rate"] is not None
        assert m["total_stale_observations"] >= 1
        assert m["total_verified_usable_offers"] >= 1
        assert m["provider_failure_rate"] is None  # honest: not computable offline
        # Product with no observations reports honestly
        no_obs = [p for p in report["products"] if p["observations_count"] == 0]
        assert all(p["coverage_unavailable_reason"] == "no_observations" for p in no_obs)


# ── Stage 7: frontend trust labels ──────────────────────────────────────────
# The frontend has no test runner configured; the trust-label mapping's
# behavioural correctness is enforced by `tsc -b && vite build` (type-checked
# build) and oxlint. Here we enforce the honest-mapping *contract* of the
# util file itself: all required statuses exist, expiry takes precedence, and
# no code path fabricates a "verified" claim from demo/unverified inputs.

class TestTrustLabels:
    @pytest.fixture
    def trust_source(self):
        path = REPO_ROOT / "frontend" / "src" / "utils" / "trustLabels.ts"
        return path.read_text(encoding="utf-8")

    def test_all_required_statuses_present(self, trust_source):
        for key in (
            "verified_live", "provider_observed", "manual_verified",
            "demo", "expired", "unverified",
        ):
            assert f"{key}:" in trust_source

    def test_expired_takes_precedence(self, trust_source):
        # The expiry check must appear before demo/manual/provider checks.
        expired_pos = trust_source.index("observationStatus === 'expired'")
        demo_pos = trust_source.index("sourceType === 'demo'")
        assert expired_pos < demo_pos

    def test_awaiting_verification_is_labelled_honestly(self, trust_source):
        assert "Awaiting Verification" in trust_source

    def test_no_fabricated_live_verification(self, trust_source):
        # A provider-observed status must never map straight to verified_live.
        assert "verified_live" in trust_source
        src_block = trust_source[trust_source.index("export function getTrustLabel"):]
        assert src_block.count("LABELS.verified_live") == 1  # only for sourceType verified_live

    def test_demo_never_labelled_live(self, trust_source):
        assert "not a real retailer price" in trust_source


# ── Chrome MCP integration boundaries (file-level, no live browser) ─────────

class TestBrowserInvestigationArtifact:
    """The Phase 16.7 browser investigation artifact must exist, must document
    the real retailers investigated, and must not claim CAPTCHA bypasses or
    unverified automated permissions. These checks read the artifact file only
    — no test depends on a live Chrome session or a live retailer site."""

    @pytest.fixture
    def artifact(self):
        return (REPO_ROOT / "PHASE_16_7_BROWSER_INVESTIGATION.md").read_text(encoding="utf-8")

    def test_artifact_exists_with_required_table(self, artifact):
        assert "| Retailer | Browser accessible | Search works | Price visible |" in artifact
        assert "| Nykaa |" in artifact
        assert "| Myntra |" in artifact
        assert "| Purplle |" in artifact
        assert "| Tira |" in artifact
        assert "| Amazon India |" in artifact

    def test_no_captcha_bypass_or_stealth_claims(self, artifact):
        # Phrases that would indicate a performed bypass/stealth action.
        # (Honest statements like "none were bypassed" are fine and expected.)
        forbidden = [
            "captcha-solving", "stealth mode enabled", "proxy rotation used",
            "bypassed captcha", "circumvented the", "solved the captcha",
        ]
        low = artifact.lower()
        for token in forbidden:
            assert token not in low, f"artifact must not claim '{token}'"
        # The honest non-bypass statement must be present.
        assert "none were bypassed" in low

    def test_restrictions_recorded_honestly(self, artifact):
        assert "NOT VERIFIED" in artifact  # Myntra robots.txt
        assert "not found" in artifact.lower()  # Tira negative finding
        assert "listing" in artifact.lower()  # evidence-type distinction

    def test_untested_fields_marked_not_tested(self, artifact):
        assert "NOT TESTED" in artifact


# ── Stage 4/8: admin API authorization + audit trail via HTTP ───────────────

@pytest.fixture
def api_db(monkeypatch, fresh_seeded_db):
    monkeypatch.setattr(
        main, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    monkeypatch.setattr(
        mrs, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    monkeypatch.setattr(
        cos, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    return fresh_seeded_db


@pytest.fixture
def admin_client17(api_db):
    from types import SimpleNamespace
    main.app.dependency_overrides[main.get_current_user] = lambda: SimpleNamespace(
        id=1, email="admin@pricewise.test", display_name="Admin"
    )
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
def anon_client17(api_db):
    return TestClient(main.app)


class TestAdminMatchReviewAPI:
    def test_queue_requires_authentication(self, anon_client17):
        r = anon_client17.get("/api/admin/match-review-queue")
        assert r.status_code in (401, 403)

    def test_resolve_requires_authentication(self, anon_client17):
        r = anon_client17.post(
            "/api/admin/match-review/1/resolve",
            json={"decision": "approve"},
        )
        assert r.status_code in (401, 403)

    def test_admin_can_list_queue(self, admin_client17, api_db):
        with get_connection(api_db) as conn:
            pid = conn.execute(
                "SELECT id FROM products WHERE is_active = 1 LIMIT 1"
            ).fetchone()["id"]
        _seed_review_obs(api_db, pid)
        r = admin_client17.get("/api/admin/match-review-queue")
        assert r.status_code == 200
        body = r.json()
        assert body["total"] >= 1
        item = body["items"][0]
        assert item["match_evidence"]["provider_title"] == "PI Listing Title 50 g"

    def test_admin_resolve_approve_updates_status(self, admin_client17, api_db):
        with get_connection(api_db) as conn:
            pid = conn.execute(
                "SELECT id FROM products WHERE is_active = 1 LIMIT 1"
            ).fetchone()["id"]
        obs_id = _seed_review_obs(api_db, pid)
        r = admin_client17.post(
            f"/api/admin/match-review/{obs_id}/resolve",
            json={"decision": "approve", "note": "PDP-verified identity"},
        )
        assert r.status_code == 200
        assert r.json()["resolved"] is True
        assert r.json()["observation"]["verification_status"] == "verified"
        with get_connection(api_db) as conn:
            row = conn.execute(
                "SELECT verification_notes FROM retail_price_observation WHERE id = ?",
                (obs_id,),
            ).fetchone()
        assert "PDP-verified identity" in row["verification_notes"]

    def test_admin_resolve_reject_flags_observation(self, admin_client17, api_db):
        with get_connection(api_db) as conn:
            pid = conn.execute(
                "SELECT id FROM products WHERE is_active = 1 LIMIT 1"
            ).fetchone()["id"]
        obs_id = _seed_review_obs(api_db, pid)
        r = admin_client17.post(
            f"/api/admin/match-review/{obs_id}/resolve",
            json={"decision": "reject", "note": "different SKU size"},
        )
        assert r.status_code == 200
        assert r.json()["observation"]["observation_status"] == "flagged"

    def test_invalid_decision_is_422(self, admin_client17, api_db):
        r = admin_client17.post(
            "/api/admin/match-review/1/resolve",
            json={"decision": "perhaps"},
        )
        assert r.status_code == 422

    def test_unknown_observation_is_404(self, admin_client17, api_db):
        r = admin_client17.post(
            "/api/admin/match-review/999999/resolve",
            json={"decision": "approve"},
        )
        assert r.status_code == 404

    def test_context_endpoint_requires_authentication(self, anon_client17):
        r = anon_client17.get("/api/admin/match-review/1/context")
        assert r.status_code in (401, 403)

    def test_context_endpoint_serves_side_by_side(self, admin_client17, api_db):
        with get_connection(api_db) as conn:
            pid = conn.execute(
                "SELECT id FROM products WHERE is_active = 1 LIMIT 1"
            ).fetchone()["id"]
        obs_id = _seed_review_obs(api_db, pid)
        r = admin_client17.get(f"/api/admin/match-review/{obs_id}/context")
        assert r.status_code == 200
        body = r.json()
        assert body["catalogue_product"]["id"] == pid
        assert body["observation"]["id"] == obs_id
        assert any(c["field"] == "brand" for c in body["comparison"])
        assert body["audit_trail"]["verified_by_admin"] is False

    def test_context_endpoint_unknown_obs_is_404(self, admin_client17, api_db):
        r = admin_client17.get("/api/admin/match-review/999999/context")
        assert r.status_code == 404
