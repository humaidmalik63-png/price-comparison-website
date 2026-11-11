"""Phase 16.6 Stage 5 tests: price freshness and price history.

Covers:

- configurable freshness thresholds (fresh <24h, aging 24-72h, stale >72h)
- threshold validation and env override
- fresh / aging / stale / unknown classification
- missing timestamps reported as unknown, never guessed
- honest age reporting (hours always included)
- latest observation per retailer with freshness annotation
- full history including superseded rows (retained, never deleted)
- price change between observations, lowest / highest / average
- price trend; single data point has no trend and no average
- last successful collection time
- no synthetic history / no interpolation (counts match stored rows)
"""

from datetime import datetime, timedelta, timezone

import pytest

from src.database.connection import get_connection
from src.scripts import collect_pi_observations as collector
from src.services import freshness_service as freshness
from src.services import price_intelligence as pi
from src.services.freshness_service import (
    AGING,
    FRESH,
    FreshnessPolicy,
    STALE,
    UNKNOWN,
    classify_freshness,
    observation_age_hours,
)


@pytest.fixture
def db(monkeypatch, fresh_seeded_db):
    monkeypatch.setattr(pi, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))
    return fresh_seeded_db


def _insert_obs(conn, pid, retailer, price, created_at, status="live",
                verification="provider_observed"):
    cursor = conn.execute(
        """
        INSERT INTO retail_price_observation
        (product_id, retailer, product_url, observed_price, observation_type,
         observation_status, verification_status, created_at, updated_at,
         currency, provider_name)
        VALUES (?, ?, 'https://retailer.example/x', ?, 'live', ?, ?, ?, ?, 'INR', 'priceinindia')
        """,
        (pid, retailer, price, status, verification, created_at, created_at),
    )
    return cursor.lastrowid


def _now():
    return datetime.now(timezone.utc)


# ── Freshness policy ─────────────────────────────────────────────────────────

def test_policy_defaults_match_suggested_thresholds():
    policy = FreshnessPolicy()
    assert policy.fresh_hours == 24
    assert policy.aging_hours == 72


def test_policy_is_configurable():
    policy = FreshnessPolicy(fresh_hours=12, aging_hours=48)
    assert classify_freshness(10, policy) == FRESH
    assert classify_freshness(20, policy) == AGING
    assert classify_freshness(50, policy) == STALE


def test_policy_rejects_invalid_thresholds():
    with pytest.raises(ValueError):
        FreshnessPolicy(fresh_hours=0, aging_hours=72)
    with pytest.raises(ValueError):
        FreshnessPolicy(fresh_hours=72, aging_hours=72)


def test_policy_from_env(monkeypatch):
    monkeypatch.setenv("PRICEWISE_FRESH_HOURS", "6")
    monkeypatch.setenv("PRICEWISE_AGING_HOURS", "18")
    policy = FreshnessPolicy.from_env()
    assert policy.fresh_hours == 6.0
    assert policy.aging_hours == 18.0


def test_classification_buckets():
    assert classify_freshness(1.0) == FRESH
    assert classify_freshness(24.0) == FRESH          # boundary: within 24h
    assert classify_freshness(24.5) == AGING
    assert classify_freshness(72.0) == AGING          # boundary: within 72h
    assert classify_freshness(72.1) == STALE
    assert classify_freshness(None) == UNKNOWN


def test_missing_timestamp_is_unknown_never_guessed():
    assert observation_age_hours(None) is None
    assert observation_age_hours("") is None
    assert observation_age_hours("not-a-date") is None
    assert classify_freshness(observation_age_hours("garbage")) == UNKNOWN


def test_annotate_reports_age_honestly():
    ts = (_now() - timedelta(hours=30)).isoformat()
    row = freshness.annotate({"created_at": ts})
    assert row["freshness"] == AGING
    assert 29.9 < row["observed_age_hours"] < 30.1


def test_future_timestamp_classified_fresh():
    ts = (_now() + timedelta(hours=1)).isoformat()
    assert classify_freshness(observation_age_hours(ts)) == FRESH


# ── History: latest per retailer, freshness, full history ────────────────────

def test_latest_observation_per_retailer_annotated_with_freshness(db):
    fresh_ts = (_now() - timedelta(hours=2)).isoformat()
    stale_ts = (_now() - timedelta(hours=100)).isoformat()
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
        _insert_obs(conn, pid, "Nykaa", 465.0, stale_ts)
        _insert_obs(conn, pid, "Nykaa", 460.0, fresh_ts)   # newest wins
        _insert_obs(conn, pid, "Tira", 470.0, fresh_ts)
        # older superseded row for a third retailer
        _insert_obs(conn, pid, "mynt.ra", 480.0, stale_ts, status="superseded")

    latest = pi.get_latest_observation_per_retailer(pid)
    by_retailer = {r["retailer"]: r for r in latest}

    assert set(by_retailer) == {"Nykaa", "Tira", "mynt.ra"}
    assert by_retailer["Nykaa"]["observed_price"] == 460.0
    assert by_retailer["Nykaa"]["freshness"] == FRESH
    assert by_retailer["mynt.ra"]["freshness"] == STALE
    assert by_retailer["mynt.ra"]["observation_status"] == "superseded"


def test_full_price_history_includes_superseded_with_price_changes(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
        _insert_obs(conn, pid, "Nykaa", 465.0, "2026-11-01T00:00:00+00:00")
        _insert_obs(conn, pid, "Nykaa", 449.0, "2026-11-02T00:00:00+00:00", status="superseded")
        _insert_obs(conn, pid, "Tira", 479.0, "2026-11-03T00:00:00+00:00")

    full = pi.get_full_price_history(pid)
    assert len(full) == 3
    assert full[0].price_change is None
    assert full[1].price_change == -16.0   # 449 - 465
    assert full[2].price_change == 30.0    # 479 - 449
    assert full[1].observation_status == "superseded"  # history retained

    # The 16.5.2-facing view still excludes superseded rows.
    short = pi.get_observation_price_history(pid)
    assert len(short) == 2
    assert all(h.observation_status != "superseded" for h in short)


def test_history_has_no_synthetic_points(db):
    """History length must equal stored rows — no interpolation."""
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
        for i in range(4):
            _insert_obs(conn, pid, "Nykaa", 400.0 + i, f"2026-11-0{i + 1}T00:00:00+00:00")

    full = pi.get_full_price_history(pid)
    assert len(full) == 4


# ── Summary statistics ───────────────────────────────────────────────────────

def test_summary_low_high_average_trend(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
        _insert_obs(conn, pid, "Nykaa", 500.0, "2026-11-01T00:00:00+00:00")
        _insert_obs(conn, pid, "Nykaa", 450.0, "2026-11-02T00:00:00+00:00", status="superseded")
        _insert_obs(conn, pid, "Tira", 475.0, "2026-11-03T00:00:00+00:00")

    summary = pi.get_price_history_summary(pid)
    assert summary["valid_price_count"] == 3
    assert summary["lowest_observed"] == 450.0
    assert summary["highest_observed"] == 500.0
    assert summary["average_observed"] == round((500 + 450 + 475) / 3, 2)
    assert summary["trend"] == "falling"   # 475 < 500 across the series
    assert summary["first_observed_at"].startswith("2026-11-01")
    assert summary["last_collection_time"].startswith("2026-11-03")


def test_summary_single_point_has_no_trend_or_average(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
        _insert_obs(conn, pid, "Nykaa", 465.0, "2026-11-01T00:00:00+00:00")

    summary = pi.get_price_history_summary(pid)
    assert summary["valid_price_count"] == 1
    assert summary["average_observed"] is None
    assert summary["trend"] is None
    assert summary["lowest_observed"] == 465.0


def test_summary_no_observations(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
    summary = pi.get_price_history_summary(pid)
    assert summary["observation_count"] == 0
    assert summary["lowest_observed"] is None
    assert summary["trend"] is None
    assert summary["last_collection_time"] is None


def test_last_collection_time_scoped_and_global(db):
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
        other = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' "
            "AND id != ? LIMIT 1",
            (pid,),
        ).fetchone()["id"]
        _insert_obs(conn, pid, "Nykaa", 465.0, "2026-11-01T00:00:00+00:00")
        _insert_obs(conn, other, "Tira", 470.0, "2026-11-05T00:00:00+00:00")

    assert pi.get_last_collection_time(pid).startswith("2026-11-01")
    assert pi.get_last_collection_time().startswith("2026-11-05")


def test_freshness_distribution_over_observations(db):
    now = _now()
    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 AND category != 'Beauty' LIMIT 1"
        ).fetchone()
        pid = row["id"]
        _insert_obs(conn, pid, "Nykaa", 465.0, (now - timedelta(hours=1)).isoformat())
        _insert_obs(conn, pid, "Tira", 470.0, (now - timedelta(hours=48)).isoformat())
        _insert_obs(conn, pid, "mynt.ra", 480.0, (now - timedelta(hours=200)).isoformat())

    with get_connection(db) as conn:
        rows = [dict(r) for r in conn.execute(
            "SELECT created_at FROM retail_price_observation WHERE product_id = ?", (pid,)
        ).fetchall()]

    dist = freshness.freshness_distribution(rows)
    assert dist["total"] == 3
    assert dist["counts"] == {FRESH: 1, AGING: 1, STALE: 1, UNKNOWN: 0}
    assert dist["policy"]["fresh_hours"] == 24
    assert dist["policy"]["aging_hours"] == 72


def test_collector_store_observation_uses_parsed_timestamps(db):
    """End-to-end: observation stored via collector has parsable created_at."""
    products = collector.load_discovery_catalog(db_path=db)
    pid = products[0]["id"]
    collector.store_observation(
        pid,
        {"id": "pi-x", "title": "t", "store": "Nykaa", "price": 465.0,
         "productPageUrl": "https://www.nykaa.com/x"},
        collector.match_pi_result_to_product(
            {"id": "pi-x", "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
             "brand": "Dot & Key", "store": "Nykaa"},
            {"id": pid, "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++",
             "brand": "Dot & Key", "category": "Sunscreens",
             "specs": {"Net Quantity": "50 g"}},
        ),
        db_path=db,
    )

    with get_connection(db) as conn:
        row = conn.execute(
            "SELECT created_at FROM retail_price_observation WHERE product_id = ?", (pid,)
        ).fetchone()
    assert freshness.classify_freshness(observation_age_hours(row["created_at"])) == FRESH
