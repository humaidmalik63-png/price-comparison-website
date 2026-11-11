"""Phase 16.6 Stage 7 tests: API integration for live price coverage.

Covers the extended and new endpoints:

- /api/products/{id}/offers — live eligible/excluded sections with
  disclosed assumptions; 404 behaviour preserved
- /api/products/{id}/cheapest — live_cheapest with eligibility basis and
  assumptions; 404 behaviour preserved
- /api/catalog/cheapest-offers — paginated live section; limit validation
- /api/products/{id}/price-history — full history incl. superseded,
  price_change, latest-per-retailer freshness, real-data summary
- /api/admin/health-stats — freshness distribution, review queue depth,
  collection job status, last collection time
- /api/admin/match-review-queue — auth required, listing, pagination
- /api/admin/match-review/{id}/resolve — approve/reject, validation, 404
- /api/admin/price-collection/status — honest never_run + artifact read

All database access is redirected to an isolated, freshly seeded temp
database. Provider endpoints are not exercised here (mocked elsewhere).
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from src.api import main
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
    monkeypatch.setattr(
        cos, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    monkeypatch.setattr(
        mrs, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    return fresh_seeded_db


@pytest.fixture
def admin_client(db):
    main.app.dependency_overrides[main.get_current_user] = lambda: SimpleNamespace(
        id=1, email="admin@pricewise.test", display_name="Admin"
    )
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.clear()


@pytest.fixture
def anon_client(db):
    """No auth override — admin endpoints must reject unauthenticated calls."""
    return TestClient(main.app)


@pytest.fixture
def product_id(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
    return row["id"]


def _insert_obs(db, pid, *, retailer="Nykaa", price=465.0, currency="INR",
                status="live", verification="provider_observed",
                created_at=None, url="https://www.nykaa.com/x", size="50 g",
                match_classification="verified_match", mrp=None,
                verified_by_admin=0):
    evidence = {"classification": match_classification, "confidence": 0.9}
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
                    'api test evidence', ?)
            """,
            (pid, retailer, url, price, mrp, currency, size, status,
             verified_by_admin, verification, ts, ts, json.dumps(evidence)),
        )
        return cursor.lastrowid


# ── Offers endpoint ──────────────────────────────────────────────────────────

def test_offers_include_live_eligible_and_excluded_sections(admin_client, db, product_id):
    _insert_obs(db, product_id, price=465.0, match_classification="verified_match")
    _insert_obs(db, product_id, retailer="Tira", price=300.0, status="superseded",
                match_classification="verified_match")
    _insert_obs(db, product_id, retailer="mynt.ra", price=999.0, currency="USD",
                match_classification="verified_match")

    body = admin_client.get(f"/api/products/{product_id}/offers").json()

    assert body["product_id"] == product_id
    live = body["live"]
    eligible = live["eligible_offers"]
    assert len(eligible) == 1
    assert eligible[0]["retailer"] == "Nykaa"
    assert eligible[0]["freshness"] == "fresh"
    assert live["assumptions"]

    reasons = {e["retailer"]: e["exclusion_reasons"] for e in live["excluded_offers"]}
    assert "not_current" in reasons["Tira"]
    assert "unsupported_currency" in reasons["mynt.ra"]


def test_offers_404_preserved_for_unknown_product(admin_client):
    response = admin_client.get("/api/products/999999/offers")
    assert response.status_code == 404
    assert "No offers" in response.json()["detail"]


def test_offers_unreviewed_possible_match_excluded_transparently(admin_client, db, product_id):
    _insert_obs(db, product_id, match_classification="possible_match",
                verification="provider_observed", verified_by_admin=0)
    body = admin_client.get(f"/api/products/{product_id}/offers").json()
    live = body["live"]
    assert live["eligible_offers"] == []
    assert any("match_unverified" in e["exclusion_reasons"]
               for e in live["excluded_offers"])


# ── Cheapest endpoint ────────────────────────────────────────────────────────

def test_cheapest_includes_live_cheapest_with_assumptions(admin_client, db, product_id):
    _insert_obs(db, product_id, price=439.0, retailer="Tira",
                match_classification="verified_match")
    _insert_obs(db, product_id, price=465.0, retailer="Nykaa",
                match_classification="verified_match")

    body = admin_client.get(f"/api/products/{product_id}/cheapest").json()

    assert body["product_id"] == product_id
    live = body["live_cheapest"]
    assert live["retailer"] == "Tira"
    assert live["price"] == 439.0
    assert live["eligibility_basis"] == "verified_match"
    assert live["assumptions"]


def test_cheapest_live_null_when_no_eligible_offer(admin_client, db, product_id):
    """Demo-only product: live_cheapest is honestly null, not demo-filled."""
    body = admin_client.get(f"/api/products/{product_id}/cheapest").json()
    assert body["live_cheapest"] is None


def test_cheapest_404_preserved_for_unknown_product(admin_client):
    response = admin_client.get("/api/products/999999/cheapest")
    assert response.status_code == 404


# ── Catalog cheapest ─────────────────────────────────────────────────────────

def test_catalog_cheapest_offers_live_section_paginated(admin_client, db, product_id):
    _insert_obs(db, product_id, price=465.0, match_classification="verified_match")
    body = admin_client.get("/api/catalog/cheapest-offers?limit=50").json()

    live = body["live"]
    assert live["total_products"] >= 1
    assert live["products_with_eligible_offers"] == 1
    assert [i["product_id"] for i in live["items"]] == [product_id]
    assert live["assumptions"]


def test_catalog_cheapest_offers_limit_validation(admin_client):
    assert admin_client.get("/api/catalog/cheapest-offers?limit=0").status_code == 422
    assert admin_client.get("/api/catalog/cheapest-offers?limit=501").status_code == 422


# ── Price history ────────────────────────────────────────────────────────────

def test_price_history_full_history_summary_and_freshness(admin_client, db, product_id):
    now = datetime.now(timezone.utc)
    _insert_obs(db, product_id, retailer="Nykaa", price=465.0,
                created_at="2026-11-01T00:00:00+00:00")
    _insert_obs(db, product_id, retailer="Nykaa", price=449.0, status="superseded",
                created_at="2026-11-02T00:00:00+00:00")
    _insert_obs(db, product_id, retailer="Tira", price=470.0,
                created_at=(now - timedelta(hours=2)).isoformat())

    body = admin_client.get(f"/api/products/{product_id}/price-history").json()

    # Compact view excludes superseded.
    assert all(h["observation_status"] != "superseded" for h in body["history_points"])
    # Full view retains them (history is never deleted).
    statuses = [h["observation_status"] for h in body["full_history"]]
    assert statuses.count("superseded") == 1
    assert len(body["full_history"]) == 3

    # Price change is chained across the full series.
    changes = [h["price_change"] for h in body["full_history"]]
    assert changes[0] is None
    assert changes[1] == -16.0
    assert changes[2] == 21.0

    # Latest per retailer carries freshness.
    by_retailer = {r["retailer"]: r for r in body["latest_per_retailer"]}
    assert by_retailer["Nykaa"]["observed_price"] == 449.0
    assert by_retailer["Tira"]["freshness"] == "fresh"

    # Summary over real observations only.
    summary = body["summary"]
    assert summary["valid_price_count"] == 3
    assert summary["lowest_observed"] == 449.0
    assert summary["highest_observed"] == 470.0
    assert summary["trend"] == "rising"


def test_price_history_limit_validation(admin_client):
    assert admin_client.get("/api/products/1/price-history?limit=0").status_code == 422
    assert admin_client.get("/api/products/1/price-history?limit=101").status_code == 422


def test_price_history_empty_product_is_honest(admin_client, db, product_id):
    body = admin_client.get(f"/api/products/{product_id}/price-history").json()
    assert body["history_points"] == []
    assert body["full_history"] == []
    assert body["latest_per_retailer"] == []
    assert body["summary"]["observation_count"] == 0
    assert body["summary"]["trend"] is None


# ── Admin health stats ───────────────────────────────────────────────────────

def test_health_stats_freshness_distribution_and_queue(admin_client, db, product_id):
    now = datetime.now(timezone.utc)
    _insert_obs(db, product_id, price=465.0,
                created_at=(now - timedelta(hours=1)).isoformat(),
                match_classification="possible_match")
    _insert_obs(db, product_id, retailer="Tira", price=470.0,
                created_at=(now - timedelta(hours=48)).isoformat())
    _insert_obs(db, product_id, retailer="mynt.ra", price=480.0,
                created_at=(now - timedelta(hours=200)).isoformat())

    body = admin_client.get("/api/admin/health-stats").json()

    fresh = body["freshness"]
    assert fresh["total"] == 3
    assert fresh["counts"]["fresh"] == 1
    assert fresh["counts"]["aging"] == 1
    assert fresh["counts"]["stale"] == 1
    assert fresh["policy"]["fresh_hours"] == 24
    assert fresh["policy"]["aging_hours"] == 72

    # The unreviewed possible_match lands in the queue depth.
    assert body["match_review_queue"]["pending"] >= 1

    assert body["collection"]["status"] in {"never_run", "completed", "running", "unreadable"}
    assert body["last_collection_time"] is not None


# ── Match review queue endpoints ─────────────────────────────────────────────

def test_match_review_queue_requires_authentication(anon_client):
    response = anon_client.get("/api/admin/match-review-queue")
    assert response.status_code == 401


def test_match_review_queue_lists_uncertain_matches(admin_client, db, product_id):
    obs = _insert_obs(db, product_id, match_classification="possible_match",
                      verification="provider_observed", verified_by_admin=0)

    response = admin_client.get("/api/admin/match-review-queue")
    assert response.status_code == 200
    body = response.json()
    row = next(r for r in body["items"] if r["id"] == obs)
    assert row["product_id"] == product_id
    assert row["match_evidence"]["classification"] == "possible_match"
    assert row["product_title"]
    assert body["total"] >= 1


def test_match_review_queue_pagination_validation(admin_client):
    assert admin_client.get("/api/admin/match-review-queue?limit=0").status_code == 422
    assert admin_client.get("/api/admin/match-review-queue?limit=201").status_code == 422
    assert admin_client.get("/api/admin/match-review-queue?offset=-1").status_code == 422
    ok = admin_client.get("/api/admin/match-review-queue?limit=1&offset=0")
    assert ok.status_code == 200
    assert len(ok.json()["items"]) <= 1


def test_resolve_approve_promotes_to_verified(admin_client, db, product_id):
    obs = _insert_obs(db, product_id, match_classification="possible_match",
                      verification="provider_observed", verified_by_admin=0)

    response = admin_client.post(
        f"/api/admin/match-review/{obs}/resolve",
        json={"decision": "approve", "note": "checked on retailer site"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["resolved"] is True
    assert body["observation"]["observation_status"] == "live"
    assert body["observation"]["verification_status"] == "verified"
    assert "review:approve" in body["observation"]["verification_notes"]

    # No longer in the queue.
    queue = admin_client.get("/api/admin/match-review-queue").json()
    assert all(r["id"] != obs for r in queue["items"])

    # Now eligible as the cheapest offer.
    offers = cos.get_eligible_offers(product_id)
    assert any(o["observation_id"] == obs for o in offers)


def test_resolve_reject_flags_and_excludes(admin_client, db, product_id):
    obs = _insert_obs(db, product_id, match_classification="possible_match",
                      verification="provider_observed", verified_by_admin=0)

    response = admin_client.post(
        f"/api/admin/match-review/{obs}/resolve", json={"decision": "reject"}
    )
    assert response.status_code == 200
    obs_body = response.json()["observation"]
    assert obs_body["observation_status"] == "flagged"
    assert obs_body["verification_status"] == "review_required"
    assert "review:reject" in obs_body["verification_notes"]

    # History retained — the row still exists.
    with get_connection(db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM retail_price_observation WHERE id = ?", (obs,)
        ).fetchone()[0]
    assert count == 1

    assert cos.get_cheapest_eligible(product_id) is None


def test_resolve_validation_and_missing_observation(admin_client):
    invalid = admin_client.post(
        "/api/admin/match-review/1/resolve", json={"decision": "maybe"}
    )
    assert invalid.status_code == 422

    unknown = admin_client.post(
        "/api/admin/match-review/999999/resolve", json={"decision": "approve"}
    )
    assert unknown.status_code == 404
    assert "not found" in unknown.json()["detail"]


# ── Collection status ────────────────────────────────────────────────────────

def test_collection_status_requires_authentication(anon_client):
    assert anon_client.get("/api/admin/price-collection/status").status_code == 401


def test_collection_status_never_run_is_honest(admin_client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "COLLECTION_STATS_PATHS", [tmp_path / "missing.json"])
    body = admin_client.get("/api/admin/price-collection/status").json()
    assert body["status"] == "never_run"
    assert body["artifact"] is None
    assert body["last_collection_time"] is None


def test_collection_status_reads_stats_artifact(admin_client, monkeypatch, tmp_path):
    artifact = tmp_path / "stats.json"
    artifact.write_text(
        json.dumps(
            {
                "started_at": "2026-11-11T10:00:00+00:00",
                "finished_at": "2026-11-11T10:05:00+00:00",
                "dry_run": False,
                "totals": {"products_attempted": 26, "observations_stored": 9},
                "error_counts": {"timeout": 1},
                "duration_seconds": 300.5,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(main, "COLLECTION_STATS_PATHS", [artifact])

    body = admin_client.get("/api/admin/price-collection/status").json()
    assert body["status"] == "completed"
    assert body["started_at"] == "2026-11-11T10:00:00+00:00"
    assert body["totals"]["products_attempted"] == 26
    assert body["error_counts"] == {"timeout": 1}
    assert body["duration_seconds"] == 300.5


def test_collection_status_unreadable_artifact_reported(admin_client, monkeypatch, tmp_path):
    artifact = tmp_path / "broken.json"
    artifact.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(main, "COLLECTION_STATS_PATHS", [artifact])
    body = admin_client.get("/api/admin/price-collection/status").json()
    assert body["status"] == "unreadable"
