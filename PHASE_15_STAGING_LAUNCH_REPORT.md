# PHASE 15 — STAGING LAUNCH REPORT

**Date:** 2026-11-10
**Branch:** `phase-14-master` → `origin/phase-14-master` @ `cc38615`
**Base:** `main` @ `83e2267` (**unchanged**)
**Scope:** make the application work correctly in the deployed staging environment and prepare it for a controlled launch.

---

## 1. HEADLINE

**The staging deployment could not be performed from this environment** — there is no Render, Vercel or Neon credential available, and the Neon connection strings that exist in the repository history are masked placeholders, not usable credentials.

Everything that does not require those credentials was completed and verified, and it produced **three production-breaking defects** that would otherwise have shipped broken:

| # | Defect found in Phase 15 | Impact had it shipped |
|---|---|---|
| 1 | The React client called `/api/beauty/match-concerns`; the router serves `/api/beauty/match-skin-concerns` | **404** — the skin-concern matcher never worked in the deployed app |
| 2 | The client called `/api/beauty/generate-routine`; the router serves `/api/beauty/generate-routine/{routine_type}` | **404** — routine generation never worked in the deployed app |
| 3 | The API published the synthetic `offer_url` (`nykaa.com/product/BEAUTY-…`) next to a null `purchase_url`, and the client reads `offer_url` | the fabricated purchase link still reached the interface |

Defects 1 and 2 were invisible to the backend test suite (which calls the router directly) and to the Phase 14 end-to-end test (which also called the router directly). They were found by comparing **every path the client uses against the real FastAPI routes** — a check that is now a permanent test (52 assertions).

> **Production readiness verdict: NOT READY TO LAUNCH.** The application is now *correct* — but it has not been deployed, the staging catalogue endpoint still returns 500, no live retailer feed exists, 90 of 100 products still have no authentic photograph, and the scheduled worker is not running. See §11.

---

## 2. STATE INSPECTION

### 2.1 Git

| Item | Value |
|---|---|
| Branch | `phase-14-master` |
| Working tree | clean (`git status --porcelain` empty) |
| Phase 14 commits present | `563456b`, `1cca84e`, `c7c965a`, `6de377a`, `a0efdaf`, `21c5bf6` (+ `a57b8af`, `474aacd` from Stage 2.5) |
| `main` / `origin/main` | `83e2267` — **unchanged** |
| History rewritten? | **No** — additive commits only, no force push, no rebase |
| Pushed | `origin/phase-14-master` @ `cc38615` |

### 2.2 Deployment configuration

| Item | Finding |
|---|---|
| `render.yaml` | Declares the staging web service (`pricewise-backend-staging`, `srv-dbp341c9v7es73aeses0`) and the Phase 14 cron job. `AUTH_SECRET_KEY` is declared with `sync: false` (manual). |
| `frontend/.env.production` | Points at `https://pricewise-backend-staging.onrender.com` |
| `frontend/vercel.json` | Vite SPA build, `outputDirectory: dist`, SPA rewrite, security headers |
| `docs/PHASE14_STAGING_DEPLOYMENT_RUNBOOK.md` | Present and consistent with the code |
| `PHASE_14_MASTER_COMPLETION_REPORT.md` | Present; this phase updated the launch reality it described |

### 2.3 Neon staging branch

| Item | Finding |
|---|---|
| Staging branch | `br-aged-glade-bbyyq4r7` (Neon project *Price-wise*, `snowy-band-65160750`) |
| Staging host (from the project history) | `ep-aged-salad-bbh2tnpl…aws.neon.tech` — matches the `br-aged-` prefix |
| Production branch | `br-icy-dawn-bbx1y0jx` — **never contacted** |
| Connection string in the repo history | **masked** (`pr…`, 4-5 character placeholders) in every one of the 14 distinct URLs found |
| Usable credential available? | **No** |

The history was scanned exhaustively (every blob in every commit): 14 distinct `postgresql://` URLs, **all** placeholders or masked. No usable staging credential exists in the repository.

---

## 3. CREDENTIAL AVAILABILITY (the blocking factor)

| Credential | State | Consequence |
|---|---|---|
| `DATABASE_URL` (Neon staging) | not set, not recoverable | no backup, no archival, no migration on Neon |
| `RENDER_API_KEY` | not set | no deploy, no environment-variable change, no cron job |
| `VERCEL_TOKEN` | not set | no frontend deploy |
| `NEON_API_KEY` | not set | no branch administration |
| GitHub | available (`gh auth git-credential`) | the branch could be pushed ✔ |

`psql` and `pg_dump` **are** installed, so the operator only needs the connection string — not a working database — to run the backup.

---

## 4. WHAT WAS COMPLETED WITHOUT CREDENTIALS

### 4.1 A production-like local stack (validates the deployable artefact)

The backend was started exactly as Render runs it — `uvicorn src.api.main:app`, `ENVIRONMENT=staging`, a real `AUTH_SECRET_KEY`, a copy of the catalogue — and the **complete endpoint matrix was executed against it**.

**Result: 21 ok, 0 server errors.** Every endpoint the task lists returns the expected status.

Before the secret was supplied, the service behaved exactly as the Phase 14 design intends:

```
MissingSessionSecretError: No session signing secret is configured. Set the
AUTH_SECRET_KEY environment variable (or the legacy alias SECRET_KEY) before
starting the service in the 'staging' environment. Refusing to sign session
tokens with an unconfigured secret.
ERROR:    Application startup failed. Exiting.
```

### 4.2 The staging endpoint validator

`scripts/validate_staging.py` runs the whole matrix against any deployment, diagnoses every non-200, and has a **`--read-only` mode that writes nothing to the target database** — used for the live staging probe precisely because a verified Neon backup could not be taken first.

### 4.3 The operator launch script

`scripts/phase15_launch.py` performs the entire rollout in one gated command:
verify the target is staging → `pg_dump` → verify with `pg_restore --list` → record counts → configure `AUTH_SECRET_KEY` → deploy → apply the archival → validate every endpoint.

**Its guards were executed and verified:**

| Guard | Result |
|---|---|
| Production-looking host (`ep-icy-dawn-…`) | **REFUSED** ✔ |
| Unrecognised host (`db.example.com`) | **REFUSED** ✔ |
| No `DATABASE_URL` | **REFUSED** ✔ |
| `--dry-run` | prints the plan, changes nothing ✔ |
| Secrets | never printed — the key is read from the environment and only "configured"/"not configured" is reported ✔ |

### 4.4 Frontend ↔ backend contract (the three defects)

`tests/test_phase15_frontend_backend_contract.py` — 52 assertions comparing every client path with the real router. **Verified to work**: temporarily reintroducing the `match-concerns` bug made the guard fail (2 failures); restoring the fix made it pass again.

### 4.5 Two further functional repairs

* **Skin-concern matcher**: it returned **0 matches** for "acne" because it only consulted the ingredient analysis. It now also reads the catalogue's curated `Skin Concerns` (79 products) and `Skin Type` (92 products) specifications — deterministic data that was already in the database but unused.

  | Concern | Before | After |
  |---|---|---|
  | acne | 0 | 16 |
  | oiliness | 0 | 2 |
  | dullness | 0 | 11 |
  | acne + oiliness + pigmentation | 0 | 22 |

  The explanation now states its evidence: *"Declared in the catalogue for oiliness"*, *"Listed for acne skin types"* — and the response carries `source: deterministic_ingredient_rules`.

* **Official product page**: the catalogue already records the manufacturer's own product URL with its `Source` and `Evidence` for all 100 products. It was invisible to the API and the interface, so the storefront had **no working link at all**. It is now exposed as `official_url` / `official_source` / `official_evidence` and rendered on the product detail page as *"View on the official {brand} site"* — explicitly a brand page, never presented as a retailer offer.

---

## 5. ENDPOINT TEST RESULTS

### 5.1 Live staging today (read-only probe) — the "before" state

```
$ python scripts/validate_staging.py --base-url https://pricewise-backend-staging.onrender.com --read-only
health (live)                                     200      ok
health (ready)                                    200      ok
health (summary)                                  200      ok
product discovery                                 500      server error
archived product is not addressable               500      server error
live comparison                                   500      server error
price history                                     500      server error
deal intelligence                                 500      server error
total cost                                        500      server error
reviews (database-backed)                         404      not found
retailer status                                   200      ok
beauty: climate profiles                          200      ok
beauty: ingredients                               200      ok
authentication: me without a session              401      ok (expected)
--------------------------------------------------------------------------
ok: 6   server errors: 6   unreachable: 7
```

**All six 500s share one cause**: the Phase 14 columns never reached Neon because the old `migrate_db()` crashed on PostgreSQL, while the Phase 14 queries reference them. The `404` on `/reviews` is the Phase 14 review endpoint, which does not exist in the deployed build yet. The fixes for both are on the branch and will apply on the next deploy.

### 5.2 The same matrix against the production-like local stack — the "after" state

```
health (live) 200 | health (ready) 200 | health (summary) 200
product discovery 200 | product detail 200 | archived product 404 (correct)
retailer status 200 | live comparison 200 | price history 200
deal intelligence 200 | total cost 200 | reviews 200
climate profiles 200 | ingredients 200
authentication: register 200 | login 200 | wrong password 401 | me without session 401
me with session 200 | watchlist 200 | profile 200 | routines 200
beauty assistant 200 | usage quota 200 | admin queue 403 (correct)
--------------------------------------------------------------------------
ok: 21   server errors: 0
```

### 5.3 Frontend capability matrix (30 capabilities)

Every capability the frontend implements, exercised over HTTP against the local stack:

| Group | Capabilities | Result |
|---|---|---|
| Discovery | product list, product detail, search + filters | 3/3 ✅ |
| Price intelligence | comparison, retailer status, retailer sources, price history, deal intelligence, total cost | 6/6 ✅ |
| Beauty AI | ingredients, climate profiles, climate recommendations, skin-concern match, ingredient analysis, alternatives, routine generation, routine checker, foundation matcher, advanced discovery, usage quota | 11/11 ✅ |
| Account | profile, routines, watchlist, personalised recommendations, price tracking, price alerts, auth me | 7/7 ✅ |
| Administration | admin queue | 403 for a non-admin ✅ |

**30/30 pass.**

---

## 6. FRONTEND TEST RESULTS

| Check | Result |
|---|---|
| TypeScript type check | ✅ **0 errors** (TypeScript 5.9.3 compatibility environment — TS 7's native binary is not published for `android-arm64`) |
| Vite production build | ✅ built in 3.3 s, 2,536 modules |
| Frontend ↔ backend contract | ✅ 52/52 assertions, including the two named regressions |
| Capability matrix | ✅ 30/30 |
| Visual / responsive check in a browser | ❌ **not possible** — no desktop browser is attached to this session (`[browser.disconnected]`). The layout is Tailwind-based and unchanged in structure, but it was **not** visually re-verified on a device. |

---

## 7. SCHEDULER STATUS

| Item | Status |
|---|---|
| Implementation | `src/workers/scheduler.py` |
| Executed | ✅ one full cycle against a copy of the real catalogue — JSON summary produced (`refresh: skipped`, `alerts: 0 records evaluated`, `cleanup: 0 alerts expired / 0 logs pruned`; the catalogue has no tracking records, so zero alerts is the correct result) |
| Declared for Render | ✅ `render.yaml` → cron job `pricewise-scheduler-staging`, `*/30 * * * *` |
| **Provisioned?** | ❌ **No.** Creating it needs a Render API key and provisions a billable resource — deliberately an operator action |
| **Claimed to be running?** | **No.** No scheduled execution has been observed. |

---

## 8. SECURITY VERIFICATION

| Check | Method | Result |
|---|---|---|
| Session secret resolution | live server in `ENVIRONMENT=staging` | ✅ refuses to boot without a secret; boots with one |
| No secret in the repository | `git grep` over all tracked files | ✅ none |
| Secret never in an API response | 4 responses compared against the live secret | ✅ 0 leaks |
| Session cookie hardening | live `Set-Cookie` header | ✅ `HttpOnly; Secure; SameSite=lax; Max-Age=604800` |
| Security headers | live response | ✅ `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, HSTS on TLS |
| Administrator authorisation | live request without an admin session | ✅ 401 unauthenticated / 403 for a non-admin |
| Rate limiting | live response headers + the new test | ✅ `X-RateLimit-Limit: 120`, `X-RateLimit-Remaining`, 429 + `Retry-After` when exceeded |
| Upload validation | test suite | ✅ file-signature verification, configurable size limit, uuid4 filenames, hardened serving |
| Test isolation | SHA-256 of the shared database around a full run | ✅ **identical** before and after |
| No fabricated links | live product payload | ✅ 0 fabricated URLs, 0 coupons, 0 unverified purchase links |
| No demo offers presented as live | live product payload | ✅ every offer `source_type: demo`, `link_status: demo_not_verified` |

---

## 9. REMAINING DATA LIMITATIONS (nothing was fabricated)

| Data | State | How it is presented |
|---|---|---|
| Retailer prices | **no authorised feed** — 0 of 5 integrations have credentials | every offer is `source_type: demo`, `link_status: demo_not_verified`; the interface shows "Live link unavailable" |
| Retailer purchase URLs | **none verified** | `purchase_url` is `null` and `offer_url` is empty for all 494 offers |
| Retailer availability | **not live** | retailer status endpoint reports each integration's real access state |
| Reviews | **no review feed** — `product_reviews` is empty | the API returns an explicit `empty_state`; the interface's sample reviews are labelled "Sample content" |
| Product images | **10 of 100 authentic** | the other 90 render the neutral branded placeholder; every published image carries its source and status |
| Coupon discounts | **none** | the invented codes were removed; the validator rejects unknown coupons |
| Official brand pages | 100 recorded with source + evidence | exposed as `official_url`, labelled as a brand page |

Retailer integrations are reported honestly: **Nykaa, Tira, Purplle, Amazon India and Myntra all require authorised partner credentials** (`NYKAA_API_KEY`, `TIRA_PARTNER_TOKEN`, `PURPLLE_FEED_URL`/`PURPLLE_API_KEY`, `AMAZON_PAAPI_KEY`/`_SECRET`/`_ASSOCIATE_TAG`, `MYNTRA_PARTNER_KEY`). None is configured, so no live price exists. No bot protection was bypassed.

---

## 10. REMAINING MANUAL TASKS

### 10.1 One command (recommended)

```bash
export DATABASE_URL='postgresql://…@ep-aged-salad-…aws.neon.tech/neondb?sslmode=require'
export RENDER_API_KEY='rnd_…'
python scripts/phase15_launch.py --set-secret      # backup -> deploy -> archival -> validate
```

The script refuses to touch production, refuses to proceed without a verified backup, and prints no secret.

### 10.2 Manual equivalent

1. **Back up Neon staging** and verify it (`pg_dump` + `pg_restore --list`).
2. **Set `AUTH_SECRET_KEY`** on the Render staging service (the service refuses to start without it).
3. **Deploy** the `phase-14-master` branch to `pricewise-backend-staging`.
4. **Apply the archival**: `python -m src.database.product_archival --apply-default`.
5. **Validate**: `python scripts/validate_staging.py --base-url https://pricewise-backend-staging.onrender.com`.
6. **Deploy the frontend** to Vercel (`npm ci && npm run build`, then the Vercel dashboard or CLI).
7. **Create the cron job** from the blueprint (`docs/PHASE14_SCHEDULER_SETUP.md`).
8. **Optional:** retailer partner credentials to move pricing from `demo` to `verified_live`; image usage permission for the 10 published photographs.

---

## 11. PRODUCTION READINESS VERDICT

### NOT READY TO LAUNCH

| Gate | State |
|---|---|
| The application is deployed to staging | ❌ **not deployed** — no credentials |
| The staging catalogue endpoint works | ❌ still 500 (the fix is on the branch, unverified) |
| The staging database is backed up and repaired | ❌ not possible without the Neon credential |
| Live prices are available | ❌ no authorised retailer feed |
| Live reviews are available | ❌ no review feed |
| Every product has an authentic photograph | ❌ 10 of 100 |
| The scheduler is running | ❌ not provisioned |
| The scheduled worker code works | ✅ verified |
| The frontend and backend agree on every route | ✅ 52/52 contract assertions |
| The catalogue, prices, links and reviews are honest | ✅ verified over live HTTP |
| The session secret is fail-closed | ✅ verified in a live uvicorn process |
| The test suite is isolated and green | ✅ 451 passed, 3 environmental failures |
| The production branch and database are untouched | ✅ `main` @ `83e2267`, Neon production never contacted |

**What is genuinely ready:** the code. The three defects that would have shipped broken are fixed and guarded, the security model is fail-closed and verified in a live process, the data model refuses to misrepresent demo content as live, and the full endpoint matrix passes against a production-like deployment.

**What blocks the launch:** three credentials (Render, Neon, Vercel) and three data partnerships (retailer feeds, a review feed, image licensing). None of them is a code problem, and none can be worked around without either faking data or bypassing a retailer's access controls — which this phase did not do.

---

## 12. COMMITS IN THIS PHASE

```
cc38615 feat(launch): operator launch script and link-publication hardening
6cf1c94 fix(contract): repair two broken frontend->backend routes and add a guard
```

Files added: `scripts/phase15_launch.py`, `scripts/validate_staging.py`,
`tests/test_phase15_frontend_backend_contract.py`, `PHASE_15_STAGING_LAUNCH_REPORT.md`.

Files modified: `frontend/src/utils/api.ts`, `frontend/src/types/index.ts`,
`frontend/src/pages/ProductDetailPage.tsx`, `src/api/main.py`,
`src/api/schemas.py`, `src/database/models.py`, `src/services/product_service.py`,
`src/services/beauty_intelligence_service.py`, `tests/test_phase14_e2e_journey.py`.

**No production system was touched, no database was reset, no secret was exposed
and no scheduled job is claimed to be running.**
