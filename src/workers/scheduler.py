"""Scheduled maintenance worker for PriceWise AI (Phase 14 Stage E).

This module implements the recurring background work the product depends on:

1. **Price refresh** — re-checks tracked / watched products through the
   retailer adapters. It only ever records prices that an authorised source
   actually returned. When no authorised source is configured (the default),
   the refresh records an explicit ``unavailable`` / ``restricted`` outcome in
   ``price_check_logs`` and leaves the existing price untouched. It never
   invents, interpolates or extrapolates a price.
2. **Watchlist / tracking checks** — evaluates the alert rules for active
   price-tracking records so that a target-price or meaningful-drop alert is
   raised even when no browser is open.
3. **Expired deal cleanup** — expires stale cached live comparisons and
   retires alert records that are older than the retention window, so the
   catalogue never shows a "deal" that was observed weeks ago.

Deployment
----------
The worker is a plain command, so it can be run by any scheduler. The
recommended architecture for this project is a **Render Cron Job** service
(see ``render.yaml`` and ``docs/PHASE14_SCHEDULER_SETUP.md``) that executes::

    python -m src.workers.scheduler --once

A single run performs one full cycle and exits, which is exactly the contract
a cron scheduler expects. ``--interval`` runs a loop instead, for a dedicated
long-running worker service.

The worker is **not** started automatically by the API process: the API is a
request/response service and should not run background jobs.
"""

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from src.database.connection import get_connection, migrate_db
from src.database.models import Product

logger = logging.getLogger("pricewise.scheduler")

# How long a live comparison result stays fresh before it is treated as stale.
COMPARISON_FRESHNESS_SECONDS = 6 * 60 * 60  # 6 hours

# How long a price alert stays actionable before it is retired.
ALERT_RETENTION_DAYS = 30

# Maximum products refreshed in a single cycle, to keep the run bounded.
DEFAULT_REFRESH_LIMIT = 25


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _tracked_product_ids(custom_path: Optional[str] = None) -> List[int]:
    """Return the distinct products that somebody is tracking or watching."""
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT DISTINCT product_id FROM price_tracking
            WHERE status = 'active'
            UNION
            SELECT DISTINCT product_id FROM wishlist
            """
        )
        return [int(row[0]) for row in cursor.fetchall() if row[0] is not None]


def refresh_prices(
    limit: int = DEFAULT_REFRESH_LIMIT,
    custom_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Refresh prices for tracked / watched products through authorised sources.

    Returns a summary. When no retailer credential is configured the summary
    reports ``unavailable`` for every product and **no price is changed**.
    """
    from src.services.price_collection_engine import collect_product_prices

    product_ids = _tracked_product_ids(custom_path)[: max(1, int(limit))]
    summary: Dict[str, Any] = {
        "started_at": _now().isoformat(),
        "products_considered": len(product_ids),
        "prices_updated": 0,
        "unavailable": 0,
        "restricted": 0,
        "errors": 0,
        "results": [],
    }

    for product_id in product_ids:
        try:
            result = collect_product_prices(product_id=product_id, custom_path=custom_path)
        except TypeError:
            # The collector does not accept a custom path; use the default.
            result = collect_product_prices(product_id=product_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Price refresh failed for product %s: %s", product_id, exc)
            summary["errors"] += 1
            continue

        status = str(result.get("status", "unknown"))
        if status == "retrieved":
            summary["prices_updated"] += 1
        elif status == "restricted":
            summary["restricted"] += 1
        elif status in ("unavailable", "unsupported"):
            summary["unavailable"] += 1
        else:
            summary["errors"] += 1

        summary["results"].append(
            {
                "product_id": product_id,
                "status": status,
                "retailer_status": result.get("retailer_status"),
            }
        )

    summary["finished_at"] = _now().isoformat()
    return summary


def evaluate_alerts(custom_path: Optional[str] = None) -> Dict[str, Any]:
    """Evaluate price-tracking alert rules for every active tracking record."""
    from src.services.price_tracking_service import evaluate_tracking_rules

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM price_tracking WHERE status = 'active'")
        tracking_ids = [int(row[0]) for row in cursor.fetchall()]

    summary = {
        "started_at": _now().isoformat(),
        "records_evaluated": len(tracking_ids),
        "alerts_created": 0,
        "errors": 0,
    }

    for tracking_id in tracking_ids:
        try:
            result = evaluate_tracking_rules(tracking_id=tracking_id, custom_path=custom_path)
        except TypeError:
            result = evaluate_tracking_rules(tracking_id=tracking_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Alert evaluation failed for tracking %s: %s", tracking_id, exc)
            summary["errors"] += 1
            continue

        created = result.get("alert_created") or result.get("alerts_created") or 0
        summary["alerts_created"] += int(created or 0)

    summary["finished_at"] = _now().isoformat()
    return summary


def _table_exists(conn, table_name: str) -> bool:
    """Return True when a table exists in the current connection."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        )
        return cursor.fetchone() is not None
    except Exception:  # pragma: no cover - defensive
        return False


def cleanup_expired(custom_path: Optional[str] = None) -> Dict[str, Any]:
    """Retire stale alerts and prune expired live price-check evidence.

    * Alerts older than ``ALERT_RETENTION_DAYS`` are marked as expired so the
      UI stops presenting them as actionable.
    * ``price_check_logs`` rows older than the freshness window are pruned so
      the audit trail does not imply a recent observation.
    """
    cutoff = _now() - timedelta(days=ALERT_RETENTION_DAYS)
    summary = {"started_at": _now().isoformat(), "alerts_expired": 0, "logs_pruned": 0}

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()

        try:
            cursor.execute(
                "UPDATE price_alerts SET is_read = 1 WHERE created_at < ?", (cutoff.strftime("%Y-%m-%d %H:%M:%S"),)
            )
            summary["alerts_expired"] = cursor.rowcount or 0
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not expire stale alerts: %s", exc)

        try:
            if _table_exists(conn, "price_check_logs"):
                stale_cutoff = _now() - timedelta(seconds=COMPARISON_FRESHNESS_SECONDS * 8)
                cursor.execute(
                    "DELETE FROM price_check_logs WHERE checked_at < ?",
                    (stale_cutoff.strftime("%Y-%m-%d %H:%M:%S"),),
                )
                summary["logs_pruned"] = cursor.rowcount or 0
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Could not prune stale price check logs: %s", exc)

    summary["finished_at"] = _now().isoformat()
    return summary


def run_cycle(
    refresh_limit: int = DEFAULT_REFRESH_LIMIT,
    custom_path: Optional[str] = None,
    do_refresh: bool = True,
) -> Dict[str, Any]:
    """Run one full maintenance cycle."""
    migrate_db(custom_path)

    cycle: Dict[str, Any] = {"started_at": _now().isoformat()}

    if do_refresh:
        cycle["refresh"] = refresh_prices(limit=refresh_limit, custom_path=custom_path)
    else:
        cycle["refresh"] = {"skipped": True}

    cycle["alerts"] = evaluate_alerts(custom_path=custom_path)
    cycle["cleanup"] = cleanup_expired(custom_path=custom_path)
    cycle["finished_at"] = _now().isoformat()
    return cycle


def main(argv: Optional[List[str]] = None) -> int:
    """Command line entry point used by the scheduler."""
    parser = argparse.ArgumentParser(
        description="PriceWise AI scheduled maintenance worker"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle and exit (default).",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=0,
        metavar="SECONDS",
        help="Loop with this interval instead of running once.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_REFRESH_LIMIT,
        help="Maximum products to refresh per cycle.",
    )
    parser.add_argument(
        "--skip-refresh",
        action="store_true",
        help="Only evaluate alerts and clean up (no retailer traffic).",
    )
    parser.add_argument(
        "--custom-path",
        default=None,
        help="Optional SQLite database path (defaults to the configured database).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if args.interval and args.interval > 0:
        while True:
            cycle = run_cycle(
                refresh_limit=args.limit,
                custom_path=args.custom_path,
                do_refresh=not args.skip_refresh,
            )
            print(json.dumps(cycle, indent=2, default=str))
            time.sleep(args.interval)

    cycle = run_cycle(
        refresh_limit=args.limit,
        custom_path=args.custom_path,
        do_refresh=not args.skip_refresh,
    )
    print(json.dumps(cycle, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
