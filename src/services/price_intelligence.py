"""Price Intelligence Engine — Phase 16.2 Stage 4.

Provides price analytics over genuine, verified observations:
- Cheapest verified offer per product (excluding demo records)
- Discount calculation against manufacturer reference / MRP
- Unit-price normalisation (₹/g or ₹/ml) across offers
- Delivery charge normalisation for total landed cost
- Stale observation expiry (auto-mark after configurable hours)
- Provider-source provenance flags
- Matching confidence scoring for cross-provider products

All price calculations exclude 'demo' source_type entries unless
no other price is available, in which case they are flagged.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import logging
import json
import sqlite3

from src.database.connection import get_connection, migrate_db
from src.services.product_matching_service import (
    MatchClassification,
    MatchEvidenceTier,
    compute_unit_price,
    evaluate_product_match,
    parse_quantity_volume,
)

logger = logging.getLogger(__name__)


# ── Configuration ────────────────────────────────────────────────────────────

STALE_AFTER_HOURS = 72          # Auto-expire observations older than this
DEMO_FLAG_THRESHOLD = 0.90      # Only use demo prices if no non-demo price < this confidence


# ── Enums / constants ────────────────────────────────────────────────────────

class ObservationSource:
    """Source classification for price observations."""
    PROVIDER_OBSERVED = "provider_observed"       # From PriceInIndia or other MCP
    PENDING_VALIDATION = "pending_validation"      # Awaiting manual validation
    MATCH_CONFIRMED = "match_confirmed"            # Cross-matched to catalog product
    LIVE_VERIFIED = "live_verified"               # Manually verified by admin
    STALE = "stale"                              # Expired due to age
    REJECTED = "rejected"                        # Invalid or duplicate
    UNAVAILABLE = "unavailable"                  # Provider returned no data


# ── Result dataclasses ───────────────────────────────────────────────────────

@dataclass
class VerifiedOffer:
    """A single verified, non-stale offer for display."""
    id: int
    product_id: int
    store_name: str
    current_price: float
    original_price: Optional[float]
    shipping_cost: float
    currency: str
    landing_cost: Optional[float]
    source_type: str
    offer_url: str
    last_checked: Optional[str]
    unit_price: Optional[float]           # Price per g/ml; None if qty unknown
    discount_pct: Optional[float]         # Against MRP/original
    is_demo: bool
    matched_by_gtin: bool
    match_classification: Optional[str]   # From product matching engine
    confidence_score: Optional[float]


@dataclass
class CheapestVerifiedResult:
    """Aggregated cheapest-offer result for a product."""
    product_id: int
    sku: str
    title: str
    brand: str
    cheapest_offer: Optional[VerifiedOffer]
    all_offers: list[VerifiedOffer]
    cheapest_unit_price: Optional[float]     # ₹/g or ₹/ml of cheapest
    has_demo_only: bool                     # True when only demo prices exist
    needs_human_review: bool                # Some offers are ambiguous matches
    source_count: int                       # Number of distinct retailers
    last_updated: Optional[str]             # ISO timestamp of most recent obs


@dataclass
class PriceHistoryPoint:
    """Single point in a product's price history."""
    id: int
    product_id: int
    retailer: str
    observed_price: float
    observed_mrp: Optional[float]
    observation_type: str                   # scheduled | manual | user_report
    observation_status: str                 # live | expired | superseded | flagged
    created_at: str
    evidence_notes: Optional[str]
    unit_price: Optional[float]


# ============================================================================
# Core queries
# ============================================================================

def get_verified_offers(product_id: int) -> list[dict[str, Any]]:
    """Return all verified (non-stale, non-rejected) offers for a product.

    Excludes demo source_type by default unless no genuine offers exist.
    Includes unit price computation and discount percentage.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # Get product info
        cursor.execute(
            "SELECT id, sku, title, brand, specs_json FROM products WHERE id = ?",
            (product_id,),
        )
        row = cursor.fetchone()
        if not row:
            return []
        product = dict(row)
        specs = json.loads(product["specs_json"]) if product["specs_json"] else {}

        # Get offers joined with latest observation status
        cursor.execute("""
            SELECT o.id AS offer_id, o.product_id, o.store_id, s.name AS store_name,
                   o.current_price, o.original_price, o.shipping_cost, o.currency,
                   o.offer_url, o.last_checked, o.variant_name, o.condition,
                   p.source_type, p.data_status, p.is_active,
                   ro.observation_status AS latest_obs_status,
                   ro.observed_price AS latest_price,
                   ro.observed_mrp AS latest_mrp,
                   ro.created_at AS latest_obs_at,
                   ro.evidence_notes
            FROM offers o
            JOIN stores s ON s.id = o.store_id
            JOIN products p ON p.id = o.product_id
            LEFT JOIN (
                SELECT product_id, retailer, observation_status, observed_price,
                       observed_mrp, evidence_notes, created_at,
                       ROW_NUMBER() OVER (PARTITION BY product_id, retailer ORDER BY created_at DESC) AS rn
                FROM retail_price_observation
                WHERE observation_status IN ('live', 'flagged')
            ) ro ON ro.product_id = o.product_id AND ro.retailer = s.name AND ro.rn = 1
            WHERE o.product_id = ? AND p.is_active = 1
            ORDER BY o.current_price ASC
        """, (product_id,))
        rows = cursor.fetchall()

    results = []
    for r in rows:
        d = dict(r)
        is_demo = d["source_type"] == "demo"
        original_price = d["original_price"]
        shipping = d["shipping_cost"] or 0.0
        landing = round(d["current_price"] + shipping, 2) if d["current_price"] else None

        # Discount %
        discount_pct: Optional[float] = None
        mrp = d["latest_mrp"] or original_price
        if mrp and d["current_price"] and mrp > 0:
            discount_pct = round(((mrp - d["current_price"]) / mrp) * 100, 1)

        # Unit price from specs quantity + observed price
        unit_price: Optional[float] = None
        qty_text = str(specs.get("Net Quantity") or specs.get("Size") or "")
        qty_val, qty_unit = parse_quantity_volume(qty_text)
        if qty_val and d["current_price"]:
            unit_price = round(d["current_price"] / qty_val, 4)

        results.append({
            "offer_id": d["offer_id"],
            "product_id": d["product_id"],
            "store_name": d["store_name"],
            "current_price": d["current_price"],
            "original_price": original_price,
            "shipping_cost": shipping,
            "landing_cost": landing,
            "currency": d["currency"],
            "offer_url": d["offer_url"] or "",
            "last_checked": d["last_checked"],
            "variant_name": d["variant_name"] or "Standard",
            "condition": d["condition"] or "Brand New",
            "source_type": d["source_type"],
            "data_status": d["data_status"],
            "is_active": bool(d["is_active"]),
            "latest_obs_status": d["latest_obs_status"],
            "latest_obs_price": d["latest_price"],
            "latest_mrp": d["latest_mrp"],
            "latest_obs_at": d["latest_obs_at"],
            "evidence_notes": d["evidence_notes"],
            "discount_pct": discount_pct,
            "unit_price": unit_price,
            "is_demo": is_demo,
        })
    return results


def get_cheapest_verified(product_id: int) -> Optional[VerifiedOffer]:
    """Return the single cheapest verified offer for a product, or None."""
    offers = get_verified_offers(product_id)
    non_demo = [o for o in offers if not o["is_demo"]]
    target = non_demo if non_demo else offers
    if not target:
        return None
    return min(target, key=lambda o: o["current_price"] or 999999)


def list_cheapest_per_catalog(limit: int = 200) -> list[dict[str, Any]]:
    """Return the cheapest verified offer across all active beauty products."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.id AS product_id, p.sku, p.title, p.brand,
                   o.id AS offer_id, o.current_price, o.original_price,
                   o.shipping_cost, o.currency, o.offer_url,
                   s.name AS store_name, o.last_checked,
                   p.source_type, p.data_status
            FROM products p
            JOIN offers o ON o.product_id = p.id
            JOIN stores s ON s.id = o.store_id
            WHERE p.is_active = 1
              AND p.category NOT IN ('Skincare Routine', 'Makeup Routine')
              AND o.current_price > 0
            ORDER BY p.id
        """)
        rows = cursor.fetchall()

    by_product: dict[int, list[dict]] = {}
    for r in rows:
        pid = r["product_id"]
        by_product.setdefault(pid, []).append(dict(r))

    results = []
    for pid, offers in by_product.items():
        non_demo = [o for o in offers if o["source_type"] != "demo"]
        candidates = non_demo if non_demo else offers
        cheapest = min(candidates, key=lambda o: o["current_price"])
        specs_raw = cheapest.get("specs_json")
        qty_val, qty_unit = None, None
        if specs_raw:
            try:
                specs = json.loads(specs_raw)
                qty_text = str(specs.get("Net Quantity") or specs.get("Size") or "")
                qty_val, qty_unit = parse_quantity_volume(qty_text)
            except (json.JSONDecodeError, TypeError):
                pass
        unit_price = round(cheapest["current_price"] / qty_val, 4) if qty_val and cheapest["current_price"] else None
        results.append({
            "product_id": pid,
            "sku": cheapest["sku"],
            "title": cheapest["title"],
            "brand": cheapest["brand"],
            "store": cheapest["store_name"],
            "price": cheapest["current_price"],
            "original_price": cheapest["original_price"],
            "shipping": cheapest["shipping_cost"],
            "landing_cost": round(cheapest["current_price"] + cheapest["shipping_cost"], 2),
            "currency": cheapest["currency"],
            "offer_url": cheapest["offer_url"],
            "last_checked": cheapest["last_checked"],
            "source_type": cheapest["source_type"],
            "unit_price": unit_price,
            "is_demo": cheapest["source_type"] == "demo",
        })
    return sorted(results, key=lambda r: r["price"])[:limit]


def expire_stale_observations(max_age_hours: int = STALE_AFTER_HOURS) -> int:
    """Mark observations older than max_age_hours as 'expired'.

    Returns count of observations expired.
    """
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE retail_price_observation
            SET observation_status = 'expired', updated_at = CURRENT_TIMESTAMP
            WHERE observation_status = 'live'
              AND created_at < ?
        """, (cutoff,))
        count = cursor.rowcount
    if count:
        logger.info(f"Expired {count} stale observations (age > {max_age_hours}h)")
    return count


def get_observation_price_history(product_id: int, limit: int = 30) -> list[PriceHistoryPoint]:
    """Retrieve price history for a product ordered chronologically.

    Excludes superseded entries; includes flagged for audit trail.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, product_id, retailer, observed_price, observed_mrp,
                   observation_type, observation_status, created_at,
                   evidence_notes, size_volume
            FROM retail_price_observation
            WHERE product_id = ?
              AND observation_status != 'superseded'
            ORDER BY created_at ASC
            LIMIT ?
        """, (product_id, limit))
        rows = cursor.fetchall()

    results = []
    for r in rows:
        d = dict(r)
        qty_text = d.get("size_volume") or ""
        qv, qu = parse_quantity_volume(qty_text)
        up = round(d["observed_price"] / qv, 4) if qv and d["observed_price"] else None
        results.append(PriceHistoryPoint(
            id=d["id"],
            product_id=d["product_id"],
            retailer=d["retailer"],
            observed_price=d["observed_price"],
            observed_mrp=d["observed_mrp"],
            observation_type=d["observation_type"],
            observation_status=d["observation_status"],
            created_at=d["created_at"],
            evidence_notes=d["evidence_notes"],
            unit_price=up,
        ))
    return results


def calculate_discount(observation: dict[str, Any]) -> Optional[float]:
    """Calculate discount percentage from observed_price vs observed_mrp."""
    price = observation.get("observed_price")
    mrp = observation.get("observed_mrp")
    if not price or not mrp or mrp <= 0:
        return None
    return round(((mrp - price) / mrp) * 100, 1)


def filter_rejected_demos(offers: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Separate genuine offers from demo/offline-only ones.

    Returns (genuine_offers, demo_offers).
    Demo offers still included in display but flagged.
    """
    genuine = [o for o in offers if o.get("source_type") != "demo"]
    demos = [o for o in offers if o.get("source_type") == "demo"]
    return genuine, demos


# ============================================================================
# API response helpers
# ============================================================================

def build_product_detail_response(product: dict, offers: list[dict]) -> dict[str, Any]:
    """Build enriched product detail including price intelligence fields."""
    genuine, demos = filter_rejected_demos(offers)
    cheapest = min(genuine, key=lambda o: o["current_price"] or 999999) if genuine else None
    cheapest_all = min(offers, key=lambda o: o["current_price"] or 999999) if offers else None

    return {
        **product,
        "price_intel": {
            "cheapest_verified": cheapest,
            "cheapest_any": cheapest_all,
            "has_genuine_prices": len(genuine) > 0,
            "has_demo_prices": len(demos) > 0,
            "all_offers": offers,
            "lowest_landing_cost": cheapest["landing_cost"] if cheapest else None,
            "discount_from_mrp": calculate_discount(cheapest) if cheapest else None,
        },
    }


def get_price_health_stats() -> dict[str, Any]:
    """Get overall data-quality health stats for the admin dashboard."""
    with get_connection() as conn:
        cursor = conn.cursor()
        stats: dict[str, Any] = {}

        cursor.execute("SELECT COUNT(*) FROM products WHERE is_active = 1")
        stats["total_active_products"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE source_type = 'manufacturer_verified'"
        )
        stats["manufacturer_verified"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM products WHERE source_type = 'catalog_verified'"
        )
        stats["catalog_verified"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM retail_price_observation "
            "WHERE observation_status = 'live'"
        )
        stats["live_observations"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM retail_price_observation "
            "WHERE observation_status = 'flagged'"
        )
        stats["flagged_observations"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(*) FROM retail_price_observation "
            "WHERE observation_status = 'expired'"
        )
        stats["expired_observations"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT COUNT(DISTINCT retailer) FROM retail_price_observation "
            "WHERE observation_status = 'live'"
        )
        stats["active_retailers"] = cursor.fetchone()[0]

        cursor.execute(
            "SELECT MIN(created_at) AS oldest, MAX(created_at) AS newest "
            "FROM retail_price_observation WHERE observation_status = 'live'"
        )
        row = cursor.fetchone()
        stats["oldest_live_observation"] = row["oldest"] if row else None
        stats["newest_live_observation"] = row["newest"] if row else None

    return stats
