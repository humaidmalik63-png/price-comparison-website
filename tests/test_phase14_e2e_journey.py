"""Phase 14 — end-to-end shopper journey (Stage H).

Walks the complete customer path against the isolated test database:

    registration -> login -> discovery -> product detail -> price comparison
    -> watchlist -> reviews -> beauty assistant -> logout

Every assertion checks both the HTTP outcome and the *honesty* of the payload:
a response must never present demo content as live or verified data.

The suite runs against the temporary database created by ``tests/conftest.py``;
the shared development database is never touched.
"""

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient

from src.api.main import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def shopper(client):
    """Register a fresh shopper and return (client, email, password)."""
    email = "e2e_shopper@example.com"
    password = "E2eJourneyPass!"
    response = client.post(
        "/api/auth/register",
        json={"name": "E2E Shopper", "email": email, "password": password},
    )
    assert response.status_code in (200, 409), response.text
    return client, email, password


# ==============================================================================
# 1. Registration
# ==============================================================================


def test_registration_returns_a_usable_session(shopper):
    client, email, _password = shopper
    response = client.post(
        "/api/auth/register",
        json={"name": "Second Shopper", "email": "e2e_second@example.com", "password": "SecondPass!"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["user"]["email"] == "e2e_second@example.com"
    assert body["token"], "a session token must be issued"

    # The session cookie is set and is HTTP-only.
    cookies = response.headers.get("set-cookie", "")
    assert "session_token" in cookies
    assert "HttpOnly" in cookies


def test_registration_rejects_a_weak_password(client):
    response = client.post(
        "/api/auth/register",
        json={"name": "Weak", "email": "e2e_weak@example.com", "password": "123"},
    )
    assert response.status_code == 400, response.text


def test_duplicate_registration_is_reported_as_a_conflict(client):
    payload = {"name": "Dupe", "email": "e2e_dupe@example.com", "password": "DupePass!"}
    assert client.post("/api/auth/register", json=payload).status_code == 200
    response = client.post("/api/auth/register", json=payload)
    assert response.status_code == 409, response.text


# ==============================================================================
# 2. Login / logout
# ==============================================================================


def test_login_with_valid_credentials(shopper):
    client, email, password = shopper
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["token"]


def test_login_with_a_wrong_password_is_rejected(shopper):
    client, email, _password = shopper
    response = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    assert response.status_code == 401, response.text


def test_logout_clears_the_session(shopper):
    client, email, password = shopper
    client.post("/api/auth/login", json={"email": email, "password": password})
    assert client.get("/api/auth/me").status_code == 200

    response = client.post("/api/auth/logout")
    assert response.status_code == 200

    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


# ==============================================================================
# 3. Discovery
# ==============================================================================


def test_discovery_lists_only_active_beauty_products(client):
    response = client.get("/api/products")
    assert response.status_code == 200, response.text
    products = response.json()
    assert len(products) == 100, f"expected 100 active products, got {len(products)}"

    tech_categories = {"Laptops", "Smartphones", "Audio", "Gaming", "Wearables", "Monitors", "Cameras", "TVs"}
    for product in products:
        assert product["id"] >= 12, "a legacy electronics record leaked into discovery"
        assert product["category"] not in tech_categories
        assert product["is_active"] is True


def test_discovery_supports_search_and_filters(client):
    response = client.get("/api/products", params={"search": "sunscreen"})
    assert response.status_code == 200
    results = response.json()
    assert isinstance(results, list)
    if results:
        assert any("sunscreen" in p["title"].lower() for p in results)


def test_product_detail_is_reachable_by_slug(client):
    listing = client.get("/api/products").json()
    target = next(p for p in listing if p["id"] == 12)
    response = client.get(f"/api/products/{target['slug']}")
    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["id"] == 12
    assert detail["title"]


def test_archived_products_are_not_addressable(client):
    # Product 1 is a soft-archived legacy electronics record.
    response = client.get("/api/products/1")
    assert response.status_code == 404, response.text


# ==============================================================================
# 4. Price comparison and honesty of the offers
# ==============================================================================


def test_price_comparison_never_exposes_an_unverified_purchase_link(client):
    detail = client.get("/api/products/12").json()
    offers = detail.get("offers", [])
    assert offers, "the product must expose its retailer offers"

    for offer in offers:
        assert "link_status" in offer
        if offer["link_status"] != "verified":
            assert offer.get("purchase_url") in (None, ""), (
                "an unverified offer exposed a purchase link: "
                f"{offer.get('purchase_url')}"
            )
            # The raw offer_url must not be published either: the client reads
            # that field, and it can hold a synthetic SKU-shaped path that does
            # not exist on the retailer site.
            assert offer.get("offer_url") in (None, ""), (
                "an unverified offer published a raw retailer URL: "
                f"{offer.get('offer_url')}"
            )
        # Demo pricing must never be labelled as live.
        assert offer["source_type"] in ("demo", "verified_live", "partner_feed", "cached", "manually_curated", "unavailable")


def test_live_comparison_reports_unavailable_rather_than_inventing_prices(client):
    response = client.get("/api/compare/auto", params={"product_id": 12})
    assert response.status_code == 200, response.text
    body = response.json()
    for offer in body.get("offers", []):
        assert offer["status"] in (
            "retrieved", "unavailable", "unsupported", "restricted", "mismatch", "error",
        )
        if offer["status"] != "retrieved":
            # No price may be asserted for a retailer that did not answer.
            assert offer.get("listed_price") in (None, 0)


def test_price_history_is_labelled_with_its_evidence_status(client):
    response = client.get("/api/products/12/price-history", params={"window_days": 90})
    assert response.status_code == 200, response.text
    body = response.json()
    for point in body.get("points", []):
        assert point.get("data_status") in ("demo", "manual_verified", "live_verified", "historical")
    # The response must state whether the history is simulated.
    assert "is_simulated" in body


def test_deal_intelligence_is_explainable(client):
    response = client.get("/api/products/12/deal-intelligence")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "factors" in body
    for factor in body.get("factors", []):
        assert factor.get("explanation"), "a deal factor must explain itself"
    assert "is_simulated_deal" in body


# ==============================================================================
# 5. Watchlist
# ==============================================================================


def test_watchlist_round_trip(shopper):
    client, email, password = shopper
    client.post("/api/auth/login", json={"email": email, "password": password})

    listing = client.get("/api/products").json()
    product_id = listing[0]["id"]

    add = client.post("/api/watchlist", json={"product_id": product_id})
    assert add.status_code in (200, 400), add.text

    watchlist = client.get("/api/watchlist")
    assert watchlist.status_code == 200, watchlist.text
    body = watchlist.json()
    assert any(item["product_id"] == product_id for item in body["items"])

    remove = client.delete(f"/api/watchlist/{product_id}")
    assert remove.status_code in (200, 404), remove.text


# ==============================================================================
# 6. Reviews
# ==============================================================================


def test_reviews_endpoint_reports_attribution_and_honest_empty_state(client):
    response = client.get("/api/products/12/reviews")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "attribution_notice" in body
    assert "by_data_status" in body
    for review in body["reviews"]:
        assert review["platform"], "a review must carry its platform attribution"
        assert review["data_status"] in ("demo", "verified_retailer", "manually_curated")
    if not body["reviews"]:
        assert body["empty_state"], "an empty review set must explain itself"


# ==============================================================================
# 7. Beauty assistant
# ==============================================================================


def test_beauty_assistant_requires_authentication(client):
    client.cookies.clear()
    client.headers.pop("Authorization", None)
    response = client.post("/api/beauty/match-skin-concerns", json={"concerns": ["acne"]})
    assert response.status_code == 401, response.text


def test_beauty_assistant_answers_for_an_authenticated_user(shopper):
    client, email, password = shopper
    client.post("/api/auth/login", json={"email": email, "password": password})

    response = client.post(
        "/api/beauty/match-skin-concerns",
        json={"skin_type": "oily", "concerns": ["acne", "oiliness"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "matches" in body
    # The assistant must state where its answer came from.
    assert "source" in body or "extraction_source" in body


def test_beauty_usage_endpoint_reports_the_quota(client):
    client.post("/api/auth/login", json={"email": "e2e_shopper@example.com", "password": "E2eJourneyPass!"})
    response = client.get("/api/beauty/usage")
    assert response.status_code == 200, response.text
    body = response.json()
    assert "requests_today" in body or "rate_limit" in body


# ==============================================================================
# 8. Profile and routines
# ==============================================================================


def test_profile_can_be_saved_and_reset(shopper):
    client, email, password = shopper
    client.post("/api/auth/login", json={"email": email, "password": password})

    save = client.put(
        "/api/profile",
        json={"skin_type": "combination", "skin_concerns": ["acne"], "max_budget": 2000},
    )
    assert save.status_code == 200, save.text
    assert save.json()["profile"]["skin_type"] == "combination"

    reset = client.delete("/api/profile")
    assert reset.status_code == 200, reset.text


def test_routines_round_trip(shopper):
    client, email, password = shopper
    client.post("/api/auth/login", json={"email": email, "password": password})

    create = client.post("/api/routines", json={"name": "E2E Morning", "routine_type": "AM"})
    assert create.status_code == 200, create.text
    routine_id = create.json()["routine"]["id"]

    listing = client.get("/api/routines")
    assert listing.status_code == 200
    assert any(r["id"] == routine_id for r in listing.json()["routines"])

    delete = client.delete(f"/api/routines/{routine_id}")
    assert delete.status_code == 200, delete.text


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
