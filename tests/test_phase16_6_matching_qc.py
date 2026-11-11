"""Phase 16.6 Stage 3 tests: product matching quality control + review path.

Covers the Stage 3 rules on top of the stabilized matching service:

- exact / wrong-brand / wrong-product / shade / formulation /
  concentration / size classification behaviour (hard-conflict rules
  must remain exactly as stabilized)
- missing quantity recorded as unknown, never silently confirmed
- ambiguous matches routed to review, never auto-promoted
- enriched match evidence persisted with observations
- a rejected candidate must not overwrite an existing valid offer
- missing provider URLs are flagged
- manual review queue: listing, approve, reject, pagination
- approved/rejected observations never delete history

The matching service is imported and used as-is — these tests also guard
that Phase 16.6 changes did not weaken it.
"""

import json

import pytest

from src.database.connection import get_connection
from src.scripts import collect_pi_observations as collector
from src.services.match_review_service import (
    list_pending_matches,
    resolve_pending_match,
)
from src.services.product_matching_service import (
    MatchClassification,
    evaluate_product_match,
)


def _catalog(**overrides):
    product = {
        "id": 1,
        "sku": "TEST-1",
        "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++",
        "brand": "Dot & Key",
        "category": "Skincare",
        "specs": {"Net Quantity": "50g", "Product Type": "Gel Sunscreen"},
    }
    product.update(overrides)
    return product


def _offer(**overrides):
    item = {
        "id": "pi-1",
        "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
        "brand": "Dot & Key",
        "price": 465.0,
        "store": "Nykaa",
        "productPageUrl": "https://www.nykaa.com/dot-key-watermelon/p/1001",
        "size": "50g",
    }
    item.update(overrides)
    return item


def _comparable_match():
    return collector.match_pi_result_to_product(_offer(), _catalog())


# ── Matching classification (hard-conflict rules unchanged) ──────────────────

def test_exact_match_is_verified():
    result = evaluate_product_match(
        target_brand="Dot & Key",
        target_title="Watermelon Cooling Sunscreen SPF 50+ 50g",
        target_specs={"Net Quantity": "50g"},
        offer_brand="Dot & Key",
        offer_title="Watermelon Cooling Sunscreen SPF 50+ 50g",
        offer_specs={"Net Quantity": "50g"},
    )
    assert result.match_classification == MatchClassification.VERIFIED_MATCH
    assert result.is_comparable is True
    assert result.size_match and result.shade_match and result.formulation_match


def test_wrong_product_same_brand_is_not_comparable():
    result = evaluate_product_match(
        target_brand="Minimalist",
        target_title="Minimalist Niacinamide 10% Face Serum 30ml",
        target_specs={"Net Quantity": "30ml"},
        offer_brand="Minimalist",
        offer_title="Minimalist Salicylic Acid 2% Face Wash 100ml",
        offer_specs={"Net Quantity": "100ml"},
    )
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
    assert result.is_comparable is False
    assert result.concentration_match is False
    assert result.size_match is False


def test_wrong_brand_alone_is_insufficient():
    result = evaluate_product_match(
        target_brand="Dot & Key",
        target_title="Dot & Key Watermelon Cooling Sunscreen SPF 50+ 50g",
        target_specs={"Net Quantity": "50g"},
        offer_brand="The Derma Co",
        offer_title="Dot & Key Watermelon Cooling Sunscreen SPF 50+ 50g",
        offer_specs={"Net Quantity": "50g"},
    )
    # Offer title contains the target brand text but the stated offer brand
    # differs: brand conflict is a hard mismatch.
    assert result.brand_match is False
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH


def test_wrong_size_rejected():
    result = evaluate_product_match(
        target_brand="Dot & Key",
        target_title="Watermelon Cooling Sunscreen SPF 50+",
        target_specs={"Net Quantity": "50g"},
        offer_brand="Dot & Key",
        offer_title="Watermelon Cooling Sunscreen SPF 50+ 30g",
        offer_specs={"Net Quantity": "30g"},
    )
    assert result.is_comparable is False
    assert result.size_match is False


def test_wrong_shade_rejected():
    result = evaluate_product_match(
        target_brand="M.A.C",
        target_title="M.A.C Retro Matte Lipstick - Ruby Woo 3g",
        target_specs={"Shade": "Ruby Woo", "Net Quantity": "3g"},
        offer_brand="M.A.C",
        offer_title="M.A.C Retro Matte Lipstick - Velvet Teddy 3g",
        offer_specs={"Shade": "Velvet Teddy", "Net Quantity": "3g"},
    )
    assert result.is_comparable is False
    assert result.shade_match is False


def test_wrong_formulation_rejected():
    result = evaluate_product_match(
        target_brand="Maybelline",
        target_title="Maybelline Lash Sensational Sky High Waterproof Mascara 7.2ml",
        target_specs={"Formulation": "Waterproof", "Net Quantity": "7.2ml"},
        offer_brand="Maybelline",
        offer_title="Maybelline Lash Sensational Sky High Washable Mascara 7.2ml",
        offer_specs={"Formulation": "Washable", "Net Quantity": "7.2ml"},
    )
    assert result.is_comparable is False
    assert result.formulation_match is False


def test_wrong_concentration_rejected():
    result = evaluate_product_match(
        target_brand="Minimalist",
        target_title="Minimalist Niacinamide 10% Serum 30ml",
        target_specs={"Net Quantity": "30ml"},
        offer_brand="Minimalist",
        offer_title="Minimalist Niacinamide 5% Serum 30ml",
        offer_specs={"Net Quantity": "30ml"},
    )
    assert result.is_comparable is False
    assert result.concentration_match is False


def test_missing_quantity_is_recorded_unknown_not_confirmed():
    """Missing quantity must surface as unknown — never silently confirmed."""
    result = evaluate_product_match(
        target_brand="Dot & Key",
        target_title="Watermelon Cooling Sunscreen SPF 50+",
        target_specs={"Net Quantity": "50g"},
        offer_brand="Dot & Key",
        offer_title="Watermelon Cooling Sunscreen SPF 50+",
        offer_specs={},
    )
    assert result.offer_size is None  # unknown is recorded, not fabricated
    assert any("Quantity not detected" in f for f in result.flagged_reasons)


def test_ambiguous_match_requires_human_review_and_is_not_comparable():
    result = evaluate_product_match(
        target_brand="Dot & Key",
        target_title="Dot & Key Watermelon Cooling Sunscreen SPF 50+ 50g",
        target_specs={"Net Quantity": "50g"},
        offer_brand="Dot & Key",
        offer_title="Dot & Key Ceramides Barrier Repair Face Moisturizer 50g",
        offer_specs={"Net Quantity": "50g"},
    )
    assert result.match_classification == MatchClassification.AMBIGUOUS_MATCH
    assert result.is_comparable is False
    assert result.requires_human_review is True


def test_pi_leniency_never_promotes_to_verified():
    """The PI leniency override may only produce possible_match, never
    verified_match — verified identity requires the full matching service."""
    result = collector.match_pi_result_to_product(_offer(), _catalog())
    assert result.match_classification == MatchClassification.POSSIBLE_MATCH
    assert result.requires_human_review is True
    assert result.confidence_score <= 0.75


# ── Observation quality control ──────────────────────────────────────────────

def _offer_row(db, product_id):
    with get_connection(db) as conn:
        return conn.execute(
            """
            SELECT o.current_price, o.offer_url FROM offers o
            JOIN stores s ON s.id = o.store_id
            WHERE o.product_id = ? AND s.name LIKE 'Nykaa%'
            """,
            (product_id,),
        ).fetchone()


def test_rejected_candidate_does_not_overwrite_valid_offer(fresh_seeded_db):
    """Stage 3 rule 9: flagged observations must never sync the offers table."""
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]

    # 1. Valid comparable observation syncs the offer.
    collector.store_observation(pid, _offer(price=465.0), _comparable_match(), db_path=fresh_seeded_db)
    assert _offer_row(fresh_seeded_db, pid)["current_price"] == 465.0

    # 2. A non-comparable candidate (size conflict) must NOT overwrite it.
    mismatch = evaluate_product_match(
        target_brand="Dot & Key",
        target_title="Watermelon Cooling Sunscreen SPF 50+",
        target_specs={"Net Quantity": "50g"},
        offer_brand="Dot & Key",
        offer_title="Watermelon Cooling Sunscreen SPF 30 30g",
        offer_specs={"Net Quantity": "30g"},
    )
    assert mismatch.is_comparable is False
    result = collector.store_observation(
        pid, _offer(price=199.0, size="30g"), mismatch, db_path=fresh_seeded_db
    )
    assert result["status"] == "stored"
    assert _offer_row(fresh_seeded_db, pid)["current_price"] == 465.0  # untouched


def test_missing_provider_url_flagged_in_evidence(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    result = collector.store_observation(
        pid, _offer(productPageUrl=""), _comparable_match(), db_path=fresh_seeded_db
    )
    assert result["status"] == "stored"
    with get_connection(fresh_seeded_db) as conn:
        row = conn.execute(
            "SELECT evidence_notes, product_url FROM retail_price_observation "
            "WHERE product_id = ? ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
    assert row["product_url"] == ""
    assert "provider_product_url_missing" in row["evidence_notes"]


def test_match_evidence_enriched_and_persisted(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    collector.store_observation(
        pid, _offer(size=""), _comparable_match(), db_path=fresh_seeded_db
    )
    with get_connection(fresh_seeded_db) as conn:
        raw = conn.execute(
            "SELECT match_result FROM retail_price_observation "
            "WHERE product_id = ? ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()["match_result"]
    evidence = json.loads(raw)
    for key in (
        "classification", "confidence", "evidence_tier", "reasons",
        "flagged_reasons", "requires_human_review", "brand_match",
        "size_match", "shade_match", "formulation_match",
        "concentration_match", "title_similarity", "target_size",
        "offer_size", "retailer", "provider_item_id",
    ):
        assert key in evidence, f"match evidence must persist '{key}'"
    assert evidence["provider_item_id"] == "pi-1"
    assert evidence["retailer"] == "Nykaa"


# ── Manual review path ───────────────────────────────────────────────────────

def _insert_uncertain(db, pid, price=263.0, retailer="myntra.com", classification="possible_match"):
    match = collector.match_pi_result_to_product(
        _offer(store=retailer, price=price),
        _catalog(),
    )
    return collector.store_observation(pid, _offer(store=retailer, price=price), match, db_path=db)


def test_review_queue_lists_uncertain_matches(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    _insert_uncertain(fresh_seeded_db, pid)

    queue = list_pending_matches(db_path=fresh_seeded_db)
    assert queue["total"] >= 1
    row = next(r for r in queue["items"] if r["product_id"] == pid)
    assert row["match_evidence"]["classification"] == "possible_match"
    assert row["verification_status"] == "provider_observed"
    assert row["product_title"]


def _admin_user(db) -> int:
    with get_connection(db) as conn:
        row = conn.execute(
            "INSERT INTO users (display_name, email, password_hash) VALUES ('Admin Q', 'review-q@test.local', 'x') "
            "RETURNING id"
        ).fetchone()
        # RETURNING requires SQLite 3.35+; fall back if needed
        if row is None:
            row = conn.execute(
                "SELECT id FROM users WHERE email = 'review-q@test.local'"
            ).fetchone()
        return row["id"]


def test_review_queue_excludes_verified_matches(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    admin = _admin_user(fresh_seeded_db)
    obs = _insert_uncertain(fresh_seeded_db, pid)
    resolve_pending_match(obs["observation"]["id"], "approve", admin_user_id=admin, db_path=fresh_seeded_db)

    queue = list_pending_matches(db_path=fresh_seeded_db)
    assert all(r["id"] != obs["observation"]["id"] for r in queue["items"])


def test_review_approval_marks_verified_and_live(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    admin = _admin_user(fresh_seeded_db)
    obs = _insert_uncertain(fresh_seeded_db, pid)

    updated = resolve_pending_match(
        obs["observation"]["id"], "approve", admin_user_id=admin, note="checked on retailer site",
        db_path=fresh_seeded_db,
    )
    assert updated["observation_status"] == "live"
    assert updated["verification_status"] == "verified"
    assert updated["verified_by_admin"] == 1
    assert "review:approve" in updated["verification_notes"]
    # History retained: the row still exists.
    with get_connection(fresh_seeded_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM retail_price_observation WHERE id = ?",
            (obs["observation"]["id"],),
        ).fetchone()[0]
    assert count == 1


def test_review_rejection_flags_and_excludes(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    admin = _admin_user(fresh_seeded_db)
    obs = _insert_uncertain(fresh_seeded_db, pid)

    updated = resolve_pending_match(
        obs["observation"]["id"], "reject", admin_user_id=admin, db_path=fresh_seeded_db
    )
    assert updated["observation_status"] == "flagged"
    assert updated["verification_status"] == "review_required"
    assert "review:reject" in updated["verification_notes"]


def test_review_reject_invalid_decision(fresh_seeded_db):
    with pytest.raises(ValueError):
        resolve_pending_match(1, "maybe", db_path=fresh_seeded_db)


def test_review_queue_pagination(fresh_seeded_db):
    with pytest.raises(ValueError):
        list_pending_matches(limit=0, db_path=fresh_seeded_db)
    with pytest.raises(ValueError):
        list_pending_matches(limit=500, db_path=fresh_seeded_db)
    page = list_pending_matches(limit=1, offset=0, db_path=fresh_seeded_db)
    assert page["limit"] == 1 and len(page["items"]) <= 1


def test_review_queue_missing_observation(fresh_seeded_db):
    with pytest.raises(LookupError):
        resolve_pending_match(999999, "approve", db_path=fresh_seeded_db)
