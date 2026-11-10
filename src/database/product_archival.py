"""Explicit product archival policy (Phase 14 Stage 2.5 — FIX 2).

This module owns *business data*: which catalogue records are visible to
customers. It is deliberately separate from the schema migration runner in
``src.database.connection`` so that re-running a migration can never change
the archival state of the catalogue.

Design rules enforced here
--------------------------
1. **Explicit identifiers only.** Every operation takes a concrete list of
   product IDs. A product is never archived or restored because its ID is
   greater than (or less than) some numeric threshold.
2. **Idempotent.** Applying an operation twice leaves the database in exactly
   the same state, so the module is safe to run repeatedly.
3. **Non-destructive.** Archival only flips the ``is_active`` flag. Rows are
   never deleted, so offers, price history, reviews, wishlist entries and
   price-tracking records keep their foreign-key references intact.
4. **Auditable.** Every call returns a summary describing which IDs were
   found, which changed and which were already in the requested state.

Usage
-----
Apply the default archival set (the legacy non-beauty demonstration records
and the two test fixtures retained for referential integrity)::

    python -m src.database.product_archival --apply-default

Target a specific SQLite file (used by tests and local tooling)::

    python -m src.database.product_archival --apply-default --custom-path data/pricewise.db

Archive or restore an explicit set of IDs::

    python -m src.database.product_archival --archive 1 2 3
    python -m src.database.product_archival --restore 1 2 3
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Iterable, Optional

from src.database.connection import get_connection, get_database_engine_type

# ------------------------------------------------------------------------------
# Explicit archival sets
# ------------------------------------------------------------------------------
# Legacy non-beauty demonstration products (laptops, smartphones, audio,
# gaming, wearables, monitors, cameras, TVs) that shipped with the original
# academic prototype. They are retained in the database for referential
# integrity but hidden from customer-facing discovery.
LEGACY_TECH_PRODUCT_IDS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11)

# Test fixtures retained for referential-integrity testing.
LEGACY_TEST_FIXTURE_PRODUCT_IDS: tuple[int, ...] = (998, 999)

# The complete explicit archival set applied by migration 001.
DEFAULT_ARCHIVED_PRODUCT_IDS: tuple[int, ...] = (
    LEGACY_TECH_PRODUCT_IDS + LEGACY_TEST_FIXTURE_PRODUCT_IDS
)


def _normalise_ids(product_ids: Iterable[int] | None) -> list[int]:
    """Return a sorted, de-duplicated list of positive integer product IDs."""
    if not product_ids:
        return []
    normalised: set[int] = set()
    for raw_id in product_ids:
        try:
            value = int(raw_id)
        except (TypeError, ValueError):
            continue
        if value > 0:
            normalised.add(value)
    return sorted(normalised)


def _is_active_value(value) -> bool:
    """Interpret a stored ``is_active`` value as a boolean.

    SQLite stores 0/1, PostgreSQL stores TRUE/FALSE, and a NULL is treated as
    active so that legacy rows are never silently hidden.
    """
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    try:
        return int(value) != 0
    except (TypeError, ValueError):
        return bool(value)


def _boolean_literal(active: bool, custom_path: Optional[str]) -> str:
    """Return the engine-appropriate SQL literal for a boolean value."""
    engine = get_database_engine_type() if not custom_path else "sqlite"
    if engine == "postgresql":
        return "TRUE" if active else "FALSE"
    return "1" if active else "0"


def _set_active_state(
    product_ids: list[int],
    active: bool,
    custom_path: Optional[str] = None,
) -> dict:
    """Set the ``is_active`` flag for exactly the given product IDs.

    Rows that are not in ``product_ids`` are never touched.
    """
    summary = {
        "requested_ids": list(product_ids),
        "found_ids": [],
        "changed_ids": [],
        "unchanged_ids": [],
        "missing_ids": [],
        "active_state": active,
    }
    if not product_ids:
        return summary

    placeholders = ",".join("?" for _ in product_ids)
    literal = _boolean_literal(active, custom_path)

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT id, is_active FROM products WHERE id IN ({placeholders})",
            product_ids,
        )
        rows = cursor.fetchall()

        found: dict[int, bool] = {}
        for row in rows:
            product_id = int(row["id"])
            found[product_id] = _is_active_value(row["is_active"])

        summary["found_ids"] = sorted(found.keys())
        summary["missing_ids"] = [pid for pid in product_ids if pid not in found]

        to_change = [pid for pid, is_active in found.items() if is_active != active]
        if to_change:
            change_placeholders = ",".join("?" for _ in to_change)
            cursor.execute(
                f"UPDATE products SET is_active = {literal} WHERE id IN ({change_placeholders})",
                to_change,
            )
            summary["changed_ids"] = sorted(to_change)

        summary["unchanged_ids"] = [
            pid for pid in product_ids if pid in found and pid not in summary["changed_ids"]
        ]

    return summary


def archive_products(
    product_ids: Iterable[int],
    custom_path: Optional[str] = None,
) -> dict:
    """Soft-archive exactly the given product IDs.

    Idempotent: products that are already archived are reported as unchanged.
    """
    return _set_active_state(_normalise_ids(product_ids), active=False, custom_path=custom_path)


def restore_products(
    product_ids: Iterable[int],
    custom_path: Optional[str] = None,
) -> dict:
    """Restore (activate) exactly the given product IDs.

    Only the IDs passed in are reactivated. There is no threshold rule and no
    implicit "everything else" behaviour.
    """
    return _set_active_state(_normalise_ids(product_ids), active=True, custom_path=custom_path)


def apply_default_archival(custom_path: Optional[str] = None) -> dict:
    """Apply the explicit default archival set.

    This is the one-time business-data operation originally performed by
    migration 001. It is idempotent and only ever archives the IDs listed in
    ``DEFAULT_ARCHIVED_PRODUCT_IDS``.
    """
    return archive_products(DEFAULT_ARCHIVED_PRODUCT_IDS, custom_path=custom_path)


def get_archival_summary(custom_path: Optional[str] = None) -> dict:
    """Return archival statistics without relying on numeric ranges."""
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, title, is_active FROM products ORDER BY id"
        )
        rows = cursor.fetchall()

    active_ids: list[int] = []
    archived_ids: list[int] = []
    for row in rows:
        product_id = int(row["id"])
        if _is_active_value(row["is_active"]):
            active_ids.append(product_id)
        else:
            archived_ids.append(product_id)

    return {
        "total_products": len(rows),
        "active_count": len(active_ids),
        "archived_count": len(archived_ids),
        "active_ids": active_ids,
        "archived_ids": archived_ids,
        "default_archived_ids": list(DEFAULT_ARCHIVED_PRODUCT_IDS),
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Command line entry point for explicit archival operations."""
    parser = argparse.ArgumentParser(
        description=(
            "Explicit product archival for PriceWise AI. Operates only on the "
            "product IDs provided on the command line."
        )
    )
    parser.add_argument(
        "--apply-default",
        action="store_true",
        help="Apply the explicit default archival set (legacy demo + test fixtures).",
    )
    parser.add_argument(
        "--archive",
        nargs="*",
        type=int,
        default=None,
        metavar="PRODUCT_ID",
        help="Archive exactly these product IDs.",
    )
    parser.add_argument(
        "--restore",
        nargs="*",
        type=int,
        default=None,
        metavar="PRODUCT_ID",
        help="Restore exactly these product IDs.",
    )
    parser.add_argument(
        "--custom-path",
        default=None,
        help="Optional SQLite database path (defaults to the configured database).",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print the current archival summary and exit.",
    )
    args = parser.parse_args(argv)

    results: dict = {}

    if args.summary:
        results["summary"] = get_archival_summary(args.custom_path)
    if args.apply_default:
        results["apply_default"] = apply_default_archival(args.custom_path)
    if args.archive is not None:
        results["archive"] = archive_products(args.archive, args.custom_path)
    if args.restore is not None:
        results["restore"] = restore_products(args.restore, args.custom_path)

    if not results:
        parser.print_help()
        return 0

    print(json.dumps(results, indent=2, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    sys.exit(main())
