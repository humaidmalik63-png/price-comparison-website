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


def get_match_review_context(
    observation_id: int,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Phase 16.7 Stage 4: full side-by-side context for one match review.

    Returns the catalogue product, the observation/listing, the stored match
    evidence (including the explainable strength overlay when present), a
    field-by-field comparison and the audit trail — so an administrator can
    decide with the evidence in view instead of trusting a confidence number.

    Approval semantics are unchanged: this function only READS context. A
    match approval still never converts an unsupported price into a verified
    observation by itself (resolve_pending_match only sets verification
    flags; eligibility gating is unchanged).
    """
    from src.services.product_matching_service import parse_quantity_volume  # local import: display helper

    with get_connection(db_path) as conn:
        obs = conn.execute(
            """
            SELECT ro.id, ro.product_id, ro.retailer, ro.retailer_domain,
                   ro.product_url, ro.observed_price, ro.observed_mrp,
                   ro.currency, ro.provider_name, ro.size_volume,
                   ro.observation_status, ro.verification_status,
                   ro.verified_by_admin, ro.admin_user_id,
                   ro.created_at, ro.updated_at, ro.evidence_notes,
                   ro.evidence_reference, ro.verification_notes, ro.match_result,
                   p.id AS product_id, p.sku AS product_sku, p.title AS product_title,
                   p.brand AS product_brand, p.category AS product_category,
                   p.specs_json AS product_specs_json
            FROM retail_price_observation ro
            JOIN products p ON p.id = ro.product_id
            WHERE ro.id = ?
            """,
            (observation_id,),
        ).fetchone()
    if not obs:
        raise LookupError(f"observation {observation_id} not found")

    row = dict(obs)
    specs = json.loads(row.pop("product_specs_json") or "{}") if row.get("product_specs_json") else {}
    evidence = _parse_match_result(row.pop("match_result"))

    catalogue_size = (
        str(specs.get("Net Quantity") or specs.get("Size") or "") or None
    )
    cat_val, cat_unit = parse_quantity_volume(catalogue_size or "")
    listing_size = row.get("size_volume")
    list_val, list_unit = parse_quantity_volume(listing_size or "")

    def _qty(val, unit) -> str | None:
        return f"{val}{unit}" if val is not None else None

    comparison = [
        {"field": "brand", "catalogue": row.get("product_brand"), "listing": evidence.get("provider_brand"), "match_evidence": evidence.get("brand_match")},
        {"field": "title", "catalogue": row.get("product_title"), "listing": evidence.get("provider_title"), "match_evidence": evidence.get("title_similarity")},
        {"field": "size", "catalogue": catalogue_size or _qty(cat_val, cat_unit), "listing": listing_size, "match_evidence": evidence.get("size_match")},
        {"field": "shade", "catalogue": None, "listing": evidence.get("offer_shade"), "match_evidence": evidence.get("shade_match"), "catalogue_parsed": evidence.get("target_shade")},
        {"field": "formulation", "catalogue": None, "listing": None, "match_evidence": evidence.get("formulation_match")},
        {"field": "price", "catalogue": None, "listing": row.get("observed_price"), "match_evidence": None, "unit": row.get("currency")},
        {"field": "mrp", "catalogue": None, "listing": row.get("observed_mrp"), "match_evidence": None, "unit": row.get("currency")},
        {"field": "retailer_url", "catalogue": None, "listing": row.get("product_url"), "match_evidence": None},
    ]

    return {
        "observation": {
            "id": row["id"],
            "product_id": row["product_id"],
            "retailer": row.get("retailer"),
            "retailer_domain": row.get("retailer_domain"),
            "provider_name": row.get("provider_name"),
            "product_url": row.get("product_url"),
            "observed_price": row.get("observed_price"),
            "observed_mrp": row.get("observed_mrp"),
            "currency": row.get("currency"),
            "size_volume": row.get("size_volume"),
            "observation_status": row.get("observation_status"),
            "verification_status": row.get("verification_status"),
            "verified_by_admin": bool(row.get("verified_by_admin")),
            "admin_user_id": row.get("admin_user_id"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "evidence_notes": row.get("evidence_notes"),
            "evidence_reference": row.get("evidence_reference"),
        },
        "catalogue_product": {
            "id": row["product_id"],
            "sku": row["product_sku"],
            "title": row["product_title"],
            "brand": row["product_brand"],
            "category": row["product_category"],
            "net_quantity": catalogue_size,
            "specs_keys": sorted(specs.keys()),
        },
        "match_evidence": evidence,
        "comparison": comparison,
        "audit_trail": {
            "verification_notes": row.get("verification_notes"),
            "verified_by_admin": bool(row.get("verified_by_admin")),
            "admin_user_id": row.get("admin_user_id"),
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
        },
        "decision_contract": {
            "approve_effect": "Marks the observation admin-verified; eligibility still requires freshness, valid price, INR currency and a usable retailer URL.",
            "reject_effect": "Flags the observation; it is excluded from eligibility but retained in history.",
            "approval_does_not": "Approval of a match never fabricates price evidence — the stored price remains a provider-observed value with its own provenance.",
        },
    }
