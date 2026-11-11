"""Phase 16.5.2 regression tests for the PriceInIndia MCP adapter.

All network access is mocked: no test touches the real
``https://mcp.priceinindia.website/mcp`` endpoint. The tests lock in:

- Streamable HTTP request shape (JSON-RPC envelope + required Accept header)
- JSON and SSE (``text/event-stream``) response parsing
- Honest empty / timeout / HTTP-error / malformed reporting — never a
  fabricated price
- Unicode and INR payload preservation
- Catalog import provenance, invalid-price rejection and observation capture
"""

import json
from functools import partial

import httpx
import pytest

from src.adapters.mcp_adapters import base_mcp_adapter
from src.adapters.mcp_adapters.base_mcp_adapter import BaseMcpAdapter, McpCallResult
from src.adapters.mcp_adapters import priceinindia_adapter as pia
from src.adapters.mcp_adapters.priceinindia_adapter import (
    MCP_ENDPOINT,
    PriceInIndiaAdapter,
)
from src.database.connection import get_connection


# ── Helpers ──────────────────────────────────────────────────────────────────

def _response(body: str, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        text=body,
        request=httpx.Request("POST", MCP_ENDPOINT),
    )


def _envelope(result: dict) -> str:
    return json.dumps({"jsonrpc": "2.0", "id": 1, "result": result})


def _products_body(products: list, total=None) -> str:
    return _envelope(
        {
            "structuredContent": {
                "total": len(products) if total is None else total,
                "products": products,
            }
        }
    )


def _sample_product(**overrides):
    product = {
        "id": "pi-1001",
        "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
        "brand": "Dot & Key",
        "price": 465.0,
        "mrp": 595.0,
        "currency": "INR",
        "store": "Nykaa",
        "productPageUrl": "https://www.nykaa.com/dot-key-watermelon/p/1001",
        "image_url": "https://cdn.example/dot-key.jpg",
    }
    product.update(overrides)
    return product


def _install_client(monkeypatch, responder):
    """Replace httpx.Client with a deterministic fake and record calls."""
    calls: list[dict] = []

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.timeout = kwargs.get("timeout")

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json=None, headers=None):
            calls.append(
                {
                    "url": url,
                    "payload": json,
                    "headers": headers,
                    "timeout": self.timeout,
                }
            )
            return responder(len(calls) - 1)

    monkeypatch.setattr(base_mcp_adapter.httpx, "Client", FakeClient)
    return calls


# ── Request shape ────────────────────────────────────────────────────────────

def test_search_sends_streamable_http_accept_header(monkeypatch):
    calls = _install_client(monkeypatch, lambda i: _response(_products_body([])))

    adapter = PriceInIndiaAdapter(max_retries=0)
    adapter.search_products("Dot & Key Sunscreen")

    assert len(calls) == 1
    headers = calls[0]["headers"]
    assert headers["Accept"] == "application/json, text/event-stream"
    assert headers["Content-Type"] == "application/json"
    assert calls[0]["url"] == MCP_ENDPOINT
    # The configured timeout must reach httpx.
    assert calls[0]["timeout"] == adapter.timeout_seconds


def test_search_sends_jsonrpc_tool_call_envelope(monkeypatch):
    calls = _install_client(monkeypatch, lambda i: _response(_products_body([])))

    adapter = PriceInIndiaAdapter(max_retries=0)
    adapter.search_products("Niacinamide Serum", brand="Minimalist", per_page=5)

    payload = calls[0]["payload"]
    assert payload["jsonrpc"] == "2.0"
    assert payload["method"] == "tools/call"
    assert payload["params"]["name"] == "search_products"
    args = payload["params"]["arguments"]
    assert args["query"] == "Niacinamide Serum"
    assert args["brand"] == "Minimalist"
    assert args["per_page"] == 5


# ── Response parsing ─────────────────────────────────────────────────────────

def test_search_parses_structured_content_products(monkeypatch):
    product = _sample_product()
    _install_client(monkeypatch, lambda i: _response(_products_body([product])))

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("Dot & Key Sunscreen")

    assert result.success is True
    assert result.tool_name == "search_products"
    assert len(result.items) == 1
    assert result.items[0]["title"] == product["title"]
    assert result.items[0]["price"] == 465.0
    assert result.items[0]["currency"] == "INR"
    assert result.items[0]["_source"] == "priceinindia"
    assert result.data["total"] == 1


def test_search_parses_sse_stream_response(monkeypatch):
    product = _sample_product(price=499.0, store="Tira")
    sse_body = f"event: message\ndata: {_products_body([product])}\n\n"
    _install_client(monkeypatch, lambda i: _response(sse_body))

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("Dot & Key Sunscreen")

    assert result.success is True
    assert len(result.items) == 1
    # The JSON-RPC envelope must be unwrapped, not treated as a product row.
    assert result.items[0]["title"] == product["title"]
    assert result.items[0]["price"] == 499.0
    assert "jsonrpc" not in result.items[0]


def test_legacy_raw_sse_events_still_surface_as_items():
    """Preserves the pre-existing raw-event parsing behaviour."""
    adapter = BaseMcpAdapter(name="T", mcp_endpoint=MCP_ENDPOINT)
    sse_text = (
        'event: message\ndata: {"tool_name": "search", "data": {"products": [{"id": 1}]}}\n\n'
        'event: message\ndata: {"tool_name": "search", "data": {"products": []}}\n\n'
    )
    result = adapter._parse_response(sse_text, 200, 1.0)
    assert result.success is True
    assert len(result.items) == 2


def test_empty_results_are_reported_without_fabricating_prices(monkeypatch):
    _install_client(
        monkeypatch,
        lambda i: _response(_products_body([], total=0)),
    )

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("product-that-does-not-exist")

    assert result.success is True
    assert result.items == []
    assert result.data["total"] == 0
    # No price was invented anywhere in the payload.
    assert all("price" not in item for item in result.items)


def test_item_without_price_is_passed_through_unchanged(monkeypatch):
    no_price = {"id": "pi-x", "title": "Unpriced Item", "store": "Nykaa"}
    _install_client(monkeypatch, lambda i: _response(_products_body([no_price])))

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("unpriced")

    assert result.items[0]["title"] == "Unpriced Item"
    assert "price" not in result.items[0]


def test_unicode_and_inr_values_are_preserved(monkeypatch):
    product = _sample_product(
        title="Dot & Key Watermelon Cooling Sunscreen ₹465 (50g) — PA++++",
        price=465.0,
        mrp=595.0,
    )
    _install_client(monkeypatch, lambda i: _response(_products_body([product])))

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("Dot & Key")

    item = result.items[0]
    assert "₹465" in item["title"]
    assert "—" in item["title"]
    assert item["price"] == 465.0
    assert item["mrp"] == 595.0
    assert item["currency"] == "INR"


def test_compare_prices_tags_every_item_with_source(monkeypatch):
    items = [_sample_product(store="Nykaa"), _sample_product(id="pi-2", store="Tira")]
    _install_client(
        monkeypatch,
        lambda i: _response(_envelope({"structuredContent": {"items": items}})),
    )

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.compare_prices("Dot & Key Sunscreen")

    assert result.success is True
    assert len(result.items) == 2
    assert all(item["_source"] == "priceinindia" for item in result.items)


# ── Failure reporting ────────────────────────────────────────────────────────

def test_timeout_is_reported_as_failure(monkeypatch):
    def responder(_index):
        raise httpx.TimeoutException("timed out")

    _install_client(monkeypatch, responder)

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("slow-product")

    assert result.success is False
    assert result.items == []
    assert "Timeout" in result.error_message
    assert adapter.health.failed_requests == 1
    assert adapter.health.is_healthy is False
    assert adapter.status == "error"


def test_retries_until_success(monkeypatch):
    monkeypatch.setattr(base_mcp_adapter.time, "sleep", lambda *_: None)
    attempt = {"count": 0}

    def responder(index):
        attempt["count"] += 1
        if index < 2:
            raise httpx.TimeoutException("temporary timeout")
        return _response(_products_body([_sample_product()]))

    calls = _install_client(monkeypatch, responder)

    adapter = PriceInIndiaAdapter(max_retries=2)
    result = adapter.search_products("Dot & Key")

    assert result.success is True
    assert len(calls) == 3
    assert len(result.items) == 1
    assert adapter.health.is_healthy is True


def test_http_rate_limit_is_reported(monkeypatch):
    _install_client(
        monkeypatch,
        lambda i: _response("Too Many Requests", status=429),
    )

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("Dot & Key")

    assert result.success is False
    assert "429" in result.error_message
    assert "Too Many Requests" in result.error_message
    assert adapter.health.is_healthy is False


def test_malformed_response_does_not_raise(monkeypatch):
    _install_client(monkeypatch, lambda i: _response("<<<not-json>>>"))

    adapter = PriceInIndiaAdapter(max_retries=0)
    result = adapter.search_products("Dot & Key")

    assert result.success is False
    assert result.items == []
    assert result.error_message == "Unparseable MCP response"


def test_client_side_rate_limit_blocks_requests(monkeypatch):
    calls = _install_client(monkeypatch, lambda i: _response(_products_body([])))

    adapter = PriceInIndiaAdapter(max_retries=0)
    adapter.rate_limit_per_minute = 0
    result = adapter.search_products("Dot & Key")

    assert result.success is False
    assert "Rate limit" in result.error_message
    assert calls == []  # no HTTP request was made


def test_health_after_successful_call(monkeypatch):
    _install_client(monkeypatch, lambda i: _response(_products_body([_sample_product()])))

    adapter = PriceInIndiaAdapter(max_retries=0)
    assert adapter.status == "never_run"

    adapter.search_products("Dot & Key")
    assert adapter.status == "healthy"
    assert adapter.health.last_success_at is not None
    assert adapter.health.total_requests == 1


# ── Catalog import ───────────────────────────────────────────────────────────

@pytest.fixture
def isolated_db(monkeypatch, fresh_seeded_db):
    """Route the adapter's default connection at an isolated seeded DB."""
    monkeypatch.setattr(
        pia, "get_connection", lambda *a, **k: get_connection(fresh_seeded_db)
    )
    return fresh_seeded_db


def test_import_rejects_non_positive_price(isolated_db):
    adapter = PriceInIndiaAdapter(max_retries=0)
    bad_item = _sample_product(id="pi-bad", price=0)
    adapter.find_beauty_product = lambda **kwargs: McpCallResult(
        success=True,
        tool_name="find_beauty_product",
        data={"total": 1},
        items=[bad_item],
    )

    summary = adapter.import_to_catalog(
        brand="Dot & Key",
        product_name="Watermelon Sunscreen",
        admin_user_id=1,
    )

    assert summary["imported_count"] == 0
    assert summary["error_count"] == 1
    assert any("invalid price" in err.lower() for err in summary["errors"])


def test_import_records_product_and_provenance_observation(isolated_db):
    adapter = PriceInIndiaAdapter(max_retries=0)
    item = _sample_product(
        id="pi-new-1",
        title="Phase Test Unique Serum 30ml",
        brand="PhaseTestBrand",
        price=349.0,
        mrp=499.0,
        store="nykaa.com",
    )
    adapter.find_beauty_product = lambda **kwargs: McpCallResult(
        success=True,
        tool_name="find_beauty_product",
        data={"total": 1},
        items=[item],
    )

    summary = adapter.import_to_catalog(
        brand="PhaseTestBrand",
        product_name="Unique Serum",
        admin_user_id=1,
    )

    assert summary["imported_count"] == 1
    assert summary["error_count"] == 0
    product_id = summary["imported"][0]["product_id"]

    with get_connection(isolated_db) as conn:
        product = conn.execute(
            "SELECT sku, brand, source_type, data_status FROM products WHERE id=?",
            (product_id,),
        ).fetchone()
        assert product["brand"] == "PhaseTestBrand"
        assert product["source_type"] == "catalog_verified"
        assert product["data_status"] == "pending_review"

        obs = conn.execute(
            "SELECT retailer, observed_price, observed_mrp, observation_status,"
            " verification_status, evidence_notes, evidence_reference"
            " FROM retail_price_observation WHERE product_id=?",
            (product_id,),
        ).fetchone()
        assert obs is not None
        assert obs["observed_price"] == 349.0
        assert obs["observed_mrp"] == 499.0
        assert obs["observation_status"] == "live"
        assert obs["evidence_reference"].startswith("https://")
        assert "Auto-imported from PriceInIndia" in obs["evidence_notes"]


def test_import_without_results_reports_failure(isolated_db):
    adapter = PriceInIndiaAdapter(max_retries=0)
    adapter.find_beauty_product = lambda **kwargs: McpCallResult(
        success=False, tool_name="find_beauty_product", error_message="no results"
    )

    summary = adapter.import_to_catalog(
        brand="Nobody", product_name="Nothing", admin_user_id=1
    )

    assert summary["success"] is False
    assert "No products found" in summary["error"]
    assert summary["actions"] == []
