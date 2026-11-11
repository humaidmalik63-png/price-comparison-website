# Phase 16.7B — PriceInIndia Safe Provider Investigation

**Status:** Investigation complete. **No live product search has been executed.**
Awaiting separate approval before the controlled 3-query live test (Stage 7).

**Date:** 2026-11-11
**Branch:** `feature/phase-16-live-price-activation` (HEAD `f8607f7b11d647874d5cfe2933af5e6834e52e74`)

**Evidence standard used throughout this report:** every claim below is labelled
as **[FACT]** (directly verified in this investigation), **[PROVIDER CLAIM]**
(stated by PriceInIndia's own docs; not independently guaranteed), or
**[ASSESSMENT]** (our reasoned conclusion from the above).

---

## 1. Repository safety status — [FACT]

- Repo path: `C:\Users\humai\Desktop\Cisco\price-comparison-website` — confirmed.
- Branch: `feature/phase-16-live-price-activation` — confirmed via `git rev-parse`.
- HEAD: `f8607f7b11d647874d5cfe2933af5e6834e52e74` — confirmed.
- Remotes: `myfork` → `humaidmalik63-png/price-comparison-website`, `origin` → `Tamanna020/price-comparison-website`.
- No database writes were performed at any point. The local SQLite DB was opened
  **read-only** (`sqlite3.connect("file:...?mode=ro", uri=True)`). No production
  Neon access, no collection scripts, no scheduler, no deploy, no commit, no push.

## 2. Existing working-tree changes preserved — [FACT]

All Phase 16.7 files remain uncommitted and untouched. Before this investigation:
9 modified + 4 new files. After this investigation: **9 modified + 5 new files**
(the only addition is this investigation's own new test file, created with the
user's pre-authorization for "new mocked tests in a new file"):

- Modified (unchanged content — verified via `git status` before and after):
  `frontend/src/components/OfferCard.tsx`,
  `src/adapters/mcp_adapters/priceinindia_adapter.py`,
  `src/api/main.py`, `src/scripts/collect_pi_observations.py`,
  `src/scripts/coverage_audit.py`, `src/services/cheapest_offer_service.py`,
  `src/services/match_review_service.py`,
  `src/services/product_matching_service.py`,
  `tests/test_phase16_6_cheapest_offer.py`.
- New (pre-existing): `PHASE_16_7_BROWSER_INVESTIGATION.md`,
  `PHASE_16_7_LIVE_PRICE_COVERAGE_REPORT.md`,
  `frontend/src/utils/trustLabels.ts`, `tests/test_phase16_7.py`.
- New (this investigation): `tests/test_phase16_7b_pi_investigation.py`,
  `PHASE_16_7_PRICEININDIA_PROVIDER_INVESTIGATION.md` (this file).
- **No existing file was modified, reset, stashed, committed or pushed.**

## 3. Official provider documentation reviewed — [FACT]

Fetched and reviewed on 2026-11-11:

| Document | URL | Key content |
|---|---|---|
| MCP docs | `https://www.priceinindia.website/mcp` | Endpoint, transport, tools, no-auth claim |
| Terms of Service | `/terms` (updated Oct 4 2026) | Affiliate model, accuracy disclaimer, scraping prohibition |
| Privacy Policy | `/privacy` (updated Oct 4 2026) | IP/tool-name logging, query cache ≤10 min |
| Affiliate Disclosure | `/affiliate-disclosure` | Affiliate redirect links, no paid rankings |
| AI-assistant manifest | `/llms.txt` | Data source description, INR, hourly refresh |
| Server descriptor | `https://mcp.priceinindia.website/.well-known/mcp.json` | Endpoint + transport confirmation |
| Contact | `/contact` | Web form only (no direct email/API contact) |

## 4. Provider permission and data-reuse findings — [FACT] + [ASSESSMENT]

**Explicitly documented:**

- Access to the MCP server is free, anonymous, no API key/account — **[PROVIDER CLAIM]**.
- All five tools are read-only (`readOnlyHint: true` verified in `tools/list`) — **[FACT]**.
- Terms prohibit "scrap[ing] or automat[ing] access in a way that overloads the
  service" — **[PROVIDER CLAIM]** (explicit restriction).
- Rate limiting: per-IP fair use; the server returns HTTP 429 with `Retry-After`
  when the limit is hit — **[PROVIDER CLAIM]** (no numeric published limit).
- Search queries are cached ≤10 min; request logs (IP + tool name) kept for
  abuse prevention — **[PROVIDER CLAIM]**.
- Prices may be inaccurate/incomplete/out-of-date; the checkout price at the
  retailer is authoritative — **[PROVIDER CLAIM]**.
- Buy links are affiliate redirects; PriceInIndia may earn commission —
  **[PROVIDER CLAIM]**. `productUrl` (affiliate) vs `productPageUrl` (citation)
  distinction documented.
- Content/IP policy: site content owned by PriceInIndia; retailer names, logos
  and images belong to the retailers — **[PROVIDER CLAIM]**.

**NOT documented (gaps — absence of a restriction is NOT permission):**

1. Whether returned data may be **stored/retained** beyond an ephemeral cache.
2. Whether observations may be **displayed in a third-party application**
   (PriceWise AI is exactly this use case).
3. Whether **commercial redistribution** is permitted.
4. Whether **attribution** is required when displaying provider-derived prices.
5. Whether **academic / non-commercial project** use is permitted.
6. Whether repeated **automated scheduled searches** (our collector pattern,
   paced at 4.5 s) are within fair use.

**[ASSESSMENT]:** Terms and privacy imply a consumer-facing free service with
abuse-based rather than usage-based limits. Nothing grants data-reuse rights;
nothing forbids our specific three-query test. Items 1–6 must be clarified with
the provider (contact form at `/contact`) before any integration beyond a
one-off diagnostic test. A single diagnostic call set is defensible as ordinary
interactive use; ongoing scheduled collection is **not** yet defensible.

## 5. MCP handshake result — [FACT]

Two POSTs were made to `https://mcp.priceinindia.website/mcp` (initialize +
tools/list). **No search, compare, browse or render tool was called.**

- `initialize` → HTTP 200, `Content-Type: application/json` (plain JSON, not SSE).
- Server info: `{name: "priceinindia", title: "PriceInIndia", version: "0.1.0",
  websiteUrl: "https://www.priceinindia.website"}`.
- Negotiated protocol version: `2025-06-18`.
- Capabilities: `tools` and `resources`, both with `listChanged: true`.
- Server `instructions` field confirms: read-only, anonymous, and recommends
  search_products → compare_prices → render_product_results.
- No session id required — stateless server, as documented.
- No `Retry-After` header encountered.
- Raw probe output preserved at
  `C:\Users\humai\AppData\Local\Temp\opencode\pi_handshake_condensed_result.txt`
  (total network cost of the handshake: 2 requests).

## 6. Discovered tool names and schemas — [FACT]

Five tools, **all** `annotations.readOnlyHint: true`, `destructiveHint: false`,
all with an `outputSchema` (structured content), none supporting task execution
(`execution.taskSupport: "forbidden"`):

| Tool | Required params | Optional params |
|---|---|---|
| `search_products` | `query` (string, 2–200) | `brand`, `store`, `category` (≤100), `min_price`/`max_price` (≥0), `sort` (relevance/price_asc/price_desc/newest), `page` (1–20), `per_page` (1–20, default 10) |
| `compare_prices` | `query` | `brand` |
| `browse_categories` | — | — |
| `list_category_products` | `slug` | `page`, `sort` |
| `render_product_results` | `products` | `title` |

This matches the published documentation exactly. The provider's published
result field set (from docs + outputSchema): `id` (opaque), `title`, `brand`,
`price`/`mrp` (INR), `discountPercent`, `store`, `imageUrl`, `productUrl`
(affiliate redirect), `productPageUrl` (citation link), `outOfStock`,
`lastUpdated` (unix seconds), `currency` (const `"INR"`).

## 7. Existing adapter compatibility assessment — [ASSESSMENT] (no code changed)

`src/adapters/mcp_adapters/priceinindia_adapter.py` + `base_mcp_adapter.py`
were fully inspected against the live schemas.

**Compatible (verified):**
- Endpoint, Streamable HTTP transport, JSON-RPC envelope — match.
- `_parse_response` handles both plain JSON (server's actual behaviour) and SSE.
- `_extract_from_json` prioritises `structuredContent` — matches the server's
  outputSchema-based responses.
- `search_products` argument surface covers the documented input schema.
- Adapter uses `productPageUrl` (citation link) for provenance — correct choice;
  it never treats the affiliate `productUrl` as the citation.
- Rate-limit posture: adapter self-paces 15 req/min (4.5 s), inside the
  provider's per-IP fair-use posture.

**Gaps recorded (NOT fixed in this investigation):**

| # | Gap | Impact |
|---|---|---|
| 1 | Adapter sends `tools/call` without a prior `initialize` handshake | Works because the server is stateless, but is not a fully conforming MCP client; would break on a session-based server |
| 2 | `outOfStock` and `lastUpdated` fields are not consumed by `normalize_pi_item` | Out-of-stock or stale results are not rejected/flagged (verified by test; see §11) |
| 3 | HTTP 429 / `Retry-After` is not honoured — retried as a generic HTTP error with 0.5 s / 1 s backoff | Could aggravate the provider's fair-use enforcement in a long run |
| 4 | `list_category_products` / `render_product_results` not implemented | Not needed for backend price collection; acceptable |

**Phase 16.7C update (2026-11-12):** gap 2 is now **partially closed** —
`lastUpdated` is mapped into the observation freshness system (see §15).
`outOfStock` remains unconsumed. Gaps 1, 3 and 4 remain open.

The provider's own `compare_prices` warning — results are "cheapest per store
for the query, not necessarily the identical SKU" — independently validates the
Phase 16.7 design decision to gate on `search_products` results with strict
match-strength classification instead of trusting `compare_prices`.

## 8. Three proposed product queries — [FACT] (catalogue) + [ASSESSMENT] (query design)

**Important deviation from the original plan:** the catalogue contains only
**6 active products** and **no Dot & Key record**. The Dot & Key Watermelon
sunscreen exists only inside test fixtures and code comments — it is not a real
catalogue row. Per the rule "do not invent product records", the sunscreen slot
is proposed to be filled by the actual catalogue sunscreen instead:

| Slot | Catalogue record (id / sku / status) | Planned query | `brand` param |
|---|---|---|---|
| Sunscreen | **2 / `OBF-SUN-PREP-30` / `catalog_verified`** — "Pharmacis Sunscreen SPF 50+ Gel Cream", 30 ml | `Pharmacis Sunscreen SPF 50+ Gel Cream 30 ml` | `Pharmacis` |
| Skincare | **3 / `OBF-SER-MIN-30` / `catalog_verified`** — "Minimalist 10% Niacinamide Serum", 30 ml | `Minimalist 10% Niacinamide Serum 30 ml` | `Minimalist` |
| Makeup | **4 / `OBF-LIP-KAY-35` / `catalog_verified`** — "Kay Beauty Matte Lipstick - Reconstruct", 3.5 g, shade Reconstruct | `Kay Beauty Matte Lipstick - Reconstruct 3.5 g` | `Kay Beauty` |

- All queries were generated with the production `build_search_query` and
  normalised with `normalize_search_query` (tests in §11 assert determinism and
  the 2–200-char schema limit).
- Every call will use **`per_page=5`, `page=1`** explicitly (the adapter's
  default is `per_page=20`; it will be overridden).
- No pagination, no broad category search, no repeated query variations.

*Alternative makeup candidate if the user prefers:* id 5, "Maybelline Fit Me
Matte Liquid Foundation - 128 Warm Nude" (shade 128 Warm Nude) — likely to
return more retailer listings than the niche Kay Beauty shade, but harder to
validate shade-exactly. Replacing a candidate requires re-approval of the plan.

## 9. Expected request count — [FACT] (plan)

- **3 `search_products` calls total** — one per approved product, `per_page=5`, `page=1`.
- **0** `compare_prices`, **0** `browse_categories`, **0** `list_category_products`,
  **0** `render_product_results` (never executed per plan).
- **0** retries on failure: a failed/timed-out call is recorded and not retried.
- Handshake already spent 2 requests (initialize + tools/list) during Stage 4.
- Adapter-side pacing (4.5 s between calls) will be respected.

## 10. Observation-validation rules — [FACT] (existing implementation)

Each returned item is passed through `normalize_pi_item` and then
`evaluate_product_match` against the catalogue record. The rules below are the
**existing Phase 16.7 implementation** (not new code):

**Field checks (per result):**
- `title`, `brand` — required; missing title → `missing_title` rejection; missing
  retailer → `missing_retailer` rejection.
- `store` → retailer; domain-like values (`nykaa.com`) preserved as
  `retailer_domain`; plain names stored with NULL domain (never guessed).
- `productPageUrl` preferred over affiliate `productUrl` for citation; missing
  URL → `missing_product_url` flag (flagged, never silently confirmed).
- `price`/`mrp` — parsed from numbers or formatted text ("₹1,299", "Rs.
  1,299.50"); unparseable → `invalid_price` rejection (never guessed); price >
  MRP → `price_above_mrp` flag.
- `currency` — only `INR` (and aliases) eligible; missing → `currency_missing`;
  non-INR → `unsupported_currency` (never converted).
- Variant/size — provider `size` field preferred, else extracted from title
  ("50 g" → `50g`, rightmost token wins for pack configs); missing size stays
  `None` (never invented) and lowers confidence.
- Availability (`outOfStock`) and freshness (`lastUpdated`) — **currently not
  consumed** (see §12).
- Search timestamp recorded as `created_at`; provider item `id` preserved as
  evidence reference.

**Match-strength classification (deterministic overlay, Phase 16.7):**

| Classification | Strength | Meaning |
|---|---|---|
| `verified_match` + barcode/GTIN evidence, no flags | `EXACT` | same SKU proven |
| `verified_match` (no barcode) | `STRONG` | high-confidence same product |
| `possible_match` | `POSSIBLE` | plausible, human review advised |
| `ambiguous_match` | `NEEDS_MANUAL_REVIEW` | cannot decide automatically |
| `incompatible_mismatch` | `REJECTED` | identity conflict (brand/size/shade/formulation/concentration) |

**Hard rules baked into the pipeline:**
- A provider result is never automatically an EXACT match (barcode/GTIN is the
  only route to EXACT; none of our 3 products have barcodes in specs → ceiling
  is STRONG even on perfect text match).
- A result without a reliable product URL or retailer attribution cannot count
  as a verified retailer offer.
- Search-result prices are stored as `provider_observed` — never described or
  displayed as confirmed checkout prices.
- Different size, shade, formulation, concentration or pack count ⇒
  `incompatible_mismatch` ⇒ REJECTED (never unit-price-compared).
- For provider results with brand match but weaker text similarity, the PI
  path relaxes to `POSSIBLE_MATCH` with `requires_human_review=True` and
  confidence capped at 0.75 — honest about uncertainty.

## 11. Mocked test results — [FACT]

New file `tests/test_phase16_7b_pi_investigation.py` — **13 tests, all passing**,
no live connection, no database:

| Plan Stage 8 case | Covered by | Result |
|---|---|---|
| Successful Streamable HTTP response | existing `test_phase16_5_2_priceinindia_adapter.py` | pass (pre-existing) |
| JSON-RPC response parsing | existing adapter tests | pass (pre-existing) |
| SSE response parsing | existing adapter tests + `test_phase16_7.TestMcpSseParsing` | pass (pre-existing) |
| Empty product results | existing `test_empty_results_are_reported_without_fabricating_prices` | pass (pre-existing) |
| Multiple product results | existing adapter tests | pass (pre-existing) |
| Missing price | existing `test_phase16_7.TestStage3Validation` | pass (pre-existing) |
| Missing retailer | **new** `test_missing_retailer_rejected` | pass |
| Missing product URL | existing `test_phase16_6_discovery` + **new** `test_missing_product_url_flagged_not_rejected` | pass |
| Invalid currency | existing `test_unsupported_currency_rejected_not_converted` | pass (pre-existing) |
| Malformed JSON | existing `test_malformed_response_does_not_raise` | pass (pre-existing) |
| Provider timeout | existing `test_timeout_is_reported_as_failure` | pass (pre-existing) |
| HTTP error responses | existing `test_http_rate_limit_is_reported` + stage3 classifier | pass (pre-existing) |
| Duplicate results | **new** `test_identical_items_share_dedupe_key`, `test_different_retailer_or_price_changes_dedupe_key` (+ existing DB supersede test) | pass |
| Wrong product size | **new** `test_wrong_size_is_not_compared` → INCOMPATIBLE/REJECTED | pass |
| Wrong brand | **new** `test_wrong_brand_rejected` → INCOMPATIBLE/REJECTED | pass |
| Incorrect variant (shade) | **new** `test_incorrect_shade_is_not_compared` (recognised shade → REJECTED) + `test_unrecognised_shade_stays_possible_but_flagged` | pass |
| Stale provider information | **new** `test_out_of_stock_and_last_updated_are_not_currently_used` — documents the CURRENT gap honestly | pass |
| Citation-link preference | **new** `test_citation_url_preferred_over_affiliate_redirect` | pass |
| Planned-query determinism (Stage 5) | **new** `TestPlannedQueriesFromCatalogue` (3 tests) | pass |

Full backend suite after adding the file: **668 passed, 0 failed** (655
pre-existing + 13 new), 57.96 s. No existing test was modified.

## 12. Known provider limitations — [PROVIDER CLAIM] + [FACT]

1. Prices exclude delivery, coupons and bank offers — **[PROVIDER CLAIM]**.
2. Prices refreshed hourly, can be inaccurate/out-of-date — **[PROVIDER CLAIM]**.
3. No published numeric rate limit — only per-IP fair use with 429 + `Retry-After`
   — **[PROVIDER CLAIM]**.
4. `productUrl` is an affiliate redirect — must never be used as citation —
   **[PROVIDER CLAIM]**, adapter already prefers `productPageUrl` — **[FACT]**.
5. `outOfStock` / `lastUpdated` not consumed by our normaliser — stale or
   out-of-stock listings are not automatically rejected today — **[FACT]**
   (verified by test; fix requires code change + separate approval).
   *Phase 16.7C update:* `lastUpdated` **is now consumed** (mapped into the
   freshness system, §15); `outOfStock` remains unconsumed.6. `compare_prices` is query-level "cheapest per store", not SKU-identical —
   **[PROVIDER CLAIM]** — hence our search_products + match-strength design.
7. No documented data-storage/reuse/redistribution/attribution terms — the
   single largest integration risk — **[FACT]** (absence documented in §4).

## 13. Outstanding permission questions (for the provider via /contact form)

1. May observations returned by `search_products` be **stored persistently** in
   a third-party database and re-served to end users?
2. May PriceWise AI **display** provider-derived prices and retailer names in
   its app, and what **attribution wording** (if any) is required?
3. Is **commercial** use of the data permitted (PriceWise is currently a
   student/academic project; if it monetises later, does that change)?
4. Is **scheduled automated collection** (e.g. 3 products/day, paced ≥4.5 s)
   within the per-IP fair-use policy?
5. What is the **attribution requirement for retailer names/logos/images**
   (owned by retailers per the Terms)?

## 14. Recommendation on whether a controlled live test is safe

**[ASSESSMENT]: YES — the 3-query diagnostic test is safe to run; broader
integration is NOT yet justified.**

- **Safe:** the test is 3 read-only, anonymously accessible, paced calls with
  pinned `per_page=5, page=1` — ordinary interactive use of a public, free,
  read-only MCP endpoint; well inside any fair-use reading of the Terms. It
  writes nothing anywhere (results will be sanitized into a local report only).
- **Justified:** it converts the largest unknowns (actual result field
  population, retailer-name formats, URL shapes, size-in-title conventions)
  from assumptions into evidence — the exact data needed to answer §13 and to
  judge §4 items 1–6.
- **Not yet safe:** recurring scheduled collection, bulk discovery runs, or any
  database persistence of provider data — blocked pending provider answers to
  §13.

**Conditions on the live test if approved:** exactly the 3 queries in §8; no
pagination; no `compare_prices`; no retry on failure; no database writes; raw
payloads sanitized before any storage; results presented as a local test report
and classified per §10; search-result prices explicitly labelled
"provider-observed, not confirmed checkout prices".

---

### Decision requested

1. Approve the 3 planned queries (§8) — noting the Dot & Key → Pharmacis
   substitution — and the 3-request budget (§9) for the Stage 7 live test; or
2. Substitute a different makeup candidate (§8 alternative) and re-approve; or
3. Skip the live test and stop at this investigation report.

---

## 15. Phase 16.7C follow-up — evidence and data quality improvements (2026-11-12)

**[FACT]** Following the Stage 7 live test findings (see
`PHASE_16_7B_PRICEININDIA_LIVE_TEST_REPORT.md`), the following improvements were
implemented against the existing pipeline. No live searches were run; no
database writes occurred during the work (tests use temporary databases only).

### 15.1 Provider `lastUpdated` mapped into the freshness system
- `freshness_service.parse_epoch_seconds()` parses unix seconds (or
  milliseconds, auto-detected by magnitude); garbage, non-finite, negative and
  implausible-future values yield `None` — never guessed.
- `freshness_service.provider_freshness()` maps the provider timestamp into the
  same fresh / aging / stale / unknown buckets used for application
  observations, alongside (never instead of) the observation's own timestamp.
- `normalize_pi_item` now exposes `last_updated_epoch`; `store_observation`
  records `provider_last_updated_iso`, `provider_age_hours` and
  `provider_freshness` in the match-result evidence JSON.

### 15.2 Price precision preserved; safe INR display policy
- Storage keeps full provider precision (e.g. `569.049988` stays exact).
- New `src/services/price_formatting.py`: `round_inr_display()` (display rounds
  to ≤2 decimals/paise) and `format_inr()` (₹ symbol, Indian digit grouping
  e.g. `₹1,29,99,999`, `None` for absent/non-finite — never a made-up number).
- `provider_price_raw` (the unmodified provider value) is recorded in evidence.
- Frontend mirror `frontend/src/utils/inrPrice.ts` (`formatINR`) is now used by
  `OfferCard` for base price, total cost, original price and coupon discount.

### 15.3 Provider URLs distinguished from retailer URLs
- `normalize_pi_item` and `store_observation` now classify every citation URL:
  `url_kind` ∈ `retailer` | `provider_page` | `provider_affiliate_redirect`,
  with separate `provider_page_url`, `affiliate_redirect_url` and
  `retailer_product_url` fields, plus `url_is_provider_page` /
  `url_is_affiliate_redirect` flags and evidence-notes markers.

### 15.4 Retailer URLs never invented
- `retailer_product_url` is `None` unless the provider supplies an explicit
  retailer URL field — never derived from a PriceInIndia page or affiliate
  redirect.
- The offers-table sync writes `offer_url` only from a genuine retailer URL;
  when none exists, an existing offer's URL is preserved (UPDATE) or left empty
  (INSERT) — a provider page is never presented as a retailer link.
- `cheapest_offer_service` eligibility adds an honest exclusion reason
  `url_is_provider_page` ("Only a provider page/redirect URL is available —
  not a retailer product URL") for evidence rows recorded with
  `url_kind` = `provider_page` / `provider_affiliate_redirect`; legacy rows
  without `url_kind` keep their previous behaviour (backward compatible).

### 15.5 Retailer attribution separate from provider identity
- Observations continue to record `retailer` (+ `retailer_domain`, only when
  the provider reports a domain-like store string — never guessed) distinctly
  from `provider_name` (`priceinindia`); the match-result evidence now also
  carries the distinct URL provenance so attribution cannot be conflated.

### 15.6 Missing size can never become EXACT/STRONG
- The PI match path (`match_pi_result_to_product`) keeps missing-size results
  at POSSIBLE_MATCH with `requires_human_review=True`.
- New belt-and-braces guard `enforce_missing_size_identity_guard()`:
  a VERIFIED evaluation whose offer side has no detectable size is downgraded
  to POSSIBLE_MATCH with human review (currently unreachable for PriceInIndia
  results, which carry no barcodes; guards future evidence paths).

### 15.7 Tests
- New `tests/test_phase16_7c_evidence_quality.py` — **27 tests, all passing**,
  covering every item above.
- Full backend suite: **695 passed, 0 failed**. No existing test was modified.

---

## 16. Phase 16.7E follow-up — final evidence and display hardening (2026-11-12)

**[FACT]** The Phase 16.7D audit (PASS WITH WARNINGS; 1 Medium + 4 Low
findings) identified five gaps. All five were resolved in 16.7E. No live
searches, no collection, and no production-database writes were performed.

### 16.1 UTM / click-id tracking parameters stripped (Medium finding resolved)
- New `src/services/url_policy.py`: `strip_tracking_params()` removes the
  `utm_*` parameter family plus known click ids (`gclid`, `fbclid`,
  `msclkid`, `mc_cid`, `mc_eid`) before any URL is stored or displayed.
  All other query parameters are preserved **byte-exactly** (the query is
  rebuilt from raw `&`-split segments — no re-encoding); when nothing is
  removed, the ORIGINAL string is returned; malformed URLs are returned
  unchanged and never reconstructed.
- Frontend mirror `frontend/src/utils/urlPolicy.ts`; `OfferCard` now renders
  `offer.purchaseUrl` through the same policy (`href` is the cleaned URL).
- Applied at every storage/display point: `normalize_pi_item`,
  `store_observation` (provider page / affiliate / retailer / observation
  URLs) and the admin collect endpoint in `src/api/main.py`.
- Provenance-preserving: `url_kind` classification operates on the CLEANED
  URLs, so a provider page stays a provider page and cleaning can never
  fabricate a retailer URL (the module can only remove parameters, never add
  or rewrite hosts/paths).

### 16.2 Future-timestamp handling hardened (Low finding resolved)
- `freshness_service.FUTURE_TOLERANCE_SECONDS = 300.0` (5-minute assumed
  clock skew). `parse_epoch_seconds()` now rejects anything further in the
  future than this (previously a 1-day guard accepted +24 h future stamps);
  rejected timestamps map to `UNKNOWN` — never silently "fresh".
- `provider_freshness()` clamps `provider_age_hours = max(0.0, age)`, so a
  within-tolerance future stamp behaves as "just observed" and the exposed
  provider age can never be negative.
- Provider freshness remains strictly separate from observation freshness;
  stored observation timestamps are never modified.

### 16.3 INR rounding parity (Low finding resolved)
- One explicit policy, implemented identically in Python and TypeScript:
  **round-half-up applied to the shortest decimal (repr) representation**.
  Backend `round_inr_display()` quantizes `Decimal(repr(number))` with
  `ROUND_HALF_UP`; frontend `roundINRDisplay()` performs the same arithmetic
  on the decimal digit string of `String(abs(value))` (exponent-form values
  expanded to plain digits first), sign re-applied after.
- Parity vectors verified identical across both layers via a temporary Node
  script (deleted after use): 0.125→0.13, 1.005→1.01, -42.505→-42.51,
  569.049988→569.05/"₹569.05", 999.995→"₹1,000", 12999999→"₹1,29,99,999",
  plus extreme magnitudes (1e21, 5e-7) and URL-cleaning vectors.
- `formatINR` matches the backend's display convention exactly: paise shown
  when non-zero ("₹1,299.50"), dropped for whole rupees ("₹569").
- Storage values and price calculations are untouched — rounding is
  display-only; `provider_price_raw` keeps full precision.

### 16.4 `url_is_provider_page` documented in ASSUMPTIONS (Low finding resolved)
- `cheapest_offer_service.ASSUMPTIONS` now records the exclusion and its
  rationale (a PriceInIndia page/redirect can never satisfy the
  retailer-URL requirement; retailer URLs are never invented; legacy rows
  keep previous behaviour). No eligibility behavior changed.

### 16.5 Inventory reconciliation (Low/finding resolved)
- Working tree after 16.7E: **10 modified tracked + 13 untracked new
  (4 reports, 3 utils, 2 services, 4 test files), 0 deleted, 0 renamed** at
  HEAD `f8607f7b`. The 16.7D audit's header count of "8 new files" was an
  undercount of its own table (which listed all 10 then-present untracked
  files); the exact per-file counts are authoritative.

### 16.6 Tests and verification
- New `tests/test_phase16_7e_display_hardening.py` — **50 tests, all
  passing**: tracking-param stripping (utm_*, click ids, case-insensitivity,
  encoded values, fragments), byte-exact preservation of legitimate params,
  malformed URLs unchanged, per-provenance kind preservation after cleaning,
  future-tolerance boundaries (exactly +300 s accepted at age 0; +301 s
  invalid/UNKNOWN; skew clamped to 0.0; observation timestamps untouched),
  and the full rounding-parity vector set.
- Full backend suite: **745 passed, 0 failed** (695 prior + 50 new).
- Frontend: production build ✓ (2.69 s), lint **0 errors**, 13 pre-existing
  warnings in files untouched by 16.7*.
