"""Phase 16.5.2 regression tests for live price observation storage.

Covers the PriceInIndia observation collector:

- observation creation with full provenance
- retailer-specific superseding (same product + same retailer only)
- independence between retailers
- history retention after superseding
- duplicate collection never leaves two live rows
- invalid prices are rejected rather than fabricated
- missing URLs never crash and never wipe an existing offer URL

All database operations target an isolated, freshly seeded temporary database.
"""

from types import SimpleNamespace

import pytest

from src.database.connection import get_connection
from src.scripts import collect_pi_observations as collector
from src.services.product_matching_service import (
    MatchClassification,
    ProductMatchResult,
    evaluate_product_match,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch, fresh_seeded_db):
    monkeypatch.setattr(
        collector, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    return fresh_seeded_db


@pytest.fixture
def product_id(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE title LIKE '%Watermelon Cooling Sunscreen%' "
            "ORDER BY id LIMIT 1"
        ).fetchone()
    assert row is not None, "seeded database must contain the sunscreen product"
    return row["id"]


def _comparable_match() -> ProductMatchResult:
    return ProductMatchResult(
        match_classification=MatchClassification.POSSIBLE_MATCH,
        confidence_score=0.75,
        is_comparable=True,
        brand_match=True,
        size_match=True,
        shade_match=True,
        formulation_match=True,
        title_similarity=0.95,
        reasons=["Brand and title match"],
        requires_human_review=True,
    )


def _pi_item(
    store: str = "Nykaa",
    price: float = 465.0,
    item_id: str = "pi-1001",
    url: str = "https://www.nykaa.com/dot-key-watermelon/p/1001",
    size: str = "50g",
) -> dict:
    return {
        "id": item_id,
        "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
        "brand": "Dot & Key",
        "price": price,
        "store": store,
        "productPageUrl": url,
        "size": size,
    }


def _rows(db, product_id, retailer=None):
    with get_connection(db) as conn:
        if retailer is None:
            return conn.execute(
                "SELECT * FROM retail_price_observation WHERE product_id=? ORDER BY id",
                (product_id,),
            ).fetchall()
        return conn.execute(
            "SELECT * FROM retail_price_observation "
            "WHERE product_id=? AND retailer=? ORDER BY id",
            (product_id, retailer),
        ).fetchall()


# ── Observation creation ─────────────────────────────────────────────────────

def test_store_observation_creates_live_provider_observation(db, product_id):
    result = collector.store_observation(
        product_id, _pi_item(), _comparable_match()
    )

    assert result["status"] == "stored"
    rows = _rows(db, product_id, "Nykaa")
    assert len(rows) == 1
    obs = rows[0]
    assert obs["observed_price"] == 465.0
    assert obs["observation_type"] == "live"
    assert obs["observation_status"] == "live"
    assert obs["verification_status"] == "provider_observed"
    assert obs["evidence_reference"] == "priceinindia_search_result_id_pi-1001"
    assert "PI match" in obs["evidence_notes"]
    assert obs["size_volume"] == "50g"
    assert obs["product_url"].startswith("https://")


def test_store_observation_dry_run_does_not_write(db, product_id):
    result = collector.store_observation(
        product_id, _pi_item(), _comparable_match(), dry_run=True
    )

    assert result["status"] == "dry_run"
    assert _rows(db, product_id, "Nykaa") == []


def test_store_observation_syncs_offer_for_known_retailer(db, product_id):
    collector.store_observation(product_id, _pi_item(price=465.0), _comparable_match())

    with get_connection(db) as conn:
        offer = conn.execute(
            """
            SELECT o.current_price, o.currency, o.offer_url
            FROM offers o
            JOIN stores s ON s.id = o.store_id
            WHERE o.product_id = ? AND s.name LIKE 'Nykaa%'
            """,
            (product_id,),
        ).fetchone()
    assert offer is not None
    assert offer["current_price"] == 465.0
    assert offer["currency"] == "INR"


# ── Superseding semantics ────────────────────────────────────────────────────

def test_same_retailer_supersedes_previous_live_observation(db, product_id):
    collector.store_observation(
        product_id, _pi_item(price=465.0, item_id="pi-a"), _comparable_match()
    )
    collector.store_observation(
        product_id, _pi_item(price=449.0, item_id="pi-b"), _comparable_match()
    )

    rows = _rows(db, product_id, "Nykaa")
    assert len(rows) == 2
    assert [r["observation_status"] for r in rows] == ["superseded", "live"]
    assert rows[-1]["observed_price"] == 449.0


def test_different_retailers_do_not_supersede_each_other(db, product_id):
    collector.store_observation(
        product_id, _pi_item(store="Nykaa", price=465.0), _comparable_match()
    )
    collector.store_observation(
        product_id, _pi_item(store="Tira", price=479.0, item_id="pi-tira"),
        _comparable_match(),
    )

    assert [r["observation_status"] for r in _rows(db, product_id, "Nykaa")] == ["live"]
    assert [r["observation_status"] for r in _rows(db, product_id, "Tira")] == ["live"]


def test_history_is_retained_after_superseding(db, product_id):
    collector.store_observation(
        product_id, _pi_item(price=465.0, item_id="pi-old"), _comparable_match()
    )
    collector.store_observation(
        product_id, _pi_item(price=455.0, item_id="pi-new"), _comparable_match()
    )

    rows = _rows(db, product_id, "Nykaa")
    old = [r for r in rows if r["observation_status"] == "superseded"]
    assert len(old) == 1
    assert old[0]["observed_price"] == 465.0
    assert old[0]["evidence_reference"] == "priceinindia_search_result_id_pi-old"


def test_duplicate_collection_leaves_only_one_live_row(db, product_id):
    item = _pi_item()
    for _ in range(3):
        collector.store_observation(product_id, item, _comparable_match())

    rows = _rows(db, product_id, "Nykaa")
    live = [r for r in rows if r["observation_status"] == "live"]
    superseded = [r for r in rows if r["observation_status"] == "superseded"]
    assert len(live) == 1
    assert len(superseded) == 2


# ── Invalid input ────────────────────────────────────────────────────────────

def test_invalid_price_is_rejected_and_not_persisted(db, product_id):
    result = collector.store_observation(
        product_id, _pi_item(price=0), _comparable_match()
    )

    assert result["status"] == "rejected"
    assert "positive" in result["reason"]
    assert _rows(db, product_id, "Nykaa") == []


def test_negative_price_is_rejected(db, product_id):
    result = collector.store_observation(
        product_id, _pi_item(price=-10.0), _comparable_match()
    )

    assert result["status"] == "rejected"
    assert _rows(db, product_id, "Nykaa") == []


def test_missing_url_is_stored_without_fabricating_one(db, product_id):
    # Create a known URL first so we can prove it is not wiped.
    collector.store_observation(product_id, _pi_item(), _comparable_match())

    item = _pi_item(item_id="pi-no-url", url="")
    result = collector.store_observation(product_id, item, _comparable_match())

    assert result["status"] == "stored"
    rows = _rows(db, product_id, "Nykaa")
    latest = rows[-1]
    assert latest["product_url"] == ""

    with get_connection(db) as conn:
        offer_url = conn.execute(
            """
            SELECT o.offer_url
            FROM offers o JOIN stores s ON s.id = o.store_id
            WHERE o.product_id = ? AND s.name LIKE 'Nykaa%'
            """,
            (product_id,),
        ).fetchone()["offer_url"]
    assert offer_url.startswith("https://")  # previous URL preserved


# ── Match handling ───────────────────────────────────────────────────────────

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


def test_pi_match_accepts_same_brand_and_title():
    result = collector.match_pi_result_to_product(
        {
            "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
            "brand": "Dot & Key",
            "store": "Nykaa",
        },
        _catalog(),
    )
    assert result.is_comparable is True
    assert result.match_classification == MatchClassification.POSSIBLE_MATCH


def test_pi_match_rejects_different_brand():
    result = collector.match_pi_result_to_product(
        {
            "title": "Minimalist Watermelon Cooling Sunscreen SPF 50+",
            "brand": "Minimalist",
            "store": "Nykaa",
        },
        _catalog(),
    )
    assert result.is_comparable is False
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH


def test_pi_match_rejects_size_conflict():
    """Leniency for PI results must never override a quantity conflict."""
    result = collector.match_pi_result_to_product(
        {
            "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ 30g",
            "brand": "Dot & Key",
            "store": "Nykaa",
        },
        _catalog(),
    )
    assert result.is_comparable is False
    assert result.size_match is False


def test_pi_match_rejects_concentration_conflict():
    result = collector.match_pi_result_to_product(
        {
            "title": "Minimalist Niacinamide 5% Serum 30ml",
            "brand": "Minimalist",
            "store": "Nykaa",
        },
        _catalog(
            title="Minimalist Niacinamide 10% Serum 30ml",
            brand="Minimalist",
            specs={"Net Quantity": "30ml"},
        ),
    )
    assert result.is_comparable is False
    assert result.concentration_match is False


def test_pi_match_rejects_shade_conflict():
    result = collector.match_pi_result_to_product(
        {
            "title": "M.A.C Retro Matte Lipstick - Velvet Teddy 3g",
            "brand": "M.A.C",
            "store": "Nykaa",
        },
        _catalog(
            title="M.A.C Retro Matte Lipstick - Ruby Woo",
            brand="M.A.C",
            specs={"Shade": "Ruby Woo", "Net Quantity": "3g"},
        ),
    )
    assert result.is_comparable is False
    assert result.shade_match is False


def test_pi_match_rejects_formulation_conflict():
    result = collector.match_pi_result_to_product(
        {
            "title": "Maybelline Lash Sensational Sky High Washable Mascara 7.2ml",
            "brand": "Maybelline",
            "store": "Nykaa",
        },
        _catalog(
            title="Maybelline Lash Sensational Sky High Waterproof Mascara",
            brand="Maybelline",
            specs={"Formulation": "Waterproof", "Net Quantity": "7.2ml"},
        ),
    )
    assert result.is_comparable is False
    assert result.formulation_match is False


def test_pi_match_tolerates_missing_provider_size():
    """Provider data often omits size; that is not an identity conflict."""
    result = collector.match_pi_result_to_product(
        {
            "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++",
            "brand": "Dot & Key",
            "store": "Nykaa",
        },
        _catalog(),
    )
    assert result.is_comparable is True
    assert result.size_match is True


def test_observation_flags_non_comparable_match(db, product_id):
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
        product_id, _pi_item(price=299.0), mismatch
    )
    assert result["status"] == "stored"
    row = _rows(db, product_id, "Nykaa")[-1]
    assert row["observation_status"] == "flagged"
    assert row["verification_status"] == "pending"
