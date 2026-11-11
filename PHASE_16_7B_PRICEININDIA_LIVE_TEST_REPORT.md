# Phase 16.7B — PriceInIndia Controlled Live Test Report

**Status:** Executed under separate user approval (2026-11-11).
**Companion document:** `PHASE_16_7_PRICEININDIA_PROVIDER_INVESTIGATION.md` (Stages 1–6, 8, 9).

---

## 1. Execution summary — [FACT]

Exactly **3 `search_products` calls** were made to
`https://mcp.priceinindia.website/mcp` — one per approved catalogue product,
`per_page=5, page=1`, brand filter set, ~4.5 s pacing between calls, adapter
instantiated with `max_retries=0` (no automatic retry per plan rules).
**No** `compare_prices`, **no** `browse_categories`, **no**
`list_category_products`, **no** `render_product_results`, **no** retries,
**no** pagination, **no** database writes of any kind.

| # | Catalogue product (id / sku) | Query | HTTP | Time | Results |
|---|---|---|---|---|---|
| 1 | Pharmacis Sunscreen SPF 50+ Gel Cream (2 / `OBF-SUN-PREP-30`) | `Pharmacis Sunscreen SPF 50+ Gel Cream 30 ml` + brand | 200 | ~1.8 s | **0** |
| 2 | Minimalist 10% Niacinamide Serum (3 / `OBF-SER-MIN-30`) | `Minimalist 10% Niacinamide Serum 30 ml` + brand | 200 | ~2.6 s | **2** |
| 3 | Kay Beauty Matte Lipstick – Reconstruct (4 / `OBF-LIP-KAY-35`) | `Kay Beauty Matte Lipstick - Reconstruct 3.5 g` + brand | 200 | ~1.8 s | **0** |

Raw responses were never persisted; only a whitelisted field subset was kept
(sanitised results at
`C:\Users\humai\AppData\Local\Temp\opencode\pi_stage7_live_results.json`).

## 2. Result-by-result validation — [FACT] (provider data) + [FACT] (pipeline output)

### Product 1 — Pharmacis Sunscreen SPF 50+ Gel Cream, 30 ml
- Provider returned 0 results (`total=0`). **No observation possible.**
- Interpretation: this product (an Open Beauty Facts-sourced record) is not
  present in PriceInIndia's index — provider coverage gap, not a query error.
  No query variation was attempted (plan rule).

### Product 2 — Minimalist 10% Niacinamide Serum, 30 ml — 2 results

| Field | Result A | Result B |
|---|---|---|
| Provider `id` | `2f48f446e151105e0668d238` | `e082b942ff29d3222668eca5` |
| Title | Niacinamide Face Serum by Minimalist | Niacinamide 10% Face Serum by Minimalist |
| Brand | `minimalist` (lower-case) | `minimalist` |
| Retailer (`store`) | `myntra.com` | `tatacliq.com` |
| Price / MRP (INR) | 569 / 599 | **569.049988** / 599 |
| Discount | 5% | 5% |
| `outOfStock` | false | false |
| `lastUpdated` | 1794375906 | 1794377968 (both ≈ hours old — fresh) |
| Normalised size | **None** (title carries no quantity; no provider `size` field) | **None** |
| Flags | none | none |
| Rejection reason | none | none |
| Match classification | `possible_match` | `possible_match` |
| Match strength | `POSSIBLE` (confidence 0.51) | `POSSIBLE` (confidence 0.49) |
| Comparable | true, **requires human review** | true, **requires human review** |
| Key reasons | title similarity 0.507; quantity missing on offer side | title similarity 0.486; quantity missing on offer side |

**Assessment:** both results are the right brand and product family, but
neither can be promoted beyond `POSSIBLE_MATCH` because:
1. the provider titles contain **no size/quantity**, so the 30 ml SKU cannot
   be confirmed (the pipeline correctly left size `None` and flagged "quantity
   not detected");
2. title similarity is ~0.49–0.51 (low);
3. the pipeline capped confidence and set `requires_human_review=True` —
   behaving exactly as designed.

### Product 3 — Kay Beauty Matte Lipstick – Reconstruct, 3.5 g
- Provider returned 0 results (`total=0`). **No observation possible.**

## 3. New empirical findings about the provider — [FACT]

These observations were only possible with live data:

1. **`productPageUrl` is a PriceInIndia page, not a retailer URL.** Both
   results' `productPageUrl` pointed to
   `https://www.priceinindia.website/products/<slug>?utm_source=chatgpt-plugin…`
   — a citation of PriceInIndia's own product page. The retailer product URL
   is **not** directly exposed by `search_products` (the affiliate
   `productUrl` is a provider-controlled redirect). Retailer attribution in
   search results is therefore limited to the `store` string.
2. **UTM tracking parameters are embedded** in both link fields
   (`utm_source=chatgpt-plugin&utm_medium=plugin&utm_content=deal|page`) —
   they must be stripped before any URL is displayed or stored.
3. **Provider titles omit size/quantity** (at least for these two results),
   while the Phase 16.7 size-extraction pipeline expects the size in the
   title. SKU-size confirmation from `search_products` alone is currently
   impossible; only `EXACT`/`STRONG` matches with other evidence could pass.
4. **Price values can carry float artifacts** (`569.049988` from Tata Cliq) —
   pass-through is honest, but a rounding policy decision is needed before
   display.
5. **Brand names can arrive lower-cased** (`minimalist`) — brand matching
   normalisation handled it correctly (case-insensitive), display formatting
   is a separate decision.
6. **`lastUpdated` is populated and fresh** (unix seconds, within hours) — the
   field is real and would give us a usable freshness signal if consumed
   (currently ignored by the normaliser — known gap §12.5 of the
   investigation report).
7. **Zero-result searches return cleanly** (`total: 0`, structured content) —
   no error, no fabricated fallback. Honest empty-result handling confirmed.
8. **`search_products` did not return Nykaa** for this serum (Myntra and Tata
   Cliq only) — coverage across the 100+ retailer claim is uneven per product
   — **[PROVIDER CLAIM]** for the breadth, **[FACT]** for this specific gap.

## 4. Request budget accounting — [FACT]

- Stage 4 handshake: 2 requests (`initialize`, `tools/list`).
- Stage 7 live test: 3 requests (`search_products` × 3).
- **Total provider requests across the entire investigation: 5.**
- All returned HTTP 200; no 429s, no timeouts, no errors, no retries.

## 5. Trustworthiness verdict — [ASSESSMENT]

**What the live test establishes:**
- The integration **works end-to-end**: schema-compatible, honest empty
  results, INR-only, structured content parsed correctly, validation pipeline
  classified results conservatively and flagged every uncertainty.
- The pipeline's Phase 16.7 safeguards behaved exactly as designed under live
  data (no false EXACT matches, human-review flags set, size uncertainty
  preserved).

**What it does NOT establish:**
- **Attribution depth:** retailer URLs are not directly exposed by
  `search_products`; verified-retailer-offer claims would require following
  the provider redirect (not done here, and not appropriate for automation).
- **SKU identity:** without sizes in titles, offers cannot be confirmed as
  the same SKU — the 30 ml serum offers stay `POSSIBLE`.
- **Legal reuse rights:** unchanged — see §4/§13 of the investigation report;
  nothing in this test grants storage/display rights.

**Bottom line:** PriceInIndia behaves as documented and can be a usable
*provider-observed* price signal at `POSSIBLE`/`STRONG` strength for products
it indexes, but (a) coverage for our current catalogue is thin (1 of 3
products found), (b) SKU confirmation is structurally limited by missing
sizes, and (c) data-reuse permission is still unclarified. **Recommendation:
treat PriceInIndia as an optional, conservatively-labelled supplementary
source after provider permission answers; do not schedule collection yet.**

## 6. Safety compliance checklist — [FACT]

- [x] No database writes (app DB never opened for writing; local DB opened read-only in Stage 5 only)
- [x] No production Neon access
- [x] No bulk collection (3 targeted calls only)
- [x] No collection scripts run, no scheduler started
- [x] No deploy, no commit, no push, no merge
- [x] No Phase 16.7 implementation files modified
- [x] No existing tests modified
- [x] No raw provider payloads persisted (whitelisted fields only)
- [x] No automatic retry on failure (adapter `max_retries=0`; no failures occurred)
- [x] Phase 16.7 working tree fully preserved
