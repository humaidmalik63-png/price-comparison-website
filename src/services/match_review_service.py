"""Match Review Service — Phase 16.6 Stage 3 manual review path.

PriceInIndia candidates whose match is not a verified_match (possible_match
or ambiguous_match classifications) are stored as observations but must
never silently become eligible cheapest offers. This service provides:

- list_pending_matches(): paginated queue of observations whose stored
  match evidence is uncertain (classification != verified_match) or whose
  verification is still pending / review_required
- resolve_pending_match(): admin decision path
    - approve  -> observation becomes a verified, live observation
                  (eligible for price intelligence)
    - reject   -> observation is flagged and excluded from eligibility

The matching service itself is never weakened; this service only applies
human decisions on top of stored match evidence. PriceInIndia observations
are never auto-promoted to admin-verified status by collection.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from src.database.connection import get_connection

_DECISIONS = ("approve", "reject")


def _parse_match_result(raw: Optional[str]) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def list_pending_matches(
    limit: int = 50,
    offset: int = 0,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Return observations that need human match review.

    A row is pending review when its stored match classification is not
    verified_match (uncertain identity) or its verification status is
    pending / review_required. Rows already admin-verified are excluded.

    Returns {"items": [...], "total": int, "limit": int, "offset": int}.
    """
    if limit <= 0 or limit > 200:
        raise ValueError("limit must be between 1 and 200")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    where = """
        FROM retail_price_observation ro
        JOIN products p ON p.id = ro.product_id
        WHERE ro.match_result IS NOT NULL
          AND ro.match_result != ''
          AND ro.match_result NOT LIKE '%"classification": "verified_match"%'
          AND ro.verified_by_admin = 0
          AND ro.verification_status != 'verified'
    """
    with get_connection(db_path) as conn:
        total = int(conn.execute(f"SELECT COUNT(*) {where}").fetchone()[0])
        rows = conn.execute(
            f"""
            SELECT ro.id, ro.product_id, ro.retailer, ro.product_url,
                   ro.observed_price, ro.observed_mrp, ro.size_volume,
                   ro.observation_status, ro.verification_status,
                   ro.created_at, ro.updated_at, ro.evidence_notes,
                   ro.evidence_reference, ro.match_result,
                   p.title AS product_title, p.brand AS product_brand,
                   p.category AS product_category
            {where}
            ORDER BY ro.created_at DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()

    items = []
    for r in rows:
        d = dict(r)
        d["match_evidence"] = _parse_match_result(d.pop("match_result"))
        items.append(d)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


def resolve_pending_match(
    observation_id: int,
    decision: str,
    admin_user_id: int | None = None,
    note: str = "",
    db_path: str | None = None,
) -> dict[str, Any]:
    """Apply a human decision to a pending match observation.

    - approve: observation_status -> 'live', verification_status -> 'verified',
      verified_by_admin -> 1 (when admin_user_id provided). The observation
      becomes eligible for price intelligence.
    - reject: observation_status -> 'flagged', verification_status ->
      'review_required'. The observation is excluded from eligibility but
      retained for history (never deleted).

    Returns the updated observation row (without match_result bulk).
    """
    if decision not in _DECISIONS:
        raise ValueError(f"decision must be one of {_DECISIONS}")

    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT id, observation_status, verification_status, verified_by_admin, "
            "verification_notes, evidence_notes "
            "FROM retail_price_observation WHERE id = ?",
            (observation_id,),
        ).fetchone()
        if not row:
            raise LookupError(f"observation {observation_id} not found")

        suffix = f" | review:{decision}"
        if note:
            suffix += f" ({note})"
        if admin_user_id is not None:
            suffix += f" by admin#{admin_user_id}"
        new_notes = ((row["verification_notes"] or "") + suffix).strip(" |")

        if decision == "approve":
            # verified_by_admin is the human-approval flag (0/1): an approval
            # always sets it. admin_user_id is a separate FK reference that is
            # only filled when the admin's user row exists in this database.
            conn.execute(
                """
                UPDATE retail_price_observation
                SET observation_status = 'live',
                    verification_status = 'verified',
                    verified_by_admin = 1,
                    admin_user_id = COALESCE(?, admin_user_id),
                    verification_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (admin_user_id, new_notes, observation_id),
            )
        else:
            conn.execute(
                """
                UPDATE retail_price_observation
                SET observation_status = 'flagged',
                    verification_status = 'review_required',
                    verification_notes = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (new_notes, observation_id),
            )

        updated = conn.execute(
            "SELECT id, product_id, retailer, product_url, observed_price, "
            "observation_status, verification_status, verified_by_admin, "
            "verification_notes, updated_at "
            "FROM retail_price_observation WHERE id = ?",
            (observation_id,),
        ).fetchone()

    return dict(updated)
