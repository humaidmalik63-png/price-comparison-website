# Phase 14 Stage C — Product Image Authenticity Report

**Date:** 2026-11-10
**Scope:** the 100 active beauty products in the catalogue (`products.is_active = 1`).

---

## 1. Starting point

The catalogue audit found that **all 100 active products pointed at only 11 unique
Unsplash stock photographs** — generic editorial images, none of which showed the
product being sold. The seeded rows also carried `image_status = 'placeholder'`,
so the database and the interface disagreed about what was being shown.

The frontend already refused to render those URLs (`isGenericStockImage()` in
`frontend/src/utils/imageFallback.ts` substitutes a neutral branded placeholder),
but the database still served them and the API still exposed them.

---

## 2. Verification method

Each candidate image had to pass **four** gates before it was accepted:

| Gate | Check |
|---|---|
| 1. Reachability | The URL returns HTTP 200 with an `image/*` content type and a plausible payload size. |
| 2. Geometry | The asset is not a banner or logo (aspect-ratio and dimension screen). |
| 3. Product identity | The page title / `og:title` describes *this* product line. |
| 4. **Visual confirmation** | The downloaded image was rendered and inspected: the packaging in the photograph must be the product in the catalogue record. |

Gate 4 is not optional. It rejected **three assets that passed gates 1-3** and would
otherwise have been published:

| Candidate | What it actually was | Why it was rejected |
|---|---|---|
| Minimalist 10% Niacinamide Face Serum | A **5% Hair Serum** bottle | Wrong product in the same brand |
| Dot & Key Vitamin C + E Lip Sleeping Mask | A **Pink Clay Mask** jar | Wrong product in the same brand |
| Cetaphil Gentle Skin Cleanser | The **Cetaphil logo** | Brand logo, not a product |
| Maybelline Lash Sensational Mascara | The **Maybelline New York logo** | Brand logo, not a product |
| Simple Micellar Cleansing Water | A **Myntra listing banner** | Retailer listing page, not a product page |
| Kay Beauty Matteinee Matte Lipstick | The **Matteinee Lip Crayon** | Different SKU in the same line |
| Minimalist Invisible Sunscreen | The **Minimalist homepage** | Not a product page |

No image was ever invented, generated or approximated. No retailer or brand
protection was bypassed: candidates behind a bot wall were skipped.

---

## 3. Result

| Metric | Value |
|---|---|
| Active products audited | 100 |
| **Authentic product photographs published** | **10** |
| Products showing the neutral branded placeholder | 90 |
| Generic stock photographs remaining in the database | **0** |
| Generic stock photographs remaining in the frontend catalogue | **0** |
| Candidates visually confirmed as the wrong product or a logo | 7 |
| Brand / retailer bot walls encountered | several (skipped, never bypassed) |

### The 10 published photographs

| DB id | Product | Source | Status |
|---|---|---|---|
| 12 | Dot & Key Watermelon Cooling Sunscreen SPF 50+ | dotandkey.com (official) | permission_review |
| 13 | The Derma Co 1% Hyaluronic Sunscreen Aqua Gel 50 g | thedermaco.com (official) | permission_review |
| 15 | Plum 15% Vitamin C Glow Boost Serum | plumgoodness.com (official) | permission_review |
| 16 | COSRX Advanced Snail 96 Mucin Power Essence 100 ml | cosrx.com (official) | permission_review |
| 19 | Clinique Moisture Surge 100H Auto-Replenishing Hydrator | clinique.com (official) | permission_review |
| 20 | Dot & Key Ceramides & Hyaluronic Barrier Repair Moisturizer | dotandkey.com (official) | permission_review |
| 24 | Rare Beauty Soft Pinch Liquid Blush | rarebeauty.com (official) | permission_review |
| 25 | Kay Beauty Creme Blush | kaybeauty.in (official) | permission_review |
| 32 | Chemist at Play Daily Exfoliating Body Wash | chemistsatplay.com (official) | permission_review |
| 1002 | Dr. Sheth's Ceramide & Vitamin C Sunscreen SPF 50+ 50 g | drsheths.com (official) | permission_review |

Every record carries its provenance:

| Column | Meaning |
|---|---|
| `image_url` | The direct asset URL (empty for the 90 placeholder products) |
| `image_source_url` | The product page the asset came from |
| `image_source_name` | The source, e.g. `Dot & Key official site` |
| `image_status` | `permission_review` (brand asset) or `placeholder` |
| `image_last_checked` | Timestamp of the last reachability check |

### Why the status is `permission_review` and not `verified_exact`

`verified_exact` is reserved for assets with a confirmed open licence. These ten
photographs are the brands' own marketing assets, hotlinked from their CDNs. They
are the **authentic packaging of the correct product**, but redistributing them
requires the brand's permission. The interface labels them accordingly:

* `verified_exact` → “Verified Packaging Photo (Open License)”
* `permission_review` → “Official Retailer Asset • Usage Review”
* `placeholder` → “Neutral Catalog Placeholder • Photo Verification Pending”

**Before a commercial launch, obtain written permission from each brand for
hotlinking, or replace the asset with a licensed photograph.** The data model
already supports a licence upgrade: set `image_status = 'verified_exact'` and
record the licence in `image_source_name`.

### Size-variant notes

Three of the published photographs show a different pack size from the catalogue
record, because the brand has since changed the size it sells:

| Product | Catalogue size | Photograph shows |
|---|---|---|
| Dot & Key Watermelon Cooling Sunscreen | 50 g | 80 ml |
| Plum 15% Vitamin C Glow Boost Serum | 30 ml | 20 ml (pack of 2) |
| Dot & Key Barrier Repair Moisturizer | 50 g | 175 g |

The product identity is correct in every case (same brand, same product line,
same formulation), but the pack size differs. Consumers should be told this
before purchase.

---

## 4. The 90 products without a verified photograph

They render the neutral branded placeholder produced by
`generateProductPlaceholderSvg()` in `frontend/src/utils/imageFallback.ts`: a
brand-toned panel with the product name and an explicit “photo verification
pending” badge. No third-party image is requested for them, so the storefront
never loads an unrelated photograph and never implies a product it does not have.

This is a deliberate product decision: **a clean placeholder is honest, a stock
photograph is not.** The remaining 90 products need the same four-gate
verification pass, which is a manual, per-product task.

---

## 5. How to continue the work

1. Research the official product page for the product (brand site first).
2. Extract the asset from `og:image` or the product gallery.
3. Run it through the four gates above — **including the visual check**.
4. Record provenance with `image_source_url` / `image_source_name` /
   `image_last_checked` and set `image_status` accordingly.

A reusable checker is available as `scripts/verify_product_images.py`; it performs
gates 1-3 and flags geometry outliers for manual review.
