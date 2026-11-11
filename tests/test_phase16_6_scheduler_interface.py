"""Phase 16.6 Stage 9 tests: scheduler-ready service interface.

Guarantees:

- importing the module starts NO threads, timers or processes
- the registry is explicit, serialisable and dependency-free
- the collection job defaults to dry_run (never writes by accident)
- the expire job only transitions live -> expired, retaining history
- the freshness snapshot job is read-only
- run_job_safely contains failures without leaking stack traces
"""

import threading

import pytest

from src.database.connection import get_connection
from src.services import scheduler_interface as si


# ── Import safety: no scheduler, no threads ──────────────────────────────────

def test_module_import_starts_no_threads():
    """Importing the interface must not spawn anything."""
    before = threading.active_count()
    import importlib

    importlib.reload(si)
    assert threading.active_count() == before


def test_registry_declares_no_scheduler():
    description = si.describe_registry()
    assert description["scheduler_exists"] is False
    assert description["jobs_started_on_import"] is False
    assert len(description["jobs"]) == 3
    assert all(job["enabled_by_default"] is False for job in description["jobs"])


def test_every_job_carries_approval_note():
    for job in si.get_scheduled_jobs():
        assert job.requires_approval_note
        assert job.name and job.description
        assert job.interval_minutes > 0


# ── Collection job ───────────────────────────────────────────────────────────

def test_collection_job_defaults_to_dry_run_never_writes(fresh_seeded_db):
    """Default invocation is a dry run: zero writes to the database."""
    with get_connection(fresh_seeded_db) as conn:
        before = conn.execute("SELECT COUNT(*) FROM retail_price_observation").fetchone()[0]

    job = next(j for j in si.get_scheduled_jobs() if j.name == "priceinindia_discovery")
    assert job.default_kwargs["dry_run"] is True

    outcome = si.run_job_safely(
        job, db_path=fresh_seeded_db, limit=2, save_stats=False
    )
    assert outcome["status"] == "ok"
    assert outcome["result"]["dry_run"] is True
    assert outcome["result"]["dry_run_verified_no_writes"] is True

    with get_connection(fresh_seeded_db) as conn:
        after = conn.execute("SELECT COUNT(*) FROM retail_price_observation").fetchone()[0]
    assert before == after


# ── Expire job ───────────────────────────────────────────────────────────────

def test_expire_job_expires_only_old_live_rows_and_keeps_history(fresh_seeded_db, monkeypatch):
    from src.services import price_intelligence as pi

    monkeypatch.setattr(pi, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db))

    with get_connection(fresh_seeded_db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 LIMIT 1"
        ).fetchone()
        pid = row["id"]
        old = "2026-01-01T00:00:00+00:00"
        now_ts = "2099-01-01T00:00:00+00:00"
        for retailer, ts in (("Nykaa", old), ("Tira", now_ts)):
            conn.execute(
                """
                INSERT INTO retail_price_observation
                (product_id, retailer, product_url, observed_price, currency,
                 observation_status, verification_status, created_at, updated_at)
                VALUES (?, ?, 'https://retailer.example/x', 465.0, 'INR',
                        'live', 'provider_observed', ?, ?)
                """,
                (pid, retailer, ts, ts),
            )

    outcome = si.run_job_safely(
        next(j for j in si.get_scheduled_jobs() if j.name == "expire_stale_observations"),
        db_path=fresh_seeded_db,
    )
    assert outcome["status"] == "ok"
    assert outcome["result"]["expired_count"] == 1

    with get_connection(fresh_seeded_db) as conn:
        rows = conn.execute(
            "SELECT retailer, observation_status FROM retail_price_observation WHERE product_id = ?",
            (pid,),
        ).fetchall()
    statuses = {r["retailer"]: r["observation_status"] for r in rows}
    assert statuses["Nykaa"] == "expired"   # old -> expired
    assert statuses["Tira"] == "live"       # fresh -> untouched
    # History retained (row still exists, not deleted).
    assert len(rows) == 2


# ── Freshness snapshot job ───────────────────────────────────────────────────

def test_freshness_snapshot_job_is_read_only(fresh_seeded_db):
    with get_connection(fresh_seeded_db) as conn:
        row = conn.execute(
            "SELECT id FROM products WHERE is_active = 1 LIMIT 1"
        ).fetchone()
        pid = row["id"]
        conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, currency,
             observation_status, verification_status, created_at, updated_at)
            VALUES (?, 'Nykaa', 'https://retailer.example/x', 465.0, 'INR',
                    'live', 'provider_observed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (pid,),
        )

    job = next(j for j in si.get_scheduled_jobs() if j.name == "freshness_snapshot")
    outcome = si.run_job_safely(job, db_path=fresh_seeded_db)
    assert outcome["status"] == "ok"
    assert outcome["result"]["counts"]["fresh"] == 1
    assert outcome["result"]["total"] == 1


# ── Failure containment ──────────────────────────────────────────────────────

def test_run_job_safely_contains_exceptions_without_stack_traces():
    exploding = si.ScheduledJob(
        name="exploding_job",
        description="test",
        interval_minutes=1,
        enabled_by_default=False,
        requires_approval_note="n/a",
        handler=lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom with secret key ABC123")),
        default_kwargs={},
    )
    outcome = si.run_job_safely(exploding)
    assert outcome["status"] == "error"
    assert "boom" in outcome["error"]
    # No stack trace leak in the payload.
    assert "Traceback" not in outcome["error"]
    assert "handler" not in outcome["error"]


def test_collection_job_reports_provider_errors_as_data(fresh_seeded_db, monkeypatch):
    """A failing provider call is data (error_counts), not a raised error."""
    from src.adapters.mcp_adapters.base_mcp_adapter import McpCallResult
    from src.scripts import collect_pi_observations as collector

    class FailingAdapter:
        name = "PriceInIndia"

        class _H:
            total_requests = 1
            failed_requests = 1
            avg_response_time_ms = 0.0
            is_healthy = False
            last_error = "HTTP 503: Service Unavailable"

        health = _H()

        def search_products(self, query, **kwargs):
            return McpCallResult(
                success=False,
                tool_name="search_products",
                error_message="HTTP 503: Service Unavailable",
            )

    monkeypatch.setattr(collector, "PriceInIndiaAdapter", FailingAdapter)

    job = next(j for j in si.get_scheduled_jobs() if j.name == "priceinindia_discovery")
    outcome = si.run_job_safely(
        job, db_path=fresh_seeded_db, limit=1, save_stats=False
    )
    assert outcome["status"] == "ok"
    assert outcome["result"]["error_counts"].get("http_error") == 1
