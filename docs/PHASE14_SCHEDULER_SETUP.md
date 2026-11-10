# Phase 14 Stage E — Scheduled Maintenance Worker Setup

The PriceWise AI catalogue needs recurring maintenance that a request/response
API must not perform inline:

| Job | What it does | Why it cannot run inside a request |
|---|---|---|
| **Price refresh** | Re-checks tracked / watched products through the retailer adapters and records the outcome in `price_check_logs`. | Network I/O to third-party sites with rate limits; must never block a shopper's request. |
| **Alert evaluation** | Applies the target-price and meaningful-drop rules to every active price-tracking record. | Needs to run even when nobody has the site open. |
| **Expired deal cleanup** | Retires stale alerts and prunes old live price-check evidence. | Housekeeping; no user is waiting for it. |

The worker implementation lives in `src/workers/scheduler.py`.

---

## 1. Run it manually

```bash
# One full cycle (recommended for a cron scheduler)
python -m src.workers.scheduler --once

# Only evaluate alerts and clean up - no outbound retailer traffic
python -m src.workers.scheduler --once --skip-refresh

# Bound the amount of retailer traffic per cycle
python -m src.workers.scheduler --once --limit 10

# Long-running worker loop (for a dedicated worker service)
python -m src.workers.scheduler --interval 1800
```

The command prints a JSON summary of the cycle:

```json
{
  "refresh": { "products_considered": 3, "prices_updated": 0, "unavailable": 3 },
  "alerts":  { "records_evaluated": 2, "alerts_created": 1 },
  "cleanup": { "alerts_expired": 0, "logs_pruned": 12 }
}
```

---

## 2. Enable it on Render (recommended architecture)

`render.yaml` already declares a **Render Cron Job** service:

```yaml
  - type: cron
    name: pricewise-scheduler-staging
    runtime: python
    buildCommand: pip install -r requirements.txt
    schedule: "*/30 * * * *"
    region: frankfurt
    envVars:
      - key: ENVIRONMENT
        value: staging
      - key: DATABASE_URL
        sync: false
      - key: AUTH_SECRET_KEY
        sync: false
    command: python -m src.workers.scheduler --once
```

### Manual activation steps

1. Open the Render dashboard → the Blueprint for this repository.
2. Confirm the new `pricewise-scheduler-staging` cron service appears.
3. Set its environment variables (the blueprint marks them `sync: false`):
   * `DATABASE_URL` — the **same** Neon connection string as the web service.
   * `AUTH_SECRET_KEY` — the same value as the web service (it is required in
     the `staging` environment; the worker refuses to start without it).
   * `GEMINI_API_KEY` — only needed if the worker is extended to refresh
     AI-derived attributes; it is not used for price collection.
4. Apply the blueprint, or create the cron job manually:
   * **New → Cron Job**
   * Repository: this repository, Branch: `main` (or the branch you deploy)
   * Runtime: Python
   * Build Command: `pip install -r requirements.txt`
   * Schedule: `*/30 * * * *`
   * Command: `python -m src.workers.scheduler --once`
5. Trigger a manual run from the Render cron job dashboard and confirm the JSON
   summary appears in the logs.

> **The cron job is not created automatically by this repository.** Applying
> the blueprint (or creating the service by hand) is a deliberate operator
> action, because it provisions a billable resource and connects it to the
> staging database.

---

## 3. Behaviour when no retailer credentials are configured

This is the default state. The adapters are credential-gated, so a refresh
attempt returns an explicit outcome rather than a price:

| Outcome | Meaning | Effect on the catalogue |
|---|---|---|
| `retrieved` | An authorised source returned a price for this exact product. | The price and a `price_check_logs` row are stored. |
| `unavailable` | The retailer could not be reached or the page could not be parsed. | Nothing is changed; the outcome is logged. |
| `restricted` | The retailer blocked the request (bot protection / access restriction). | Nothing is changed. The worker **never** attempts to bypass a block. |
| `unsupported` | No integration is configured for this retailer. | Nothing is changed. |

The worker **never** interpolates, extrapolates or invents a price, and it
never labels demo pricing as live.

---

## 4. Operational notes

* **Region and database:** the cron job must run in the same region as the
  Neon database to avoid cross-region latency (both are `frankfurt`).
* **Overlap:** Render does not start a new cron run while the previous one is
  still running, so a slow cycle cannot pile up.
* **Idempotency:** every cycle is safe to re-run. Alert evaluation uses the
  existing `trigger_key` uniqueness constraint, so re-evaluating an unchanged
  price does not create duplicate alerts.
* **Rate limits:** the collection engine honours the per-retailer rate limits
  and trips its circuit breaker on a perimeter block.
* **Observability:** the JSON summary is printed to stdout and captured in the
  Render cron job logs. `price_check_logs` provides the per-product audit
  trail.
