# Phase 16.2 Stage 3.1 — Manual Retailer Price Entry Report

**Date:** 2026-11-10  
**Status:** ✅ Complete — All tests passing (51/51)

---

## Overview

Phase 16.2 Stage 3.1 implements a **Manual Retailer Price Entry** workflow, enabling authenticated admin users to manually record price observations from supported retailers without auto-verification. This stage fills the gap identified in the Stage 3 audit where only scheduled sweep observations were available.

---

## Implementation Summary

### New Files

| File | Description |
|------|-------------|
| `src/services/price_collection_engine.py` | Core service engine with all observation and verification functions |
| `tests/test_phase16_2_stage3_price_observations.py` | 29 regression tests for Stage 3 price observations and manual entry |
| `tests/test_phase16_2_obf_verification.py` | 22 regression tests for OBF product verification workflow |

### Modified Files

| File | Changes |
|------|---------|
| `data/schema.sql` | Added `products` columns (`data_status`, `source_type`, `is_active`, `updated_at`); added `retail_price_observation` table; added `obf_product_verification` table |
| `src/database/connection.py` | Added migration #15 (products columns), migration #16 (evidence columns), migration #17 (remove UNIQUE constraint on observations); added `updated_at` column migration for products |
| `src/api/main.py` | Added `POST /api/admin/price-observations/manual` endpoint with Pydantic request/response schemas |
| `src/database/seed.py` | Added `DEMO_OBF_PRODUCTS` array (5 beauty products) and OBF seeding logic in `seed_database()` |

---

## Key Components

### Enums

- **ObservationType**: `scheduled`, `manual`, `user_report`
- **ObservationStatus**: `live`, `expired`, `superseded`, `flagged`
- **VerificationStatus**: `pending_review`, `catalog_verified`, `manufacturer_verified`

### Service Functions

| Function | Purpose |
|----------|---------|
| `record_price_observation()` | Record scheduled/user-reported observations; auto-supersedes LIVE obs |
| `record_manual_price_observation()` | Admin-only manual entry; creates FLAGGED + pending obs |
| `admin_verify_observation()` | Admin verifies/corrects an observation; sets status to LIVE |
| `get_price_observations()` | Query observations with flexible filters |
| `count_price_observations()` | Count matching observations |
| `run_scheduled_observations()` | Scheduled sweep; handles restricted retailers |
| `approve_obf_product_verification()` | Approve OBF product → manufacturer_verified |
| `reject_obf_product_verification()` | Reject OBF product → pending_review |
| `request_obf_product_review()` | Flag for review without changing data_status |
| `count_obf_products_pending_verification()` | Count pending OBF products |
| `get_obf_products_pending_verification()` | Get list of pending OBF products |
| `get_obf_verification_history()` | Retrieve audit history |

### Validation Rules (Stage 3.1)

- Admin user required (`TypeError` if None)
- Product must exist and be active (`ValueError`)
- Retailer must be supported (`ValueError`)
- Price must be positive finite number (`ValueError`)
- URL cannot be retailer homepage (`ValueError`)
- URL must match retailer domain (`ValueError`)
- Manual observations created as `FLAGGED` + `pending` — **no auto-verification**

### Supersede Semantics

- When recording a new observation for `product_id + retailer`, any existing `LIVE` observation is automatically set to `SUPERSEDED`
- `FLAGGED` observations are preserved for audit trail
- Multiple manual entries for the same product+retailer are both recorded (only LIVE ones supersede)

---

## Test Results

```
============================= test session starts ==============================
collected 51 items

tests/test_phase16_2_stage3_price_observations.py ............
tests/test_phase16_2_obf_verification.py ...........................
============================= 51 passed in 3.59s ===============================
```

### Test Coverage by Category

**Stage 3 — Price Observations (29 tests):**
- Schema and migration idempotency (3)
- Observation type/status validation (2)
- Recording with supersede semantics (3)
- Query filters and counts (2)
- Admin verification workflow (3)
- Scheduled sweep handling (2)
- Status transitions (3)
- Full lifecycle: supersede → verify (1)
- Manual price entry validation (6)
- Manual entry audit history (2)
- Sweep does not revert manual flagged (1)

**Stage 2 — OBF Verification (22 tests):**
- Initial state verification (2)
- Status distinction and promotion (5)
- Audit history preservation (4)
- Auth requirement enforcement (1)
- Migration idempotency (3)
- Transition matrix (7)

---

## API Endpoint

```http
POST /api/admin/price-observations/manual
Content-Type: application/json
Authorization: Bearer <token>

{
  "product_id": 1,
  "retailer": "nykaa",
  "product_url": "https://nykaa.com/product/sunscreen",
  "observed_price": 849.0,
  "observed_mrp": 999.0,
  "size_volume": "50ml",
  "shade": "Rose",
  "formulation": "Serum",
  "evidence_notes": "Admin confirmed via retailer listing",
  "evidence_reference": "https://nykaa.com/product/sunscreen"
}
```

**Response (200 OK):**
```json
{
  "id": 1,
  "product_id": 1,
  "retailer": "nykaa",
  "product_url": "https://nykaa.com/product/sunscreen",
  "observed_price": 849.0,
  "observed_mrp": 999.0,
  "size_volume": "50ml",
  "shade": "Rose",
  "formulation": "Serum",
  "observation_type": "manual",
  "observation_status": "flagged",
  "verified_by_admin": false,
  "verified_price": null,
  "verification_status": "pending",
  "admin_user_id": 1,
  "created_at": "2026-11-10T...",
  "evidence_notes": "Admin confirmed via retailer listing",
  "evidence_reference": "https://nykaa.com/product/sunscreen"
}
```

---

## Design Decisions

1. **No UNIQUE(product_id, retailer)** — Removed to allow multiple observations per product-retailer pair for audit history. Supersede logic handled programmatically.

2. **Manual = FLAGGED + pending** — Manual entries are never auto-verified. They require explicit admin verification before becoming LIVE.

3. **Flagged observations preserved** — Only LIVE observations are superseded. Previous FLAGGED entries remain accessible for audit.

4. **VerificationStatus as Enum (not str Enum)** — Avoided Python 3.15 compatibility issues with `str, Enum` class-level tuple initialization. Used `.value` for DB operations and string comparisons.

5. **Evidence notes normalization** — Empty/None evidence_notes stored as empty string to satisfy NOT NULL constraint while allowing optional input.

---

## Files Changed

```
data/schema.sql
src/database/connection.py
src/database/seed.py
src/services/price_collection_engine.py
src/api/main.py
tests/test_phase16_2_stage3_price_observations.py  [NEW]
tests/test_phase16_2_obf_verification.py           [NEW]
```
