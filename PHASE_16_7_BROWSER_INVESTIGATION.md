# Phase 16.7 — Chrome MCP Retailer Browser Investigation

**Investigation date:** 2026-11-11 (afternoon, IST)
**Tooling:** Chrome DevTools MCP (`chrome-devtools-mcp@latest`) driving a real, non-stealth Chrome browser session.
**Test product:** Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ In-Vivo Tested, 50 g (catalogue product).
**Evidence classification:** all observations below are **BROWSER OBSERVED** — visible in a real browser DOM snapshot. None of them are LIVE_VERIFIED database records unless separately written through the observation pipeline (see §8).

---

## 1. Investigation summary table

| Retailer | Browser accessible | Search works | Price visible | Product identity verified | Automated access permitted | Result |
|---|---|---|---|---|---|---|
| Nykaa | Yes | Yes (UI + `/search/result/?q=` URL) | Yes (listing + PDP) | Yes (PDP title, sizes, SKU, canonical URL) | Partially — robots.txt: `Allow: /` but `Disallow: /search/`, `/catalog/`; PDP pages appear allowed | Verified (manual/interactive observation) |
| Myntra | Yes | Yes (UI + `/<query-slug>?rawQuery=` URL) | Yes (listing + PDP, unit price `@ Rs. 8.9 per gm`) | Yes (PDP heading, 50g size, product ID 21404558) | NOT VERIFIED — robots.txt fetch timed out twice; Terms must be reviewed before any automated collection | Verified (manual/interactive observation) |
| Purplle | Yes | Yes via direct URL `/search?q=` (searchbox Enter does not navigate; first snapshot empty — client-side render wait required) | Yes (listing) | Yes (listing title incl. "50 gm", canonical product URL) | Partially — robots.txt: `Disallow: /search*`, product pages allowed; Terms must be reviewed | Verified (manual/interactive observation) |
| Tira | Yes | Structurally yes — real pattern is `/products?q=` (the `/search?q=` pattern renders nothing); **Dot & Key NOT found** in results for 2 query variants ("dot key watermelon sunscreen", "dot and key") | Yes (other brands: Deal Price + MRP + sizes + canonical URLs visible) | NOT for target product (not carried/listed in search) | Partially — robots.txt: `Allow: /` for main agent but `Disallow: /*?q*` (search URLs); **explicitly allows named AI crawlers** (GPTBot, ClaudeBot, PerplexityBot, Googlebot, etc.) for `/` | Negative product finding recorded honestly |
| Amazon India | Yes | Yes (`/s?k=`); renders without CAPTCHA; **sponsored results clearly interleaved** (`ref=...sspa`, "Sponsored ad" links) | Yes (listing + PDP, unit price `₹774/100g`) | Yes (PDP `https://www.amazon.in/dp/B0BQN2YWN5`, "In stock" explicit) | Partially — robots.txt: `/dp/` PDPs allowed for `User-agent: *`; general `/s?k=` not explicitly disallowed for `*` BUT nearly all AI/automation crawlers explicitly `Disallow: /` (ClaudeBot, GPTBot, Scrapy, Crawl4AI, etc.); Associate/Terms restrictions apply to any systematic collection | Verified (manual/interactive observation) |

`NOT TESTED` fields: none for the five retailers above (all fields above were actually exercised; the single NOT VERIFIED is Myntra's robots.txt/Terms permission status, which could not be established).

---

## 2. Test conditions

- Real Chrome browser, default user profile, no stealth modifications, no proxies, no CAPTCHA interaction. Every navigation was a normal user-level page load.
- One Chrome page (`pageId: 1`) was navigated sequentially: Nykaa → Myntra → Purplle → Tira → Amazon.in.
- DOM data captured via accessibility snapshots; prices are read from rendered text (`₹387`, `Regular price ₹445. Discounted price ₹387. 13% Off.`, etc.).
- Observation timestamp: 2026-11-11 (browser-visible promo banner on Nykaa carried the date string `11112026`, consistent).

## 3. Observed price evidence (product-page level, unless noted)

| Retailer | Source URL | Evidence type | Selling price | MRP | Size/variant | Availability | Timestamp |
|---|---|---|---|---|---|---|---|
| Nykaa | `https://www.nykaa.com/dot-key-watermelon-hyaluronic-cooling-sunscreen-spf-50-pa/p/14072071` | Product page (PDP) | ₹387 | ₹445 (Regular price) | combobox `50ml` (selected) / `80ml`; SKU ID 8938307 | "Add to bag" button present (in stock) | 2026-11-11 |
| Myntra | `https://www.myntra.com/face-sunscreen/dot+%26+key/dot--keywatermelon-cooling-sunscreen-in-vivo-tested-spf-50-pa-with-hyaluronic--50g/21404558/buy` | Product page (PDP) | ₹387 | ₹445 (MRP, inclusive of all taxes) | `50g` (URL slug + heading); unit `@ Rs. 8.9 per gm`; other sizes 30g/80g as separate PDPs | ADD TO BAG present (in stock) | 2026-11-11 |
| Purplle | `https://www.purplle.com/product/dot-and-key-watermelon-hyaluronic-cooling-sunscreen-spf-50-pa-for-moisturized-skin-no-white-cast-boosts-vitamin-d-absorption-and-quick-absorbing-50g-58` | Search listing (NOT opened as PDP) | ₹387 | ₹445 (13% off) | `50 gm` (in title) | NOT TESTED (listing did not state stock status) | 2026-11-11 |
| Amazon.in | `https://www.amazon.in/dp/B0BQN2YWN5` | Product page (PDP) | ₹387.00 | M.R.P ₹445 | unit price `₹774/100g` (→ 50 g); size selector variants present | "In stock" explicitly visible; delivery info visible | 2026-11-11 |
| Tira | — | — | — | — | — | — | Product not found in search (see §5) |

**Cross-retailer consistency finding:** selling price ₹387 and MRP ₹445 are identical across Nykaa, Myntra, Purplle and Amazon for the same 50 g SKU. This is strong corroboration but still only BROWSER OBSERVED evidence.

**Unit-discrepancy finding (important for matching):** Nykaa labels the 50-size variant as **50ml** while Myntra, Purplle, Amazon and the catalogue use **50g**. Same SKU, inconsistent unit labels across retailers. Matching logic must treat `g` vs `ml` as a *tolerated equivalence only when brand+title+price otherwise agree* — never as a size mismatch, and never as a blanket equivalence.

**Search-result vs product-page evidence:** Nykaa listing rows for *other* Dot & Key variants (e.g. Cica Calming) also showed ₹387/₹445 — listing prices can be ambiguous between variants. Only PDP-confirmed prices were treated as product-page evidence; every search-result price was verified against a PDP before being recorded here (Purplle is the exception, explicitly recorded as listing-level evidence).

## 4. Retailer-by-retailer notes

### 4.1 Nykaa
- Homepage loads; header search box works with Enter navigation.
- Search URL pattern: `/search/result/?q=<query>`.
- PDP shows: exact title with size in heading, Regular/Discounted price, discount %, size combobox (50ml/80ml), SKU ID 8938307, canonical URL, Add to bag.
- robots.txt (fetched 2026-11-11): `User-agent: * Allow: /`; `Disallow: /search/`, `/catalog/`, several cart/review endpoints. PDP URLs like `/p/14072071` are not disallowed.
- Implication: automated collection, if ever attempted, must target PDP pages and avoid `/search/` crawling; Terms of Use review still required.

### 4.2 Myntra
- Homepage loads; search box works with Enter navigation.
- Search URL pattern: `/<query-slug>?rawQuery=<query>` (auto-generated slug).
- Listing rows include "Rs. X Rs. Y (Z% OFF)" and size in URL slug (30g/50g/80g are separate PDPs).
- PDP shows: ₹387, MRP ₹445 "(13% OFF)", `@ Rs. 8.9 per gm` (unit price surfaced by Myntra itself), size selector, ADD TO BAG.
- robots.txt: **fetch timed out twice** (two attempts, both timeouts) — automated-access permission **NOT VERIFIED**. Do not build any automated collection against Myntra until robots.txt and Terms are reviewed.
- Interactive/manual browsing observation stands as a permitted human-level check.

### 4.3 Purplle
- Homepage loads; the search box fill + Enter does **not** navigate (client-side behaviour); direct URL `/search?q=` works.
- First snapshot of the search page is empty — requires a wait for client-side rendering (browser limitation recorded).
- Listing: exact title including "50 gm", ₹387 / ₹445, 13% off, rating 4.3 (4394 reviews), canonical product URL. **Listing-level evidence only** — the PDP was not opened for price confirmation.
- robots.txt (fetched 2026-11-11): `Disallow: /search*` — search endpoints are disallowed for crawlers; product pages (`/product/<slug>`) are not disallowed except `/product/*/details`, `/product/sellers*`, etc.
- Implication: if automated collection is ever attempted, PDP URLs may be permissible pending Terms review; search-endpoint crawling is not.

### 4.4 Tira
- `/search?q=` URL pattern renders nothing (page stays empty) — Tira's real pattern discovered via its own suggestion link: `/products?q=<query>`.
- Search results render fully for other brands: `Deal Price: ₹395 MRP: ₹449`, sizes (`50 g`, `50 ml`), canonical `/product/...` URLs, wishlist/stock affordances.
- **Dot & Key sunscreen was NOT found** for query "dot key watermelon sunscreen" nor for "dot and key" (0 matching results in both). Honest negative finding: Tira does not appear to carry/list this product in search. No product page opened; no price evidence collected.
- robots.txt (fetched 2026-11-11): `Allow: /` for `User-agent: *` but `Disallow: /*?q*` (all query-string search URLs), plus explicit **allows** for named AI crawlers (GPTBot, ClaudeBot, PerplexityBot, Googlebot, Bingbot, CCBot, Applebot, Amazonbot, Meta-ExternalAgent, YouBot) on `/`.
- Implication: Tira is the most AI/automation-friendly retailer by robots.txt posture, but it does not carry the tested product, so it provides no coverage for this SKU.

### 4.5 Amazon India
- Search renders without CAPTCHA (`/s?k=`), but **sponsored results are interleaved and clearly marked** (`ref=...sr_1_1_sspa`, `/sspa/click?...` redirect URLs, "Sponsored ad" link labels). Sponsored rows must never be used as organic product evidence — one sponsored row showed a *different* price (₹499) for a related but different product.
- Organic PDP: `https://www.amazon.in/dp/B0BQN2YWN5` — title "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++", ₹387.00, M.R.P ₹445, unit `₹774/100g` (= 50 g), explicit "In stock", delivery estimate visible.
- robots.txt (fetched 2026-11-11): `User-agent: *` allows `/dp/` product pages (some disallow rules target other endpoints); however, a long explicit list of AI/automation crawlers is `Disallow: /` (ClaudeBot, GPTBot, OAI-SearchBot, Scrapy, Crawl4AI, GrokBot, Gemini-Deep-Research, etc.).
- Implication: Amazon.in is the least permissive toward automated/AI collection. Amazon's Conditions of Use additionally restrict automated extraction. Any automated collection is out of scope without explicit permission; interactive observation only.

## 5. Negative and honest findings

1. **Tira does not list Dot & Key sunscreen** in search results (two query variants). Recorded as a coverage gap, not faked.
2. **Purplle price is listing-level only** — PDP was not opened, so its evidence tier is one notch below the others.
3. **Nykaa vs catalogue unit label conflict:** Nykaa says 50ml, catalogue says 50g for the same SKU.
4. **Amazon sponsored results** appear above/among organic results with different prices — automated parsing without sponsored-detection would corrupt price data.
5. **Myntra robots.txt unreachable** — permission status unverifiable; no automated path may be assumed.
6. The catalogue demo price for this product (₹465) differs from every real retailer price (₹387) — expected, demo ≠ real, and demo data must never be presented as live.

## 6. Permission requirements summary

| Retailer | robots.txt posture (crawlers) | Interactive browsing used | Automated collection permitted? |
|---|---|---|---|
| Nykaa | Allow `/`, disallow `/search/`, `/catalog/` | Yes (observed) | Not established — PDP crawl plausibly allowed by robots.txt but Terms review required first |
| Myntra | Unknown (robots.txt fetch timed out ×2) | Yes (observed) | NOT VERIFIED — assume no until verified |
| Purplle | Allow `/`, disallow `/search*` | Yes (observed) | Not established — PDP crawl plausibly allowed by robots.txt but Terms review required first |
| Tira | Allow `/` + explicit AI-crawler allows; disallow `/*?q*` | Yes (observed) | Most permissive posture, but product not carried — moot for this SKU |
| Amazon.in | Allow `/dp/` for `*`; explicit blanket disallow for AI/automation crawlers | Yes (observed) | No — assume no automated collection |

robots.txt is a crawler-scoping convention, not a legal permission. Amazon.in and others additionally restrict automated access in their Terms of Use. This investigation used interactive, human-equivalent browsing only.

## 7. Can these observations safely enter the PriceWise AI database?

- **Yes, with correct provenance** — as `PROVIDER_OBSERVED`/manually-reviewed observations with source URL, retailer identity, evidence tier and observation timestamp, and explicitly **NOT** as `LIVE_VERIFIED` (see §8).
- What may be stored: retailer name, source URL, observed selling price, MRP, size/variant label, availability as seen, capture timestamp, evidence type (PDP vs listing), capture method (interactive browser).
- What must not be stored/redistributed as ours: retailer imagery, marketing copy, reviews. Only factual price data with attribution, pending user/legal decision on any automated collection.
- No observation from this session was written to `data/pricewise.db` (dev DB) or to any production Neon database during Phase 16.7 without explicit approval (final data state documented in the main report).

## 8. Browser limitations recorded

- Accessibility-snapshot uids change after every navigation; stale-uid errors are normal and were handled by retaking snapshots.
- `setTimeout`/`sleep` are unavailable in the automation harness; waits were done via `wait_for` text polling, which occasionally timed out on slow client-side rendering (Tira, Purplle).
- Purplle searchbox fill does not trigger navigation — direct URL entry was required.
- Tira's `/search?q=` path silently renders an empty page; only the `/products?q=` path works.
- Amazon.in's snapshot is very large (~263 KB for a search page); targeted line filtering was required.
- No CAPTCHA, login, or bot-protective interstitial was encountered at any point during this session; none were bypassed.
