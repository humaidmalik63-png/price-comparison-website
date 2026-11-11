"""Cheapest Offer Eligibility Service — Phase 16.6 Stage 6.

Decides which price observations may participate in live cheapest-offer
rankings, and computes the cheapest eligible offer with fully disclosed
input assumptions.

Eligibility rules (all exclusions are recorded, never silent):

1. Demo prices never participate in live rankings (this service works
   exclusively over retail_price_observation — demo offers are not
   observations).
2. Rejected matches are excluded: the stored match classification must be
   verified_match, or possible_match that an admin has verified
   (verification_status='verified'). Un-reviewed possible_match and every
   ambiguous/incompatible classification are excluded (Stage 3 rule 8).
3. Incompatible variants are excluded by the same classification gate:
   the matching service hard-conflict rules enforce same size / shade /
   formulation / concentration before a match can be verified, so a lower
   price for a different quantity or variant can never win.
4. Invalid prices are excluded (price must be > 0 and finite).
5. Unsupported currencies are excluded — only INR participates; foreign
   currencies are never converted.
6. Missing or invalid retailer URLs are excluded when the application
   requires a purchase link (configurable).
7. Stale prices are excluded from CURRENT-price rankings according to the
   configured freshness policy (default: older than 72h). Stale rows stay
   available in history views.
8. Catalog-verified and provider-observed prices are kept clearly
   distinguishable through verification_status / source attribution in
   every returned row.

Unit price normalisation (INR/ml, INR/g, INR/unit) is computed only when a
comparable quantity is known; incompatible units are never compared.
Discounts are computed only against a real observed MRP — never invented.
"""

from __future__ import annotations

import json
import math
from typing import Any, Optional

from src.database.connection import get_connection
from src.services import freshness_service as freshness
from src.services.freshness_service import FreshnessPolicy
from src.services.product_matching_service import (
    MatchClassification,
    parse_quantity_volume,
)

INR = "INR"

EXCLUSION_REASONS = {
    "invalid_price": "Observed price is missing, non-numeric or not positive",
    "unsupported_currency": "Currency is not INR and prices are never converted",
    "currency_missing": "Provider did not state a currency",
    "not_current": "Observation is not the current live row for the retailer",
    "match_unverified": "Match classification is not verified and not admin-approved",
    "match_rejected": "Match was rejected or flagged (incompatible/ambiguous)",
    "stale": "Observation is older than the configured freshness policy allows",
    "missing_retailer_url": "No retailer product URL while a purchase link is required",
    "invalid_retailer_url": "Retailer URL is not a usable http(s) link",
}

ASSUMPTIONS = [
    "Only INR prices participate; foreign currencies are excluded, never converted.",
    "Only the latest live observation per retailer participates; superseded and "
    "expired rows are history.",
    "Stale observations (older than the configured aging threshold) are excluded "
    "from current-price rankings.",
    "Only verified matches, or possible matches explicitly approved by an admin, "
    "are eligible — unreviewed and ambiguous matches never win.",
    "Eligibility requires an identity match, which enforces the same quantity, "
    "shade, formulation and concentration as the catalog product.",
    "Unit prices are computed only when a comparable quantity is known "
    "(INR per g / ml / unit).",
    "Discounts are computed only against a provider-observed MRP; original "
    "prices are never invented.",
]


def parse_match_evidence(match_result: Optional[str]) -> dict[str, Any]:
    if not match_result:
        return {}
    try:
        data = json.loads(match_result)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _is_valid_url(url: Optional[str]) -> bool:
    return bool(url) and str(url).strip().lower().startswith(("http://", "https://"))


def evaluate_eligibility(
    observation: dict[str, Any],
    *,
    require_url: bool = True,
    policy: Optional[FreshnessPolicy] = None,
    now: Any = None,
) -> tuple[bool, list[str]]:
    """Return (eligible, exclusion_reasons) for one observation dict.

    The observation must include observed_price, currency,
    observation_status, verification_status, created_at, product_url and
    (optionally) match_result JSON.
    """
    policy = policy or freshness.DEFAULT_POLICY
    reasons: list[str] = []

    # 4. Invalid price
    price = observation.get("observed_price")
    try:
        price = float(price) if price is not None else None
    except (TypeError, ValueError):
        price = None
    if price is None or not math.isfinite(price) or price <= 0:
        reasons.append("invalid_price")

    # 5. Currency (honest: never converted)
    currency = observation.get("currency")
    if currency is None or not str(currency).strip():
        reasons.append("currency_missing")
    elif str(currency).strip().upper() != INR:
        reasons.append("unsupported_currency")

    # 2./7. Only the current live row participates in current rankings
    if observation.get("observation_status") != "live":
        reasons.append("not_current")

    # 2. Match gate — verified or admin-approved possible match only
    evidence = parse_match_evidence(observation.get("match_result"))
    classification = evidence.get("classification")
    verification_status = observation.get("verification_status")
    admin_verified = verification_status == "verified" or (
        bool(observation.get("verified_by_admin"))
    )
    if classification == MatchClassification.VERIFIED_MATCH:
        pass  # verified identity
    elif classification == MatchClassification.POSSIBLE_MATCH and admin_verified:
        pass  # human-approved
    elif classification in (
        MatchClassification.INCOMPATIBLE_MISMATCH,
        MatchClassification.AMBIGUOUS_MATCH,
    ):
        reasons.append("match_rejected")
    elif classification is None:
        # No match evidence at all: only an admin-verified row may pass.
        if not admin_verified:
            reasons.append("match_unverified")
    else:
        reasons.append("match_unverified")

    # 7. Freshness — stale prices excluded from CURRENT rankings
    age = freshness.observation_age_hours(observation.get("created_at"), now=now)
    if age is None:
        pass  # unknown age cannot be proven stale; flagged via disclosure
    elif age > policy.aging_hours:
        reasons.append("stale")

    # 6. Retailer URL
    url = observation.get("product_url")
    if require_url:
        if not url:
            reasons.append("missing_retailer_url")
        elif not _is_valid_url(url):
            reasons.append("invalid_retailer_url")

    return (len(reasons) == 0, reasons)


def _normalise_unit_price(
    price: Optional[float], size_volume: Optional[str]
) -> tuple[Optional[float], Optional[str]]:
    """Unit price (INR per g/ml/unit) plus the unit, or (None, None)."""
    if price is None or price <= 0 or not size_volume:
        return None, None
    value, unit = parse_quantity_volume(str(size_volume))
    if value is None or value <= 0 or not unit:
        return None, None
    return round(price / value, 4), unit


def get_eligible_offers(
    product_id: int,
    *,
    require_url: bool = True,
    policy: Optional[FreshnessPolicy] = None,
    db_path: str | None = None,
    now: Any = None,
) -> list[dict[str, Any]]:
    """Latest observation per retailer, filtered down to eligible ones.

    Every returned row includes freshness fields, match evidence, unit
    price and the eligibility basis. Rows that failed eligibility are NOT
    returned here (use get_excluded_offers for a transparent breakdown).
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ro.id, ro.product_id, ro.retailer, ro.retailer_domain, ro.product_url,
                   ro.observed_price, ro.observed_mrp, ro.currency, ro.provider_name,
                   ro.observation_status, ro.verification_status, ro.verified_by_admin,
                   ro.created_at, ro.size_volume, ro.match_result, ro.evidence_notes
            FROM retail_price_observation ro
            WHERE ro.product_id = ?
              AND ro.id = (
                  SELECT ro2.id FROM retail_price_observation ro2
                  WHERE ro2.product_id = ro.product_id AND ro2.retailer = ro.retailer
                  ORDER BY ro2.created_at DESC, ro2.id DESC LIMIT 1
              )
        """, (product_id,))
        rows = [dict(r) for r in cursor.fetchall()]

    eligible: list[dict[str, Any]] = []
    for row in rows:
        ok, reasons = evaluate_eligibility(
            row, require_url=require_url, policy=policy, now=now
        )
        if not ok:
            continue
        eligible.append(_build_offer(row, policy, now))
    return eligible


def get_excluded_offers(
    product_id: int,
    *,
    require_url: bool = True,
    policy: Optional[FreshnessPolicy] = None,
    db_path: str | None = None,
    now: Any = None,
) -> list[dict[str, Any]]:
    """Latest observation per retailer that failed eligibility, with reasons.

    Provides the transparent "why is this retailer not ranked" breakdown.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ro.id, ro.product_id, ro.retailer, ro.retailer_domain, ro.product_url,
                   ro.observed_price, ro.observed_mrp, ro.currency, ro.provider_name,
                   ro.observation_status, ro.verification_status, ro.verified_by_admin,
                   ro.created_at, ro.size_volume, ro.match_result, ro.evidence_notes
            FROM retail_price_observation ro
            WHERE ro.product_id = ?
              AND ro.id = (
                  SELECT ro2.id FROM retail_price_observation ro2
                  WHERE ro2.product_id = ro.product_id AND ro2.retailer = ro.retailer
                  ORDER BY ro2.created_at DESC, ro2.id DESC LIMIT 1
              )
        """, (product_id,))
        rows = [dict(r) for r in cursor.fetchall()]

    excluded: list[dict[str, Any]] = []
    for row in rows:
        ok, reasons = evaluate_eligibility(
            row, require_url=require_url, policy=policy, now=now
        )
        if ok:
            continue
        annotated = freshness.annotate(row, policy=policy or freshness.DEFAULT_POLICY, now=now)
        annotated["exclusion_reasons"] = reasons
        annotated["exclusion_details"] = {
            r: EXCLUSION_REASONS.get(r, r) for r in reasons
        }
        excluded.append(annotated)
    return excluded


def _build_offer(
    row: dict[str, Any], policy: FreshnessPolicy | None, now: Any
) -> dict[str, Any]:
    policy = policy or freshness.DEFAULT_POLICY
    annotated = freshness.annotate(row, policy=policy, now=now)
    evidence = parse_match_evidence(row.get("match_result"))
    unit_price, unit = _normalise_unit_price(
        annotated.get("observed_price"), annotated.get("size_volume")
    )
    discount: Optional[float] = None
    mrp = annotated.get("observed_mrp")
    price = annotated.get("observed_price")
    if mrp and mrp > 0 and price and mrp > price:
        discount = round(((mrp - price) / mrp) * 100, 1)

    return {
        "observation_id": row["id"],
        "product_id": row["product_id"],
        "retailer": row["retailer"],
        "retailer_domain": row.get("retailer_domain"),
        "retailer_url": row.get("product_url") or "",
        "price": row["observed_price"],
        "currency": row.get("currency"),
        "mrp": row.get("observed_mrp"),
        "discount_pct": discount,
        "unit_price": unit_price,
        "unit": unit,
        "provider_name": row.get("provider_name"),
        "source_attribution": row.get("evidence_notes"),
        "observation_status": row.get("observation_status"),
        "verification_status": row.get("verification_status"),
        "verified_by_admin": bool(row.get("verified_by_admin")),
        "match_classification": evidence.get("classification"),
        "match_confidence": evidence.get("confidence"),
        "requires_human_review": bool(evidence.get("requires_human_review")),
        "observed_at": row.get("created_at"),
        "observed_age_hours": annotated["observed_age_hours"],
        "freshness": annotated["freshness"],
        "size_volume": row.get("size_volume"),
        "eligibility_basis": "verified_match"
        if evidence.get("classification") == MatchClassification.VERIFIED_MATCH
        else "admin_verified",
    }


def get_cheapest_eligible(
    product_id: int,
    *,
    require_url: bool = True,
    policy: Optional[FreshnessPolicy] = None,
    db_path: str | None = None,
    now: Any = None,
) -> Optional[dict[str, Any]]:
    """Single cheapest eligible offer for a product, or None.

    Discloses the input assumptions with every result.
    """
    offers = get_eligible_offers(
        product_id, require_url=require_url, policy=policy, db_path=db_path, now=now
    )
    if not offers:
        return None
    cheapest = min(offers, key=lambda o: o["price"])
    cheapest = dict(cheapest)
    cheapest["assumptions"] = list(ASSUMPTIONS)
    return cheapest


def get_catalog_cheapest_eligible(
    *,
    limit: int = 200,
    offset: int = 0,
    require_url: bool = True,
    policy: Optional[FreshnessPolicy] = None,
    db_path: str | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Cheapest eligible offer per product across the active beauty catalogue.

    Paginated. Only products with at least one eligible offer appear —
    products without eligible offers are honestly absent (not demo-filled).
    """
    if limit <= 0 or limit > 500:
        raise ValueError("limit must be between 1 and 500")
    if offset < 0:
        raise ValueError("offset must be >= 0")

    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, sku, title, brand, category FROM products
            WHERE is_active = 1
            ORDER BY id LIMIT ? OFFSET ?
            """,
            (limit, offset),
        )
        products = cursor.fetchall()
        total = int(conn.execute(
            "SELECT COUNT(*) FROM products WHERE is_active = 1"
        ).fetchone()[0])

    items: list[dict[str, Any]] = []
    for product in products:
        cheapest = get_cheapest_eligible(
            product["id"], require_url=require_url, policy=policy,
            db_path=db_path, now=now,
        )
        if cheapest is None:
            continue
        items.append(
            {
                "product_id": product["id"],
                "sku": product["sku"],
                "title": product["title"],
                "brand": product["brand"],
                "category": product["category"],
                "cheapest_offer": cheapest,
            }
        )
    return {
        "items": items,
        "total_products": total,
        "products_with_eligible_offers": len(items),
        "limit": limit,
        "offset": offset,
        "assumptions": list(ASSUMPTIONS),
    }
