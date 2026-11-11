"""Scheduler-Ready Service Interface — Phase 16.6 Stage 9.

Provides a plain, explicit job registry that a production scheduler
(APScheduler, cron, Celery beat, etc.) could consume later.

IMPORTANT (Phase 16.6 constraint): **no scheduler exists in this
application and none is started by this module.** Importing this module
has zero side effects: no threads, no processes, no timers, no network
calls. The registry below is data + callables. A job only ever runs when
something *explicitly* invokes its callable (a human, a CLI command, or a
future, separately approved scheduler process).

Design rules:

- Every job is a small function with an explicit ``db_path`` argument and
  no hidden global state; it returns a serialisable stats dict.
- Jobs never delete observations or history; the only status transitions
  are the lifecycle ones defined in earlier stages (expire/supersede).
- The dry-run mode of the discovery job performs provider calls but never
  writes, so it is safe to exercise the pipeline without approval.
- Failure containment: each job captures exceptions and reports them in
  its result dict instead of raising, so a scheduler loop would not crash
  on a single failing job.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger("pricewise.scheduler_interface")

# No scheduling library is imported or required here — the interface is
# intentionally dependency-free.


@dataclass(frozen=True)
class ScheduledJob:
    """Definition of one scheduler-ready job."""

    name: str
    description: str
    interval_minutes: int
    enabled_by_default: bool
    requires_approval_note: str
    handler: Callable[..., dict[str, Any]]
    default_kwargs: dict[str, Any] = field(default_factory=dict)


def run_collection_job(
    *,
    db_path: Optional[str] = None,
    limit: Optional[int] = None,
    dry_run: bool = True,
    force: bool = False,
    pacing_seconds: float | None = None,
    save_stats: bool = True,
) -> dict[str, Any]:
    """Scheduled job: controlled PriceInIndia discovery cycle.

    Defaults to ``dry_run=True`` so wiring the job up can never write the
    application database by accident. A live (non-dry-run) invocation is an
    explicit, approved action — documented in the job registry notes.
    """
    from src.scripts.collect_pi_observations import run_discovery_pipeline

    kwargs: dict[str, Any] = {
        "db_path": db_path,
        "limit": limit,
        "dry_run": dry_run,
        "force": force,
        "save_stats": save_stats,
    }
    if pacing_seconds is not None:
        kwargs["pacing_seconds"] = pacing_seconds
    return run_discovery_pipeline(**kwargs)


def run_expire_stale_job(
    *,
    db_path: Optional[str] = None,
    max_age_hours: int = 72,
) -> dict[str, Any]:
    """Scheduled job: expire live observations older than the policy.

    Only transitions observation_status live -> expired. History rows are
    never deleted.
    """
    from src.services.price_intelligence import expire_stale_observations

    expired = expire_stale_observations(max_age_hours=max_age_hours)
    return {"expired_count": expired, "max_age_hours": max_age_hours, "db_path": db_path or "default"}


def build_freshness_snapshot_job(
    *,
    db_path: Optional[str] = None,
) -> dict[str, Any]:
    """Scheduled job: snapshot the freshness distribution for dashboards."""
    from src.database.connection import get_connection
    from src.services import freshness_service as freshness

    with get_connection(db_path) as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT created_at FROM retail_price_observation "
                "WHERE observation_status = 'live'"
            ).fetchall()
        ]
    distribution = freshness.freshness_distribution(rows)
    return {"db_path": db_path or "default", **distribution}


def run_job_safely(job: ScheduledJob, **overrides: Any) -> dict[str, Any]:
    """Execute one job with failure containment.

    Exceptions are captured into the result (``status: 'error'`` with a
    short, secret-free message) instead of propagating, so an external
    scheduler loop would not crash on a single failing job. Stack traces
    are logged, never returned to API clients.
    """
    kwargs = dict(job.default_kwargs)
    kwargs.update(overrides)
    try:
        result = job.handler(**kwargs)
        return {"job": job.name, "status": "ok", "result": result}
    except Exception as exc:  # noqa: BLE001 - containment is the point
        logger.exception("Scheduled job %s failed", job.name)
        # Never leak secrets or stack traces in the returned payload.
        return {
            "job": job.name,
            "status": "error",
            "error": f"{type(exc).__name__}: {exc}",
        }


def get_scheduled_jobs() -> list[ScheduledJob]:
    """Return the scheduler-ready job registry.

    Nothing in this registry runs on import or on call — a job executes
    only when its handler is explicitly invoked (or via
    :func:`run_job_safely`). No scheduler process exists in this
    application; adopting one is a separate, explicit approval.
    """
    return [
        ScheduledJob(
            name="priceinindia_discovery",
            description=(
                "Controlled PriceInIndia discovery cycle over the beauty "
                "catalogue (pacing-aware, restartable). dry_run=True by "
                "default: provider calls happen, nothing is written."
            ),
            interval_minutes=360,
            enabled_by_default=False,
            requires_approval_note=(
                "Live (non dry-run) collection writes observations and "
                "requires explicit operator approval per the Phase 16.6 "
                "constraints; no scheduler exists to trigger it."
            ),
            handler=run_collection_job,
            default_kwargs={"dry_run": True, "save_stats": False},
        ),
        ScheduledJob(
            name="expire_stale_observations",
            description=(
                "Expire live observations older than the freshness policy "
                "(default 72h). Retains history; never deletes rows."
            ),
            interval_minutes=60,
            enabled_by_default=False,
            requires_approval_note=(
                "Safe (additive lifecycle transition only), but still not "
                "wired to any scheduler in this phase."
            ),
            handler=run_expire_stale_job,
            default_kwargs={"max_age_hours": 72},
        ),
        ScheduledJob(
            name="freshness_snapshot",
            description=(
                "Compute the freshness distribution of live observations "
                "for dashboards. Read-only."
            ),
            interval_minutes=15,
            enabled_by_default=False,
            requires_approval_note="Read-only; safe to run manually.",
            handler=build_freshness_snapshot_job,
            default_kwargs={},
        ),
    ]


def describe_registry() -> dict[str, Any]:
    """Serialisable view of the registry for docs and admin endpoints."""
    return {
        "scheduler_exists": False,
        "jobs_started_on_import": False,
        "jobs": [
            {
                "name": job.name,
                "description": job.description,
                "interval_minutes": job.interval_minutes,
                "enabled_by_default": job.enabled_by_default,
                "requires_approval_note": job.requires_approval_note,
            }
            for job in get_scheduled_jobs()
        ],
    }
