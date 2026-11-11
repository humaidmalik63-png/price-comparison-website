# Phase 16.5.2 — Stabilization Report

**Date:** 2026-11-11
**Branch:** `feature/phase-16-live-price-activation` (never left; no `main`, no merge)
**Base commit:** `5ffc314b647537d21bd5ee77a62adc2245ae5544`
**Backup before any work:** `C:\Users\humai\Backups\pricewise-phase16.5.2-baseline-20261111`
**Status:** All stages complete. **Nothing committed, nothing pushed.**

---

## 1. Baseline vs. final

Exact command (identical for both runs):

```
.venv\Scripts\python.exe -m pytest -q
```

Python 3.15.0 · SQLite 3.53.4 · pytest config `pythonpath = .`, `testpaths = tests`

| Metric | Baseline (`5ffc314`) | Final (working tree) |
|---|---|---|
| Collected | 343 | 447 |
| Passed | 234 | **447** |
| Failed | 7 | **0** |
| Errors | 102 | **0** |
| Skipped | 0 | 0 |
| Duration | 35.24s | 45.09s |

Baseline detail: `PHASE_16_5_2_BASELINE_REPORT.md`.

> The suite was additionally run with `data/pricewise.db` **moved out of the tree**
> (clean-checkout simulation): **447 passed**, 53.84s. The database file was
> restored afterwards and verified intact (6 products / 5 stores / 9 offers,
> `PRAGMA integrity_check = ok` — unchanged from before the work).

---

## 2. Root cause → fix (the 5 defect classes)

### 2.1 Matching regression (2 failures) — real product bug

`evaluate_product_match()` appended `"Unit price unavailable for comparison"` to
`quality_issues` whenever `reference_price` / `offer_price` were omitted. That
downgraded otherwise exact identity matches to `POSSIBLE_MATCH`.

**Fix (`src/services/product_matching_service.py`):** unit price is an analytics
output, not identity evidence, so its absence no longer contributes a quality
issue. Unit prices are still computed and returned. Identity rules were
**strengthened**, not weakened:

- `concentration_match` added as a first-class identity attribute (e.g. 10% vs 5%
  niacinamide is `INCOMPATIBLE_MISMATCH`).
- Formulation comparison generalized via `normalise_formulation()` — previously
  only the waterproof/washable pair was checked; now any differing canonical
  formulation (`gel` vs `cream`, `serum` vs `lotion`, `waterproof` vs `washable`,
  …) is a mismatch.
- `parse_formulation()` extended with `mask` / `solution`.
- `admin_correct_match()` propagates the new field.

### 2.2 SQLite migration failure (1 failure) — real product bug

`ALTER TABLE products ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP`
raises `OperationalError: Cannot add a column with non-constant default`.

**Fix (`src/database/connection.py`):**

- Add `updated_at` **without** a default, then `UPDATE ... SET updated_at =
  CURRENT_TIMESTAMP WHERE updated_at IS NULL` — existing timestamps untouched.
- Install idempotent `CREATE TRIGGER IF NOT EXISTS` insert/update triggers so
  future rows keep correct timestamps.
- Guard every `products` operation on the table existing (`migrate_db()` can run
  on an empty DB before `init_db()`).
- Data, foreign keys, and indexes preserved — the migration test asserts row
  counts, FK integrity, and index survival across two consecutive runs.

### 2.3 Closed-database errors (102 errors) — real product bug

The Phase 16.2 Open Beauty Facts seed block was **dedented outside** its
`with get_connection(...)` body, so it reused `cursor` after the context manager
closed the connection.

**Fix (`src/database/seed.py`):** block re-indented into the `with` body. While
fixing it, two latent repeat-seed bugs were removed:

- hard-coded `store_id = 6` → the Nykaa demo store is resolved by name prefix
  (forced reseeds recreate stores with new AUTOINCREMENT ids);
- forced reseed now clears `obf_product_verification` and
  `retail_price_observation` before `products`/`stores`, in FK-safe order.

### 2.4 Environmental failures (4) — test defects, not product defects

`test_database_counts`, `test_backup_file_exists`, `test_get_product_by_slug_or_id`,
`test_list_products_filtering` depended on a developer-local `data/pricewise.db`
and on hard-coded id `76`.

**Fix:**

- New `tests/conftest.py` points `PRICEWISE_DB_PATH` at a session-seeded isolated
  temp DB **before `src.config` is imported**, so the suite is identical on a
  clean checkout.
- `test_get_product_by_slug_or_id` resolves the sunscreen id from the seeded DB
  (a fresh seed yields id 12, never 76).
- `test_database_counts` derives expected counts from the seed constants.
- `test_backup_file_exists` → `test_database_backup_is_valid`: creates a real
  SQLite backup via the backup API and verifies `integrity_check = ok`
  (stronger, and repo-independent).
- `test_phase6_live_price_engine.py` and `test_phase16_2_obf_verification.py`
  made self-contained (no reliance on id 76, on leftover audit rows, or on a
  duplicate `Nykaa` store).

### 2.5 Phase 16.3–16.5 defects found while adding tests — real product bugs

| # | Area | Defect | Fix |
|---|---|---|---|
| a | `data/schema.sql`, `connection.py` | `verification_status` CHECK omitted `provider_observed`, so the live PI pipeline failed on a **fresh** checkout once `schema.sql` had created the table. | CHECK extended in `schema.sql`; migration detects the stale constraint from `sqlite_master` and rebuilds. |
| b | `base_mcp_adapter.py` | SSE (`text/event-stream`) responses surfaced raw JSON-RPC envelopes as if they were products. | Envelopes are unwrapped through the same `_extract_from_json` path; legacy raw-event behaviour preserved. |
| c | `price_intelligence.py` | `list_cheapest_per_catalog()` returned only one product (bad indentation) and never selected `specs_json`, so unit prices were always missing. | Loop corrected; `specs_json` selected; unit prices computed per product. |
| d | `price_intelligence.py` | Provider-observed block was nested inside the quantity-calculation branch → live offers usually classified as `demo`. | Block lifted to offer level; `is_demo` forced `False` when a live provider observation backs the offer. |
| e | `price_intelligence.py` | Retailer↔store join only matched exact names/domains (`Nykaa` never matched `Nykaa (Demo)`). | Prefix/`LIKE` matching on name and domain. |
| f | `collect_pi_observations.py` | Superseding ignored retailer → collecting Tira superseded the Nykaa observation. | Supersede only the same product **and** same retailer; new row inserted as `live`; history retained. |
| g | `collect_pi_observations.py`, `api/main.py` | Non-positive prices were accepted; `productPageUrl` was not read; missing URL wiped an existing offer URL. | Explicit rejection of price ≤ 0; `productPageUrl`/`productUrl`/`product_page_url` supported; offer URL uses `COALESCE(NULLIF(...))`. |
| h | `collect_pi_observations.py` | PI leniency overrode hard conflicts, turning brand/shade/size mismatches into comparable matches. | Leniency now applies **only** when the evaluation is not `INCOMPATIBLE_MISMATCH`. |
| i | `frontend/OfferCard.tsx`, `DealSection.tsx`, `LiveRetailerPriceComparison.tsx` | Demo offers displayed “Provider Observed”; `provider_observed` had no badge. | “Provider Observed” limited to genuine feed sources; `provider_observed` renders **“Live Price”**; demo renders “Demo Data”. No auto-`LIVE_VERIFIED`. |

### 2.6 Preservation invariants

- No `LIVE_VERIFIED` auto-promotion — the string is not introduced anywhere in the diff.
- No schema/table drops, no DB reset, no data deletion. The only destructive path is
  the **already-existing, explicitly forced** reseed, made FK-safe.
- No MySQL/Neon/production access. No network calls in tests (all MCP is mocked).
- No merge, no rebase, no force-push, no push.

---

## 3. Regression tests added — 104 tests

| File | Tests | Focus |
|---|---|---|
| `tests/test_phase16_5_2_matching_regressions.py` | 11 | Unit price never blocks identity; concentration/shade/size/formulation/brand conflicts still rejected; exact match still `verified_match`. |
| `tests/test_phase16_5_2_migration.py` | 8 | Idempotency, data/FK/index preservation, timestamp backfill, empty-DB safety, `provider_observed` CHECK. |
| `tests/test_phase16_5_2_db_lifecycle.py` | 7 | Repeated seed, forced reseed, closed-connection regressions, connection reuse. |
| `tests/test_phase16_5_2_priceinindia_adapter.py` | 18 | MCP request shape (JSON-RPC + streamable Accept header), JSON & SSE parsing, empty/timeout/429/malformed honesty, INR & Unicode, catalog import provenance, invalid-price rejection. |
| `tests/test_phase16_5_2_price_observations.py` | 18 | Observation creation, per-retailer superseding, history retention, one-live-row invariant, invalid prices, URL preservation, match rejections. |
| `tests/test_phase16_5_2_price_intelligence.py` | 20 | Provider-observed classification, retailer/domain joins, demo fallback, superseded vs live selection, unit price/discount, catalog list, expiry. |
| `tests/test_phase16_5_2_api.py` | 22 | Offers/cheapest/catalog endpoints, history, health stats, connector health/search/find (mocked), admin collection pipeline, auth, error paths. |

Net count: baseline 343 → 447 (**+104**). One environmental test was replaced
1:1 (`test_backup_file_exists` → `test_database_backup_is_valid`); no test was
deleted, skipped, or marked xfail.

---

## 4. Verification evidence

### Backend — full suite

```
447 passed, 1 warning in 45.09s
```

The single warning is a pre-existing Starlette `TestClient` cookie deprecation.

### Backend — clean checkout (no `data/pricewise.db`)

```
447 passed, 1 warning in 53.84s
```

### Backend — the 7 exact baseline failures, run by node id

```
7 passed in 4.20s
```

### Frontend

```
npm run build  → tsc -b && vite build … ✓ built in 4.47s
npm run lint   → 0 errors, 12 warnings (all pre-existing; none on changed lines)
```

Notes: the build emits the pre-existing >500 kB chunk warning and an
`INEFFECTIVE_DYNAMIC_IMPORT` note for `v2-client.ts` — both present before this
work.

### Data safety

`data/pricewise.db` still holds 6 products / 5 stores / 9 offers, integrity `ok`.
Test runs never touch it (isolated temp DB per session, pristine copy per test).
The working tree contains no `*.db`, `*.db.backup*`, `.env`, or credential file.

### Secret scan

Scanned every changed/new file for `api_key|secret|access_token|private_key|password =|BEGIN (RSA|OPENSSH|PRIVATE)|bearer <token>|sk-…|ghp_…`.

```
no secret-like patterns found
```

---

## 5. Change inventory (uncommitted)

```
 data/schema.sql                                     |   2 +-
 frontend/src/components/DealSection.tsx             |  11 ++
 frontend/src/components/LiveRetailerPriceComparison.tsx |  2 +-
 frontend/src/components/OfferCard.tsx               |   7 +-
 src/adapters/mcp_adapters/base_mcp_adapter.py       |  50 +++++-
 src/adapters/mcp_adapters/priceinindia_adapter.py   |   7 +-
 src/api/main.py                                     |  43 ++++--
 src/database/connection.py                          |  60 +++++++-
 src/database/seed.py                                |  94 +++++++-----
 src/scripts/collect_pi_observations.py              |  38 +++--
 src/services/price_intelligence.py                  | 168 +++++++++++----------
 src/services/product_matching_service.py            | 101 +++++++++++--
 tests/test_phase16_2_obf_verification.py            |  13 +-
 tests/test_phase6_live_price_engine.py              |  51 +++++--
 tests/test_phase6a_foundation.py                    |  79 ++++++++--
 15 files changed, 527 insertions(+), 199 deletions(-)
```

Plus new files: `PHASE_16_5_2_BASELINE_REPORT.md`, `PHASE_16_5_2_STABILIZATION_REPORT.md`,
`tests/conftest.py`, and the 7 `tests/test_phase16_5_2_*.py` suites.

---

## 6. Known limitations (deliberately not changed)

- `parse_concentration()` compares the *set* of stated percentages. A different
  active at the same percentage is not distinguished (e.g. 10% vitamin C vs 10%
  niacinamide). This cannot introduce a false *downgrade* — it only avoids
  upgrading a genuinely ambiguous pair.
- Superseding is scoped to product + retailer, per the Phase 16.5 brief. Variant-
  level superseding is out of scope for this stabilization.
- The demo catalog remains demo data and is still badged as such. No demo row is
  promoted to “live” or “verified”.

---

## 7. Approval checkpoint

Work is **staged for review only**. Nothing has been committed or pushed.

To commit (after approval) the intended message is:

```
fix(phase16.5.2): stabilize live price activation

- matching: unit price no longer blocks identity; add concentration checks
- sqlite: idempotent updated_at migration with backfill + triggers
- seed: fix closed-connection OBF block, hard-coded store id, FK-safe reseed
- tests: isolated seeded DB fixture; suite green on a clean checkout
- phase16.3-16.5: SSE unwrapping, provider_observed CHECK, catalog/offer
  classification, observation superseding, PI leniency guard, provenance badges
- add 104 regression tests across matching, migration, lifecycle, adapter,
  observations, price intelligence and API
```
