"""PriceInIndia MCP Adapter for PriceWise AI Beauty (Phase 16.2 Stage 4).

Connects to https://mcp.priceinindia.website/mcp via Streamable HTTP MCP protocol
to fetch real INR prices for Indian beauty products. Implements search, price
comparison, and product detail retrieval with full provenance tracking.

No prices are fabricated. If the provider has no data for a product, the adapter
reports it as 'unavailable' rather than inventing a value.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from src.adapters.mcp_adapters.base_mcp_adapter import BaseMcpAdapter, McpCallResult
from src.database.connection import get_connection
from src.services.product_matching_service import evaluate_product_match, MatchClassification

logger = logging.getLogger("pricewise.adapters.priceinindia")

MCP_ENDPOINT = "https://mcp.priceinindia.website/mcp"


class PriceInIndiaAdapter(BaseMcpAdapter):
    """Adapter for the PriceInIndia Streamable HTTP MCP server."""

    def __init__(self, timeout_seconds: float = 10.0, max_retries: int = 2):
        super().__init__(
            name="PriceInIndia",
            mcp_endpoint=MCP_ENDPOINT,
            timeout_seconds=timeout_seconds,
            max_retries=max_retries,
            rate_limit_per_minute=15,
        )

    # ── Internal: parse MCP text response ───────────────────────────────────

    # ── Tool: search_products ───────────────────────────────────────────────

    def search_products(
        self,
        query: str,
        brand: Optional[str] = None,
        store: Optional[str] = None,
        category: Optional[str] = None,
        min_price: Optional[float] = None,
        max_price: Optional[float] = None,
        sort: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> McpCallResult:
        """Search PriceInIndia for beauty products matching the query.

        Returns products with fields: id, title, price, currency, store,
        product_url, product_page_url, mrp, discount_percent, image_url, brand.
        """
        args: dict[str, Any] = {"query": query.strip(), "page": page, "per_page": per_page}
        if brand:
            args["brand"] = brand
        if store:
            args["store"] = store
        if category:
            args["category"] = category
        if min_price is not None:
            args["min_price"] = min_price
        if max_price is not None:
            args["max_price"] = max_price
        if sort:
            args["sort"] = sort

        result = self.call_tool("search_products", args)
        if not result.success or not result.items:
            return result

        total = result.data.get("total", len(result.items)) if result.data else len(result.items)
        for item in result.items:
            item.setdefault("_source", "priceinindia")

        logger.info(f"PriceInIndia '{query}' → {len(result.items)} products found (total={total})")
        return McpCallResult(
            success=True,
            tool_name="search_products",
            data={"total": total, "page": page},
            items=result.items,
            response_time_ms=result.response_time_ms,
        )

    # ── Tool: compare_prices ────────────────────────────────────────────────

    def compare_prices(self, query: str, brand: Optional[str] = None) -> McpCallResult:
        """Compare prices across retailers for a product query."""
        args: dict[str, Any] = {"query": query.strip()}
        if brand:
            args["brand"] = brand

        result = self.call_tool("compare_prices", args)
        if not result.success or not result.items:
            return result

        for item in result.items:
            item.setdefault("_source", "priceinindia")

        logger.info(f"PriceInIndia compare '{query}' → {len(result.items)} offers found")
        return McpCallResult(
            success=True,
            tool_name="compare_prices",
            data=result.data,
            items=result.items,
            response_time_ms=result.response_time_ms,
        )

    # ── Tool: browse_categories ─────────────────────────────────────────────

    def browse_categories(self) -> McpCallResult:
        """List available product categories on PriceInIndia."""
        return self.call_tool("browse_categories", {})

    # ── High-level: find best product match ─────────────────────────────────

    def find_beauty_product(
        self,
        brand: str,
        product_name: str,
        size_volume: Optional[str] = None,
        max_results: int = 5,
    ) -> McpCallResult:
        """Best-effort single-product price lookup combining search + filtering.

        Searches PriceInIndia and returns up to max_results products. The caller
        should use product_matching_service.evaluate_product_match() to rank
        against the local catalog.
        """
        query = f"{brand} {product_name}"
        if size_volume:
            query += f" {size_volume}"

        result = self.search_products(query=query, brand=brand)
        if not result.success or not result.items:
            return McpCallResult(
                success=False,
                tool_name="find_beauty_product",
                error_message=f"No results for '{query}' in PriceInIndia",
            )

        # Limit and tag each item
        items = result.items[:max_results]
        for item in items:
            item["_source"] = "priceinindia"
            item["_fetched_at"] = result.data.get("fetched_at") if result.data else None

        return McpCallResult(
            success=True,
            tool_name="find_beauty_product",
            data={"query": query, "total": result.data.get("total", 0) if result.data else 0},
            items=items,
            response_time_ms=result.response_time_ms,
        )

    # ── Catalog sync: import products into DB ───────────────────────────────

    def import_to_catalog(
        self,
        brand: str,
        product_name: str,
        admin_user_id: int,
        catalog_product_id: Optional[int] = None,
    ) -> dict[str, Any]:
        """Import a PriceInIndia product into the local catalog with provenance.

        Creates or updates a product record and records a price observation.
        Returns a summary dict of actions taken.
        """
        result = self.find_beauty_product(brand=brand, product_name=product_name)
        if not result.success or not result.items:
            return {"success": False, "error": f"No products found for '{brand} {product_name}'",
                    "actions": []}

        imported = []
        errors = []

        with get_connection() as conn:
            cursor = conn.cursor()

            for item in result.items:
                try:
                    title = str(item.get("title", product_name))
                    price = float(item.get("price", 0))
                    mrp = float(item.get("mrp", 0) or 0)
                    store = str(item.get("store", ""))
                    url = str(item.get("product_page_url") or item.get("productUrl", ""))
                    image = str(item.get("image_url", ""))
                    currency = str(item.get("currency", "INR"))
                    discount = float(item.get("discountPercent", 0) or 0)

                    if price <= 0:
                        errors.append(f"Skipping item with invalid price: {title}")
                        continue

                    # Check if product already exists by matching on title+brand similarity
                    if catalog_product_id:
                        prod_id = catalog_product_id
                    else:
                        cursor.execute(
                            "SELECT id FROM products WHERE brand = ? AND title LIKE ? AND is_active = 1 LIMIT 1",
                            (brand, f"%{product_name[:20]}%"),
                        )
                        row = cursor.fetchone()
                        prod_id = row["id"] if row else None

                    if not prod_id:
                        # Insert new product
                        specs_json = json.dumps({
                            "source": "priceinindia",
                            "imported_at": result.data.get("fetched_at"),
                        })
                        cursor.execute(
                            """INSERT INTO products (sku, title, brand, category, description,
                               specs_json, image_url, source_type, data_status, is_active)
                               VALUES (?, ?, ?, ?, ?, ?, ?, 'catalog_verified', 'pending_review', 1)""",
                            (
                                f"PII-{item.get('id','')}",
                                title,
                                brand,
                                "Skincare",
                                f"Sourced from PriceInIndia ({store})",
                                specs_json,
                                image or "",
                            ),
                        )
                        prod_id = cursor.lastrowid

                    # Record price observation
                    cursor.execute(
                        """INSERT INTO retail_price_observation
                           (product_id, retailer, product_url, observed_price, observed_mrp,
                            observation_type, observation_status, verification_status,
                            evidence_notes, evidence_reference, created_at)
                           VALUES (?, ?, ?, ?, ?, 'scheduled', 'live', 'pending',
                                   ?, ?, CURRENT_TIMESTAMP)""",
                        (
                            prod_id,
                            store.replace(".com", "").replace(".in", ""),
                            url,
                            price,
                            mrp if mrp > 0 else None,
                            f"Auto-imported from PriceInIndia; discount={discount}%",
                            url,
                        ),
                    )

                    imported.append({
                        "product_id": prod_id,
                        "title": title,
                        "price": price,
                        "store": store,
                        "url": url,
                    })

                except Exception as e:
                    errors.append(f"Error importing {item.get('title', '?')}: {e}")

        return {
            "success": True,
            "imported_count": len(imported),
            "error_count": len(errors),
            "imported": imported,
            "errors": errors,
        }
