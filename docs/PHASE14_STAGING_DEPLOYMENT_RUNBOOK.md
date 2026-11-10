# Phase 14 — Staging Deployment Runbook

**Target:** the Render staging backend `pricewise-backend-staging`
(`srv-dbp341c9v7es73aeses0`) and the Neon **staging** branch
`br-aged-glade-bbyyq4r7` of the Neon project *Price-wise* (`snowy-band-65160750`).

> **The production branch `br-icy-dawn-bbx1y0jx` must never be touched by this
> runbook.** Every command below targets the staging branch explicitly.

The code for this deployment is on the branch **`phase-14-master`**
(remote: `origin/phase-14-master`). The branch has been pushed; nothing has been
merged into `main` and **no deploy has been triggered**.

---

## 0. Why this is a manual runbook

This runbook exists because the deployment requires credentials that are not
available in the build environment:

| Credential | Status | Needed for |
|---|---|---|
| `RENDER_API_KEY` | not present | Creating / deploying the service, reading its configuration |
| `DATABASE_URL` (Neon staging) | not present | The `pg_dump` backup and the verification queries |
| `NEON_API_KEY` | not present | Branch administration |
| `VERCEL_TOKEN` | not present | The frontend deployment |

Everything below is therefore an **operator action**. Each step states exactly
what to run and what a correct result looks like.

---

## 1. Back up the Neon staging database (do this first)

```bash
# 1. Confirm you are on the STAGING branch, not production.
export DATABASE_URL='postgresql://<user>:<password>@<staging-host>/<db>?sslmode=require'

psql "$DATABASE_URL" -c "SELECT current_database(), inet_server_addr();"
# -> the host must be the staging branch host (br-aged-glade-bbyyq4r7),
#    never the production branch host (br-icy-dawn-bbx1y0jx).

# 2. Record the pre-change counts.
psql "$DATABASE_URL" -c "
  SELECT 'products' t, count(*) FROM products
  UNION ALL SELECT 'offers', count(*) FROM offers
  UNION ALL SELECT 'price_history', count(*) FROM price_history
  UNION ALL SELECT 'stores', count(*) FROM stores
  UNION ALL SELECT 'users', count(*) FROM users;"

# 3. Take the backup.
pg_dump "$DATABASE_URL" --format=custom \
  --file "pricewise_staging_pre_phase14_$(date +%Y%m%d_%H%M%S).dump"

# 4. Verify the backup is readable and complete.
pg_restore --list "pricewise_staging_pre_phase14_<timestamp>.dump" | tail -5
sha256sum "pricewise_staging_pre_phase14_<timestamp>.dump"
```

**Stop here if the backup cannot be verified.** A `pg_restore --list` that
errors, or a dump that does not contain the `products` and `offers` tables, is
not a usable backup.

---

## 2. Configure the session signing secret

The backend **refuses to start** in the `staging` environment without a session
secret — that is deliberate (Phase 14 Stage 2.5, FIX 1).

1. Render dashboard → `pricewise-backend-staging` → **Environment** → **Add**.
2. Key: `AUTH_SECRET_KEY`
3. Value: a fresh random secret.

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

4. Also confirm `SECRET_KEY` is present (it is the legacy alias and keeps the
   service running until the canonical variable is added).
5. Confirm `ENVIRONMENT=staging` and `DATABASE_URL` are set.

> **Rotation semantics:** changing `AUTH_SECRET_KEY` invalidates every issued
> session token. Every staging user must sign in again.

---

## 3. Deploy the backend

**Option A — from the branch (recommended for this rollout)**

1. Render → `pricewise-backend-staging` → **Settings** → **Build & Deploy**.
2. Set the branch to `phase-14-master`.
3. Leave **Auto-Deploy** off for now, or on if you want every push deployed.
4. **Deploy now** / **Save & Deploy**.

**Option B — merge the branch into `main`**

```bash
git checkout main
git merge --no-ff phase-14-master -m "Phase 14 master: staging recovery"
git push origin main
```

The Render blueprint tracks the repository's default branch, so merging to
`main` is what the blueprint will deploy.

**What happens on the first start after this deploy**

| Step | Result |
|---|---|
| `validate_session_secret_configuration()` | Raises `MissingSessionSecretError` if the secret is missing → the service refuses to start. Set the secret first. |
| `migrate_db()` | Applies the additive Phase 14 migrations to Neon: `products.is_active`, the four `products.image_*` columns, `offers.link_status`, `offers.link_checked_at`, `users.is_admin`, `users.token_version`, plus the two indexes. |
| Archive the legacy demo rows | **Not** automatic — archival is business data. Run step 4. |

---

## 4. Apply the archival to Neon staging (explicit business data)

The legacy electronics rows (ids 1-11) and the two test fixtures (998, 999)
must be archived explicitly. On the staging branch this is:

```bash
# Apply the explicit archival set (idempotent).
python -m src.database.product_archival --apply-default

# Verify.
python -m src.database.product_archival --summary
```

Expected: `archived_count` = 13, `active_count` = 100 (or the staging
equivalent), `archived_ids` = `[1..11, 998, 999]`.

The equivalent SQL, if you prefer to run it by hand:

```bash
psql "$DATABASE_URL" -f data/migrations/001_add_is_active_to_products.sql
```

---

## 5. Verify the deployment

```bash
BASE=https://pricewise-backend-staging.onrender.com

curl -s $BASE/api/health/live     # {"status":"alive"}
curl -s $BASE/api/health/ready    # {"status":"ready","database_engine":"postgresql",...}
curl -s $BASE/api/products | head -c 400
```

| Check | Expected |
|---|---|
| `/api/health/live` | `200 {"status":"alive"}` |
| `/api/health/ready` | `200 {"status":"ready","database_engine":"postgresql"}` |
| `/api/products` | **`200`** with 100 products (this was the `500` before the deploy) |
| `/api/products` payload | every product has `is_active: true`; the legacy electronics records are absent |
| `/api/products/{slug}` for a legacy id | `404` |
| `/api/auth/register` + `/api/auth/login` | `200`, a `session_token` cookie is issued |
| `/api/products/{id}/price-history` | `200` with `is_simulated` and per-point `data_status` |
| `/api/products/{id}/deal-intelligence` | `200` with a `factors` array |
| `/api/products/{id}/reviews` | `200` with an explicit `empty_state` (no retailer feed is connected) |
| `X-RateLimit-Limit` header | present on API responses |

---

## 6. Deploy the frontend

The frontend is a static Vite build deployed on Vercel.

```bash
cd frontend
npm ci
npm run build          # tsc -b && vite build
npx vercel --prod --token "$VERCEL_TOKEN"   # or trigger the Vercel dashboard build
```

`frontend/.env.production` already points at the staging backend:

```
VITE_API_URL=https://pricewise-backend-staging.onrender.com
VITE_API_BASE_URL=https://pricewise-backend-staging.onrender.com
```

---

## 7. Enable the scheduled worker (optional but recommended)

`render.yaml` declares a **Render Cron Job** service
(`pricewise-scheduler-staging`, every 30 minutes, running
`python -m src.workers.scheduler --once`). Apply the blueprint or create it by
hand, then set its `DATABASE_URL` and `AUTH_SECRET_KEY` to the same values as
the web service. Full details: `docs/PHASE14_SCHEDULER_SETUP.md`.

---

## 8. Rollback

```bash
# 1. Point Render back at the previous branch/commit and deploy.
# 2. Restore the database if the schema needs to be reverted:
pg_restore --clean --if-exists --dbname "$DATABASE_URL" \
  "pricewise_staging_pre_phase14_<timestamp>.dump"
```

Every Phase 14 schema change is additive (new columns and indexes only), so a
code rollback alone is normally sufficient; the database restore is only needed
if the data itself must be reverted.
