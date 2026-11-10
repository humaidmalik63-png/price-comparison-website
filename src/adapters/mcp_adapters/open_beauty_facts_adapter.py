"""Open Beauty Facts API Adapter for PriceWise AI Beauty (Phase 16.2 Stage 4).

Fetches open product data from https://world.openbeautyfacts.org/ including:
- Product barcode / GTIN information
- Brand and product name normalization
- Ingredient lists (for Gemini-powered explanations, NOT pricing)
- Image references with attribution/licensing
- Modification timestamps

All data is open-source under Creative Commons Attribution Share-Alike 4.0.
No prices are fetched — OBF is strictly an information/provenance source.

Note: OBF CGI endpoints return HTML rather than JSON. We use their REST-like
pattern via direct product code requests where possible, and document fallbacks.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from datetime import datetime, timezone

import httpx

from src.adapters.mcp_adapters.base_mcp_adapter import McpCallResult

logger = logging.getLogger("pricewise.adapters.obf")

OBF_BASE = "https://world.openbeautyfacts.org"
OBF_API_V2 = f"{OBF_BASE}/api/v2"
USER_AGENT = "PriceWiseAI/1.0 (+https://pricewise.ai)"


class OpenBeautyFactsAdapter:
    """Client for the Open Beauty Facts open product database.

    Uses the public REST endpoints documented at:
    https://world.openbeautyfacts.org/data-api
    """

    TIMEOUT_SECONDS = 10.0
    RATE_LIMIT_PER_MINUTE = 10

    def __init__(self):
        self._request_timestamps: list[float] = []
        self._last_success: Optional[str] = None
        self._last_error: Optional[str] = None
        self._healthy = True

    # ── Properties ──────────────────────────────────────────────────────────

    @property
    def health_status(self) -> dict[str, Any]:
        return {
            "name": "OpenBeautyFacts",
            "endpoint": OBF_BASE,
            "is_healthy": self._healthy,
            "last_success_at": self._last_success,
            "last_error": self._last_error,
        }

    def _check_rate_limit(self) -> tuple[bool, Optional[str]]:
        import time
        now = time.time()
        self._request_timestamps = [t for t in self._request_timestamps if now - t < 60.0]
        if len(self._request_timestamps) >= self.RATE_LIMIT_PER_MINUTE:
            return False, "Rate limit exceeded for OBF"
        self._request_timestamps.append(now)
        return True, None

    def _record_success(self) -> None:
        self._last_success = datetime.now(timezone.utc).isoformat()
        self._healthy = True
        self._last_error = None

    def _record_failure(self, error: str) -> None:
        self._last_error = error
        self._healthy = False

    # ── Barcode lookup ──────────────────────────────────────────────────────

    def lookup_by_barcode(self, barcode: str) -> McpCallResult:
        """Look up a product by EAN/GTIN barcode using OBF v2 API.

        Returns normalized product data if found, or an unavailable result.
        """
        clean_barcode = re.sub(r"\D", "", barcode)[:13]
        allowed, err = self._check_rate_limit()
        if not allowed:
            return McpCallResult(success=False, tool_name="obf_lookup",
                                 error_message=err or "rate_limited")

        url = f"{OBF_API_V2}/product/{clean_barcode}"
        params = {"fields": "code,product_name,brands,quantity,categories_tags,"
                            "ingredients_text,image_url,nutriments,last_modified_t"}

        try:
            with httpx.Client(timeout=self.TIMEOUT_SECONDS) as client:
                resp = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
                if resp.status_code == 404:
                    return McpCallResult(success=False, tool_name="obf_lookup",
                                         error_message=f"Barcode {clean_barcode} not found in OBF")
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            self._record_failure(f"HTTP {e.response.status_code}")
            return McpCallResult(success=False, tool_name="obf_lookup",
                                 error_message=f"OBF API error: {e.response.status_code}")
        except httpx.TimeoutException:
            self._record_failure("timeout")
            return McpCallResult(success=False, tool_name="obf_lookup",
                                 error_message="OBF request timed out")
        except Exception as e:
            self._record_failure(str(e))
            return McpCallResult(success=False, tool_name="obf_lookup",
                                 error_message=str(e))

        self._record_success()
        product = data.get("product", {})
        normalized = self._normalize_product(product, clean_barcode)
        return McpCallResult(
            success=True,
            tool_name="obf_lookup",
            data=normalized,
        )

    # ── Search ───────────────────────────────────────────────────────────────

    def search_products(
        self,
        query: Optional[str] = None,
        brands: Optional[list[str]] = None,
        categories: Optional[list[str]] = None,
        limit: int = 20,
        page: int = 1,
    ) -> McpCallResult:
        """Search OBF for products by query terms and/or filters.

        Uses the OBF search endpoint. Returns normalized product listings.
        """
        allowed, err = self._check_rate_limit()
        if not allowed:
            return McpCallResult(success=False, tool_name="obf_search",
                                 error_message=err or "rate_limited")

        params: dict[str, Any] = {
            "page": page,
            "page_size": min(limit, 50),  # OBF caps at 50
            "fields": "code,product_name,brands,quantity,categories_tags,image_url,last_modified_t",
        }
        if query:
            params["search_terms"] = query
        if brands:
            params["brands"] = ", ".join(brands)
        if categories:
            params["categories_tags_like"] = ",".join(categories)

        url = f"{OBF_API_V2}/products"
        try:
            with httpx.Client(timeout=self.TIMEOUT_SECONDS) as client:
                resp = client.get(url, params=params, headers={"User-Agent": USER_AGENT})
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            self._record_failure(f"HTTP {e.response.status_code}")
            return McpCallResult(success=False, tool_name="obf_search",
                                 error_message=f"OBF search failed: {e.response.status_code}")
        except Exception as e:
            self._record_failure(str(e))
            return McpCallResult(success=False, tool_name="obf_search",
                                 error_message=str(e))

        self._record_success()
        products = data.get("products", [])
        normalized = [self._normalize_product(p, p.get("code", "")) for p in products]
        return McpCallResult(
            success=True,
            tool_name="obf_search",
            data={"count": len(normalized), "page": page, "total": data.get("count", len(normalized))},
            items=normalized,
        )

    # ── Ingredient enrichment ───────────────────────────────────────────────

    def get_ingredient_details(self, barcode: str) -> McpCallResult:
        """Get detailed ingredient info for a product (for Gemini explanations).

        Returns ingredients text and a simplified breakdown suitable for LLM
        context — does NOT include pricing.
        """
        lookup = self.lookup_by_barcode(barcode)
        if not lookup.success:
            return lookup  # propagate error

        product = lookup.data or {}
        ingredients_text = product.get("ingredients_text", "")
        ingredients_list = [
            ig.strip() for ig in re.split(r"[,\n]+", ingredients_text)
            if ig.strip() and len(ig.strip()) > 2
        ] if ingredients_text else []

        return McpCallResult(
            success=True,
            tool_name="obf_ingredients",
            data={
                "barcode": barcode,
                "product_name": product.get("product_name", ""),
                "brand": product.get("brand", ""),
                "ingredients_text": ingredients_text,
                "ingredients_list": ingredients_list[:50],  # Cap for token budget
                "category": product.get("categories_tags", []),
                "source_url": product.get("source_url", ""),
                "attribution": "Open Beauty Facts (CC BY-SA 4.0)",
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _normalize_product(self, raw: dict[str, Any], barcode: str) -> dict[str, Any]:
        """Normalize an OBF product entry for internal consumption."""
        images = raw.get("images", {})
        main_image = self._extract_best_image(images)
        modified_ts = raw.get("last_modified_t")
        last_modified = datetime.fromtimestamp(modified_ts, tz=timezone.utc).isoformat() \
            if modified_ts else None

        return {
            "barcode": barcode,
            "brand": raw.get("brands", ""),
            "product_name": raw.get("product_name", ""),
            "quantity": raw.get("quantity", ""),
            "categories": raw.get("categories_tags", []),
            "ingredients_text": raw.get("ingredients_text", ""),
            "image_url": main_image,
            "source_url": f"{OBF_BASE}/product/{barcode}",
            "attribution": "Open Beauty Facts (CC BY-SA 4.0)",
            "last_modified": last_modified,
            "nutriments": raw.get("nutriments", {}),
        }

    def _extract_best_image(self, images: dict) -> str:
        """Pick the best available image URL from OBF image metadata."""
        if not images:
            return ""
        # OBF stores images keyed by number; key 'main' is preferred
        for key in ("main", "photo_1", "photo_2", "photo_3"):
            img = images.get(key)
            if isinstance(img, dict):
                url = img.get("imgurl_small") or img.get("imgurl") or img.get("thumb_url")
                if url:
                    return str(url)
        # Fallback: first available image
        for v in images.values():
            if isinstance(v, dict):
                url = v.get("imgurl_small") or v.get("imgurl")
                if url:
                    return str(url)
        return ""
