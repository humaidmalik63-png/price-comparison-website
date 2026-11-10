# Phase 16.4: Frontend Integration Report — PriceWise AI Beauty

**Date**: 2026-11-11  
**Status**: Backend Complete · Frontend Ready to Wire  

---

## Current State

Backend API is fully operational with 43 routes including all 14 new Stage 4 endpoints. The React 19 frontend exists but has NOT yet been connected to the new price intelligence endpoints. This is the remaining integration work.

---

## Backend Endpoints Available for Frontend

### Product Detail Page Enhancement

| Endpoint | Purpose | Frontend Component |
|----------|---------|-------------------|
| `GET /api/products/{id}/offers` | Fetch all verified offers with prices | `ProductDetailPage.tsx` → offers section |
| `GET /api/products/{id}/cheapest` | Get best price at a glance | Header badge component |
| `GET /api/products/{id}/price-history` | Line chart of price over time | `PriceHistoryChart` component |
| `POST /api/match/product` | Evaluate offer-to-product match | Offer card match badge logic |

### Admin Dashboard Enhancement

| Endpoint | Purpose | Frontend Component |
|----------|---------|-------------------|
| `GET /api/admin/health-stats` | Overall data quality metrics | Dashboard stats cards |
| `GET /api/connectors/priceinindia/health` | MCP connector status | Connector health widget |
| `POST /api/connectors/priceinindia/search?q=` | Manual price search | Admin product editor |
| `POST /api/admin/match/correct` | Override mismatched matches | Match review panel |
| `POST /api/admin/price-observations/expire-stale` | Clean up stale data | Maintenance actions |

---

## Data Flow Architecture

```
User visits product page
    │
    ▼
GET /api/products/{slug_or_id}     ← existing product detail
    │
    ▼
GET /api/products/{id}/offers      ← NEW: verified offers
    │
    ▼
For each offer, call:
POST /api/match/product            ← NEW: verify match quality
    │
    ├─ verified_match   → Show green "Verified" badge
    ├─ possible_match   → Show yellow "Possible Match" badge  
    ├─ ambiguous_match  → Flag for admin review
    └── incompatible   → Hide offer / show warning
    │
    ▼
GET /api/products/{id}/price-history  ← NEW: sparkline chart
    │
    ▼
Display:
- Cheapest verified price (big number)
- Discount from MRP (%)
- Unit price (₹/ml or ₹/g)
- Price history sparkline
- Source badges (PriceInIndia / Manual / Demo)
```

---

## Proposed Frontend Components (Not Yet Built)

### 1. `OfferCard.tsx` — Display a single verified offer
```tsx
interface OfferCardProps {
  offer: VerifiedOffer;
  match?: ProductMatchResult;
  onCorrectMatch?: (override: string) => void;
}

// Shows: store name, price, discount %, unit price, 
// match badge (green/yellow/red), source provenance icon
```

### 2. `PriceHistoryChart.tsx` — Sparkline of past prices
```tsx
interface PriceHistoryChartProps {
  points: PriceHistoryPoint[];
  productTitle: string;
}

// SVG line chart, last 30 days, shaded area
// Shows current price as highlighted point
```

### 3. `MatchBadge.tsx` — Visual indicator of match confidence
```tsx
interface MatchBadgeProps {
  classification: string;  // 'verified_match' | 'possible_match' | ...
  confidence: number;       // 0.0–1.0
  onReview?: () => void;
}

// Color coding:
// verified_match   → 🟢 green + "Verified"
// possible_match   → 🟡 yellow + "Possible Match"  
// ambiguous_match  → 🟠 orange + "Needs Review"
// incompatible     → 🔴 red + "Different Product"
```

### 4. `ConnectorHealthWidget.tsx` — Admin dashboard widget
```tsx
interface ConnectorHealthProps {
  adapter: McpConnectorHealth;
}

// Shows: healthy/unhealthy icon, last checked time,
// avg response time, request count, error count
```

---

## API Client Module (Recommended)

Create `src/lib/api/client.ts`:
```typescript
export const api = {
  // Product offers
  getProductOffers: (productId: number) =>
    fetch(`/api/products/${productId}/offers`).then(r => r.json()),
  
  getProductCheapest: (productId: number) =>
    fetch(`/api/products/${productId}/cheapest`).then(r => r.json()),
  
  getPriceHistory: (productId: number, limit = 30) =>
    fetch(`/api/products/${productId}/price-history?limit=${limit}`).then(r => r.json()),
  
  // Product matching
  evaluateMatch: (params: MatchRequest) =>
    fetch('/api/match/product', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(params),
    }).then(r => r.json()),
  
  // Admin
  getHealthStats: () =>
    fetch('/api/admin/health-stats').then(r => r.json()),
  
  searchPriceInIndia: (query: string, brand?: string) =>
    fetch('/api/connectors/priceinindia/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, brand }),
    }).then(r => r.json()),
};
```

---

## Migration from Old to New Data Model

| Old Field | New Field | Mapping |
|-----------|-----------|---------|
| `offer.price` | `offer.current_price` | Direct |
| `offer.discount` | Calculated from `(original - current) / original` | Compute |
| `offer.unit_price` | `offer.unit_price` | Already present if qty in specs |
| `offer.source` | `offer.source_type` + `offer.latest_obs_status` | Merge |
| N/A | `offer.evidence_notes` | NEW — provenance trail |

---

## Security Considerations

1. **Admin endpoints** (`/api/admin/*`) require authentication — enforce via existing `get_current_user` dependency
2. **Manual price entry** validates URL format (must contain path, not just domain)
3. **Matching engine** is server-side only — frontend cannot manipulate classification scores
4. **Admin corrections** require explicit user identity logged in `evidence_notes`

---

## Estimated Implementation Effort

| Component | Estimated Time | Priority |
|-----------|---------------|----------|
| `api/client.ts` module | 1 hour | P0 |
| `OfferCard.tsx` with match badge | 2 hours | P0 |
| Update `ProductDetailPage.tsx` | 2 hours | P0 |
| `PriceHistoryChart.tsx` (SVG) | 3 hours | P1 |
| `ConnectorHealthWidget.tsx` | 1.5 hours | P1 |
| Admin dashboard wiring | 2 hours | P2 |
| **Total** | **~12 hours** | |

---

## Verification Checklist (Post-Integration)

- [ ] Product page shows cheapest verified price prominently
- [ ] Discount percentage renders correctly against MRP
- [ ] Unit price shown when quantity is known
- [ ] Price history chart renders without errors
- [ ] Match badges appear with correct colours
- [ ] Admin can see health stats on dashboard
- [ ] PriceInIndia search works from admin panel
- [ ] Expired observations don't appear in product offers
- [ ] Loading states handled for slow MCP responses
- [ ] Error fallbacks shown when MCP is down

---

## Status

**Backend**: ✅ Complete and tested (115 tests passing)  
**Frontend wiring**: ⏳ Pending (documented above)  
**Live MCP integration**: ✅ Tested (60% coverage on 20 SKU sweep)  
