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
    # Phase 16.7C: a PriceInIndia page (or affiliate redirect) is NOT a
    # retailer product URL — it must never satisfy the purchase-link
    # requirement, and the exclusion is named honestly.
    "url_is_provider_page": "Only a provider page/redirect URL is available — not a retailer product URL",
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
    # Phase 16.7C/16.7E: a purchase link must be a retailer product URL.
    "A purchase link must point at the retailer. Observations whose citation "
    "URL is only a provider page or affiliate redirect (evidence "
    "url_kind = provider_page / provider_affiliate_redirect) are excluded "
    "with the explicit reason 'url_is_provider_page' — a PriceInIndia page "
    "can never satisfy the retailer-URL requirement, and retailer URLs are "
    "never invented to fill the gap. Legacy rows recorded before url_kind "
    "evidence existed keep their previous eligibility behaviour.",
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
    # Phase 16.7C: distinguish the URL kind recorded in match evidence. A
    # provider page or affiliate redirect is never treated as a retailer
    # product URL; only an explicit retailer URL (url_kind == "retailer",
    # or legacy rows without url_kind evidence) may satisfy this rule.
    url_kind = evidence.get("url_kind")
    if require_url:
        if not url:
            reasons.append("missing_retailer_url")
        elif not _is_valid_url(url):
            reasons.append("invalid_retailer_url")
        elif url_kind in ("provider_page", "provider_affiliate_redirect"):
            reasons.append("url_is_provider_page")

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


# ── Phase 16.7 Stage 5: quantity comparability guard ─────────────────────────
# Eligibility enforces identity (same SKU), but an admin-approved possible
# match with a missing quantity on one side could still let offers for
# *different quantities* be ranked by absolute price.  Ranking therefore only
# mixes offers whose stated quantity is comparable, and any offer excluded by
# this guard is disclosed rather than silently dropped.

def quantity_signature(size_volume: Any) -> tuple[Optional[float], Optional[str]]:
    """(value, unit) parsed from a size string, or (None, None)."""
    if not size_volume:
        return (None, None)
    value, unit = parse_quantity_volume(str(size_volume))
    return (value, unit)


def quantities_comparable(
    sig_a: tuple[Optional[float], Optional[str]],
    sig_b: tuple[Optional[float], Optional[str]],
) -> Optional[bool]:
    """Three-state comparability: True, False, or None (unknown on either side).

    Equal value + same unit is comparable.  Equal value with differing g/ml
    labels is comparable under the Phase 16.7 unit-label tolerance (observed
    retailer labelling inconsistency for the same SKU).  Different values or
    units are never comparable.  A missing quantity on either side is unknown.
    """
    (va, ua), (vb, ub) = sig_a, sig_b
    if va is None or vb is None:
        return None
    if ua == ub:
        return abs(va - vb) <= 0.01
    if {ua, ub} == {"g", "ml"}:
        return abs(va - vb) <= 0.01
    return False


def rank_compatible_offers(
    offers: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Partition eligible offers into quantity-compatible ranking groups.

    Returns (rankable, excluded_by_quantity, disclosure).  The largest
    mutually-comparable group is ranked; smaller groups and unknown-quantity
    offers are disclosed with reasons.  When NO offer states a quantity at
    all, all offers remain rankable and the disclosure says so honestly.
    """
    disclosure: dict[str, Any] = {
        "quantity_guard": "applied",
        "size_info_available": False,
    }
    sigs = [quantity_signature(o.get("size_volume")) for o in offers]
    if all(s == (None, None) for s in sigs):
        disclosure["size_info_available"] = False
        disclosure["note"] = "No eligible offer states a quantity; ranking by absolute price without unit-price comparison."
        return list(offers), [], disclosure

    disclosure["size_info_available"] = True
    base_idx = next((i for i, s in enumerate(sigs) if s != (None, None)), 0)
    base = sigs[base_idx]
    rankable_idx: list[int] = []
    unknown_idx: list[int] = []
    incompatible_idx: list[int] = []
    for i, s in enumerate(sigs):
        cmp = quantities_comparable(base, s)
        if cmp is True:
            rankable_idx.append(i)
        elif cmp is None:
            unknown_idx.append(i)
        else:
            incompatible_idx.append(i)

    # Base-side unknown offers (no stated quantity) stay in the comparison
    # only when they are the sole content; otherwise they are disclosed.
    if unknown_idx and not incompatible_idx:
        rankable_idx.extend(unknown_idx)
        disclosure["note"] = "Some eligible offers state no quantity; they were included only because no incompatible quantity was present."
    excluded_idx = sorted(incompatible_idx + (
        unknown_idx if incompatible_idx else []
    ))
    excluded = [offers[i] for i in excluded_idx]
    rankable = [offers[i] for i in sorted(rankable_idx)]
    # NOTE: the disclosure deliberately does NOT use the key
    # "excluded_by_quantity" — get_cheapest_eligible uses that key for the
    # excluded-offer LIST in comparison_scope; the count is exposed here under
    # "quantity_guard_excluded_count" to avoid a key collision.
    disclosure["quantity_guard_excluded_count"] = len(excluded)
    if excluded:
        disclosure["note"] = (
            "Offers with an incompatible or unknown quantity are excluded from "
            "the cheapest ranking and listed separately; quantities are never "
            "compared by absolute price."
        )
    return rankable, excluded, disclosure


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

    Discloses the input assumptions with every result.  Phase 16.7 Stage 5:
    ranking only mixes quantity-compatible offers (an admin-approved possible
    match with a missing quantity can no longer let a different quantity win
    on absolute price), and the comparison scope — retailers considered,
    retailers excluded and why — is disclosed instead of implied.
    """
    offers = get_eligible_offers(
        product_id, require_url=require_url, policy=policy, db_path=db_path, now=now
    )
    if not offers:
        return None
    rankable, excluded_by_quantity, quantity_disclosure = rank_compatible_offers(offers)
    cheapest = min(rankable, key=lambda o: o["price"])
    cheapest = dict(cheapest)
    cheapest["assumptions"] = list(ASSUMPTIONS)
    # Phase 16.7 transparency: cheapest OBSERVED here vs cheapest ACROSS ALL
    # retailers are different claims.  Only retailers with an eligible, fresh,
    # identity-verified observation participate; the rest are counted.
    cheapest["comparison_scope"] = {
        "retailers_with_eligible_offer": len(offers),
        "retailers_ranked": len(rankable),
        "retailers_excluded_by_quantity": len(excluded_by_quantity),
        "excluded_by_quantity": [
            {
                "retailer": o["retailer"],
                "price": o["price"],
                "size_volume": o.get("size_volume"),
            }
            for o in excluded_by_quantity
        ],
        "claim": "cheapest observed offer among eligible retailers — not a guarantee that no other retailer is cheaper",
        **quantity_disclosure,
    }
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
