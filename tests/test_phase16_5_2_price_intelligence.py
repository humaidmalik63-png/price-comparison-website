"""Phase 16.5.2 regression tests for the price intelligence layer.

Covers the Phase 16.2/16.5 price analytics that Phase 16.5 relies on:

- retailer name/domain matching between offers and observations
- ``provider_observed`` classification for live PI observations
- demo vs provider-observed distinction
- latest-observation selection and superseding/history semantics
- cheapest eligible offer selection
- catalog-wide cheapest offers (all products, unit prices, specs selection)
- stale observation expiry

All database access is redirected to an isolated, freshly seeded temp database.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.database.connection import get_connection
from src.services import price_intelligence as pi


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch, fresh_seeded_db):
    monkeypatch.setattr(pi, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))
    return fresh_seeded_db


def _store_id(conn, name_like: str) -> int:
    row = conn.execute(
        "SELECT id FROM stores WHERE name LIKE ? LIMIT 1", (f"{name_like}%",)
    ).fetchone()
    assert row is not None, f"seeded store {name_like!r} missing"
    return row["id"]


def _make_product(
    conn,
    sku: str,
    *,
    source_type: str = "demo",
    title: str = "Phase Test Serum",
    brand: str = "PhaseBrand",
    specs: dict | None = None,
    category: str = "Skincare",
) -> int:
    cursor = conn.execute(
        "INSERT INTO products (sku, title, brand, category, specs_json, source_type,"
        " data_status, is_active) VALUES (?, ?, ?, ?, ?, ?, 'pending_review', 1)",
        (sku, title, brand, category, json.dumps(specs or {}), source_type),
    )
    return cursor.lastrowid


def _make_offer(conn, product_id: int, store_name: str, price: float, original=None) -> int:
    store_id = _store_id(conn, store_name)
    cursor = conn.execute(
        "INSERT INTO offers (product_id, store_id, current_price, original_price,"
        " shipping_cost, currency, availability, offer_url)"
        " VALUES (?, ?, ?, ?, 0, 'INR', 'In Stock', ?)",
        (product_id, store_id, price, original, f"https://{store_name.lower()}.test/p"),
    )
    return cursor.lastrowid


def _make_observation(
    conn,
    product_id: int,
    retailer: str,
    price: float,
    *,
    status: str = "live",
    verification: str = "provider_observed",
    created_at: str | None = None,
    size: str | None = "30ml",
) -> int:
    created_at = created_at or datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO retail_price_observation"
        " (product_id, retailer, product_url, observed_price, size_volume,"
        "  observation_type, observation_status, verification_status, created_at)"
        " VALUES (?, ?, ?, ?, ?, 'live', ?, ?, ?)",
        (
            product_id,
            retailer,
            f"https://{retailer.lower()}.test/p",
            price,
            size,
            status,
            verification,
            created_at,
        ),
    )
    return cursor.lastrowid


# ── Provider-observed classification ────────────────────────────────────────

def test_live_provider_observation_marks_offer_provider_observed(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "PI-1")
        _make_offer(conn, pid, "Nykaa", 465.0, original=595.0)
        _make_observation(conn, pid, "Nykaa", 465.0)

    offers = pi.get_verified_offers(pid)
    assert len(offers) == 1
    offer = offers[0]
    assert offer["source_type"] == "provider_observed"
    assert offer["data_status"] == "provider_observed"
    assert offer["verification_status"] == "provider_observed"
    assert offer["is_demo"] is False
    assert offer["latest_obs_status"] == "live"
    assert offer["latest_obs_price"] == 465.0


def test_retailer_matches_store_domain(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "PI-2")
        _make_offer(conn, pid, "Nykaa", 479.0)
        _make_observation(conn, pid, "nykaa.com", 479.0)

    offers = pi.get_verified_offers(pid)
    assert offers[0]["source_type"] == "provider_observed"


def test_retailer_matches_store_display_name_prefix(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "PI-2B")
        _make_offer(conn, pid, "Tira", 479.0)
        _make_observation(conn, pid, "Tira", 479.0)

    offers = pi.get_verified_offers(pid)
    assert offers[0]["source_type"] == "provider_observed"


def test_observation_for_other_retailer_does_not_relabel_offer(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "PI-3")
        _make_offer(conn, pid, "Nykaa", 465.0)
        _make_offer(conn, pid, "Tira", 479.0)
        _make_observation(conn, pid, "Tira", 479.0)

    offers = {o["store_name"]: o for o in pi.get_verified_offers(pid)}
    nykaa = next(v for k, v in offers.items() if k.startswith("Nykaa"))
    tira = next(v for k, v in offers.items() if k.startswith("Tira"))
    assert nykaa["source_type"] == "demo"
    assert nykaa["verification_status"] == "unverified"
    assert tira["source_type"] == "provider_observed"


def test_demo_product_without_observations_stays_demo(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "DEMO-1", source_type="demo")
        _make_offer(conn, pid, "Nykaa", 999.0)

    offer = pi.get_verified_offers(pid)[0]
    assert offer["source_type"] == "demo"
    assert offer["is_demo"] is True
    assert offer["verification_status"] == "unverified"


def test_flagged_observation_is_not_provider_observed(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "FLAG-1")
        _make_offer(conn, pid, "Nykaa", 465.0)
        _make_observation(conn, pid, "Nykaa", 465.0, status="flagged", verification="pending")

    offer = pi.get_verified_offers(pid)[0]
    assert offer["source_type"] == "demo"
    assert offer["verification_status"] == "pending"


def test_superseded_observation_is_not_selected_over_live(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "SUPER-1")
        _make_offer(conn, pid, "Nykaa", 449.0)
        _make_observation(
            conn,
            pid,
            "Nykaa",
            465.0,
            status="superseded",
            created_at="2026-01-01T00:00:00+00:00",
        )
        _make_observation(
            conn,
            pid,
            "Nykaa",
            449.0,
            status="live",
            created_at="2026-02-01T00:00:00+00:00",
        )

    offer = pi.get_verified_offers(pid)[0]
    assert offer["latest_obs_status"] == "live"
    assert offer["latest_obs_price"] == 449.0


# ── Cheapest selection ──────────────────────────────────────────────────────

def test_cheapest_verified_excludes_demo_when_real_offer_exists(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "CHEAP-1", source_type="demo")
        _make_offer(conn, pid, "Nykaa", 100.0)   # demo source, cheapest
        _make_offer(conn, pid, "Tira", 450.0)
        _make_observation(conn, pid, "Tira", 450.0)

    cheapest = pi.get_cheapest_verified(pid)
    assert cheapest["current_price"] == 450.0
    assert cheapest["source_type"] == "provider_observed"


def test_cheapest_verified_falls_back_to_demo(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "CHEAP-2", source_type="demo")
        _make_offer(conn, pid, "Nykaa", 100.0)

    cheapest = pi.get_cheapest_verified(pid)
    assert cheapest["current_price"] == 100.0
    assert cheapest["is_demo"] is True


def test_cheapest_verified_returns_none_for_unknown_product(db):
    assert pi.get_cheapest_verified(999999) is None


# ── Unit price & discount ───────────────────────────────────────────────────

def test_unit_price_uses_product_specs_quantity(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "UNIT-1", specs={"Net Quantity": "50g"})
        _make_offer(conn, pid, "Nykaa", 500.0)

    offer = pi.get_verified_offers(pid)[0]
    assert offer["unit_price"] == 10.0  # 500 / 50g


def test_discount_percent_uses_mrp_or_original_price(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "DISC-1", specs={"Net Quantity": "10ml"})
        _make_offer(conn, pid, "Nykaa", 750.0, original=1000.0)

    offer = pi.get_verified_offers(pid)[0]
    assert offer["discount_pct"] == 25.0
    assert offer["landing_cost"] == 750.0


# ── History ─────────────────────────────────────────────────────────────────

def test_price_history_excludes_superseded_but_keeps_flagged(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "HIST-1")
        _make_observation(
            conn, pid, "Nykaa", 465.0, status="superseded",
            created_at="2026-01-01T00:00:00+00:00", size="50g",
        )
        _make_observation(
            conn, pid, "Nykaa", 449.0, status="live",
            created_at="2026-02-01T00:00:00+00:00", size="50g",
        )
        _make_observation(
            conn, pid, "Tira", 500.0, status="flagged", verification="pending",
            created_at="2026-03-01T00:00:00+00:00", size="50g",
        )

    history = pi.get_observation_price_history(pid)
    assert [h.observed_price for h in history] == [449.0, 500.0]
    assert all(h.observation_status != "superseded" for h in history)
    assert history[0].unit_price == round(449.0 / 50, 4)


def test_price_history_limit_is_respected(db):
    with get_connection(db) as conn:
        pid = _make_product(conn, "HIST-2")
        for day in range(5):
            _make_observation(
                conn, pid, "Nykaa", 400.0 + day, status="live",
                created_at=f"2026-01-0{day + 1}T00:00:00+00:00",
            )

    assert len(pi.get_observation_price_history(pid, limit=3)) == 3


# ── Catalog-wide cheapest offers ────────────────────────────────────────────

def test_list_cheapest_per_catalog_returns_every_eligible_product(db):
    with get_connection(db) as conn:
        expected = conn.execute(
            """
            SELECT COUNT(DISTINCT p.id)
            FROM products p
            JOIN offers o ON o.product_id = p.id
            WHERE p.is_active = 1
              AND p.category NOT IN ('Skincare Routine', 'Makeup Routine')
              AND o.current_price > 0
            """
        ).fetchone()[0]

    results = pi.list_cheapest_per_catalog(limit=500)
    assert len(results) == expected
    assert expected > 1  # no longer collapses to a single product


def test_list_cheapest_per_catalog_computes_unit_prices(db):
    results = pi.list_cheapest_per_catalog(limit=500)
    assert any(r["unit_price"] for r in results)
    # specs_json is selected so unit prices can be derived for each row.
    for row in results:
        assert "unit_price" in row
        assert row["price"] > 0
        assert row["landing_cost"] >= row["price"]


def test_list_cheapest_per_catalog_respects_limit(db):
    results = pi.list_cheapest_per_catalog(limit=2)
    assert len(results) == 2
    assert results[0]["price"] <= results[1]["price"]


# ── Expiry ──────────────────────────────────────────────────────────────────

def test_expire_stale_observations_only_expires_old_live_rows(db):
    old = (datetime.now(timezone.utc) - timedelta(hours=200)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    with get_connection(db) as conn:
        pid = _make_product(conn, "EXPIRE-1")
        old_id = _make_observation(conn, pid, "Nykaa", 400.0, created_at=old)
        fresh_id = _make_observation(conn, pid, "Tira", 410.0, created_at=fresh)
        flagged_id = _make_observation(
            conn, pid, "Amazon India", 420.0, status="flagged", created_at=old
        )

    expired = pi.expire_stale_observations(max_age_hours=72)
    assert expired >= 1

    with get_connection(db) as conn:
        statuses = {
            row["id"]: row["observation_status"]
            for row in conn.execute(
                "SELECT id, observation_status FROM retail_price_observation"
                " WHERE id IN (?, ?, ?)",
                (old_id, fresh_id, flagged_id),
            )
        }
    assert statuses[old_id] == "expired"
    assert statuses[fresh_id] == "live"
    assert statuses[flagged_id] == "flagged"


# ── Helpers ─────────────────────────────────────────────────────────────────

def test_filter_rejected_demos_splits_lists():
    offers = [
        {"source_type": "demo", "current_price": 1},
        {"source_type": "catalog_verified", "current_price": 2},
    ]
    genuine, demos = pi.filter_rejected_demos(offers)
    assert len(genuine) == 1 and len(demos) == 1
    assert genuine[0]["source_type"] == "catalog_verified"


def test_calculate_discount_handles_missing_fields():
    assert pi.calculate_discount({"observed_price": 100.0, "observed_mrp": 200.0}) == 50.0
    assert pi.calculate_discount({"observed_price": 100.0}) is None
    assert pi.calculate_discount({"observed_price": None, "observed_mrp": 0}) is None
