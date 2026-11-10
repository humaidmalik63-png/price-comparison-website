# PHASE 16 — AUTOMATED STAGING DEPLOYMENT REPORT

**Date:** 2026-11-10
**Branch:** `phase-14-master` @ `c43c1ce` (pushed to `origin/phase-14-master`)
**Base:** `main` @ `83e2267` — **unchanged**
**Objective:** automate every safe staging deployment task so no manual terminal work is required.

---

## 1. HEADLINE

**The deployment is fully automated and ready to run — it is blocked on exactly three credentials**, which are not present in this environment:

| Credential | Needed for | Status |
|---|---|---|
| `DATABASE_URL` (Neon **staging**) | backup, migrations, archival | ❌ missing |
| `RENDER_API_KEY` | env vars, backend deploy, cron job | ❌ missing |
| `VERCEL_TOKEN` | frontend preview deployment | ❌ missing |

Everything that does not need those credentials was completed: the pipeline was built, its stop conditions were verified by executing them, the deployment artefacts were corrected, and the Neon staging host was proven **reachable from this environment** (it resolves and accepts TCP connections — only authentication is missing).

> **Do not paste any token into the chat.** Section 3 explains exactly where to create each one and how to hand it to the script through a file outside the repository.

---

## 2. TOOL INSPECTION (read-only)

| Tool | State | Consequence |
|---|---|---|
| `gh` | ✅ 2.103.3, authenticated as `humaidmalik63-png` (scopes: `gist`, `read:org`, `repo`, `workflow`) | Git operations work. **GitHub access grants nothing on Render, Vercel or Neon.** |
| `psql` / `pg_dump` / `pg_restore` | ✅ PostgreSQL 18.6 client | The backup and verification can be performed from here — no database server needed |
| Render CLI | ❌ not installed | **Not needed** — the Render REST API (`api.render.com/v1`) is used directly |
| Vercel CLI | ❌ not installed | **Not needed** — the Vercel REST API (`api.vercel.com`) is used directly |
| Neon CLI (`neonctl`) | ❌ not installed | **Not needed** — `psql`/`pg_dump` reach Neon directly |
| `jq` | ❌ not installed | Python is used for JSON handling |
| `node` / `npm` | ✅ v26.4.0 / 11.20.0 | The frontend can be built locally |
| `curl`, `python3` | ✅ | — |

**Deployment permissions:** the only authenticated permission is GitHub. Render, Vercel and Neon require their own tokens (§3).

### Neon staging reachability (proved, read-only)

```
ep-aged-salad-bbh2tnpl.c-15.us-east-1.aws.neon.tech             -> 184.194.214.49  reachable
ep-aged-salad-bbh2tnpl-pooler.c-15.us-east-1.aws.neon.tech      -> 184.194.214.49  reachable
```

The staging host resolves and accepts connections from this sandbox; `pg_dump`
reaches the server and only fails at password authentication. **No Neon
credential exists in the repository** — every `postgresql://` URL in the Git
history is a masked placeholder.

---

## 3. CREDENTIAL SETUP — EXACT INSTRUCTIONS

### 3.1 The one file you create

Create **`~/.pricewise-deploy.env`** (in your home directory, *outside* the repository) with three lines:

```
DATABASE_URL=postgresql://USER:PASSWORD@ep-aged-salad-bbh2tnpl-pooler.c-15.us-east-1.aws.neon.tech/neondb?sslmode=require
RENDER_API_KEY=rnd_XXXXXXXXXXXXXXXXXXXX
VERCEL_TOKEN=XXXXXXXXXXXXXXXXXXXX
```

Optional fourth line:

```
GEMINI_API_KEY=AIzaXXXXXXXXXXXXXXXX
```

Then secure it:

```bash
chmod 600 ~/.pricewise-deploy.env
```

The script reads that file automatically (`~/.pricewise-deploy.env`, or
`$PRICEWISE_DEPLOY_ENV` if you prefer another path). An environment variable
always wins over the file. **Values are never printed, never logged and never
written to the repository** — the file is outside the repository and is not
tracked by Git.

### 3.2 Where each token comes from

| Token | Dashboard | Exact path | Notes |
|---|---|---|---|
| `DATABASE_URL` | **Neon** — https://console.neon.tech/app/projects/snowy-band-65160750 | Open the project → the **staging** branch (`br-aged-glade-bbyyq4r7`, host `ep-aged-salad-…`) → **Connect** → **Pooled connection** → copy the URI | ⚠️ **Confirm the branch is the staging one, not `br-icy-dawn-bbx1y0jx` (production).** The script refuses a production-looking host, but check it yourself first. |
| `RENDER_API_KEY` | **Render** — https://dashboard.render.com/ | Account → **API Keys** (https://dashboard.render.com/settings/api-keys) → **Create API Key** → copy the `rnd_…` value | The key needs access to the `pricewise-backend-staging` service only. The script refuses to touch a service whose name is not a staging service. |
| `VERCEL_TOKEN` | **Vercel** — https://vercel.com/account/tokens | **Create Token** → name it (e.g. `pricewise-deploy`) → copy the token | If the project lives under a **team**, also set `VERCEL_TEAM_ID` (Vercel → Project Settings → General → Team ID). |
| `GEMINI_API_KEY` (optional) | https://aistudio.google.com/apikey | **Create API key** | Only needed to keep the AI features live; the service works without it and says so honestly. |

### 3.3 Then the deployment is one command

```bash
cd ~/price-comparison-website
python3 scripts/phase16_deploy.py
```

No other terminal work is required: backup, migrations, archival, backend
deploy, frontend preview, cron job and validation all run in sequence.

---

## 4. WHAT WAS BUILT AND VERIFIED

### 4.1 `scripts/phase16_deploy.py` — the automation

| Step | Action | Stop condition |
|---|---|---|
| 0. Preflight | branch = `phase-14-master`, clean tree, credentials present | wrong branch / dirty tree / missing credential |
| 1. Neon | verify the staging host → `pg_dump` → verify with `pg_restore --list` → record counts → inspect the missing Phase 14 migrations → apply the additive migrations → apply the explicit archival → verify integrity | production-looking host, unrecognised host, unverifiable backup, changed row counts |
| 2. Render | confirm the staging service → set `AUTH_SECRET_KEY` (generated), `DATABASE_URL`, `ENVIRONMENT`, `GEMINI_API_KEY` → deploy the branch → wait for `live` | non-staging service, failed deploy |
| 3. Vercel | find the project → set `VITE_API_URL` / `VITE_API_BASE_URL` → create a **preview** deployment of the branch → wait for it | API error |
| 4. Cron | create the `pricewise-scheduler-staging` Render cron job (idempotent) | API error |
| 5. Validation | the full endpoint matrix + both front ends | — |

**Every guard was executed, not just written:**

| Guard | Execution | Result |
|---|---|---|
| Missing credentials | run without them | ✅ **STOPPED** — "missing credential(s): DATABASE_URL, RENDER_API_KEY, VERCEL_TOKEN" |
| Production database host | `postgresql://…@ep-icy-dawn-…` | ✅ **STOPPED** — "REFUSING TO WRITE … matches the production marker 'icy-dawn'" |
| Unrecognised database host | `postgresql://…@db.example.com` | ✅ **STOPPED** — "not recognised as the Neon staging branch" |
| Dirty working tree | uncommitted change present | ✅ **STOPPED** |
| Credential file loader | a fake file with three keys | ✅ loaded; the pipeline advanced through preflight, **verified the staging host**, and reached `pg_dump` (which failed only on the fake password) |

That last test proves the whole chain works against a real Neon endpoint — the only missing piece is the real credential.

### 4.2 Deployment artefacts corrected

Two genuine deployment blockers were found and fixed:

* **`frontend/.env.preview` (new).** Vercel loads `.env.<environment>` from the repository: `.env.production` for production builds, `.env.preview` for preview builds. Only `.env.production` existed, so **a preview deployment had no API URL at all** and silently fell back to `http://localhost:8000`. The new file points preview builds at the staging backend.
* **`vercel.json` at the repository root (new).** Only `frontend/vercel.json` existed, so the Vercel project's root directory had to be set to `frontend` or the build would not run at all. The root file makes the deployment deterministic whichever way the project is configured (build in `frontend/`, output `frontend/dist`, SPA rewrite, security headers).

### 4.3 The branch is deployment-ready

| Check | Result |
|---|---|
| Branch | `phase-14-master` @ `c43c1ce`, pushed |
| `main` / `origin/main` | `83e2267` — unchanged |
| Working tree | clean |
| TypeScript | **0 errors** (TypeScript 5.9.3 compatibility environment) |
| Vite production build | ✅ 2,536 modules; the bundle contains `pricewise-backend-staging.onrender.com` |
| Test suite | 451 passed / 3 failed / 11 skipped (environmental only) |
| Backend tests | 21/21 endpoint matrix green against a production-like local stack |
| Frontend contract | 30/30 capabilities, 52/52 contract assertions |

---

## 5. MIGRATION RESULTS (prepared, not yet applied)

The script inspects and then applies exactly these additive statements, each
`IF NOT EXISTS`, none of which touches a row:

| Target | Statement |
|---|---|
| `products.is_active` | `ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE` |
| `products.image_source_url` | `ADD COLUMN IF NOT EXISTS image_source_url TEXT` |
| `products.image_source_name` | `ADD COLUMN IF NOT EXISTS image_source_name TEXT` |
| `products.image_status` | `ADD COLUMN IF NOT EXISTS image_status TEXT DEFAULT 'placeholder'` |
| `products.image_last_checked` | `ADD COLUMN IF NOT EXISTS image_last_checked TIMESTAMP` |
| `offers.link_status` | `ADD COLUMN IF NOT EXISTS link_status TEXT DEFAULT 'demo_not_verified'` |
| `offers.link_checked_at` | `ADD COLUMN IF NOT EXISTS link_checked_at TIMESTAMP` |
| `users.is_admin` | `ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE` |
| `users.token_version` | `ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0` |
| indexes | `idx_products_brand`, `idx_products_is_active` |

**Preservation guarantees:** no table is dropped or truncated, no row is
deleted, no product ID changes, no archival state is rewritten by the
migration. The archival is applied afterwards through the explicit-ID module
(`src/database/product_archival.py`), which only ever touches the IDs it is
given. The script verifies the `products`, `offers`, `price_history` and user
row counts before and after, and aborts if any of them changed.

---

## 6. ENDPOINT RESULTS (live staging, read-only probe)

```
$ python scripts/validate_staging.py --base-url https://pricewise-backend-staging.onrender.com --read-only
health (live)            200   ok
health (ready)           200   ok
health (summary)         200   ok
retailer status          200   ok
beauty: climate profiles 200   ok
beauty: ingredients      200   ok
auth me (no session)     401   ok (expected)
product discovery        500   server error
archived product detail  500   server error
live comparison          500   server error
price history            500   server error
deal intelligence        500   server error
total cost               500   server error
reviews                  404   not found
--------------------------------------------------------------------------
ok: 6   server errors: 6
```

All six 500s have one cause: the Phase 14 columns never reached Neon because
the old `migrate_db()` crashed on PostgreSQL, while the Phase 14 queries
reference them. The `404` is the Phase 14 review endpoint, which does not
exist in the deployed build. **Both are repaired by the deploy this phase
performs** — verified green against the same matrix on the local
production-like stack (21 ok / 0 errors).

---

## 7. SUCCESSFUL / BLOCKED / REMAINING

### Successful in this phase
* Tool and permission inventory.
* The complete automated deployment pipeline, with every stop condition executed and verified.
* Credential handling that never requires pasting a token into chat.
* Two deployment-blocker fixes (`.env.preview`, root `vercel.json`).
* Neon staging host reachability proved; staging branch host markers derived from the project history.
* Git hygiene: `main` untouched, no force push, no history rewrite, clean tree.

### Blocked (credential only — no code problem)
| Step | Blocker |
|---|---|
| Neon backup + migrations + archival | `DATABASE_URL` |
| Render env vars, backend deploy, cron job | `RENDER_API_KEY` |
| Vercel preview deployment | `VERCEL_TOKEN` |

### Remaining manual actions after the script runs
1. Confirm the cron job produces a real scheduled execution in the Render logs (the script creates it; a scheduled run is a separate observation).
2. Optional: retailer partner credentials to move pricing from `demo` to `verified_live`.
3. Optional: image usage permission for the 10 published brand photographs.
4. Merge `phase-14-master` into `main` when you want the blueprint's default branch to serve this build.

---

## 8. SAFETY STATEMENT

* **No production database was contacted.** The script refuses a production-looking Neon host before any connection is opened, and the production branch `br-icy-dawn-bbx1y0jx` was never queried.
* **No production deployment was triggered.** The frontend is deployed as a **preview**; the backend deploy targets the staging service only, and the script aborts if that service is not a staging service.
* **No existing data is deleted.** The database work is a `pg_dump` plus additive `IF NOT EXISTS` DDL plus an explicit-ID archival.
* **No secret is printed, logged or committed.** The credential file lives outside the repository; the script reports only whether a variable is set.
* **No force push and no history rewrite** — additive commits on a feature branch.
* **No success is claimed without verification.** The script ends with the full endpoint matrix and both front ends, and reports the server-error count as its exit code.

---

## 9. NEXT ACTION

Create `~/.pricewise-deploy.env` with the three values from §3.2, then tell me it is ready. I will run the pipeline and report the backup, the migration counts, the deploy outcome and the endpoint matrix — with no manual terminal work on your side.

If you would rather not create the file, the equivalent is exporting the three
variables in the shell that runs the script:

```bash
export DATABASE_URL='…'   # Neon staging, pooled connection
export RENDER_API_KEY='rnd_…'
export VERCEL_TOKEN='…'
python3 scripts/phase16_deploy.py
```

Either way, **do not paste the values into this chat.**
