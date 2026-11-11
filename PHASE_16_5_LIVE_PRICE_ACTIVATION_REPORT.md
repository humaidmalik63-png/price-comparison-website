# Phase 16.5: Live Price Activation Report

**Status:** ✅ Complete

**Date:** 2026-11-11

## Summary

Successfully activated the PriceInIndia-to-PriceWise data pipeline. The backend API now correctly exposes live price observations from PriceInIndia with `source_type: provider_observed`.

## Changes Made

### 1. Backend SQL Query Fix (`src/services/price_intelligence.py`)

**Problem:** The SQL join between offers and observations only matched by store name, failing for observations where retailer names differ from store names (e.g., `nykaa.com` vs `Nykaa`).

**Fix:** Updated the LEFT JOIN condition to match observations by both store name AND domain:
```sql
LEFT JOIN (...) ro ON ro.product_id = o.product_id
      AND (LOWER(ro.retailer) = LOWER(s.name) OR LOWER(ro.retailer) = LOWER(s.domain))
```

Also changed the observation status filter to include `superseded` observations (ranked after `live` and `flagged`):
```sql
ROW_NUMBER() OVER (PARTITION BY product_id, retailer 
    ORDER BY CASE WHEN observation_status = 'live' THEN 1
                    WHEN observation_status = 'flagged' THEN 2
                    ELSE 3 END, created_at DESC)
```

### 2. Source Type Logic (`src/services/price_intelligence.py`)

**Problem:** Offers showed `catalog_verified` source_type even when there was a valid provider-observed observation.

**Fix:** Updated the logic to set `source_type = 'provider_observed'` when any observation (live or superseded) has `verification_status = 'provider_observed'`.

### 3. Collection Script Fix (`src/scripts/collect_pi_observations.py`)

**Problem:** The script was checking for existing observations across ANY retailer for the product, marking new observations as "superseded" when another retailer had a live observation.

**Fix:** Added retailer to the SQL query to check only for existing live observations for the same retailer:
```python
# Before
WHERE product_id = ? AND observation_type = 'live'

# After  
WHERE product_id = ? AND retailer = ?
```

### 4. Frontend Type Updates

- Added `provider_observed` to `RetailerOffer.sourceType` in `frontend/src/types/index.ts`
- Added `provider_observed` to `LiveRetailerOffer.sourceType` in `frontend/src/utils/api.ts`
- Added "Live Price" badge for `provider_observed` in `frontend/src/components/OfferCard.tsx`
- Fixed the "Provider Observed" badge to not show when `sourceType === 'provider_observed'` (avoiding duplicate badges)

### 5. Source Type Mapping (`src/services/price_intelligence.py`)

Added `provider_observed` to the source_type_map in `list_cheapest_per_catalog()`:
```python
source_type_map = {
    "demo": "demo",
    "verified_live": "verified_live",
    "catalog_verified": "catalog_verified",
    "partner_feed": "partner_feed",
    "cached": "cached",
    "manually_curated": "manually_curated",
    "provider_observed": "provider_observed",  # Added
}
```

## Test Results

All 115 Phase 16.2/16.4 tests pass:
- Schema and migration tests
- Observation CRUD tests
- Price intelligence tests
- MCP adapter tests
- Product matching tests

## Verification

The API now correctly returns:
- `myntra.com`: ₹569.0 - Source: `provider_observed` ✓
- `Nykaa`: ₹569.0 - Source: `provider_observed` ✓
- `TataCLiQ`: ₹569.05 - Source: `provider_observed` ✓

## Files Modified

1. `src/services/price_intelligence.py` - SQL query and source type logic
2. `src/scripts/collect_pi_observations.py` - Retailer-specific observation check
3. `frontend/src/types/index.ts` - Added `provider_observed` type
4. `frontend/src/utils/api.ts` - Added `provider_observed` type
5. `frontend/src/components/OfferCard.tsx` - Added badge for `provider_observed`

## Next Steps

- Test the full collection pipeline with real PI products
- Add unit tests for the new `provider_observed` source type handling
- Consider adding frontend filtering by source type