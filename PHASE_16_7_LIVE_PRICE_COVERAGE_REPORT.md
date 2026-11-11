# Phase 16.7 — Live Price Coverage Expansion, Chrome MCP Browser Investigation & Verification

**Date:** 2026-11-11
**Branch:** `feature/phase-16-live-price-activation`
**Base commit:** `f8607f7b11d647874d5cfe2933af5e6834e52e74` (Phase 16.6, verified before work started)
**Working tree at end of phase:** changes left **uncommitted** (per phase rules — no commit, push, merge, PR, or deploy was performed)

---

## Evidence classification legend

| Label | Meaning |
|---|---|
| VERIFIED LOCALLY | Confirmed by running the project's own checks/tests/builds on this machine |
| BROWSER OBSERVED | Seen in a real Chrome DOM via Chrome MCP; not a DB record, not LIVE_VERIFIED |
| PROVIDER OBSERVED | Came from the PriceInIndia MCP provider pipeline (none collected this phase) |
| MANUALLY VERIFIED | An admin explicitly verified (none performed this phase) |
| LIVE VERIFIED | A retailer price stored and verified in the PriceWise DB (none stored this phase) |
| NOT VERIFIED | Could not be established; recorded honestly |

---

## 1. Original baseline (VERIFIED LOCALLY)

Independently re-verified at phase start (not taken on trust):

- Branch `feature/phase-16-live-price-activation`, HEAD `f8607f7`, clean working tree, remotes: `myfork` (humaidmalik63-png), `origin` (Tamanna020, untouched).
- Backend suite: **590 passed** (67.5s) with `PRICEWISE_DEMO_USER_PASSWORD` unset.
- Frontend production build: passed; lint: **0 errors** (13 pre-existing warnings).
- Fresh-seeded DB integrity: ok — 37 products / 10 stores / 100 offers / 941 price_history / 0 observations; Phase 16.6 §19 migration columns present.
- Chrome MCP: 33 tools discovered; real navigation + accessibility snapshot against example.com confirmed the session works before any retailer was visited.

## 2. Files changed

Modified (9):
- `src/services/product_matching_service.py` — Stage 1 (see §8)
- `src/adapters/mcp_adapters/priceinindia_adapter.py` — Stage 2
- `src/scripts/collect_pi_observations.py` — Stage 2/3
- `src/services/match_review_service.py` — Stage 4
- `src/services/cheapest_offer_service.py` — Stage 5
- `src/scripts/coverage_audit.py` — Stage 6
- `src/api/main.py` — Stage 4 admin context endpoint
- `frontend/src/components/OfferCard.tsx` — Stage 7
- `tests/test_phase16_6_cheapest_offer.py` — one assertion updated to the Phase 16.7 Stage 5 quantity-guard rule (documented in-test)

Created (3):
- `PHASE_16_7_BROWSER_INVESTIGATION.md` — §5 artifact (full Chrome MCP investigation record)
- `PHASE_16_7_LIVE_PRICE_COVERAGE_REPORT.md` — this report
- `frontend/src/utils/trustLabels.ts` — Stage 7 honest trust-label mapping
- `tests/test_phase16_7.py` — Stage 8 tests (65 tests)

Totals: 9 files changed (+737/−13 by diffstat) + 4 new files. No existing test was deleted or skipped; no existing data was modified or deleted.

## 3. Database migrations

**None required.** No schema change was needed: the Phase 16.6 observation table already carries `retailer_domain`, `currency`, `provider_name`, `match_result` (JSON evidence) etc., and all Phase 16.7 additions are computed from existing columns. No migration was added to `connection.py`; migration idempotency is therefore unaffected.

## 4. Chrome MCP discovery and verification (VERIFIED LOCALLY)

- 33 Chrome DevTools MCP tools discovered via the tool catalog (`list_pages`, `navigate_page`, `take_snapshot`, `fill`, `wait_for`, `evaluate_script`, `list_network_requests`, …).
- Session verified with a real operation: navigation to `https://example.com` + accessibility snapshot, before touching any retailer.
- Harness limitations encountered and recorded: snapshot uids go stale after every navigation (retake required); no `setTimeout` in the automation runtime (waits via `wait_for`); searchbox Enter does not navigate on Purplle (direct URL required); Tira's `/search?q=` renders empty (real pattern `/products?q=` discovered from its own suggestion link); Amazon.in search snapshot is ~263 KB (targeted filtering used).
- Full record: `PHASE_16_7_BROWSER_INVESTIGATION.md` (BROWSER OBSERVED).

## 5. Retailer browser investigation (BROWSER OBSERVED — full table in the artifact)

| Retailer | Browser accessible | Search works | Price visible | Product identity verified | Automated access permitted | Result |
|---|---|---|---|---|---|---|
| Nykaa | Yes | Yes | Yes (listing + PDP) | Yes (PDP: title, sizes 50ml/80ml, SKU 8938307, canonical URL) | Partial — robots.txt: `Allow: /` but `Disallow: /search/`, `/catalog/` | Verified |
| Myntra | Yes | Yes | Yes (listing + PDP + `@ Rs. 8.9 per gm`) | Yes (PDP 50g, ID 21404558) | NOT VERIFIED — robots.txt fetch timed out ×2 | Verified |
| Purplle | Yes | Yes via `/search?q=` (searchbox Enter doesn't navigate) | Yes (listing) | Yes (listing title + canonical URL) | Partial — `Disallow: /search*` | Verified |
| Tira | Yes | Structurally yes (`/products?q=`) | Yes (other brands) | NOT for target product | Partial — `Disallow: /*?q*`; explicitly allows named AI crawlers | Negative finding |
| Amazon India | Yes | Yes (`/s?k=`), no CAPTCHA | Yes (listing + PDP) | Yes (`/dp/B0BQN2YWN5`, "In stock") | No — `/dp/` allowed for `*` but AI/automation crawlers blanket-disallowed | Verified |

- **Products tested:** Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ In-Vivo Tested 50 g (catalogue product).
- **Consistent price evidence:** ₹387 selling / ₹445 MRP observed identically on Nykaa (PDP), Myntra (PDP), Purplle (search listing — PDP not opened) and Amazon.in (PDP) on 2026-11-11. All BROWSER OBSERVED.
- **Honest negative findings:** Tira does not list Dot & Key sunscreen (2 query variants); Purplle evidence is listing-level only; Nykaa labels the SKU "50ml" while Myntra/Purplle/Amazon/catalogue say "50g"; Amazon sponsored results are interleaved with organics (a sponsored row showed ₹499 for a related product — never used as evidence); the catalogue demo price (₹465) differs from every real price (₹387), confirming demo ≠ live.
- **Nothing from the browser session was written to any database.** No CAPTCHA, login, bot-protection bypass, stealth technique or proxy was used at any point; none were encountered.

## 6. Products tested

One catalogue SKU end-to-end across all 5 retailers (above). A second product was not added: the phase's purpose was to validate the pipeline and permission landscape, and every additional retailer probe would have multiplied automated load without a matching capability decision from the user (see §17).

## 7. Provider findings (PriceInIndia MCP)

- Endpoint/protocol unchanged (`https://mcp.priceinindia.website/mcp`, Streamable HTTP; rate limit 15 req/min; timeout 10s; 2 retries) — configuration snapshot verified in the coverage audit output.
- **No live provider calls were made during Phase 16.7** (the investigation used Chrome MCP instead). Pipeline improvements were tested with mocked responses only (VERIFIED LOCALLY).
- Improvements shipped (VERIFIED LOCALLY via tests):
  - Query normalization (`normalize_search_query`) before any provider call.
  - Variant/size extraction from PI titles (`extract_size_from_title`, rightmost-quantity rule) with `size_from_title` provenance flag; structured provider size still preferred; missing size stays honestly None.
  - Error classification now also recognises "timed out" (was only "timeout").
  - Observation evidence now stores `provider_title`/`provider_brand` and the explainable `match_strength` overlay.
- Limitation (NOT VERIFIED): whether the provider's Terms permit storing/redistributing its data at production volume is a user/legal decision; the adapter stays rate-limit conservative.

## 8. Matching improvements (Stage 1) — VERIFIED LOCALLY

- **Canonical classifications unchanged:** `verified_match` / `possible_match` / `ambiguous_match` / `incompatible_mismatch` remain the only stored strings (no conflicting status introduced).
- **Explainable strength overlay added** (`MatchStrength`): `exact` (verified + barcode/GTIN + no tolerance flags), `strong` (verified otherwise), `possible`, `needs_manual_review`, `rejected` — derived deterministically in `__post_init__` with recorded `strength_reasons`. An arbitrary confidence threshold can never create an exact match; confidence alone never escalates strength (tested).
- **Brand-alias registry** (`BRAND_ALIAS_REGISTRY`): only evidence-cited aliases; ships with exactly one pair (`dotkey` ↔ `dotandkey` — Myntra "DOT & KEY" vs Purplle slug "dot-and-key", observed 2026-11-11). Alias-based matches are flagged and capped at `strong`.
- **g↔ml unit-label tolerance:** equal quantity with differing g/ml label is tolerated (same SKU) but flagged and capped at `strong` — driven by the observed Nykaa-50ml/Myntra-50g conflict. Unequal quantities across g/ml remain hard-rejected.
- `explain()` dict added for admin UI consumption.

## 9. Live observations collected

**None were stored** — by design. Browser observations are evidence in the artifact, not DB rows; provider collection was not run (no approval for automated collection had been obtained, and production Neon writes were prohibited). Coverage numbers are therefore unchanged; the capability and gating are what changed.

## 10–13. Matches accepted / pending / rejected / verified usable offers

- Exact matches accepted: **0** (no observation runs)
- Possible matches awaiting review: **0**
- Rejected matches: **0**
- Verified usable offers: **0**
These are the honest fresh-seed values (`PHASE_16_6_STAGE_1_COVERAGE_AUDIT.md`-style audit output re-run in this phase). The pipeline that produces and gates them is now stronger and fully tested (see §14).

## 14. Catalogue coverage before and after (NOT VERIFIED — no live collection run)

| Metric | Before (16.6 fresh seed) | After (16.7, fresh seed, no collection) |
|---|---|---|
| Beauty products | 26 | 26 |
| PROVIDER_OBSERVED | 0 | 0 |
| MATCH_REVIEW_REQUIRED | 0 | 0 |
| MANUAL_VERIFIED_ONLY | 0 | 0 |
| CATALOG_VERIFIED_ONLY | 5 | 5 |
| DEMO_ONLY | 21 | 21 |
| Products with verified usable live offers | 0 | 0 |

The after-state is identical because no provider run was executed. New aggregate metrics (`phase16_7_metrics`) now make exact/strong/possible/rejected counts, fresh/stale counts, verified-usable offers, match rates and an honest per-product `coverage_unavailable_reason` auditable for any future run.

## 15. Test results (VERIFIED LOCALLY)

- New Phase 16.7 suite (`tests/test_phase16_7.py`): **66 passed** — matching strength/aliases/tolerance, size extraction, price/currency validation, duplicate supersede, stale exclusion, provider error classification, MCP/SSE parsing (malformed inputs), match-review context + audit trail + admin authorization (anon 401/403), cheapest quantity-guard + comparison scope, coverage-metric accuracy, trust-label contract, browser-artifact contract.
- Full backend suite: see final status line below (run with `PRICEWISE_DEMO_USER_PASSWORD` unset).
- Frontend build (`tsc -b && vite build`): passed; lint: 0 errors.
- Secret scan over all changed/new files: **0 hits**.
- No test depends on a live Chrome session, a live retailer site, or the live provider — all provider/browser behaviour is mocked; the browser-artifact tests read the report file only.

*(Full-suite result: **655 passed, 0 failed** (60.8s) — 590 Phase 16.6 baseline + 65 new Phase 16.7 tests; one Phase 16.6 cheapest-offer test (`test_incompatible_units_not_compared`) was updated to the stricter Phase 16.7 Stage 5 ranking rule with an in-test rationale, because different quantities may no longer win an absolute-price race.)*

## 16. Known limitations

- Retailer pages change constantly; the 2026-11-11 observations are a snapshot, not a feed.
- Purplle price is listing-level (PDP not opened); Tira has no coverage for the tested SKU; Myntra robots.txt could not be fetched (permission status unknown).
- Amazon sponsored results require sponsored-detection before any automated parsing would be safe.
- Chrome MCP cannot run unattended headless schedules in this harness; it is an investigation/verification tool, not a collector.
- Coverage numbers did not move because no collection run was performed — moving them requires a permission decision (§17).

## 17. Retailer permission requirements (user decisions required)

1. **Myntra** — robots.txt unreachable; Terms unreviewed. Treat automated access as NOT PERMITTED until reviewed.
2. **Nykaa / Purplle** — robots.txt permits PDP paths for crawlers but disallows search endpoints; retailer Terms of Use must still be reviewed before any automated collection.
3. **Amazon.in** — assume no automated collection (blanket AI-crawler disallow + Conditions of Use); interactive observation only.
4. **Tira** — most permissive robots.txt posture (explicit AI-crawler allows) but didn't carry the tested product.
5. **PriceInIndia provider** — confirm permitted usage/volume and data redistribution rights before scaling collection.
6. Decide whether BROWSER OBSERVED prices (e.g. the ₹387/₹445 evidence) may be entered as observations (correctly typed as `PROVIDER_OBSERVED`/manual with source attribution, never `LIVE_VERIFIED`).

## 18. Remaining production-readiness gaps

- No scheduled/background collection (prohibited this phase); scheduler integration is untested in production mode.
- Live comparison engine still doesn't consume the browser-investigation insights (e.g. per-retailer sponsored-result filters for Amazon).
- Frontend has no test runner; trust-label behaviour is enforced by `tsc` build + lint and a file-contract test, not a DOM test.
- Multi-product browser verification (only one SKU tested).
- Provider Terms confirmation and a sanctioned collection run to convert capability into actual coverage.

---

## Final state

- Repository: `C:\Users\humai\Desktop\Cisco\price-comparison-website`
- Branch: `feature/phase-16-live-price-activation`
- HEAD: `f8607f7b11d647874d5cfe2933af5e6834e52e74` (unchanged — nothing committed)
- Working tree: 8 modified + 3 new files, all left uncommitted
- No push / merge / PR / deploy / production Neon write / background scheduler
- **STOP — awaiting user approval** for: commit/push, any permitted automated collection path, and whether the browser-observed price evidence may be entered into the database with correct provenance.
