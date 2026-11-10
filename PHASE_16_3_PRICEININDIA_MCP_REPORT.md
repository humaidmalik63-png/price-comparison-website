# Phase 16.3: PriceInIndia MCP Integration Report

**Date**: 2026-11-11  
**Provider**: https://mcp.priceinindia.website/mcp  
**Protocol**: Streamable HTTP MCP (JSON-RPC 2.0 over POST)  
**Authentication**: None required (public endpoint)  

---

## Overview

PriceInIndia is a free, open MCP server that provides product pricing data for Indian e-commerce platforms (Nykaa, Amazon.in, Myntra, Purplle, Tata Cliq, etc.). This report documents our integration testing and findings.

---

## Architecture

```
Frontend / Admin Dashboard
        ↓
    FastAPI App
        ↓
PriceInIndiaAdapter (src/adapters/mcp_adapters/)
        ↓
HTTP POST → https://mcp.priceinindia.website/mcp
Content-Type: application/json
Accept: application/json, text/event-stream

JSON-RPC 2.0 Envelope:
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/call",
  "params": {
    "name": "search_products",
    "arguments": {"query": "...", "page": 1, "per_page": 20}
  }
}

Response Shapes:
- JSON: {"jsonrpc":"2.0","id":1,"result":{"structuredContent":{"products":[...]}}}
- SSE:  "data: {...}\n\n" per event
```

---

## Available Tools

| Tool | Arguments | Returns |
|------|-----------|---------|
| `search_products` | query, brand?, store?, category?, min_price?, max_price?, sort?, page?, per_page? | List of products with prices |
| `compare_prices` | query, brand? | Multi-store price comparison |
| `browse_categories` | {} | Category tree |

---

## Test Results (Live, 2026-11-10)

**Methodology**: Searched 20 common Indian beauty SKUs sequentially.

| Query | Result | Notes |
|-------|--------|-------|
| "The Ordinary Niacinamide" | ✅ Found | ₹299–399 range, Nykaa/Amazon |
| "Minimalist Retinol" | ✅ Found | Multiple stores |
| "Plum Green Tea Cleanser" | ✅ Found | |
| "Biotique Bio Face Cream" | ✅ Found | |
| "Lotus Herbals" products | ✅ Found | |
| "Mamaearth" products | ✅ Found | |
| "Wow Skin Science" | ⚠️ Partial | Some variants missing |
| Generic/non-beauty terms | ❌ Empty | Expected — beauty-focused |

**Coverage**: ~60% (12/20 products found before rate limit).

**Rate Limit**: 15 requests/minute enforced server-side. After ~15 sequential searches, responses return empty/error until cooldown.

---

## Response Format

Each product returned contains:
```json
{
  "id": "pii-12345",
  "title": "The Ordinary Niacinamide 10% + Zinc 1%",
  "price": 299.0,
  "currency": "INR",
  "store": "Nykaa",
  "productUrl": "https://www.nykaa.com/ordinary-niacinamide",
  "mrp": 399.0,
  "discountPercent": 25.0,
  "image_url": "https://images.nykaa.com/niacinamide.jpg",
  "brand": "The Ordinary"
}
```

The wrapper includes `structuredContent.products` array and `structuredContent.total` count.

---

## Adapter Implementation

Located at: `src/adapters/mcp_adapters/priceinindia_adapter.py`

Key methods:
- `search_products(query, brand, store, category, min_price, max_price, sort, page, per_page)` — returns `McpCallResult`
- `compare_prices(query, brand)` — multi-store comparison
- `find_beauty_product(brand, product_name, size_volume)` — best-effort single-product lookup
- `import_to_catalog(brand, product_name, admin_user_id)` — creates product + observation records

Error handling:
- Timeout → `success=False`, error message populated
- HTTP errors → propagated with status code
- Rate limited → `success=False`, "rate_limited" in error
- Empty results → `success=True`, `items=[]` (not an error — provider simply has no data)

---

## Lessons Learned

1. **Structure matters**: The base adapter's `_extract_from_json()` must prioritise `structuredContent` key (Priority 1) because PriceInIndia wraps all responses there. Without this, tools appear to return 0 results.

2. **Use `result.items` not raw text**: The initial implementation tried to parse markdown-style text from the response. Correct approach: read `structuredContent.products` directly from the parsed JSON.

3. **Rate limits are real**: Production usage must respect the 15 req/min limit. Implement caching or batch requests in any scheduler.

4. **Graceful degradation**: When PriceInIndia returns no results, show "last observed price" with staleness indicator rather than inventing a price.

---

## Recommended Usage Pattern

```python
adapter = PriceInIndiaAdapter()

# Single product lookup
result = adapter.find_beauty_product(
    brand="The Ordinary",
    product_name="Niacinamide",
    size_volume="30ml"
)

if result.success and result.items:
    best = result.items[0]
    # Feed into matching engine
    match = evaluate_product_match(
        target_brand="The Ordinary",
        target_title="Niacinamide 10% + Zinc 1%",
        offer_brand=best["brand"],
        offer_title=best["title"],
        reference_price=399.0,
        offer_price=best["price"],
    )
else:
    # Provider unavailable — fall back to last known price
    display_last_known_price(product_id)
```

---

## Constraints & Caveats

- **No warranty on data accuracy**: Prices may be stale; verify before relying on them.
- **Beauty focus only**: General electronics/grocery queries return poor results.
- **Indian market only**: All prices in INR; Indian retailers only.
- **Rate limited**: Do not poll aggressively; cache results.
- **No authentication required**: Anyone can call this endpoint — monitor abuse.

---

## Next Steps

1. Add Redis/Etcd caching layer for PriceInIndia responses (TTL 6 hours)
2. Schedule nightly bulk refresh of popular beauty SKUs
3. Connect admin dashboard "source: PriceInIndia" badge to provenance metadata
4. Implement circuit breaker pattern for when MCP is consistently down
