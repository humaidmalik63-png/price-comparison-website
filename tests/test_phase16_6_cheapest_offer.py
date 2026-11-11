"""Phase 16.6 Stage 6 tests: cheapest-offer eligibility and deal intelligence.

Covers:

- demo prices never participate in live cheapest rankings
- rejected / ambiguous / unreviewed matches are excluded
- invalid prices, unsupported and missing currencies are excluded
- stale prices excluded from current rankings per freshness policy
- superseded / expired / flagged rows excluded from current rankings
- retailer URL required (or optionally not) for eligibility
- admin-approved possible matches become eligible
- unit price normalisation (INR per g/ml) only with comparable quantities
- discounts computed only from a real provider MRP
- input assumptions are disclosed with results
- catalog-wide pagination and honest absence of products without offers
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.database.connection import get_connection
from src.services import cheapest_offer_service as cos
from src.services.cheapest_offer_service import (
    ASSUMPTIONS,
    evaluate_eligibility,
    get_catalog_cheapest_eligible,
    get_cheapest_eligible,
    get_eligible_offers,
    get_excluded_offers,
)
from src.services.freshness_service import FreshnessPolicy


@pytest.fixture
def svc_db(monkeypatch, fresh_seeded_db):
    monkeypatch.setattr(cos, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))
    return fresh_seeded_db


def _pid(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        return row["id"]


def _insert_obs(db, pid, *, retailer="Nykaa", price=465.0, currency="INR",
                status="live", verification="provider_observed",
                created_at=None, url="https://www.nykaa.com/x", size="50g",
                match_classification="possible_match", mrp=None,
                verified_by_admin=0):
    evidence = {
        "classification": match_classification,
        "confidence": 0.7,
        "requires_human_review": match_classification == "possible_match",
    }
    ts = created_at or datetime.now(timezone.utc).isoformat()
    with get_connection(db) as conn:
        cursor = conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observed_mrp, currency,
             provider_name, size_volume, observation_type, observation_status,
             verified_by_admin, verification_status, created_at, updated_at,
             evidence_notes, match_result)
            VALUES (?, ?, ?, ?, ?, ?, 'priceinindia', ?, 'live', ?, ?, ?, ?, ?,
                    'test evidence', ?)
            """,
            (
                pid, retailer, url, price, mrp, currency, size, status,
                verified_by_admin, verification, ts, ts,
                __import__("json").dumps(evidence),
            ),
        )
        return cursor.lastrowid


def _now():
    return datetime.now(timezone.utc)


# ── Demo exclusion ───────────────────────────────────────────────────────────

def test_demo_prices_never_win_live_rankings(svc_db):
    """Product has only demo offers — no eligible offer exists at all."""
    product_id = _pid(svc_db)
    assert get_cheapest_eligible(product_id) is None


def test_provider_observed_beats_nothing_but_stands_alone(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, price=465.0, match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest is not None
    assert cheapest["price"] == 465.0
    assert cheapest["source_attribution"]
    assert cheapest["provider_name"] == "priceinindia"


# ── Match-based exclusion ────────────────────────────────────────────────────

def test_unreviewed_possible_match_excluded(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, match_classification="possible_match",
                verification="provider_observed", verified_by_admin=0)
    assert get_cheapest_eligible(product_id) is None
    excluded = get_excluded_offers(product_id)
    assert any("match_unverified" in r["exclusion_reasons"] for r in excluded)


def test_ambiguous_and_incompatible_excluded(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, retailer="Tira",
                match_classification="ambiguous_match")
    _insert_obs(svc_db, product_id, retailer="mynt.ra",
                match_classification="incompatible_mismatch")
    assert get_cheapest_eligible(product_id) is None
    reasons = [r for e in get_excluded_offers(product_id) for r in e["exclusion_reasons"]]
    assert reasons.count("match_rejected") == 2


def test_verified_match_eligible(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest is not None
    assert cheapest["eligibility_basis"] == "verified_match"


def test_admin_approved_possible_match_eligible(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, match_classification="possible_match",
                verification="verified", verified_by_admin=1)
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest is not None
    assert cheapest["eligibility_basis"] == "admin_verified"
    assert cheapest["verified_by_admin"] is True


# ── Price and currency validation ────────────────────────────────────────────

def test_invalid_price_excluded(svc_db):
    # The schema CHECK blocks non-positive prices at storage time; the
    # eligibility gate must also reject them (defense in depth).
    for price in (0.0, -5.0, None, "abc"):
        ok, reasons = evaluate_eligibility(
            {
                "observed_price": price,
                "currency": "INR",
                "observation_status": "live",
                "verification_status": "provider_observed",
                "created_at": _now().isoformat(),
                "product_url": "https://www.nykaa.com/x",
                "match_result": '{"classification": "verified_match"}',
            },
            require_url=True,
        )
        assert ok is False
        assert "invalid_price" in reasons


@pytest.mark.parametrize("currency", ["USD", "EUR", None])
def test_unsupported_or_missing_currency_excluded(svc_db, currency):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, currency=currency,
                match_classification="verified_match")
    assert get_cheapest_eligible(product_id) is None


# ── Freshness and lifecycle ──────────────────────────────────────────────────

def test_stale_price_excluded_from_current_ranking(svc_db):
    product_id = _pid(svc_db)
    old = (_now() - timedelta(hours=100)).isoformat()
    _insert_obs(svc_db, product_id, created_at=old, match_classification="verified_match")

    assert get_cheapest_eligible(product_id) is None
    excluded = get_excluded_offers(product_id)
    assert any("stale" in r["exclusion_reasons"] for r in excluded)

    # Under a wider policy the same observation participates (its age is
    # still disclosed honestly).
    wide = FreshnessPolicy(fresh_hours=24, aging_hours=168)
    cheapest = get_cheapest_eligible(product_id, policy=wide)
    assert cheapest is not None
    assert cheapest["freshness"] == "aging"
    assert cheapest["observed_age_hours"] > 99


def test_superseded_and_expired_never_rank(svc_db):
    product_id = _pid(svc_db)
    now = _now()
    _insert_obs(svc_db, product_id, retailer="Tira", price=300.0, status="superseded",
                created_at=(now - timedelta(hours=1)).isoformat(),
                match_classification="verified_match")
    _insert_obs(svc_db, product_id, retailer="mynt.ra", price=310.0, status="expired",
                created_at=(now - timedelta(hours=1)).isoformat(),
                match_classification="verified_match")
    assert get_cheapest_eligible(product_id) is None
    reasons = [r for e in get_excluded_offers(product_id) for r in e["exclusion_reasons"]]
    assert reasons.count("not_current") == 2


# ── Retailer URL requirement ────────────────────────────────────────────────

def test_missing_url_excluded_when_purchase_link_required(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, url="", match_classification="verified_match")
    assert get_cheapest_eligible(product_id, require_url=True) is None
    cheapest = get_cheapest_eligible(product_id, require_url=False)
    assert cheapest is not None
    assert cheapest["retailer_url"] == ""


def test_non_http_url_flagged_invalid(svc_db):
    ok, reasons = evaluate_eligibility(
        {
            "observed_price": 100.0,
            "currency": "INR",
            "observation_status": "live",
            "verification_status": "provider_observed",
            "created_at": _now().isoformat(),
            "product_url": "javascript:alert(1)",
            "match_result": '{"classification": "verified_match"}',
        },
        require_url=True,
    )
    assert ok is False
    assert "invalid_retailer_url" in reasons


# ── Unit price normalisation ────────────────────────────────────────────────

def test_unit_price_computed_from_size_volume(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, price=500.0, size="50 g",
                match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest["unit_price"] == 10.0   # 500 / 50 g
    assert cheapest["unit"] == "g"


def test_unit_price_absent_without_quantity(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, price=500.0, size=None,
                match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest["unit_price"] is None
    assert cheapest["unit"] is None


def test_incompatible_units_not_compared(svc_db):
    """ml and g rows keep their own unit prices; ranking never mixes them."""
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, retailer="Nykaa", price=500.0, size="50 ml",
                match_classification="verified_match")
    _insert_obs(svc_db, product_id, retailer="Tira", price=400.0, size="100 g",
                match_classification="verified_match")
    offers = get_eligible_offers(product_id)
    by_retailer = {o["retailer"]: o for o in offers}
    assert by_retailer["Nykaa"]["unit_price"] == 10.0 and by_retailer["Nykaa"]["unit"] == "ml"
    assert by_retailer["Tira"]["unit_price"] == 4.0 and by_retailer["Tira"]["unit"] == "g"
    # cheapest is by absolute price with unit disclosure, not a mixed-unit race
    assert get_cheapest_eligible(product_id)["retailer"] == "Tira"


# ── Discounts ────────────────────────────────────────────────────────────────

def test_discount_only_from_real_mrp(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, price=400.0, mrp=500.0,
                match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest["discount_pct"] == 20.0


def test_no_mrp_means_no_invented_discount(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, price=400.0, mrp=None,
                match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest["discount_pct"] is None


# ── Disclosure ───────────────────────────────────────────────────────────────

def test_assumptions_disclosed_with_result(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest["assumptions"] == ASSUMPTIONS
    assert any("INR" in a for a in cheapest["assumptions"])
    assert any("stale" in a.lower() for a in cheapest["assumptions"])


def test_freshness_and_age_reported(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id,
                created_at=(_now() - timedelta(hours=30)).isoformat(),
                match_classification="verified_match")
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest["freshness"] == "aging"
    assert 29.9 < cheapest["observed_age_hours"] < 30.5


# ── Catalog-wide ────────────────────────────────────────────────────────────

def test_catalog_pagination_and_honest_absence(svc_db):
    product_id = _pid(svc_db)
    _insert_obs(svc_db, product_id, match_classification="verified_match")

    result = get_catalog_cheapest_eligible(limit=50)
    assert result["total_products"] >= 1
    assert result["products_with_eligible_offers"] == 1
    ids = [item["product_id"] for item in result["items"]]
    assert ids == [product_id]  # everyone else honestly absent
    assert result["assumptions"] == ASSUMPTIONS

    with pytest.raises(ValueError):
        get_catalog_cheapest_eligible(limit=0)
    with pytest.raises(ValueError):
        get_catalog_cheapest_eligible(limit=1000)


def test_multiple_retailers_cheapest_wins_per_latest_observation(svc_db):
    product_id = _pid(svc_db)
    now = _now()
    _insert_obs(svc_db, product_id, retailer="Nykaa", price=465.0,
                match_classification="verified_match",
                created_at=(now - timedelta(hours=2)).isoformat())
    _insert_obs(svc_db, product_id, retailer="Tira", price=439.0,
                match_classification="verified_match",
                created_at=(now - timedelta(hours=3)).isoformat())
    cheapest = get_cheapest_eligible(product_id)
    assert cheapest["retailer"] == "Tira"
    assert cheapest["price"] == 439.0
