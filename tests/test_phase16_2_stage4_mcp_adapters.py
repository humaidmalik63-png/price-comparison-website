"""Tests for Phase 16.2 Stage 4: MCP Adapters (PriceInIndia & OBF).

Validates adapter behaviour under mocked conditions. Network calls are stubbed
so tests are deterministic and fast.
"""
import json
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.adapters.mcp_adapters.base_mcp_adapter import BaseMcpAdapter, McpCallResult, McpConnectorHealth
from src.adapters.mcp_adapters.priceinindia_adapter import PriceInIndiaAdapter
from src.adapters.mcp_adapters.open_beauty_facts_adapter import OpenBeautyFactsAdapter


# ── Helper fixtures ────────────────────────────────────────────────────────────

FIXTURE_PRODUCT_RESPONSE = {
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "structuredContent": {
            "products": [
                {
                    "id": "pii-001",
                    "title": "The Ordinary Niacinamide 10% + Zinc 1%",
                    "price": 299.0,
                    "currency": "INR",
                    "store": "Nykaa",
                    "productUrl": "https://nykaa.com/ordinary-niacinamide",
                    "product_page_url": "https://nykaa.com/ordinary-niacinamide",
                    "mrp": 399.0,
                    "discountPercent": 25.0,
                    "image_url": "https://images.nykaa.com/niacinamide.jpg",
                    "brand": "The Ordinary",
                }
            ],
            "total": 1,
            "query": "The Ordinary Niacinamide",
        }
    }
}


def make_mock_response(text: str, status: int = 200):
    resp = MagicMock()
    resp.text = text
    resp.status_code = status
    resp.raise_for_status.return_value = None
    return resp


# ── BaseMcpAdapter tests ──────────────────────────────────────────────────────

class TestBaseMcpAdapter:
    def test_make_post_succeeds(self):
        adapter = BaseMcpAdapter(name="TestAdapter", mcp_endpoint="http://localhost/mcp")
        with patch("src.adapters.mcp_adapters.base_mcp_adapter.httpx.Client") as MockClient:
            mock_resp = MagicMock()
            mock_resp.text = json.dumps(FIXTURE_PRODUCT_RESPONSE)
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            MockClient.return_value.__enter__.return_value.post.return_value = mock_resp
            result = adapter._make_post({"jsonrpc": "2.0", "method": "tools/call"})
            assert result.success is True
            assert len(result.items) == 1
            assert result.items[0]["title"] == "The Ordinary Niacinamide 10% + Zinc 1%"

    def test_make_post_times_out(self):
        adapter = BaseMcpAdapter(name="TestAdapter", mcp_endpoint="http://localhost/mcp")
        with patch("src.adapters.mcp_adapters.base_mcp_adapter.httpx.Client") as MockClient:
            import httpx
            MockClient.return_value.__enter__.return_value.post.side_effect = httpx.TimeoutException("timeout")
            result = adapter._make_post({"jsonrpc": "2.0", "method": "tools/call"})
            assert result.success is False
            assert "Timeout" in result.error_message

    def test_make_post_http_error(self):
        adapter = BaseMcpAdapter(name="TestAdapter", mcp_endpoint="http://localhost/mcp")
        with patch("src.adapters.mcp_adapters.base_mcp_adapter.httpx.Client") as MockClient:
            import httpx
            bad_resp = MagicMock()
            bad_resp.status_code = 500
            bad_resp.text = "Internal Server Error"
            MockClient.return_value.__enter__.return_value.post.side_effect = httpx.HTTPStatusError(
                "error", request=MagicMock(), response=bad_resp
            )
            result = adapter._make_post({"jsonrpc": "2.0", "method": "tools/call"})
            assert result.success is False
            assert "HTTP 500" in result.error_message

    def test_rate_limiting_blocks_requests(self):
        adapter = BaseMcpAdapter(name="TestAdapter", mcp_endpoint="http://localhost/mcp", rate_limit_per_minute=2)
        # Simulate two prior requests
        import time
        now = time.time()
        adapter._request_timestamps = [now, now]
        allowed, err = adapter.check_rate_limit()
        assert allowed is False
        assert "Rate limit" in err

    def test_health_after_success(self):
        adapter = BaseMcpAdapter(name="TestAdapter", mcp_endpoint="http://localhost/mcp")
        assert adapter.health.is_configured is True
        assert adapter.health.total_requests == 0

    def test_parse_sse_response(self):
        adapter = BaseMcpAdapter(name="TestAdapter", mcp_endpoint="http://localhost/mcp")
        sse_text = (
            'event: message\ndata: {"tool_name": "search", "data": {"products": [{"id": 1}]}}\n\n'
            'event: message\ndata: {"tool_name": "search", "data": {"products": []}}\n\n'
        )
        result = adapter._parse_response(sse_text, 200, 50.0)
        assert result.success is True
        assert len(result.items) == 2


class TestExtractFromJson:
    def test_priority_structured_content_products(self):
        adapter = BaseMcpAdapter(name="T", mcp_endpoint="http://x")
        payload = {
            "tool_name": "search_products",
            "result": {
                "structuredContent": {
                    "products": [{"id": 1, "title": "A"}],
                    "total": 1,
                }
            }
        }
        result = adapter._extract_from_json(payload, 10.0)
        assert result.success is True
        assert result.items == [{"id": 1, "title": "A"}]

    def test_falls_back_to_content_array(self):
        adapter = BaseMcpAdapter(name="T", mcp_endpoint="http://x")
        payload = {
            "tool_name": "search_products",
            "result": {
                "content": [{"type": "text", "text": json.dumps({"items": [{"id": 2}]})}]
            }
        }
        result = adapter._extract_from_json(payload, 10.0)
        assert result.success is True
        assert result.data.get("items") == [{"id": 2}]

    def test_direct_data_key(self):
        adapter = BaseMcpAdapter(name="T", mcp_endpoint="http://x")
        payload = {
            "tool_name": "browse_categories",
            "result": {
                "data": {"categories": ["Skincare", "Makeup"]}
            }
        }
        result = adapter._extract_from_json(payload, 10.0)
        assert result.success is True
        assert result.data == {"categories": ["Skincare", "Makeup"]}


# ── PriceInIndiaAdapter tests ────────────────────────────────────────────────

class TestPriceInIndiaAdapter:
    def test_search_products_found(self):
        adapter = PriceInIndiaAdapter(timeout_seconds=0.1, max_retries=1)
        with patch.object(adapter, "_make_post") as mock_post:
            mock_post.return_value = McpCallResult(
                success=True, tool_name="search_products",
                data={"total": 1}, items=[{"id": "pii-001", "title": "Test"}],
            )
            result = adapter.search_products(query="Niacinamide", page=1, per_page=5)
            assert result.success is True
            assert result.items
            assert result.items[0]["_source"] == "priceinindia"
            assert result.data["total"] == 1

    def test_search_products_empty(self):
        adapter = PriceInIndiaAdapter(timeout_seconds=0.1, max_retries=1)
        with patch.object(adapter, "_make_post") as mock_post:
            mock_post.return_value = McpCallResult(success=False, tool_name="search_products",
                                                    error_message="No results")
            result = adapter.search_products(query="nonexistent-product-zzz")
            assert result.success is False

    def test_find_beauty_product_success(self):
        adapter = PriceInIndiaAdapter(timeout_seconds=0.1, max_retries=1)
        with patch.object(adapter, "search_products") as mock_search:
            mock_search.return_value = McpCallResult(
                success=True, tool_name="search_products",
                data={"total": 3},
                items=[{"id": "p1", "title": "Product A"}],
            )
            result = adapter.find_beauty_product(brand="TestBrand", product_name="Product")
            assert result.success is True
            assert len(result.items) == 1

    def test_find_beauty_product_no_results(self):
        adapter = PriceInIndiaAdapter(timeout_seconds=0.1, max_retries=1)
        with patch.object(adapter, "search_products") as mock_search:
            mock_search.return_value = McpCallResult(success=False, tool_name="search_products")
            result = adapter.find_beauty_product(brand="Unknown", product_name="Xyz")
            assert result.success is False
            assert "No results" in result.error_message

    def test_health_property(self):
        adapter = PriceInIndiaAdapter()
        h = adapter.health
        assert h.name == "PriceInIndia"
        assert h.is_configured is True


# ── OpenBeautyFactsAdapter tests ──────────────────────────────────────────────

class TestOpenBeautyFactsAdapter:
    def test_lookup_by_barcode_not_found(self):
        adapter = OpenBeautyFactsAdapter()
        with patch("src.adapters.mcp_adapters.open_beauty_facts_adapter.httpx.Client") as MockClient:
            bad_resp = MagicMock()
            bad_resp.status_code = 404
            bad_resp.raise_for_status.side_effect = Exception("404")
            MockClient.return_value.__enter__.return_value.get.return_value = bad_resp
            result = adapter.lookup_by_barcode("9999999999999")
            assert result.success is False
            assert "not found" in result.error_message.lower()

    def test_lookup_by_barcode_success(self):
        adapter = OpenBeautyFactsAdapter()
        mock_product = {
            "code": "5901234123454",
            "product_name": "Test Cream",
            "brands": "TestBrand",
            "quantity": "50 ml",
            "categories_tags": ["skincare", "face-cream"],
            "ingredients_text": "Aqua, Glycerin",
            "last_modified_t": 1700000000,
        }
        with patch("src.adapters.mcp_adapters.open_beauty_facts_adapter.httpx.Client") as MockClient:
            good_resp = MagicMock()
            good_resp.json.return_value = {"product": mock_product}
            good_resp.raise_for_status.return_value = None
            MockClient.return_value.__enter__.return_value.get.return_value = good_resp
            result = adapter.lookup_by_barcode("5901234123454")
            assert result.success is True
            assert result.data["barcode"] == "5901234123454"
            assert result.data["product_name"] == "Test Cream"

    def test_search_products_success(self):
        adapter = OpenBeautyFactsAdapter()
        with patch("src.adapters.mcp_adapters.open_beauty_facts_adapter.httpx.Client") as MockClient:
            good_resp = MagicMock()
            good_resp.json.return_value = {
                "products": [{"code": "111", "product_name": "Search Result", "brands": "BrandX"}],
                "count": 1,
            }
            good_resp.raise_for_status.return_value = None
            MockClient.return_value.__enter__.return_value.get.return_value = good_resp
            result = adapter.search_products(brands=["BrandX"], limit=5)
            assert result.success is True
            assert len(result.items) == 1

    def test_health_status(self):
        adapter = OpenBeautyFactsAdapter()
        hs = adapter.health_status
        assert hs["name"] == "OpenBeautyFacts"
        assert "endpoint" in hs
        assert "is_healthy" in hs

    def test_rate_limiting(self):
        adapter = OpenBeautyFactsAdapter()
        import time
        now = time.time()
        adapter._request_timestamps = [now] * 10  # hit limit
        allowed, err = adapter._check_rate_limit()
        assert allowed is False
        assert "rate limit" in err.lower()
