#!/usr/bin/env python
"""PriceInIndia Observation Collector + Controlled Discovery Workflow.

Phase 16.5 introduced the live collection pipeline:
1. Run migrations to add required columns
2. Load catalog products
3. Search PriceInIndia for each product
4. Match results against catalog
5. Store observations with full provenance
6. Expose via API

Phase 16.6 Stage 2 hardens this into a controlled catalogue-wide discovery
workflow with:

- Beauty-only catalogue targeting (legacy electronics demo excluded)
- Search queries built from brand + title + net quantity
- Safe normalization of provider items (price parsing incl. "₹1,299",
  currency validation — only INR is eligible, retailer/URL extraction)
- Provider outcome classification (empty results, timeout, HTTP error,
  rate limit, malformed response, network error, provider error)
- Conservative sequential concurrency with provider pacing (default 4.5s
  between searches; provider limit is 15 req/min)
- Restartable runs: products with a recent live provider_observed
  observation are skipped unless --force is given; reruns therefore never
  create uncontrolled duplicates (store_observation additionally
  supersedes per product+retailer)
- Dry-run support that never writes the application database and verifies
  the observation count is unchanged after the run
- Full per-run statistics persisted to a JSON artifact

Usage:
    python -m src.scripts.collect_pi_observations --products 20 [--dry-run]
    python -m src.scripts.collect_pi_observations --product-id 14 --dry-run
    python -m src.scripts.collect_pi_observations --db data/pricewise.db --force
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from dataclasses import replace as dataclasses_replace
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# Add project root to path (portable; previously a hard-coded MSYS path)
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.adapters.mcp_adapters.base_mcp_adapter import McpCallResult
from src.adapters.mcp_adapters.priceinindia_adapter import PriceInIndiaAdapter
from src.database.connection import get_connection, migrate_db
from src.database.seed import DEMO_PRODUCTS
from src.services.freshness_service import parse_epoch_seconds, provider_freshness
from src.services.url_policy import strip_tracking_params
from src.services.product_matching_service import (
    MatchClassification,
    evaluate_product_match,
    ProductMatchResult,
)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pi-collector")

# Legacy electronics demo categories — never targets of beauty price discovery.
ELECTRONICS_CATEGORIES = {p.get("category", "") for p in DEMO_PRODUCTS}

# ── Discovery defaults (conservative) ────────────────────────────────────────

DEFAULT_SKIP_RECENT_HOURS = 24      # skip products observed live within this window
DEFAULT_PACING_SECONDS = 4.5        # provider limit is 15 req/min (= 4s); margin included
DEFAULT_CANDIDATES_PER_PRODUCT = 3  # top-N provider results evaluated per product
DEFAULT_PER_PAGE = 5                # provider results requested per search
DEFAULT_STATS_PATH = REPO_ROOT / "data" / "phase16_6_collection_stats.json"

# Currencies accepted for eligibility (Indian market). Anything else is
# recorded as an unsupported-currency rejection, never silently converted.
_INR_ALIASES = {"inr", "₹", "rs", "rs.", "rupees", "rupee"}


def migrate_observation_table():
    """Add required columns to retail_price_observation table for Phase 16.5."""
    with get_connection() as conn:
        cursor = conn.cursor()

        # Check existing columns
        cursor.execute("PRAGMA table_info(retail_price_observation)")
        existing_cols = {row["name"] for row in cursor.fetchall()}

        # Add new columns if missing
        migrations = [
            ("observation_type", "TEXT DEFAULT 'live' CHECK(observation_type IN ('live', 'historical', 'superseded'))"),
            ("observation_status", "TEXT DEFAULT 'live' CHECK(observation_status IN ('live', 'expired', 'superseded', 'flagged'))"),
            ("verified_by_admin", "INTEGER DEFAULT 0 CHECK(verified_by_admin IN (0, 1))"),
            ("verification_status", "TEXT DEFAULT 'provider_observed' CHECK(verification_status IN ('pending', 'review_required', 'verified', 'provider_observed'))"),
            ("evidence_notes", "TEXT"),
            ("evidence_reference", "TEXT"),
            ("match_result", "TEXT"),
        ]

        for col_name, col_def in migrations:
            if col_name not in existing_cols:
                logger.info(f"Adding column: {col_name}")
                cursor.execute(f"ALTER TABLE retail_price_observation ADD COLUMN {col_name} {col_def}")

        conn.commit()
    logger.info("Database migrations complete")


def load_catalog_products(limit: int = 20) -> list[dict]:
    """Load products from database."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, sku, title, brand, category, specs_json, data_status, source_type
            FROM products
            WHERE is_active = 1
            ORDER BY id
            LIMIT ?
        """, (limit,))
        rows = cursor.fetchall()
        products = []
        for r in rows:
            specs = json.loads(r["specs_json"]) if r["specs_json"] else {}
            products.append({
                "id": r["id"],
                "sku": r["sku"],
                "title": r["title"],
                "brand": r["brand"],
                "category": r["category"],
                "specs": specs,
                "data_status": r["data_status"],
                "source_type": r["source_type"],
            })
        return products


def extract_size_from_specs(specs: dict) -> Optional[str]:
    """Extract size/volume from product specs."""
    if not specs:
        return None
    # Common size fields
    for key in ["Net Quantity", "Size", "Volume", "Quantity", "size", "volume"]:
        val = specs.get(key)
        if val:
            return str(val)
    return None


def extract_size_from_title(title: str) -> Optional[str]:
    """Extract the variant size/volume stated inside a provider product title.

    Phase 16.7 Stage 2: PriceInIndia titles usually carry the size
    ("… Watermelon Cooling Sunscreen 50 g") but do not always populate the
    structured ``size`` field.  The size is only *extracted*, never invented:
    when no quantity pattern is present the result is None and downstream
    matching preserves the uncertainty (missing size lowers confidence rather
    than being guessed).
    """
    if not title:
        return None
    # Prefer the LAST quantity token in the title: titles often mention
    # pack configurations ("2 x 100 ml") where the shipped size is the
    # rightmost statement.  This mirrors the retailer convention seen in the
    # Phase 16.7 browser investigation (URL slugs end with the size).
    tokens = list(
        re.finditer(
            r"(\d+(?:\.\d+)?)\s*(ml|gm|g|grams?|oz|kg|litres?|l)\b",
            str(title).lower(),
        )
    )
    if not tokens:
        return None
    last = tokens[-1]
    value, unit = last.group(1), last.group(2)
    if unit in ("gm", "grams", "gram"):
        unit = "g"
    elif unit in ("litres", "litre"):
        unit = "l"
    # Canonical display form: "50g", "50 ml" style kept minimal
    return f"{value}{unit}"


def match_pi_result_to_product(pi_item: dict, catalog_product: dict) -> ProductMatchResult:
    """Evaluate match between PriceInIndia result and catalog product.

    Uses a more lenient threshold for PI results since:
    - PI titles may differ slightly from catalog
    - PI may not include explicit size info
    - Brand match is the primary signal

    For PI live data, we consider a match valid if:
    1. Brand match (primary signal)
    2. At least 40% title similarity
    3. Not a clear mismatch (shade/formulation conflict)

    This is appropriate because PI returns actual live retailer prices
    that represent real consumer prices, even if not exact matches.
    """
    from src.services.product_matching_service import evaluate_product_match, MatchClassification

    pi_brand = pi_item.get("brand", "").lower()
    pi_title = pi_item.get("title", "")
    pi_store = pi_item.get("store", "")

    # Check if PI brand matches (primary signal)
    target_brand = catalog_product["brand"].lower()
    brand_match = pi_brand in target_brand or target_brand in pi_brand

    if not brand_match:
        # No brand match = definitely not a match
        return evaluate_product_match(
            target_brand=catalog_product["brand"],
            target_title=catalog_product["title"],
            target_specs=catalog_product.get("specs", {}),
            offer_brand=pi_item.get("brand", ""),
            offer_title=pi_item.get("title", ""),
            offer_specs=pi_item.get("specs", {}),
        )

    # Brand matches - check title similarity tolerance
    result = evaluate_product_match(
        target_brand=catalog_product["brand"],
        target_title=catalog_product["title"],
        target_specs=catalog_product.get("specs", {}),
        offer_brand=pi_item.get("brand", ""),
        offer_title=pi_item.get("title", ""),
        offer_specs=pi_item.get("specs", {}),
    )

    # For brand-matched PI items, relax to POSSIBLE_MATCH only when the
    # underlying evaluation did not find a hard identity conflict. Shade,
    # formulation, concentration, size and brand conflicts are never
    # overridden — those are exactly the cases that must not be compared.
    if (
        result.match_classification != MatchClassification.INCOMPATIBLE_MISMATCH
        and result.title_similarity >= 0.4
    ):
        # Create a new result that overrides is_comparable
        # We use a dataclass replace pattern
        result_dict = {
            "match_classification": MatchClassification.POSSIBLE_MATCH,
            "confidence_score": round(min(result.confidence_score, 0.75), 2),
            "is_comparable": True,
            "brand_match": result.brand_match,
            "size_match": result.size_match,
            "shade_match": result.shade_match,
            "formulation_match": result.formulation_match,
            "title_similarity": result.title_similarity,
            "reasons": result.reasons,
            "target_size": result.target_size,
            "offer_size": result.offer_size,
            "target_shade": result.target_shade,
            "offer_shade": result.offer_shade,
            "evidence_tier": result.evidence_tier,
            "barcode_match": result.barcode_match,
            "gtin_matched": result.gtin_matched,
            "unit_price_target": result.unit_price_target,
            "unit_price_offer": result.unit_price_offer,
            "requires_human_review": True,  # Mark for potential review
            "flagged_reasons": result.flagged_reasons,
            "admin_corrections_applied": False,
        }
        return ProductMatchResult(**result_dict)

    # Phase 16.7C: belt-and-braces identity guard — a provider item with no
    # detectable size/quantity can never be a verified identity match.
    # Missing size means missing SKU identity, so a verified evaluation is
    # downgraded to POSSIBLE_MATCH with human review (currently unreachable
    # for PriceInIndia results, which carry no barcodes; kept as a guard
    # against future evidence paths).
    return enforce_missing_size_identity_guard(result)


def enforce_missing_size_identity_guard(result: ProductMatchResult) -> ProductMatchResult:
    """Downgrade a VERIFIED_MATCH whose offer side has no detectable size.

    Missing size means missing SKU identity: such a result can never stand as
    a verified match. It is downgraded to POSSIBLE_MATCH with human review
    required. Results of other classifications pass through unchanged.
    """
    if (
        result.match_classification == MatchClassification.VERIFIED_MATCH
        and result.offer_size is None
    ):
        return dataclasses_replace(
            result,
            match_classification=MatchClassification.POSSIBLE_MATCH,
            match_strength="",
            strength_reasons=[],
            is_comparable=True,
            confidence_score=min(result.confidence_score, 0.75),
            requires_human_review=True,
            reasons=[
                *result.reasons,
                "Missing size on provider item — SKU identity unconfirmed; downgraded to possible match",
            ],
        )
    return result


def store_observation(
    product_id: int,
    pi_item: dict,
    match_result: ProductMatchResult,
    dry_run: bool = False,
    db_path: str | None = None,
) -> dict[str, Any]:
    """Store price observation in database."""
    timestamp = datetime.now(timezone.utc).isoformat()
    # Prices may arrive formatted ("₹1,299", "Rs. 1,299.50"); parse safely.
    # Unparseable prices become 0 and are rejected by the validation below —
    # they are never guessed or coerced.
    parsed_price = parse_price(pi_item.get("price"))
    parsed_mrp = parse_price(pi_item.get("mrp"))
    observation_retailer = str(pi_item.get("store") or "unknown")
    # Phase 16.7C: distinguish URL kinds. The stored product_url remains the
    # citation link (best available), but the evidence record now states WHAT
    # KIND of link it is. A retailer product URL is never invented: when only
    # a PriceInIndia page or affiliate redirect exists, retailer_product_url
    # is None and the evidence says so.
    # Phase 16.7E: tracking parameters are stripped before storage; cleaning
    # is provenance-preserving so url_kind classification is unaffected.
    provider_page_url = strip_tracking_params(
        str(pi_item.get("productPageUrl") or pi_item.get("product_page_url") or "").strip()
    ) or None
    affiliate_redirect_url = strip_tracking_params(
        str(pi_item.get("productUrl") or "").strip()
    ) or None
    retailer_product_url = strip_tracking_params(
        str(pi_item.get("retailerUrl") or pi_item.get("retailer_product_url") or "").strip()
    ) or None
    observation_url = strip_tracking_params(
        str(pi_item.get("productPageUrl") or pi_item.get("productUrl") or "").strip()
    ) or ""
    if observation_url and retailer_product_url and observation_url == retailer_product_url:
        url_kind = "retailer"
    elif observation_url and provider_page_url and observation_url == provider_page_url:
        url_kind = "provider_page"
    elif observation_url and affiliate_redirect_url and observation_url == affiliate_redirect_url:
        url_kind = "provider_affiliate_redirect"
    else:
        url_kind = None
    observation_currency = normalize_currency(pi_item.get("currency"))
    # Phase 16.7C: provider freshness (lastUpdated, unix seconds) mapped into
    # the observation freshness system alongside the observation's own time.
    provider_freshness_evidence = provider_freshness(pi_item.get("lastUpdated"))
    # Stage 4: preserve the retailer domain the provider reported. Domain-like
    # strings ("myntra.com") are kept as-is; plain names ("Nykaa") get NULL —
    # never guessed.
    observation_domain = (
        observation_retailer if "." in observation_retailer and " " not in observation_retailer
        else None
    )
    evidence_notes = (
        f"PI match: {match_result.match_classification}, evidence: {match_result.evidence_tier}"
    )
    if not observation_url:
        # Stage 3 rule 7: a missing provider URL is flagged, never silently
        # confirmed. Eligibility may exclude URL-less observations.
        evidence_notes += " | provider_product_url_missing"
    if url_kind == "provider_page":
        # Phase 16.7C: the URL points at PriceInIndia, not at the retailer.
        evidence_notes += " | url_is_provider_page"
    elif url_kind == "provider_affiliate_redirect":
        evidence_notes += " | url_is_affiliate_redirect"

    observation = {
        "product_id": product_id,
        "retailer": observation_retailer,
        "retailer_domain": observation_domain,
        "provider_name": "priceinindia",
        "currency": observation_currency,
        "product_url": observation_url,
        "observed_price": parsed_price if parsed_price is not None else 0.0,
        "observed_mrp": parsed_mrp if parsed_mrp is not None and parsed_mrp > 0 else None,
        "size_volume": (
            extract_size_from_specs({"Net Quantity": pi_item.get("size", "")})
            or pi_item.get("size")
            or extract_size_from_title(str(pi_item.get("title") or pi_item.get("product_title") or ""))
        ),
        "observation_type": "live",
        "observation_status": "live" if match_result.is_comparable else "flagged",
        "verified_by_admin": 0,
        "verification_status": "provider_observed" if match_result.is_comparable else "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
        "evidence_notes": evidence_notes,
        "evidence_reference": f"priceinindia_search_result_id_{pi_item.get('id')}",
        # Full match evidence: classification, conflicts, and unknowns are
        # preserved so eligibility and the review queue can inspect them
        # without re-deriving the decision (Stage 3 quality control).
        "match_result": json.dumps({
            "classification": match_result.match_classification,
            "confidence": match_result.confidence_score,
            "evidence_tier": match_result.evidence_tier,
            "reasons": match_result.reasons,
            "flagged_reasons": match_result.flagged_reasons,
            "requires_human_review": match_result.requires_human_review,
            "brand_match": match_result.brand_match,
            "size_match": match_result.size_match,
            "shade_match": match_result.shade_match,
            "formulation_match": match_result.formulation_match,
            "concentration_match": match_result.concentration_match,
            "title_similarity": match_result.title_similarity,
            "target_size": match_result.target_size,
            "offer_size": match_result.offer_size,
            "target_shade": match_result.target_shade,
            "offer_shade": match_result.offer_shade,
            "unit_price_target": match_result.unit_price_target,
            "unit_price_offer": match_result.unit_price_offer,
            "barcode_match": match_result.barcode_match,
            "gtin_matched": match_result.gtin_matched,
            "retailer": observation_retailer,
            "provider_item_id": pi_item.get("id"),
            "provider_product_url_missing": not observation_url,
            # Phase 16.7 Stage 4: the provider listing title is preserved so
            # the admin review UI can display a true catalogue-vs-listing
            # side-by-side without re-querying the provider.
            "provider_title": str(pi_item.get("title") or pi_item.get("product_title") or "") or None,
            "provider_brand": str(pi_item.get("brand") or "") or None,
            # Phase 16.7 Stage 1: explainable strength overlay (derived
            # deterministically from the classification + evidence tier).
            "match_strength": match_result.match_strength,
            "strength_reasons": match_result.strength_reasons,
            # ── Phase 16.7C: URL provenance and price-precision evidence ──
            # The citation URL's kind, the distinct provider/retailer URLs,
            # the raw provider price (full precision kept auditable), and the
            # provider's own freshness (lastUpdated) mapped into the same
            # fresh/aging/stale/unknown buckets the application uses.
            "url_kind": url_kind,
            "provider_page_url": provider_page_url,
            "affiliate_redirect_url": affiliate_redirect_url,
            # Never invented: None unless the provider supplied an explicit
            # retailer product URL.
            "retailer_product_url": retailer_product_url,
            "provider_price_raw": pi_item.get("price"),
            **provider_freshness_evidence,
        }),
    }

    if dry_run:
        return {"status": "dry_run", "observation": observation}

    if observation["observed_price"] <= 0:
        return {
            "status": "rejected",
            "reason": "observed_price must be positive",
            "observation": observation,
        }

    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Supersede any existing live observation for the SAME product+retailer.
        # Other retailers' observations remain independent and untouched.
        cursor.execute("""
            SELECT id FROM retail_price_observation
            WHERE product_id = ? AND retailer = ?
              AND observation_status = 'live'
              AND created_at > datetime('now', '-7 days')
        """, (product_id, observation["retailer"]))
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "UPDATE retail_price_observation "
                "SET observation_status = 'superseded', updated_at = ? WHERE id = ?",
                (timestamp, existing["id"]),
            )

        cursor.execute("""
            INSERT INTO retail_price_observation
            (product_id, retailer, retailer_domain, product_url, observed_price, observed_mrp,
             currency, provider_name, size_volume, observation_type, observation_status,
             verified_by_admin, verification_status, created_at, updated_at,
             evidence_notes, evidence_reference, match_result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            observation["product_id"],
            observation["retailer"],
            observation["retailer_domain"],
            observation["product_url"],
            observation["observed_price"],
            observation["observed_mrp"],
            observation["currency"],
            observation["provider_name"],
            observation["size_volume"],
            observation["observation_type"],
            observation["observation_status"],
            observation["verified_by_admin"],
            observation["verification_status"],
            observation["created_at"],
            observation["updated_at"],
            observation["evidence_notes"],
            observation["evidence_reference"],
            observation["match_result"],
        ))

        conn.commit()
        observation["id"] = cursor.lastrowid

        # Stage 3 rule 9: only a comparable (accepted) match may sync the
        # offers table. A rejected/flagged candidate must never overwrite an
        # existing valid offer price or URL.
        if not match_result.is_comparable:
            return {"status": "stored", "observation": observation}

        # Also update/sync the offers table for API compatibility
        # Map retailer name to store_id (match by name or domain)
        retailer_name = observation["retailer"]
        cursor.execute("""
            SELECT id, name, domain FROM stores
            WHERE LOWER(name) = LOWER(?)
               OR LOWER(domain) = LOWER(?)
               OR LOWER(name) LIKE LOWER(?) || '%'
               OR ? LIKE '%' || LOWER(domain) || '%'
        """, (retailer_name, retailer_name, retailer_name, retailer_name))
        store_row = cursor.fetchone()

        if store_row:
            store_id = store_row["id"]
        else:
            # Try to find by partial match in domain
            cursor.execute("SELECT id FROM stores WHERE ? LIKE '%' || domain || '%'", (retailer_name,))
            store_row = cursor.fetchone()
            store_id = store_row["id"] if store_row else None

        if store_id:
            # Check if offer exists
            cursor.execute("SELECT id FROM offers WHERE product_id = ? AND store_id = ?",
                          (observation["product_id"], store_id))
            existing_offer = cursor.fetchone()

            if existing_offer:
                # Update existing offer. The provider MRP is authoritative for
                # the original price; when absent, the existing original price
                # is preserved instead of being wiped with NULL.
                cursor.execute("""
                    UPDATE offers SET
                        current_price = ?,
                        original_price = COALESCE(?, original_price),
                        shipping_cost = 0,
                        currency = 'INR',
                        offer_url = COALESCE(NULLIF(?, ''), offer_url),
                        last_checked = ?
                    WHERE id = ?
                """, (
                    observation["observed_price"],
                    observation["observed_mrp"],
                    # Phase 16.7C: only a genuine retailer product URL may be
                    # written to offer_url. A provider page or affiliate
                    # redirect is never presented as a retailer link — when
                    # none exists the previous offer_url is preserved.
                    retailer_product_url or "",
                    timestamp,
                    existing_offer["id"],
                ))
            else:
                # Create new offer
                cursor.execute("""
                    INSERT INTO offers (product_id, store_id, current_price, original_price,
                                        shipping_cost, currency, availability, offer_url, last_checked)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    observation["product_id"],
                    store_id,
                    observation["observed_price"],
                    observation["observed_mrp"],
                    0,  # shipping_cost
                    "INR",
                    "In Stock",
                    # Phase 16.7C: offer_url is the retailer purchase link. A
                    # PriceInIndia page URL is not a retailer URL and is never
                    # substituted for one (left empty instead).
                    retailer_product_url or None,
                    timestamp,
                ))

            conn.commit()

    return {"status": "stored", "observation": observation}


# ============================================================================
# Phase 16.6 Stage 2: controlled catalogue-wide discovery
# ============================================================================

_PRICE_STRIP_RE = re.compile(r"[^0-9.]")
_CURRENCY_PREFIX_RE = re.compile(r"^(₹|rs\.?|inr)\s*", re.IGNORECASE)


def parse_price(value: Any) -> Optional[float]:
    """Parse a provider price that may be numeric or formatted text.

    Accepts 465.0, "465", "₹1,299", "Rs. 1,299.50", "INR 1299".
    Returns None for anything unparseable (never guesses).
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        return f if math.isfinite(f) else None
    text = str(value).strip()
    if not text:
        return None
    text = _CURRENCY_PREFIX_RE.sub("", text).strip()
    cleaned = _PRICE_STRIP_RE.sub("", text.replace(",", ""))
    if not cleaned:
        return None
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        cleaned = parts[0] + "." + "".join(parts[1:])
    try:
        f = float(cleaned)
    except ValueError:
        return None
    return f if math.isfinite(f) else None


def normalize_currency(value: Any) -> Optional[str]:
    """Map provider currency tokens to a canonical code.

    Returns "INR" for Indian aliases, None when absent, otherwise the
    upper-cased token (e.g. "USD") so the caller can reject it honestly.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text in _INR_ALIASES or text.lower() in _INR_ALIASES:
        return "INR"
    return text.upper()


def build_search_query(product: dict) -> str:
    """Build a PriceInIndia search query from brand, title and net quantity.

    The brand and size are only prepended/appended when the title does not
    already contain them, avoiding duplicated tokens in the query.
    """
    title = str(product.get("title") or "").strip()
    brand = str(product.get("brand") or "").strip()
    size = extract_size_from_specs(product.get("specs") or {})

    parts: list[str] = []
    if brand and brand.lower() not in title.lower():
        parts.append(brand)
    if title:
        parts.append(title)
    if size and size.lower() not in title.lower():
        parts.append(size)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def normalize_pi_item(item: dict) -> dict[str, Any]:
    """Normalize a raw PriceInIndia result item for matching and storage.

    Returns a dict with retailer, title, brand, price, currency, url, mrp,
    size, dedupe_key, flags and rejection_reason (None when usable).
    """
    flags: list[str] = []

    title = str(item.get("title") or item.get("product_title") or "").strip()
    retailer = str(item.get("store") or item.get("retailer") or "").strip()
    brand = str(item.get("brand") or "").strip()
    price = parse_price(item.get("price"))
    currency = normalize_currency(item.get("currency"))
    # Phase 16.7E: tracking parameters are stripped before classification or
    # storage. Cleaning is provenance-preserving (see src/services/url_policy),
    # so the url_kind classification below operates on the cleaned URLs.
    provider_page_url = strip_tracking_params(
        str(item.get("productPageUrl") or item.get("product_page_url") or "").strip()
    ) or None
    affiliate_redirect_url = strip_tracking_params(
        str(item.get("productUrl") or "").strip()
    ) or None
    # Phase 16.7C: a retailer product URL is NEVER derived or invented. The
    # provider's search results do not expose retailer URLs (their
    # productPageUrl is a PriceInIndia page and productUrl is an affiliate
    # redirect). A retailer URL is only ever taken from an explicit provider
    # field, should the provider ever supply one.
    retailer_product_url = strip_tracking_params(
        str(item.get("retailerUrl") or item.get("retailer_product_url") or "").strip()
    ) or None
    url = str(
        provider_page_url
        or affiliate_redirect_url
        or retailer_product_url
        or item.get("product_url")
        or ""
    ).strip()
    # Phase 16.7C: classify what kind of URL the citation actually is, so
    # downstream consumers can distinguish a provider page from a retailer
    # product link and never present one as the other.
    if url and retailer_product_url and url == retailer_product_url:
        url_kind = "retailer"
    elif url and provider_page_url and url == provider_page_url:
        url_kind = "provider_page"
    elif url and affiliate_redirect_url and url == affiliate_redirect_url:
        url_kind = "provider_affiliate_redirect"
    else:
        url_kind = None
    mrp = parse_price(item.get("mrp"))
    # Phase 16.7C: map the provider's lastUpdated (unix seconds) into the
    # freshness system. Raw provider prices are preserved alongside parsed
    # values so full precision stays auditable.
    last_updated_dt = parse_epoch_seconds(item.get("lastUpdated"))
    last_updated_epoch = (
        last_updated_dt.timestamp() if last_updated_dt is not None else None
    )
    # Phase 16.7 Stage 2: variant/size extraction. Prefer the structured
    # provider field; fall back to the size stated inside the title. When
    # neither is present the size stays None (never guessed), and matching
    # handles the missing quantity honestly.
    size = str(item.get("size") or "").strip() or None
    size_source = "provider_field" if size else None
    if size is None:
        extracted = extract_size_from_title(title)
        if extracted:
            size = extracted
            size_source = "title_extracted"
            flags.append("size_from_title")

    rejection_reason: Optional[str] = None
    if not title:
        rejection_reason = "missing_title"
    elif not retailer:
        rejection_reason = "missing_retailer"
    elif price is None or price <= 0:
        rejection_reason = "invalid_price"
    elif currency is None:
        rejection_reason = "currency_missing"
    elif currency != "INR":
        rejection_reason = "unsupported_currency"

    if not url and rejection_reason is None:
        # Missing URLs are flagged, never silently confirmed (Stage 3 rule 7).
        flags.append("missing_product_url")
    # Phase 16.7C: make the URL kind explicit so a provider page or affiliate
    # redirect is never mistaken for a retailer product link.
    if url_kind == "provider_page":
        flags.append("url_is_provider_page")
    elif url_kind == "provider_affiliate_redirect":
        flags.append("url_is_affiliate_redirect")
    if mrp is not None and mrp > 0 and price is not None and price > mrp:
        flags.append("price_above_mrp")

    if url:
        dedupe_key = (retailer.lower(), url.lower(), price)
    else:
        dedupe_key = (retailer.lower(), (title or "").lower(), price)

    return {
        "raw": item,
        "retailer": retailer,
        "title": title,
        "brand": brand,
        "price": price,
        # Phase 16.7C: raw provider price preserved alongside the parsed value
        # so full provider precision stays auditable (display rounds, storage
        # does not).
        "price_raw": item.get("price"),
        "currency": currency,
        "url": url,
        "url_kind": url_kind,
        "provider_page_url": provider_page_url,
        "affiliate_redirect_url": affiliate_redirect_url,
        "retailer_product_url": retailer_product_url,
        "mrp": mrp,
        "size": size,
        "size_source": size_source,
        # Phase 16.7C: provider freshness mapping (unix-seconds lastUpdated).
        "last_updated_epoch": last_updated_epoch,
        "dedupe_key": dedupe_key,
        "flags": flags,
        "rejection_reason": rejection_reason,
    }


def classify_provider_error(result: McpCallResult) -> str:
    """Classify a failed/unusable provider call into a stable error category."""
    msg = (result.error_message or "").lower()
    if "rate limit" in msg or "rate_limited" in msg:
        return "rate_limit"
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if msg.startswith("http "):
        return "http_error"
    if "unparseable" in msg or "malformed" in msg:
        return "malformed_response"
    if "json-rpc" in msg or "mcp" in msg:
        return "mcp_error"
    if "request error" in msg or "network" in msg:
        return "network_error"
    if not result.success:
        return "provider_error"
    return "empty_results"


def load_discovery_catalog(
    db_path: str | None = None,
    limit: int | None = None,
    product_ids: Iterable[int] | None = None,
) -> list[dict]:
    """Load the beauty discovery target list.

    Beauty products = every active product outside the legacy electronics
    demo categories. Optionally restricted to specific product IDs and/or
    the first N products (limited-run support).
    """
    id_filter = set(product_ids) if product_ids else None
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT id, sku, title, brand, category, specs_json, data_status, source_type
            FROM products
            WHERE is_active = 1
            ORDER BY id
            """
        ).fetchall()
    products: list[dict] = []
    for r in rows:
        if r["category"] in ELECTRONICS_CATEGORIES:
            continue
        if id_filter is not None and r["id"] not in id_filter:
            continue
        specs = json.loads(r["specs_json"]) if r["specs_json"] else {}
        products.append({
            "id": r["id"],
            "sku": r["sku"],
            "title": r["title"],
            "brand": r["brand"],
            "category": r["category"],
            "specs": specs,
            "data_status": r["data_status"],
            "source_type": r["source_type"],
        })
    if limit is not None:
        products = products[:limit]
    return products


def has_recent_live_observation(
    product_id: int,
    within_hours: int = DEFAULT_SKIP_RECENT_HOURS,
    db_path: str | None = None,
) -> bool:
    """True when the product already has a live provider_observed observation
    newer than the window — used to make runs restartable and to avoid
    unnecessary repeated searches."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=within_hours)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT created_at FROM retail_price_observation
            WHERE product_id = ?
              AND observation_status = 'live'
              AND verification_status = 'provider_observed'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (product_id,),
        ).fetchall()
    for row in rows:
        raw = row["created_at"]
        if not raw:
            continue
        try:
            created = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        if created >= cutoff:
            return True
    return False


def _count_observations(db_path: str | None = None) -> int:
    with get_connection(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM retail_price_observation").fetchone()[0])


def run_discovery_pipeline(
    *,
    limit: int | None = None,
    product_ids: Iterable[int] | None = None,
    dry_run: bool = False,
    db_path: str | None = None,
    skip_recent_hours: int = DEFAULT_SKIP_RECENT_HOURS,
    force: bool = False,
    candidates_per_product: int = DEFAULT_CANDIDATES_PER_PRODUCT,
    pacing_seconds: float = DEFAULT_PACING_SECONDS,
    per_page: int = DEFAULT_PER_PAGE,
    adapter: PriceInIndiaAdapter | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    save_stats: bool = True,
    stats_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the controlled Phase 16.6 discovery workflow.

    Sequential (conservative concurrency), rate-limit aware pacing,
    bounded evaluation (top N candidates per product), restartable via
    recent-observation skipping, and dry-run that never writes.
    """
    started = datetime.now(timezone.utc)
    adapter = adapter or PriceInIndiaAdapter()
    if not dry_run:
        # Stage 4: ensure provenance columns exist before writing. Idempotent,
        # additive-only, and skipped entirely for dry runs (never writes).
        migrate_db(db_path)
    products = load_discovery_catalog(db_path=db_path, limit=limit, product_ids=product_ids)
    logger.info(
        "Discovery pipeline: products=%d dry_run=%s skip_recent_hours=%s force=%s pacing=%ss",
        len(products), dry_run, skip_recent_hours, force, pacing_seconds,
    )

    stats: dict[str, Any] = {
        "started_at": started.isoformat(),
        "dry_run": dry_run,
        "db_path": db_path or "default",
        "config": {
            "skip_recent_hours": skip_recent_hours,
            "force": force,
            "candidates_per_product": candidates_per_product,
            "pacing_seconds": pacing_seconds,
            "per_page": per_page,
        },
        "totals": {
            "products_attempted": 0,
            "products_searched": 0,
            "products_skipped_recent": 0,
            "products_with_results": 0,
            "products_no_results": 0,
            "products_accepted": 0,
            "products_rejected": 0,
            "products_provider_error": 0,
            "provider_calls": 0,
            "candidates_evaluated": 0,
            "candidates_accepted": 0,
            "candidates_rejected": 0,
            "candidates_invalid": 0,
            "observations_stored": 0,
            "duplicate_candidates_skipped": 0,
        },
        "error_counts": {},
        "rejection_reason_counts": {},
        "products": [],
        "observations": [],
    }

    obs_before = _count_observations(db_path)
    last_call: float | None = None

    for product in products:
        entry: dict[str, Any] = {
            "product_id": product["id"],
            "title": product["title"],
            "brand": product["brand"],
            "query": build_search_query(product),
        }

        # Restartability: skip products already observed recently.
        if not force and has_recent_live_observation(product["id"], skip_recent_hours, db_path):
            entry["outcome"] = "skipped_recent"
            stats["totals"]["products_skipped_recent"] += 1
            stats["products"].append(entry)
            continue

        # Rate-limit pacing between provider calls (first call unpaced).
        if last_call is not None and pacing_seconds > 0:
            elapsed = time.monotonic() - last_call
            wait = pacing_seconds - elapsed
            if wait > 0:
                logger.info("  pacing: waiting %.1fs before next provider call", wait)
                sleep_fn(wait)

        logger.info("--- Searching: %s ---", entry["query"])
        result = adapter.search_products(query=entry["query"], page=1, per_page=per_page)
        last_call = time.monotonic()
        stats["totals"]["products_attempted"] += 1
        stats["totals"]["provider_calls"] += 1

        if not result.success:
            category = classify_provider_error(result)
            stats["error_counts"][category] = stats["error_counts"].get(category, 0) + 1
            stats["totals"]["products_provider_error"] += 1
            entry.update({"outcome": "provider_error", "error_category": category,
                          "error_message": result.error_message})
            stats["products"].append(entry)
            logger.warning("  provider error (%s): %s", category, result.error_message)
            continue

        if not result.items:
            entry["outcome"] = "no_results"
            stats["totals"]["products_no_results"] += 1
            stats["products"].append(entry)
            logger.info("  no provider results")
            continue

        stats["totals"]["products_searched"] += 1

        # Normalize + dedupe candidates (same retailer+url+price evaluated once).
        candidates: list[dict] = []
        seen: set[tuple] = set()
        for item in result.items[:candidates_per_product]:
            normalized = normalize_pi_item(item)
            stats["totals"]["candidates_evaluated"] += 1
            if normalized["rejection_reason"]:
                reason = normalized["rejection_reason"]
                stats["rejection_reason_counts"][reason] = (
                    stats["rejection_reason_counts"].get(reason, 0) + 1
                )
                stats["totals"]["candidates_invalid"] += 1
                entry.setdefault("invalid_candidates", []).append({
                    "title": normalized["title"], "reason": reason,
                })
                continue
            if normalized["dedupe_key"] in seen:
                stats["totals"]["duplicate_candidates_skipped"] += 1
                continue
            seen.add(normalized["dedupe_key"])
            candidates.append(normalized)

        if not candidates:
            entry["outcome"] = "no_usable_candidates"
            stats["totals"]["products_rejected"] += 1
            stats["products"].append(entry)
            continue

        accepted_for_product = 0
        candidate_rows: list[dict] = []
        for cand in candidates:
            match = match_pi_result_to_product(cand["raw"], product)
            classification = match.match_classification
            row = {
                "retailer": cand["retailer"],
                "title": cand["title"],
                "price": cand["price"],
                "currency": cand["currency"],
                "url": cand["url"],
                "flags": cand["flags"],
                "match_classification": classification,
                "confidence": match.confidence_score,
                "requires_human_review": match.requires_human_review,
            }
            if match.is_comparable:
                outcome = store_observation(
                    product["id"], cand["raw"], match,
                    dry_run=dry_run, db_path=db_path,
                )
                row["storage"] = outcome["status"]
                if outcome["status"] in ("stored", "dry_run"):
                    accepted_for_product += 1
                    stats["totals"]["candidates_accepted"] += 1
                    stats["totals"]["observations_stored"] += 1
                    stats["observations"].append({
                        "product_id": product["id"],
                        "product_title": product["title"],
                        "retailer": cand["retailer"],
                        "price": cand["price"],
                        "currency": cand["currency"],
                        "url": cand["url"],
                        "match_classification": classification,
                        "confidence": match.confidence_score,
                        "requires_human_review": match.requires_human_review,
                    })
                else:
                    stats["totals"]["candidates_rejected"] += 1
                    row["storage_reason"] = outcome.get("reason")
            else:
                stats["totals"]["candidates_rejected"] += 1
                row["storage"] = "not_comparable"
                row["match_reasons"] = match.reasons[:3]
            candidate_rows.append(row)

        entry["candidates"] = candidate_rows
        if accepted_for_product:
            entry["outcome"] = "accepted"
            stats["totals"]["products_with_results"] += 1
            stats["totals"]["products_accepted"] += 1
        else:
            entry["outcome"] = "match_rejected"
            stats["totals"]["products_with_results"] += 1
            stats["totals"]["products_rejected"] += 1
        stats["products"].append(entry)

    finished = datetime.now(timezone.utc)
    obs_after = _count_observations(db_path)

    stats["finished_at"] = finished.isoformat()
    stats["duration_seconds"] = round((finished - started).total_seconds(), 2)
    stats["adapter_stats"] = {
        "total_requests": adapter.health.total_requests,
        "failed_requests": adapter.health.failed_requests,
        "avg_response_time_ms": adapter.health.avg_response_time_ms,
        "is_healthy": adapter.health.is_healthy,
        "last_error": adapter.health.last_error,
    }
    stats["observations_before"] = obs_before
    stats["observations_after"] = obs_after
    if dry_run:
        stats["dry_run_verified_no_writes"] = obs_after == obs_before

    if save_stats:
        path = Path(stats_path) if stats_path else DEFAULT_STATS_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(stats, indent=2, default=str), encoding="utf-8")
        stats["stats_saved_to"] = str(path)

    logger.info(
        "=== Discovery Complete: attempted=%d accepted=%d rejected=%d errors=%d skipped=%d (%.1fs) ===",
        stats["totals"]["products_attempted"],
        stats["totals"]["products_accepted"],
        stats["totals"]["products_rejected"],
        stats["totals"]["products_provider_error"],
        stats["totals"]["products_skipped_recent"],
        stats["duration_seconds"],
    )
    return stats


def run_collection_pipeline(product_count: int = 20, dry_run: bool = False):
    """Back-compat wrapper: run the controlled discovery pipeline.

    Phase 16.6 note: discovery now targets beauty products only
    (legacy electronics demo categories are excluded) and supports
    restartable, dry-run, limited-run behaviour.
    """
    return run_discovery_pipeline(limit=product_count, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect PriceInIndia price observations")
    parser.add_argument("--products", "-n", type=int, default=None,
                        help="Limit to the first N beauty products (limited-run)")
    parser.add_argument("--product-id", type=int, action="append", dest="product_ids",
                        help="Target a specific product ID (repeatable)")
    parser.add_argument("--db", default=None, help="Database path (defaults to the configured app DB)")
    parser.add_argument("--dry-run", action="store_true", help="Evaluate without writing the database")
    parser.add_argument("--skip-recent-hours", type=int, default=DEFAULT_SKIP_RECENT_HOURS,
                        help="Skip products with a live observation newer than this (restartability)")
    parser.add_argument("--force", action="store_true",
                        help="Search even when a recent live observation exists")
    parser.add_argument("--candidates", type=int, default=DEFAULT_CANDIDATES_PER_PRODUCT,
                        help="Top-N provider results evaluated per product")
    parser.add_argument("--pacing", type=float, default=DEFAULT_PACING_SECONDS,
                        help="Seconds between provider searches (rate-limit safety)")
    parser.add_argument("--per-page", type=int, default=DEFAULT_PER_PAGE,
                        help="Provider results requested per search")
    parser.add_argument("--output", default=None, help="Path for the run-stats JSON artifact")
    parser.add_argument("--no-save", action="store_true", help="Do not persist the stats artifact")
    args = parser.parse_args()

    results = run_discovery_pipeline(
        limit=args.products,
        product_ids=args.product_ids,
        dry_run=args.dry_run,
        db_path=args.db,
        skip_recent_hours=args.skip_recent_hours,
        force=args.force,
        candidates_per_product=args.candidates,
        pacing_seconds=args.pacing,
        per_page=args.per_page,
        save_stats=not args.no_save,
        stats_path=args.output,
    )
    print(json.dumps(results, indent=2, default=str))
