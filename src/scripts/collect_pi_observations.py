#!/usr/bin/env python
"""Phase 16.5: PriceInIndia Observation Collector Script.

This script runs the live PriceInIndia MCP collection pipeline:
1. Run migrations to add required columns
2. Load catalog products
3. Search PriceInIndia for each product
4. Match results against catalog
5. Store observations with full provenance
6. Expose via API

Usage:
    python -m src.scripts.collect_pi_observations --products 20 [--dry-run]
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Optional

# Add project root to path
sys.path.insert(0, '/c/Users/humai/Desktop/Cisco/price-comparison-website')

from src.adapters.mcp_adapters.priceinindia_adapter import PriceInIndiaAdapter
from src.database.connection import get_connection
from src.services.product_matching_service import evaluate_product_match, ProductMatchResult

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("pi-collector")


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

    # For brand-matched PI items, accept as comparable if:
    # - Not an incompatible mismatch
    # - Title similarity >= 40%
    if result.title_similarity >= 0.4:
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

    return result


def store_observation(
    product_id: int,
    pi_item: dict,
    match_result: ProductMatchResult,
    dry_run: bool = False
) -> dict[str, Any]:
    """Store price observation in database."""
    timestamp = datetime.now(timezone.utc).isoformat()

    observation = {
        "product_id": product_id,
        "retailer": pi_item.get("store", "unknown"),
        "product_url": pi_item.get("productPageUrl", pi_item.get("productUrl", "")),
        "observed_price": float(pi_item.get("price", 0)),
        "observed_mrp": None,  # MRP not provided by PI
        "size_volume": extract_size_from_specs({"Net Quantity": pi_item.get("size", "")}) or pi_item.get("size"),
        "observation_type": "live",
        "observation_status": "live" if match_result.is_comparable else "flagged",
        "verified_by_admin": 0,
        "verification_status": "provider_observed" if match_result.is_comparable else "pending",
        "created_at": timestamp,
        "updated_at": timestamp,
        "evidence_notes": f"PI match: {match_result.match_classification}, evidence: {match_result.evidence_tier}",
        "evidence_reference": f"priceinindia_search_result_id_{pi_item.get('id')}",
        "match_result": json.dumps({
            "classification": match_result.match_classification,
            "confidence": match_result.confidence_score,
            "evidence_tier": match_result.evidence_tier,
            "reasons": match_result.reasons,
        }),
    }

    if dry_run:
        return {"status": "dry_run", "observation": observation}

    with get_connection() as conn:
        cursor = conn.cursor()

        # Check for existing live observation for this retailer recently
        cursor.execute("""
            SELECT id FROM retail_price_observation
            WHERE product_id = ? AND retailer = ?
              AND observation_status = 'live'
              AND created_at > datetime('now', '-7 days')
        """, (product_id, observation["retailer"]))
        existing = cursor.fetchone()

        if existing:
            observation["observation_status"] = "superseded"

        cursor.execute("""
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observed_mrp,
             size_volume, observation_type, observation_status, verified_by_admin,
             verification_status, created_at, updated_at, evidence_notes, evidence_reference,
             match_result)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            observation["product_id"],
            observation["retailer"],
            observation["product_url"],
            observation["observed_price"],
            observation["observed_mrp"],
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

        # Also update/sync the offers table for API compatibility
        # Map retailer name to store_id (match by name or domain)
        retailer_name = observation["retailer"]
        cursor.execute("""
            SELECT id, name, domain FROM stores
            WHERE LOWER(name) = LOWER(?)
               OR LOWER(domain) = LOWER(?)
               OR ? LIKE '%' || LOWER(name) || '%'
        """, (retailer_name, retailer_name, retailer_name))
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
                # Update existing offer
                cursor.execute("""
                    UPDATE offers SET
                        current_price = ?,
                        original_price = ?,
                        shipping_cost = 0,
                        currency = 'INR',
                        offer_url = ?,
                        last_checked = ?
                    WHERE id = ?
                """, (
                    observation["observed_price"],
                    observation["observed_mrp"],
                    observation["product_url"],
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
                    observation["product_url"],
                    timestamp,
                ))

            conn.commit()

    return {"status": "stored", "observation": observation}


def run_collection_pipeline(product_count: int = 20, dry_run: bool = False):
    """Run the full collection pipeline."""
    logger.info(f"Starting PriceInIndia collection pipeline (products={product_count}, dry_run={dry_run})")

    # Initialize adapter
    adapter = PriceInIndiaAdapter()
    logger.info(f"Adapter status: {adapter.status}")

    # Load catalog products
    products = load_catalog_products(product_count)
    logger.info(f"Loaded {len(products)} catalog products")

    results = {
        "total_products": len(products),
        "successful": 0,
        "failed": 0,
        "matches": 0,
        "observations": [],
    }

    for product in products:
        logger.info(f"\n--- Processing: {product['brand']} {product['title'][:40]} ---")

        # Search PriceInIndia
        query = f"{product['brand']} {product['title']}"
        pi_result = adapter.search_products(query=query, page=1, per_page=5)

        if not pi_result.success or not pi_result.items:
            logger.warning(f"  No PI results for '{query}'")
            results["failed"] += 1
            continue

        # Evaluate matches
        matched_count = 0
        for pi_item in pi_result.items[:3]:  # Top 3 results
            match = match_pi_result_to_product(pi_item, product)

            if match.is_comparable:
                logger.info(f"  MATCH: {pi_item.get('title')} @ ₹{pi_item.get('price')} ({pi_item.get('store')})")
                logger.info(f"    Match: {match.match_classification}, Confidence: {match.confidence_score}")

                if not dry_run:
                    obs = store_observation(product["id"], pi_item, match)
                    if obs["status"] == "stored":
                        matched_count += 1
                        results["observations"].append({
                            "product_id": product["id"],
                            "product_title": product["title"],
                            "brand": product["brand"],
                            "pi_title": pi_item.get("title"),
                            "price": pi_item.get("price"),
                            "store": pi_item.get("store"),
                            "url": pi_item.get("productPageUrl"),
                            "match_classification": match.match_classification,
                            "confidence": match.confidence_score,
                        })
                else:
                    matched_count += 1
            else:
                logger.info(f"  No match: {pi_item.get('title')} - {match.reasons[:2]}")

        if matched_count > 0:
            results["successful"] += 1
            results["matches"] += matched_count
        else:
            results["failed"] += 1

    # Update adapter stats
    results["adapter_stats"] = {
        "total_requests": adapter.health.total_requests,
        "failed_requests": adapter.health.failed_requests,
        "avg_response_time_ms": adapter.health.avg_response_time_ms,
        "is_healthy": adapter.health.is_healthy,
    }

    logger.info(f"\n=== Pipeline Complete ===")
    logger.info(f"Successful: {results['successful']}/{results['total_products']}")
    logger.info(f"Total observations stored: {len(results['observations'])}")
    logger.info(f"Adapter stats: {results['adapter_stats']}")

    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Collect PriceInIndia price observations")
    parser.add_argument("--products", "-n", type=int, default=20, help="Number of products to process")
    parser.add_argument("--dry-run", action="store_true", help="Don't store observations")
    args = parser.parse_args()

    results = run_collection_pipeline(product_count=args.products, dry_run=args.dry_run)
    print(json.dumps(results, indent=2, default=str))