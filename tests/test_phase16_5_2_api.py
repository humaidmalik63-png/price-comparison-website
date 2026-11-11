"""Phase 16.5.2 regression tests for the FastAPI surface.

Covers the Phase 16.2–16.5 endpoints used by the live-price pipeline:

- verified offers / cheapest offer / catalog cheapest offers
- price history and health stats
- connector health, search and find (MCP fully mocked — no network)
- admin PriceInIndia collection endpoint (auth overridden, MCP mocked)
- honest error handling for missing products and provider failures

All database access is redirected to an isolated, freshly seeded temp database.
"""

import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from src.api import main
from src.adapters.mcp_adapters.base_mcp_adapter import McpCallResult
from src.database.connection import get_connection
from src.services import cheapest_offer_service as cos
from src.services import match_review_service as mrs
from src.services import price_intelligence as pi


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture
def db(monkeypatch, fresh_seeded_db):
    monkeypatch.setattr(
        main, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    monkeypatch.setattr(
        pi, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    # Phase 16.6 services consulted by the extended endpoints.
    monkeypatch.setattr(
        cos, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    monkeypatch.setattr(
        mrs, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    return fresh_seeded_db


@pytest.fixture
def client(db):
    main.app.dependency_overrides[main.get_current_user] = lambda: SimpleNamespace(
        id=1, email="admin@pricewise.test", display_name="Admin"
    )
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
def sunscreen(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id, title, brand FROM products "
            "WHERE title LIKE '%Watermelon Cooling Sunscreen%' ORDER BY id LIMIT 1"
        ).fetchone()
    assert row is not None
    return dict(row)


def _pi_item(title: str, brand: str, price=465.0, store="Nykaa", item_id="pi-1"):
    return {
        "id": item_id,
        "title": title,
        "brand": brand,
        "price": price,
        "store": store,
        "productPageUrl": f"https://www.nykaa.com/{item_id}",
        "size": "50 g",
    }


def _patch_search(monkeypatch, items=None, success=True, error=None):
    result = McpCallResult(
        success=success,
        tool_name="search_products",
        data={"total": len(items or [])},
        items=items or [],
        error_message=error,
    )
    monkeypatch.setattr(
        main.PriceInIndiaAdapter, "search_products", lambda self, **kwargs: result
    )
    return result


def _observations(db, product_id):
    with get_connection(db) as conn:
        return conn.execute(
            "SELECT * FROM retail_price_observation WHERE product_id=? ORDER BY id",
            (product_id,),
        ).fetchall()


# ── Offer endpoints ─────────────────────────────────────────────────────────

def test_product_offers_returns_verified_offers(client, sunscreen):
    response = client.get(f"/api/products/{sunscreen['id']}/offers")
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == sunscreen["id"]
    assert isinstance(body["offers"], list)
    assert body["offers"]
    first = body["offers"][0]
    for key in ("offer_id", "current_price", "unit_price", "discount_pct", "source_type"):
        assert key in first


def test_product_offers_404_for_unknown_product(client):
    response = client.get("/api/products/999999/offers")
    assert response.status_code == 404
    assert "No offers" in response.json()["detail"]


def test_product_cheapest_returns_single_offer(client, sunscreen):
    response = client.get(f"/api/products/{sunscreen['id']}/cheapest")
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == sunscreen["id"]
    assert body["cheapest"]["current_price"] > 0


def test_product_cheapest_404_for_unknown_product(client):
    response = client.get("/api/products/999999/cheapest")
    assert response.status_code == 404


def test_catalog_cheapest_offers_returns_all_products(client, db):
    expected = pi.list_cheapest_per_catalog(limit=500)
    response = client.get("/api/catalog/cheapest-offers?limit=500")
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == len(expected)
    assert len(body["offers"]) == len(expected)
    assert body["offers"][0]["price"] <= body["offers"][-1]["price"]


def test_catalog_cheapest_offers_validates_limit(client):
    assert client.get("/api/catalog/cheapest-offers?limit=0").status_code == 422
    assert client.get("/api/catalog/cheapest-offers?limit=501").status_code == 422


# ── History & health ────────────────────────────────────────────────────────

def test_price_history_endpoint_returns_points(client, db, sunscreen):
    with get_connection(db) as conn:
        conn.execute(
            "INSERT INTO retail_price_observation"
            " (product_id, retailer, product_url, observed_price, size_volume,"
            "  observation_type, observation_status, verification_status)"
            " VALUES (?, 'Nykaa', 'https://nykaa.test/p', 449.0, '50 g',"
            "         'live', 'live', 'provider_observed')",
            (sunscreen["id"],),
        )

    response = client.get(f"/api/products/{sunscreen['id']}/price-history")
    assert response.status_code == 200
    body = response.json()
    assert body["product_id"] == sunscreen["id"]
    assert any(p["observed_price"] == 449.0 for p in body["history_points"])
    point = next(p for p in body["history_points"] if p["observed_price"] == 449.0)
    assert point["unit_price"] == round(449.0 / 50, 4)


def test_admin_health_stats_endpoint(client):
    response = client.get("/api/admin/health-stats")
    assert response.status_code == 200
    stats = response.json()
    for key in (
        "total_active_products",
        "live_observations",
        "flagged_observations",
        "expired_observations",
        "active_retailers",
    ):
        assert key in stats


# ── Connector endpoints (mocked MCP) ────────────────────────────────────────

def test_connector_health_reports_configuration_without_network(client):
    response = client.get("/api/connectors/priceinindia/health")
    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "PriceInIndia"
    assert body["endpoint"] == "https://mcp.priceinindia.website/mcp"
    assert body["is_configured"] is True
    # A fresh adapter has made no requests; the endpoint must not invent health.
    assert body["total_requests"] == 0
    assert body["last_success_at"] is None


def test_connector_search_returns_mocked_products(client, monkeypatch):
    item = _pi_item("Dot & Key Sunscreen", "Dot & Key")
    _patch_search(monkeypatch, items=[item])

    response = client.post(
        "/api/connectors/priceinindia/search", json={"query": "Dot & Key Sunscreen"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["total"] == 1
    assert body["products"][0]["title"] == item["title"]
    assert body["error"] is None


def test_connector_search_reports_provider_failure(client, monkeypatch):
    _patch_search(monkeypatch, success=False, error="provider unavailable")

    response = client.post(
        "/api/connectors/priceinindia/search", json={"query": "nothing"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["products"] == []
    assert body["error"] == "provider unavailable"


def test_connector_search_requires_query(client):
    response = client.post("/api/connectors/priceinindia/search", json={})
    assert response.status_code == 422


def test_connector_find_uses_mocked_search(client, monkeypatch):
    item = _pi_item("Dot & Key Sunscreen", "Dot & Key")
    monkeypatch.setattr(
        main.PriceInIndiaAdapter,
        "find_beauty_product",
        lambda self, **kwargs: McpCallResult(
            success=True, tool_name="find_beauty_product", data={"total": 1}, items=[item]
        ),
    )

    response = client.post(
        "/api/connectors/priceinindia/find",
        json={"brand": "Dot & Key", "product_name": "Sunscreen"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["query"] == "Dot & Key Sunscreen"
    assert body["products"][0]["price"] == 465.0


# ── Match endpoint ──────────────────────────────────────────────────────────

def test_match_endpoint_verified_without_prices(client):
    payload = {
        "target_brand": "Dot & Key",
        "target_title": "Watermelon Cooling Sunscreen SPF 50+ PA++++",
        "target_specs": {"Net Quantity": "50g", "Product Type": "Gel Sunscreen"},
        "offer_brand": "Dot & Key",
        "offer_title": "Watermelon Cooling Sunscreen SPF 50+ PA++++",
        "offer_variant": "50g Standard",
        "offer_specs": {"Net Quantity": "50g", "Product Type": "Gel Sunscreen"},
    }
    response = client.post("/api/match/product", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["match_classification"] == "verified_match"
    assert body["is_comparable"] is True
    assert body["display_badge"] == "Verified Exact Variant"


def test_match_endpoint_rejects_shade_conflict(client):
    payload = {
        "target_brand": "M.A.C",
        "target_title": "Retro Matte Lipstick - Ruby Woo",
        "target_specs": {"Shade": "Ruby Woo", "Net Quantity": "3g"},
        "offer_brand": "M.A.C",
        "offer_title": "Retro Matte Lipstick - Velvet Teddy",
        "offer_specs": {"Shade": "Velvet Teddy", "Net Quantity": "3g"},
    }
    response = client.post("/api/match/product", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["match_classification"] == "incompatible_mismatch"
    assert body["is_comparable"] is False


# ── Admin collection endpoint ───────────────────────────────────────────────

def test_collect_endpoint_stores_provider_observation(client, db, sunscreen, monkeypatch):
    item = _pi_item(sunscreen["title"], sunscreen["brand"])
    _patch_search(monkeypatch, items=[item])

    response = client.post(
        "/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["total_products"] == 1
    assert body["matches"] == 1
    assert len(body["observations"]) == 1
    assert body["observations"][0]["retailer"] == "Nykaa"
    assert body["observations"][0]["price"] == 465.0

    rows = _observations(db, sunscreen["id"])
    assert len(rows) == 1
    assert rows[0]["observation_status"] == "live"
    assert rows[0]["verification_status"] == "provider_observed"
    assert rows[0]["observation_type"] == "live"


def test_collect_endpoint_supersedes_same_retailer(client, db, sunscreen, monkeypatch):
    item = _pi_item(sunscreen["title"], sunscreen["brand"], item_id="pi-a")
    _patch_search(monkeypatch, items=[item])
    client.post("/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]})

    item = _pi_item(sunscreen["title"], sunscreen["brand"], price=449.0, item_id="pi-b")
    _patch_search(monkeypatch, items=[item])
    client.post("/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]})

    rows = _observations(db, sunscreen["id"])
    assert len(rows) == 2
    assert [r["observation_status"] for r in rows] == ["superseded", "live"]
    assert rows[-1]["observed_price"] == 449.0


def test_collect_endpoint_keeps_other_retailers_independent(
    client, db, sunscreen, monkeypatch
):
    nykaa = _pi_item(sunscreen["title"], sunscreen["brand"], store="Nykaa", item_id="pi-n")
    _patch_search(monkeypatch, items=[nykaa])
    client.post("/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]})

    tira = _pi_item(
        sunscreen["title"], sunscreen["brand"], price=479.0, store="Tira", item_id="pi-t"
    )
    _patch_search(monkeypatch, items=[tira])
    client.post("/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]})

    rows = _observations(db, sunscreen["id"])
    assert [r["observation_status"] for r in rows] == ["live", "live"]
    assert {r["retailer"] for r in rows} == {"Nykaa", "Tira"}


def test_collect_endpoint_rejects_invalid_price(client, db, sunscreen, monkeypatch):
    item = _pi_item(sunscreen["title"], sunscreen["brand"], price=0)
    _patch_search(monkeypatch, items=[item])

    response = client.post(
        "/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == 0
    assert body["observations"] == []
    assert any("Invalid price" in err for err in body["errors"])
    assert _observations(db, sunscreen["id"]) == []


def test_collect_endpoint_skips_non_comparable_matches(
    client, db, sunscreen, monkeypatch
):
    item = _pi_item("Minimalist Niacinamide 10% Serum 30ml", "Minimalist", price=399.0)
    _patch_search(monkeypatch, items=[item])

    response = client.post(
        "/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]}
    )
    assert response.status_code == 200
    assert response.json()["matches"] == 0
    assert _observations(db, sunscreen["id"]) == []


def test_collect_endpoint_reports_no_results(client, db, sunscreen, monkeypatch):
    _patch_search(monkeypatch, success=False, error="no results")

    response = client.post(
        "/api/collect/priceinindia", json={"product_ids": [sunscreen["id"]]}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == 0
    assert body["failed"] == 1
    assert any("No PI results" in err for err in body["errors"])


def test_collect_endpoint_requires_authentication(db, monkeypatch):
    """Without the dependency override the endpoint must reject anonymous calls."""
    item = _pi_item("x", "y")
    _patch_search(monkeypatch, items=[item])
    anonymous = TestClient(main.app)
    response = anonymous.post("/api/collect/priceinindia", json={"product_ids": [1]})
    assert response.status_code == 401
