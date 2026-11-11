# Phase 16.5.2 — Stage 1 Test Baseline Report

**Date:** 2026-11-11
**Branch:** `feature/phase-16-live-price-activation`
**Commit:** `5ffc314b647537d21bd5ee77a62adc2245ae5544`
**Working tree:** clean at start; no application code changed in this stage.

## Exact command

```
.venv\Scripts\python.exe -m pytest -q
```
(Python 3.15.0, pytest config: `pythonpath = .`, `testpaths = tests`)

## Collection

- **343 tests collected** (`pytest --collect-only -q`).

## Result (baseline)

| Metric | Count |
|---|---|
| Passed | 234 |
| Failed | 7 |
| Errors | 102 |
| Skipped | 0 |
| Duration | 35.24s |

This **reproduces** the previously reported 234 passed / 7 failed / 102 errors on the current commit.

## Failures (7)

| # | Test | Category |
|---|---|---|
| 1 | `tests/test_phase5_retailer_integrations_and_deals.py::test_verified_match_for_identical_variant` | Product matching |
| 2 | `tests/test_phase6_live_price_engine.py::TestPhase6LivePriceEngine::test_variant_matching_exact_match` | Product matching |
| 3 | `tests/test_phase6a_foundation.py::TestFastApiBridge::test_get_product_by_slug_or_id` | Environmental / DB fixture |
| 4 | `tests/test_phase6a_foundation.py::TestFastApiBridge::test_list_products_filtering` | Environmental / DB fixture |
| 5 | `tests/test_phase6a_foundation.py::TestDatabaseIntegrity::test_backup_file_exists` | Environmental / DB fixture |
| 6 | `tests/test_phase6a_foundation.py::TestDatabaseIntegrity::test_database_counts` | Environmental / DB fixture |
| 7 | `tests/test_phase8_integration.py::test_p8_08_migrate_database_with_existing_phase6_records` | SQLite migration |

## Representative tracebacks

### 1. Product matching (both failures)

```
assert 'possible_match' == 'verified_match'
```
Root cause: `evaluate_product_match()` adds `"Unit price unavailable for comparison"` to
`quality_issues` whenever `reference_price` / `offer_price` are not supplied. Because both
calls in these tests omit prices, the function downgrades an otherwise exact identity match
to `POSSIBLE_MATCH`. Unit price is an analytics output, not product-identity evidence.

### 2. SQLite migration

```
src/database/connection.py:456: OperationalError
E  sqlite3.OperationalError: Cannot add a column with non-constant default
E  ALTER TABLE products ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
```
SQLite forbids adding a column whose default is a non-constant expression (`CURRENT_TIMESTAMP`).

### 3. Closed database (102 errors)

All 102 errors are identical:

```
src/database/seed.py:706: ProgrammingError
E  sqlite3.ProgrammingError: Cannot operate on a closed database.
```
The Phase 16.2 OBF seeding block (lines 703–744) is **dedented outside** the
`with get_connection(...) as conn:` block (it sits at 4-space function level instead of
8-space `with`-body level), so it reuses `cursor` after the context manager closed the
connection. Reproduced in isolation with a standalone `seed_database(custom_path=tmp)` call.

### 4. Environmental (4)

- `test_database_counts` — asserts 32 products / 10 stores / 95 offers against the **developer's
  local** `data/pricewise.db`, which currently holds 6 products (`AssertionError: 6 != 32`).
  A fresh `seed_database()` produces exactly 32 / 10 / 95 / 941, so the test is valid only
  against a freshly seeded isolated DB.
- `test_backup_file_exists` — expects `data/pricewise.db.backup_phase6a`, which is not present
  on this checkout.
- `test_get_product_by_slug_or_id` — expects a hard-coded product id `76`; a fresh seed assigns
  the watermelon sunscreen id `12`.
- `test_list_products_filtering` — depends on the local DB containing the seeded beauty catalog.

## Reproduction confirmation

The 7 failures and 102 errors reproduce identically on the current commit `5ffc314`.
No application code was modified during this stage.
