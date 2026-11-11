# Phase 16.6 — Stage 1: Beauty Catalogue Coverage Audit

**Generated:** 2026-11-11T11:27:14.856079+00:00
**Audited database:** `C:\Users\humai\AppData\Local\Temp\pricewise-audit-8hf34_05.db`
**Method:** offline inspection of the canonical seeded catalogue and its offers/observations. No provider requests were made in this stage.

## Category definitions (mutually exclusive, precedence order)

- **PROVIDER_OBSERVED** — Has a live, provider_observed PriceInIndia observation that is eligible as a current price. Not independently verified.
- **MATCH_REVIEW_REQUIRED** — Provider candidates exist but every live candidate is flagged or pending review; no usable current provider price.
- **MANUAL_VERIFIED_ONLY** — Price verified by an admin manual entry; no live provider observation. Not a live retailer price.
- **CATALOG_VERIFIED_ONLY** — Product identity verified in catalog (Open Beauty Facts); no current retailer observation. Catalog verification does not imply live pricing.
- **DEMO_ONLY** — Only seeded demo prices exist; clearly labelled demo data, not real retailer prices.
- **NO_PRICE_AVAILABLE** — No usable offer or observation of any kind.

## Totals

| Metric | Count |
|---|---|
| Beauty products (non-electronics, active) | 26 |
| PROVIDER_OBSERVED | 0 |
| MATCH_REVIEW_REQUIRED | 0 |
| MANUAL_VERIFIED_ONLY | 0 |
| CATALOG_VERIFIED_ONLY | 5 |
| DEMO_ONLY | 21 |
| NO_PRICE_AVAILABLE | 0 |

## Pipeline metrics

| Metric | Count |
|---|---|
| Products searched (this stage) | 0 |
| Products with provider results | 0 |
| Products with accepted matches | 0 |
| Products with rejected matches | 0 |
| Products requiring manual review | 0 |
| Products without any usable price | 21 |

## PriceInIndia adapter health (configuration snapshot)

| Field | Value |
|---|---|
| Name | PriceInIndia |
| Endpoint | `https://mcp.priceinindia.website/mcp` |
| Configured | True |
| Status | never_run |
| Rate limit | 15 req/min |
| Timeout | 10.0s |
| Max retries | 2 |
| Requests made (stage 1) | 0 |

## Per-product coverage

| ID | Title | Brand | Category | Size | Formulation | Concentration | Shade | Offers | Observations | Coverage |
|---|---|---|---|---|---|---|---|---|---|---|
| 12 | Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ | Dot & Key | Sunscreens | 50 g | Fluid Sunscreen | — | — | 4 (4 demo) | 0 | DEMO_ONLY |
| 13 | The Derma Co 1% Hyaluronic Sunscreen Aqua Gel SPF 50 PA+++ | The Derma Co | Sunscreens | 50 g | Aqua Gel Sunscreen | 1% | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 14 | Minimalist 10% Niacinamide Face Serum with Zinc PCA | Minimalist | Serums | 30 ml | Active Face Serum | 10% | — | 4 (4 demo) | 0 | DEMO_ONLY |
| 15 | Plum 15% Vitamin C Glow Face Serum with Mandarin | Plum | Serums | 30 ml | Glow Face Serum | 15% | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 16 | COSRX Advanced Snail 96 Mucin Power Essence | COSRX | Serums | 100 ml | Repair Essence / Serum | — | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 17 | Cetaphil Gentle Skin Cleanser Hydrating Formula | Cetaphil | Face cleansers | 125 ml | Cream Cleanser | — | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 18 | Forest Essentials Delicate Facial Cleanser Kashmiri Saffro | Forest Essentials | Face cleansers | 200 ml | Gel Cleanser | — | — | 2 (2 demo) | 0 | DEMO_ONLY |
| 19 | Clinique Moisture Surge 100H Auto-Replenishing Hydrator | Clinique | Moisturizers | 50 ml | Gel-Cream Moisturizer | — | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 20 | Dot & Key Ceramides & Hyaluronic Skin Barrier Repair Face  | Dot & Key | Moisturizers | 50 g | Barrier Cream Moisturizer | — | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 21 | M.A.C Retro Matte Lipstick - Ruby Woo | M.A.C | Lipsticks | 3 g | Bullet Lipstick | — | Ruby Woo (Vivid Blue-Red) | 3 (3 demo) | 0 | DEMO_ONLY |
| 22 | Kay Beauty Matteinee Matte Lipstick - Reconstruct | Kay Beauty | Lipsticks | 3.5 g | Bullet Lipstick | — | Reconstruct (Deep True Red) | 2 (2 demo) | 0 | DEMO_ONLY |
| 23 | Maybelline Fit Me Matte + Poreless Liquid Foundation - 128 | Maybelline | Foundations | 30 ml | Liquid Foundation | — | 128 Warm Nude | 4 (4 demo) | 0 | DEMO_ONLY |
| 24 | Rare Beauty Soft Pinch Liquid Blush - Encourage | Rare Beauty | Blushes | 7.5 ml | Liquid Blush | — | Encourage (Soft Neutral Pink) | 2 (2 demo) | 0 | DEMO_ONLY |
| 25 | Kay Beauty Creme Blush - Sweetheart Pink | Kay Beauty | Blushes | 4 g | Cream Blush | — | Sweetheart Pink | 2 (2 demo) | 0 | DEMO_ONLY |
| 26 | Maybelline Lash Sensational Sky High Waterproof Mascara | Maybelline | Mascaras | 7.2 ml | Waterproof Mascara | — | Very Black | 3 (3 demo) | 0 | DEMO_ONLY |
| 27 | Kay Beauty 24HR Waterproof Metallic Gel Kajal Eyeliner | Kay Beauty | Eyeliners | 0.35 g | Gel Kajal Eyeliner | — | Midnight Black | 2 (2 demo) | 0 | DEMO_ONLY |
| 28 | Laneige Lip Sleeping Mask Berry | Laneige | Lip care | 20 g | Lip Sleeping Mask | — | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 29 | Dot & Key Vitamin C + E Lip Sleeping Mask | Dot & Key | Lip care | 12 g | Lip Sleeping Mask | — | — | 2 (2 demo) | 0 | DEMO_ONLY |
| 30 | Simple Kind to Skin Micellar Cleansing Water | Simple | Makeup removers | 200 ml | Micellar Makeup Remover | — | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 31 | Minimalist Maleic Bond Repair Complex 5% Hair Serum | Minimalist | Haircare | 50 ml | Bond Repair Hair Treatment | 5% | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 32 | Chemist at Play Exfoliating Lactic Acid Body Wash | Chemist at Play | Body care | 250 ml | Exfoliating Body Wash | — | — | 3 (3 demo) | 0 | DEMO_ONLY |
| 33 | Pharmacis Sunscreen SPF 50+ Gel Cream | Pharmacis | Sunscreens | 30 ml | Gel Cream Sunscreen | — | — | 1 (1 demo) | 0 | CATALOG_VERIFIED_ONLY |
| 34 | Minimalist 10% Niacinamide Serum | Minimalist | Serums | 30 ml | Face Serum | 10% | — | 1 (1 demo) | 0 | CATALOG_VERIFIED_ONLY |
| 35 | Kay Beauty Matte Lipstick - Reconstruct | Kay Beauty | Lipsticks | 3.5 g | Bullet Lipstick | — | Reconstruct | 1 (1 demo) | 0 | CATALOG_VERIFIED_ONLY |
| 36 | Maybelline Fit Me Matte Liquid Foundation - 128 Warm Nude | Maybelline | Foundations | 30 ml | Liquid Foundation | — | 128 Warm Nude | 1 (1 demo) | 0 | CATALOG_VERIFIED_ONLY |
| 37 | Maybelline Lash Sensational Sky High Mascara - Very Black | Maybelline | Mascaras | 7.2 ml | Waterproof Mascara | — | Very Black | 1 (1 demo) | 0 | CATALOG_VERIFIED_ONLY |

## Observation detail (non-empty only)

_No observations exist in the audited database._

## Expected vs actual catalogue size

The Phase 16.6 brief expects a beauty catalogue of approximately 100 products. The actual canonical seeded catalogue contains **26 beauty products**:

| Source | Count | Notes |
|---|---|---|
| `DEMO_BEAUTY_PRODUCTS` (src/database/beauty_seed_data.py) | 21 | Demo-priced beauty products, 15 brands, 13 categories |
| `DEMO_OBF_PRODUCTS` (src/database/seed.py) | 5 | Open Beauty Facts catalog-verified products |
| Legacy electronics (`DEMO_PRODUCTS`) | 11 | **Excluded** from beauty coverage per stage scope |
| **Beauty total** | **26** | |

The ~100-product expectation is not met by the current seed data. Expanding the catalogue is a seed-data change and is **out of scope** for this phase: Phase 16.6 improves live price *coverage* over the existing catalogue and must not fabricate products. The 26 existing products are the full discovery target for Stage 2.

### Note on the 5 catalog-verified products

Products 33–37 (OBF-sourced) each also carry a single demo offer (Pharmacis/Nykaa demo). Because product identity is catalog-verified (Open Beauty Facts), they are classified `CATALOG_VERIFIED_ONLY` under the precedence rules above — but their **only prices are demo offers**; catalog verification does not imply any live retailer price. They differ from the 21 demo products only in that product identity is externally verified.

## Local development database discrepancy

A read-only audit of `data/pricewise.db` (the local dev database, never modified by this phase) shows a **degraded state that does not contain the canonical beauty catalogue**:

| Table | Dev DB rows | Fresh-seed rows |
|---|---|---|
| products | 6 | 37 |
| stores | 5 | 10 |
| offers | 9 | 100 |
| price_history | 0 | 941 |
| retail_price_observation | 0 | 0 |
| users | 26 | 0 |

Dev DB contents: 1 legacy test fixture (`Test Product One`, category `Beauty`, `demo`/`pending_review`, classified `DEMO_ONLY`) and 5 OBF catalog-verified products with non-demo Nykaa/myntra.com/TataCLiQ offers, 0 observations anywhere.

**Implication:** running the app locally against `data/pricewise.db` will not show the demo beauty catalogue or price history. Tests and this audit use isolated seeded temporary databases, so this does not affect test results. **Recommendation (not executed):** reseed the dev database (`python -m src.database.seed`) to restore the canonical catalogue. This phase does not perform the reseed — no writes to the app database without approval.

## Adapter health snapshot (no requests made)

- PriceInIndia adapter configured, endpoint `https://mcp.priceinindia.website/mcp`, status `never_run`
- Rate limit 15 req/min, timeout 10.0 s, max retries 2
- Stage 1 makes zero provider calls; Stage 2 will begin controlled discovery

## Recommendations carried into Stage 2

1. Discovery target = all 26 beauty products (21 demo-priced + 5 catalog-verified).
2. Demo offers must never enter live cheapest-offer rankings (Stage 6).
3. The dev DB should be reseeded separately with user approval; not part of this phase.
4. `retail_price_observation` currently has no rows anywhere — the full observation lifecycle (Stages 2–4) will be exercised from zero, so migration idempotency and superseding rules must be tested on both empty and populated states.
5. `observed_mrp` is currently always NULL although PI items carry `mrp` — Stage 4 should preserve it.
