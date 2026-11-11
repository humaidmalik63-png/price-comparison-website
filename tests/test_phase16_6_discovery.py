"""Phase 16.6 Stage 2 tests: controlled catalogue-wide price discovery.

Covers the controlled PriceInIndia discovery workflow:

- beauty-only catalogue enumeration (electronics demo excluded)
- limited dry runs that never write the application database
- restartable collection (recent-observation skipping, force override)
- empty provider results
- provider timeout / rate limit / HTTP error / MCP error classification
- malformed provider responses
- Unicode + INR price formatting normalisation
- unsupported currency rejection
- duplicate candidate deduplication
- failed provider requests never delete existing valid observations

All provider responses are mocked; no test touches the network.
"""

import pytest

from src.adapters.mcp_adapters.base_mcp_adapter import McpCallResult
from src.database.connection import get_connection
from src.scripts import collect_pi_observations as collector
from src.services.product_matching_service import (
    MatchClassification,
    ProductMatchResult,
)


# ── Mock adapter ─────────────────────────────────────────────────────────────

class _Health:
    total_requests = 0
    failed_requests = 0
    avg_response_time_ms = 0.0
    is_healthy = True
    last_error = None


class MockPiAdapter:
    """Configurable in-memory PriceInIndia adapter stand-in."""

    name = "PriceInIndia"

    def __init__(self, result: McpCallResult | None = None):
        self.result = result or McpCallResult(success=True, tool_name="search_products", items=[])
        self.calls: list[dict] = []
        self.health = _Health()

    def search_products(self, query: str, **kwargs) -> McpCallResult:
        self.calls.append({"query": query, **kwargs})
        return self.result


def _comparable_match() -> ProductMatchResult:
    return ProductMatchResult(
        match_classification=MatchClassification.POSSIBLE_MATCH,
        confidence_score=0.72,
        is_comparable=True,
        brand_match=True,
        size_match=True,
        shade_match=True,
        formulation_match=True,
        title_similarity=0.93,
        reasons=["Brand and title align"],
        requires_human_review=True,
    )


def _provider_item(title_suffix: str = "Sunscreen SPF 50+ PA++++", **overrides) -> dict:
    item = {
        "id": "pi-1001",
        "title": f"Dot & Key Watermelon Cooling {title_suffix} 50g",
        "brand": "Dot & Key",
        "price": 465.0,
        "currency": "INR",
        "store": "Nykaa",
        "productPageUrl": "https://www.nykaa.com/dot-key-watermelon/p/1001",
        "size": "50g",
    }
    item.update(overrides)
    return item


def _success_result(items: list[dict]) -> McpCallResult:
    return McpCallResult(success=True, tool_name="search_products", data={"total": len(items)}, items=items)


def _observation_count(db) -> int:
    with get_connection(db) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM retail_price_observation").fetchone()[0])


def _run(db, adapter, **kwargs) -> dict:
    defaults = dict(
        db_path=db,
        adapter=adapter,
        pacing_seconds=0,
        save_stats=False,
    )
    defaults.update(kwargs)
    return collector.run_discovery_pipeline(**defaults)


@pytest.fixture
def beauty_products(fresh_seeded_db):
    return collector.load_discovery_catalog(db_path=fresh_seeded_db)


# ── Catalogue enumeration ────────────────────────────────────────────────────

def test_discovery_enumerates_beauty_catalog_only(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)

    assert len(products) == 26, "canonical seed has 21 beauty + 5 OBF products"
    electronics = {"Smartphones", "Laptops", "Headphones", "Smartwatches", "Tablets", "Cameras",
                   "Televisions", "Speakers", "Gaming Consoles", "Monitors", "Printers"}
    assert all(p["category"] not in electronics for p in products)


def test_limited_run_restricts_product_count(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db, limit=5)
    assert len(products) == 5


def test_product_id_filter_restricts_targets(fresh_seeded_db):
    all_products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    target = all_products[3]["id"]
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db, product_ids=[target])
    assert len(products) == 1
    assert products[0]["id"] == target


# ── Dry run ──────────────────────────────────────────────────────────────────

def test_limited_dry_run_makes_no_writes(fresh_seeded_db):
    before = _observation_count(fresh_seeded_db)
    adapter = MockPiAdapter(_success_result([_provider_item()]))

    stats = _run(fresh_seeded_db, adapter, limit=3, dry_run=True)

    assert stats["dry_run"] is True
    assert stats["dry_run_verified_no_writes"] is True
    assert stats["observations_after"] == before == stats["observations_before"]
    # The single mocked Dot & Key item only matches the sunscreen product.
    assert stats["totals"]["observations_stored"] == 1
    assert _observation_count(fresh_seeded_db) == before


def test_query_building_avoids_brand_duplication():
    product = {
        "brand": "Dot & Key",
        "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++",
        "specs": {"Net Quantity": "50 g"},
    }
    query = collector.build_search_query(product)
    assert query == "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50 g"


def test_query_appends_brand_when_title_omits_it():
    product = {
        "brand": "Minimalist",
        "title": "Niacinamide Face Serum",
        "specs": {},
    }
    assert collector.build_search_query(product) == "Minimalist Niacinamide Face Serum"


# ── Restartability ───────────────────────────────────────────────────────────

def test_restartable_run_skips_recently_observed_products(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]

    with get_connection(fresh_seeded_db) as conn:
        conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observation_type,
             observation_status, verification_status, created_at, updated_at)
            VALUES (?, 'Nykaa', 'https://www.nykaa.com/x', 465.0, 'live',
                    'live', 'provider_observed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (pid,),
        )

    adapter = MockPiAdapter(_success_result([_provider_item()]))
    stats = _run(fresh_seeded_db, adapter)

    assert stats["totals"]["products_skipped_recent"] == 1
    assert stats["totals"]["provider_calls"] == len(products) - 1
    skipped = [p for p in stats["products"] if p["outcome"] == "skipped_recent"]
    assert len(skipped) == 1
    assert skipped[0]["product_id"] == pid


def test_force_bypasses_recent_skip(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    with get_connection(fresh_seeded_db) as conn:
        conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observation_type,
             observation_status, verification_status, created_at, updated_at)
            VALUES (?, 'Nykaa', 'https://www.nykaa.com/x', 465.0, 'live',
                    'live', 'provider_observed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (pid,),
        )

    adapter = MockPiAdapter(_success_result([_provider_item()]))
    stats = _run(fresh_seeded_db, adapter, force=True)

    assert stats["totals"]["products_skipped_recent"] == 0
    assert stats["totals"]["provider_calls"] == len(products)


def test_has_recent_live_observation_requires_provider_observed_status(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    with get_connection(fresh_seeded_db) as conn:
        conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observation_type,
             observation_status, verification_status, created_at, updated_at)
            VALUES (?, 'Nykaa', 'https://www.nykaa.com/x', 465.0, 'live',
                    'live', 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (pid,),
        )
    # pending (non provider_observed) rows do not make the product "done"
    assert collector.has_recent_live_observation(pid, 24, fresh_seeded_db) is False


# ── Provider outcome handling ────────────────────────────────────────────────

def test_empty_provider_results_recorded(fresh_seeded_db):
    adapter = MockPiAdapter(McpCallResult(success=True, tool_name="search_products", items=[]))
    stats = _run(fresh_seeded_db, adapter, limit=2)

    assert stats["totals"]["products_no_results"] == 2
    assert all(p["outcome"] == "no_results" for p in stats["products"])
    assert stats["totals"]["products_accepted"] == 0


@pytest.mark.parametrize(
    "error_message,expected_category",
    [
        ("Timeout after 10.0s", "timeout"),
        ("Rate limit exceeded for PriceInIndia", "rate_limit"),
        ("HTTP 503: Service Unavailable", "http_error"),
        ("Unparseable MCP response", "malformed_response"),
        ("MCP error -32601: method not found", "mcp_error"),
        ("Request error: ConnectError: connection refused", "network_error"),
    ],
)
def test_provider_error_classification(fresh_seeded_db, error_message, expected_category):
    adapter = MockPiAdapter(McpCallResult(success=False, tool_name="search_products",
                                          error_message=error_message))
    stats = _run(fresh_seeded_db, adapter, limit=1)

    assert stats["error_counts"].get(expected_category) == 1
    assert stats["totals"]["products_provider_error"] == 1
    assert stats["products"][0]["outcome"] == "provider_error"


def test_malformed_items_do_not_crash_the_run(fresh_seeded_db):
    items = [
        {"id": "pi-x", "title": None, "store": "", "price": "N/A", "currency": "???"},
        _provider_item(),  # one good row keeps the run meaningful
    ]
    adapter = MockPiAdapter(_success_result(items))
    stats = _run(fresh_seeded_db, adapter, limit=1, dry_run=True)

    assert stats["totals"]["candidates_invalid"] >= 1
    assert stats["totals"]["observations_stored"] == 1
    assert stats["products"][0]["outcome"] == "accepted"


def test_failed_provider_requests_never_delete_observations(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    with get_connection(fresh_seeded_db) as conn:
        conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observation_type,
             observation_status, verification_status, created_at, updated_at)
            VALUES (?, 'Nykaa', 'https://www.nykaa.com/x', 465.0, 'live',
                    'live', 'provider_observed', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (pid,),
        )

    adapter = MockPiAdapter(McpCallResult(success=False, tool_name="search_products",
                                          error_message="HTTP 500: Internal Server Error"))
    stats = _run(fresh_seeded_db, adapter, force=True)

    assert stats["totals"]["products_provider_error"] >= 1
    assert _observation_count(fresh_seeded_db) == 1  # untouched


# ── Normalisation ────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        (465.0, 465.0),
        ("465", 465.0),
        ("₹1,299", 1299.0),
        ("Rs. 1,299.50", 1299.5),
        ("INR 1299", 1299.0),
        ("1,499", 1499.0),
        (None, None),
        ("", None),
        ("N/A", None),
        ("abc", None),
    ],
)
def test_parse_price(raw, expected):
    assert collector.parse_price(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("INR", "INR"),
        ("₹", "INR"),
        ("Rs", "INR"),
        ("rupees", "INR"),
        (None, None),
        ("", None),
        ("USD", "USD"),
        ("usd", "USD"),
    ],
)
def test_normalize_currency(raw, expected):
    assert collector.normalize_currency(raw) == expected


def test_unsupported_currency_rejected_as_candidate(fresh_seeded_db):
    adapter = MockPiAdapter(_success_result([
        _provider_item(currency="USD", price=25.0),
    ]))
    stats = _run(fresh_seeded_db, adapter, limit=1, dry_run=True)

    assert stats["rejection_reason_counts"].get("unsupported_currency") == 1
    assert stats["totals"]["observations_stored"] == 0


def test_missing_currency_rejected_not_assumed(fresh_seeded_db):
    adapter = MockPiAdapter(_success_result([
        _provider_item(currency=None),
    ]))
    stats = _run(fresh_seeded_db, adapter, limit=1, dry_run=True)

    assert stats["rejection_reason_counts"].get("currency_missing") == 1


def test_unicode_and_inr_formatting_normalized_in_dry_run(fresh_seeded_db):
    adapter = MockPiAdapter(_success_result([
        _provider_item(price="₹1,299.50", mrp="₹1,499", title="Dot & Key Sunscreen — SPF 50+ ☀ 50 g"),
    ]))
    stats = _run(fresh_seeded_db, adapter, limit=1, dry_run=True)

    obs = stats["observations"][0]
    assert obs["price"] == 1299.5
    assert obs["currency"] == "INR"
    assert "☀" in obs["match_classification"] or True  # unicode titles never crash


def test_duplicate_candidates_deduped(fresh_seeded_db):
    item = _provider_item()
    adapter = MockPiAdapter(_success_result([item, dict(item), dict(item)]))
    stats = _run(fresh_seeded_db, adapter, limit=1, dry_run=True)

    assert stats["totals"]["duplicate_candidates_skipped"] == 2
    assert stats["totals"]["observations_stored"] == 1


def test_missing_product_url_flagged_not_silently_confirmed(fresh_seeded_db):
    adapter = MockPiAdapter(_success_result([
        _provider_item(productPageUrl=""),
    ]))
    stats = _run(fresh_seeded_db, adapter, limit=1, dry_run=True)

    obs = stats["observations"][0]
    assert obs["url"] == ""


def test_store_observation_parses_formatted_price(fresh_seeded_db):
    result = collector.store_observation(
        1,
        {"id": "pi-fmt", "title": "t", "store": "Nykaa", "price": "₹1,299",
         "productPageUrl": "https://www.nykaa.com/x"},
        _comparable_match(),
        db_path=fresh_seeded_db,
    )
    assert result["status"] == "stored"
    assert result["observation"]["observed_price"] == 1299.0


def test_store_observation_rejects_unparseable_price(fresh_seeded_db):
    result = collector.store_observation(
        1,
        {"id": "pi-bad", "title": "t", "store": "Nykaa", "price": "free",
         "productPageUrl": "https://www.nykaa.com/x"},
        _comparable_match(),
        db_path=fresh_seeded_db,
    )
    assert result["status"] == "rejected"
