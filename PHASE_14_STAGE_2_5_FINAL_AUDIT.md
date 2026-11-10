# PHASE 14 STAGE 2.5 — FINAL INDEPENDENT AUDIT

**Audit date:** 2026-11-10
**Audited commit:** `474aacd5ac6c369baf53960b9c6b5910749f3d6d`
**Audited branch:** `phase-14-stage-2-5-recovery`
**Auditor scope:** read-only verification of the Stage 2.5 implementation report
**Method:** Git inspection, source reading, runtime probes in isolated temporary databases, read-only HTTP GETs against staging, static analysis of the test suite. No file, database, environment variable or deployment setting was modified by this audit.

---

## 0. AUDIT CONSTRAINTS AND HONEST DISCLOSURES

| Constraint | How it was honoured |
|---|---|
| No file modifications | Only this report was created. `git status --porcelain` was empty before and after. |
| No database modifications | The shared development database was opened **read-only** (`file:...?mode=ro`). All migration behaviour was exercised against **temporary** databases under `$TMPDIR`. |
| No environment-variable changes | No `export` of project variables; only in-process `os.environ` mutation inside throwaway Python processes to prove fail-closed behaviour. |
| No deployment settings | `render.yaml` was read only. No Render/Neon API was called. |
| No archival commands | `python -m src.database.product_archival --apply-default` / `--archive` / `--restore` were **not** executed. The CLI was verified by reading `src/database/product_archival.py`. |
| No Stage 3 work | Nothing outside the two Stage 2.5 fixes was touched. |
| Tests that could modify real data were not executed | The full suite was deliberately **not** re-run (see §9.3). Only 4 of the 6 failing tests were executed; the 2 that `INSERT` into the shared database were skipped by design. |

**One factual correction to the Stage 2.5 report:** it states that the staging backend was unreachable from the recovery environment (curl timeout, `http_code=000`). During this audit the service **was** reachable (`http_code=200`). The Stage 2.5 conclusion still holds — no remote database was modified — but the stated *reason* (unreachable) was transient and is now inaccurate. See Finding F-01.

---

## 1. BRANCH — ✅ PASS

```
$ git branch --show-current
phase-14-stage-2-5-recovery
```

The repository is on the required branch. `git log --graph` confirms the branch topology:

```
* 474aacd (HEAD -> phase-14-stage-2-5-recovery) Phase 14 Stage 2.5: Security and database integrity recovery
* 83e2267 (origin/main, origin/HEAD, main) Phase 14 Stage 2 & 3: ...
```

`git branch -a --contains 474aacd` returns only `phase-14-stage-2-5-recovery`; the commit exists on the feature branch only.

---

## 2. COMMIT EXISTENCE AND CONTENTS — ✅ PASS

```
$ git cat-file -t 474aacd
commit
$ git log -1 --format="commit : %H%nauthor : %an <%ae>%ndate   : %ad%nsubject: %s" 474aacd
commit : 474aacd5ac6c369baf53960b9c6b5910749f3d6d
author : opencode <opencode@local>
date   : Tue Nov 10 16:45:40 2026 +0530
subject: Phase 14 Stage 2.5: Security and database integrity recovery
```

File manifest of `474aacd` (16 files, +1771 / −55) matches the Stage 2.5 report exactly:

| File | Δ | In report? |
|---|---|---|
| `.env.example` | +12 | ✅ |
| `.env.production.example` | +16 | ✅ |
| `.env.staging.example` | +16 | ✅ |
| `PHASE_14_STAGE_2_5_RECOVERY_REPORT.md` | +447 | ✅ |
| `app.py` | +6 | ✅ |
| `data/migrations/001_add_is_active_to_products.sql` | +35 | ✅ |
| `data/migrations/001_rollback_is_active_to_products.sql` | +19 | ✅ |
| `render.yaml` | +11 | ✅ |
| `src/api/main.py` | +36 | ✅ |
| `src/config.py` | +107 | ✅ |
| `src/database/__init__.py` | +6 | ✅ |
| `src/database/connection.py` | +211 | ✅ |
| `src/database/product_archival.py` | +281 | ✅ (new file) |
| `src/services/auth_service.py` | +45 | ✅ |
| `tests/test_phase14_stage2_5_security_and_integrity.py` | +570 | ✅ (new file) |
| `tests/test_phase8e_beauty_intelligence.py` | +8 | ✅ |

`main` and `origin/main` are both still at `83e2267` — **the baseline branch was not advanced**.

---

## 3. WORKING TREE — ✅ PASS

```
$ git status --porcelain
(empty)
$ git status -sb
## phase-14-stage-2-5-recovery
```

No modified, staged or untracked files. The audit itself introduced no repository artefacts (pytest was run with `-p no:cacheprovider` and `PYTHONDONTWRITEBYTECODE=1`).

---

## 4. AUTHENTICATION SECRET RESOLVER — ✅ PASS (4/4)

### 4.1 Production and staging fail safely without `AUTH_SECRET_KEY` — ✅ PASS

`src/config.py` (audited at commit `474aacd`):

```python
SECRET_REQUIRED_ENVIRONMENTS = ("production", "prod", "staging")
...
def _secret_is_required() -> bool:
    current_env = (os.environ.get("ENVIRONMENT") or "development").strip().lower()
    return current_env in SECRET_REQUIRED_ENVIRONMENTS
```

Runtime probe (throwaway process, no DB access):

| Scenario | Result |
|---|---|
| `ENVIRONMENT=production`, no secret → `get_session_secret()` | **PASS** — raises `MissingSessionSecretError` |
| `ENVIRONMENT=production`, no secret → `generate_session_token()` | **PASS** — raises `MissingSessionSecretError` |
| `ENVIRONMENT=production`, no secret → `verify_session_token()` | **PASS** — raises `MissingSessionSecretError` |
| `ENVIRONMENT=staging`, no secret → `get_session_secret()` | **PASS** — raises `MissingSessionSecretError` |

The requirement check is evaluated **dynamically** from the live environment (not from an import-time snapshot), so it cannot be desynchronised from the running environment.

Start-up enforcement was additionally confirmed in the Stage 2.5 run: the FastAPI `lifespan` calls `validate_session_secret_configuration()` before serving, and `app.py` (Streamlit) calls it before rendering. A misconfigured deployment therefore refuses to boot.

### 4.2 The development fallback cannot be reached in production — ✅ PASS

The ephemeral secret is only reachable **after** the `_secret_is_required()` guard raises:

```python
    if _secret_is_required():
        raise MissingSessionSecretError(...)
    global _EPHEMERAL_DEV_SESSION_SECRET
    if _EPHEMERAL_DEV_SESSION_SECRET is None:
        _EPHEMERAL_DEV_SESSION_SECRET = secrets.token_urlsafe(48)
```

Probe result: `ENVIRONMENT=development`, no secret → a 64-character `secrets.token_urlsafe(48)` value, containing no project string, stable within the process. The `production`/`staging` branches return before this code, so the fallback is unreachable there.

> **Residual note (O-01):** the fail-closed behaviour is conditional on `ENVIRONMENT` being set correctly. If a deployment omits `ENVIRONMENT` entirely it is treated as `development` and receives an *ephemeral* (not published) secret — sessions break on every restart, but tokens are not forgeable. `render.yaml` sets `ENVIRONMENT=staging`, so the intended deployment is covered.

### 4.3 Signing and verification use the same resolver — ✅ PASS

Both call sites import and invoke the identical function:

| Purpose | Location | Call |
|---|---|---|
| Signing | `src/services/auth_service.py:393` | `secret = get_session_secret()` |
| Verification | `src/services/auth_service.py:415` | `secret = get_session_secret()` |

Both then compute the signature through the same helper `_sign_payload(payload_b64, secret)` (`auth_service.py:361-369`). No second key source, no separate constant, no independent derivation.

A repository-wide scan for secret material and token-signing primitives returns **only** these sites:

```
src/config.py:29        SECRET_KEY = (os.environ.get("SECRET_KEY") or "").strip()
src/config.py:59        SESSION_SECRET_ENV_VARS = ("AUTH_SECRET_KEY", "SECRET_KEY")
src/config.py:80        def get_session_secret() -> str
src/config.py:108       _EPHEMERAL_DEV_SESSION_SECRET = secrets.token_urlsafe(48)
src/services/auth_service.py:334  from src.config import MissingSessionSecretError, get_session_secret
src/services/auth_service.py:368  hashlib.pbkdf2_hmac(... secret ...)
src/services/auth_service.py:393  secret = get_session_secret()   # sign
src/services/auth_service.py:415  secret = get_session_secret()   # verify
```

There is **no** JWT library, no second HMAC key and no module-level secret constant anywhere else. The two remaining `hashlib.pbkdf2_hmac` calls in `auth_service.py` (lines 38 and 64) belong to **password hashing** (`hash_password` / `verify_password`), which uses a per-password random salt from `secrets.token_bytes(16)` and is unrelated to token signing.

Runtime probes:

| Check | Result |
|---|---|
| Token round-trip with a configured secret | **PASS** — `verify_session_token()` returns the payload |
| Signing and verification resolve to the same secret | **PASS** |
| Rotation invalidates an issued token | **PASS** — a token signed with secret A does not verify under secret B |
| Tampered token rejected | **PASS** (covered by the committed test suite) |
| Expired token rejected | **PASS** (covered by the committed test suite) |

### 4.4 No committed public fallback secret remains — ✅ PASS (functional) / ⚠️ OBSERVATION

**Functional status: PASS.** Neither previously published literal can be used as a fallback:

```
$ git grep -n "pricewise_beauty_super_secret_session_key_2026" 474aacd -- src/ app.py
(no output)
$ git grep -n "pricewise-dev-secret-key-phase12-change-in-prod" 474aacd -- src/ app.py
(no output)
```

There is no `os.getenv(..., <literal>)` fallback anywhere in the signing path.

**Observation O-02 (low severity, non-blocking).** Both literals still appear verbatim in the tracked tree, in two non-executable places:

* `PHASE_14_STAGE_2_5_RECOVERY_REPORT.md` (lines 17, 33, 41) — the root-cause narrative quoting the old code;
* `tests/test_phase14_stage2_5_security_and_integrity.py` (lines 58-59) — the `LEGACY_PUBLIC_SECRETS` list used by the source-scanning guard test.

Neither is a code path, so neither can sign or verify a token. The values remain *known* to anyone with repository access, which means that reintroducing either as a fallback would be immediately exploitable. Optional hardening: assemble the guard literals at runtime (e.g. `"pricewise_beauty_" + "super_secret_session_key_2026"`) so the exact strings no longer appear in the tree. **Not a FAIL** — the audit requirement concerns the *fallback secret*, which is gone.

---

## 5. MIGRATION BEHAVIOUR — ✅ PASS (4/4)

### 5.1 `migrate_db()` does not automatically reactivate archived products — ✅ PASS

Static proof — the migration layer contains **no `is_active` write at all**:

```
$ grep -nE "UPDATE" src/database/connection.py
398:  UPDATE price_alerts          <- legacy Phase 7 user_id backfill (schema migration)

$ grep -n "is_active" src/database/connection.py
211:  if "is_active" not in existing_product_cols:
212:      cursor.execute("ALTER TABLE products ADD COLUMN is_active BOOLEAN DEFAULT 1")
231:  cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active)")
810:  cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
820:  cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active)")
```

Every remaining reference is DDL (column creation / index creation). The previous statements
`UPDATE products SET is_active = 1 WHERE id >= 12 AND id NOT IN (998, 999)` and
`UPDATE products SET is_active = 0 WHERE id <= 11 OR id IN (998, 999)` are gone.

Empirical proof — scratch database (temporary file under `$TMPDIR`), 3 forced migrations:

```
before: {13: 0, 5: 1, 12: 1, 500: 1}
after : {13: 0, 5: 1, 12: 1, 500: 1}
archival preserved through 3 forced migrations : PASS
archived product NOT reactivated (id=13)       : PASS
high-id product NOT reactivated (id=500)       : PASS
low-id product NOT archived (id=5)             : PASS
```

The previously observed defect — `id=500` (above the old threshold) being reactivated — no longer occurs, and `id=5` is no longer archived.

### 5.2 Schema migrations are idempotent — ✅ PASS

* All DDL uses `IF NOT EXISTS` (PostgreSQL path) or a column-existence check before `ALTER TABLE` (SQLite path).
* Probe: column set of `products` is stable across 3 forced re-runs → **PASS**; Phase 14 columns (`is_active`, `image_source_url`, `image_source_name`, `image_status`, `image_last_checked`) present → **PASS**.
* The runner itself is guarded (`_MIGRATION_SIGNATURES`, keyed by SQLite inode or PostgreSQL URL digest). Probe on a scratch DB:

```
after 3 unforced calls : 0   -> PASS   (no DDL on repeat calls)
after 1 forced call    : 1   -> PASS
after 2 forced calls   : 2   -> PASS   (force=True re-runs deliberately)
```

The guard also survives database replacement: the SQLite fingerprint is the file **inode**, which changes when a database file is deleted and recreated, so a replaced database is re-migrated rather than silently skipped.

### 5.3 Archival is controlled through explicit product IDs — ✅ PASS

`src/database/product_archival.py` was scanned for threshold/range logic:

```
$ grep -nE "is_active[[:space:]]*(>|<|>=|<=)|id[[:space:]]*(>|<|>=|<=)[[:space:]]*[0-9]+" src/database/product_archival.py
(no matches)
```

The module issues exactly three SQL statements, all `id IN (...)` bound-parameter form:

```
SELECT id, is_active FROM products WHERE id IN (?, ?, ...)
UPDATE products SET is_active = {0|1|FALSE|TRUE} WHERE id IN (?, ?, ...)
SELECT id, title, is_active FROM products ORDER BY id
```

The archival set is an explicit tuple (`LEGACY_TECH_PRODUCT_IDS` + `LEGACY_TEST_FIXTURE_PRODUCT_IDS`), and the engine-appropriate boolean literal is selected at runtime (`FALSE`/`TRUE` for PostgreSQL, `0`/`1` for SQLite). The same rule was applied to the SQL migration files:

* `data/migrations/001_add_is_active_to_products.sql` — the blanket reactivation was removed; the archival set is an explicit `id IN (...)` list.
* `data/migrations/001_rollback_is_active_to_products.sql` — the blanket `UPDATE products SET is_active = TRUE;` was replaced with an explicit list matching migration 001.

### 5.4 PostgreSQL and SQLite code paths are correctly separated — ✅ PASS

| Concern | SQLite path | PostgreSQL path |
|---|---|---|
| Function | `_migrate_sqlite_schema(custom_path)` | `_migrate_postgres_schema()` |
| Connection | `get_connection(str(db_path))` | `get_connection()` → psycopg/psycopg2 |
| DDL dialect | `PRAGMA table_info`, `CREATE TABLE … AUTOINCREMENT` | `ALTER TABLE … ADD COLUMN IF NOT EXISTS`, `information_schema.tables` |
| Dispatch | `migrate_db()` selects via `get_database_engine_type()` when no `custom_path` is supplied | idem |
| Cross-contamination | SQLite DDL is never replayed against PostgreSQL | PostgreSQL DDL is never replayed against SQLite |

Probe:

```
engine (no DATABASE_URL)   : sqlite
engine (with DATABASE_URL) : postgresql
postgres target key        : postgresql:67dc06057cfeb11b
credentials absent from key: PASS      (the URL is hashed, never logged)
init_db() on PostgreSQL    : PASS - raises RuntimeError with an actionable message
```

`init_db()` explicitly refuses PostgreSQL, because `data/schema.sql` is SQLite-specific (`AUTOINCREMENT`, `PRAGMA`) and `executescript` has no PostgreSQL equivalent.

### 5.5 Migration-runner risk not present in the baseline

Worth recording for context: the pre-Stage-2.5 `migrate_db()` always opened the **SQLite** file while selecting SQL by `get_database_engine_type()`. On a PostgreSQL deployment it therefore executed PostgreSQL-flavoured DDL against SQLite, and `PRAGMA` statements against PostgreSQL. The new engine-aware runner eliminates that class of failure. (Directly relevant to Finding F-01 below.)

---

## 6. MANUAL NEON STAGING INSTRUCTIONS — ✅ PASS (instructions) / ⚠️ NOT VERIFIED (database state)

### 6.1 The instructions match the repository — ✅ PASS

| Instruction in the Stage 2.5 report (§9) | Verified against the repo | Result |
|---|---|---|
| Add `AUTH_SECRET_KEY` to `pricewise-backend-staging` in the Render dashboard | `render.yaml` declares `- key: AUTH_SECRET_KEY` with `sync: false` and a manual-step comment; `SECRET_KEY` (`generateValue: true`) is retained as the legacy alias | ✅ |
| `python -m src.database.product_archival --apply-default` | `src/database/product_archival.py` implements `main()` with `--apply-default`, `--archive`, `--restore`, `--summary`, `--custom-path` | ✅ |
| `psql "$DATABASE_URL" -f data/migrations/001_add_is_active_to_products.sql` | File exists; every statement is PostgreSQL-valid (`ADD COLUMN IF NOT EXISTS … BOOLEAN`, `UPDATE … WHERE id IN (…)`) | ✅ |
| `python -m src.database.product_archival --summary` for verification | `--summary` returns `total_products`, `active_count`, `archived_count`, `active_ids`, `archived_ids` | ✅ |
| `pg_dump "$DATABASE_URL" --format=custom --file …` before deployment | Standard, correct procedure | ✅ |
| `curl …/api/health/ready` post-restart | Endpoint exists and is the configured `healthCheckPath` in `render.yaml` | ✅ |
| "Rotating the secret invalidates all issued sessions" | Verified by runtime probe (§4.3) | ✅ |

No instruction directs an operator to modify the **production** branch; every command targets the staging `DATABASE_URL`.

### 6.2 The Neon staging database state — ⚠️ NOT VERIFIED

No `DATABASE_URL`, Neon credential or Neon API token is present in this environment, and the production branch was not contacted at any point. Therefore:

* the current contents of the Neon staging branch (whether `is_active` / image columns exist) → **NOT VERIFIED** by direct query;
* the current archival state of the Neon staging catalogue → **NOT VERIFIED**;
* whether the Neon staging DB contains the legacy demo rows 1-11 and 998/999 → **NOT VERIFIED**.

### 6.3 Read-only observation of the live staging service

Staging was reachable during this audit, so read-only `GET` probes were performed (no POST, no authentication, no write):

```
GET /api/health/live            → 200  {"status":"alive", ...}
GET /api/health/ready           → 200  {"status":"ready","database_engine":"postgresql",
                                           "database_healthy":true,"product_count":113,
                                           "environment":"staging"}
GET /api/health                 → 200  {"status":"ok","database":"postgresql","record_count":113}
GET /api/prices/retailer-status → 200
GET /api/beauty/climate-profiles→ 200
GET /api/auth/me                → 401  (correct: no credentials supplied)
GET /api/products               → 500  "Internal Server Error"
GET /api/products?category=Serum→ 500  "Internal Server Error"
```

**Finding F-01 — the live staging catalogue endpoint is broken (severity: high, operational).**

The staging service is serving from Neon PostgreSQL with 113 products (matching the local catalogue, so the legacy demo rows are present there), but **every product-listing endpoint returns HTTP 500**, while health, retailer-status and climate-profile endpoints return 200.

The failure is isolated exactly to the queries introduced by Phase 14 Stage 2, which reference the `is_active` column:

* `src/services/product_service.py:115` — `SELECT … p.is_active … FROM products p` (`get_products`)
* `src/services/product_service.py:23` — `SELECT DISTINCT category FROM products WHERE (is_active IS NULL OR is_active = 1)`

This is precisely the consequence predicted by the Stage 2.5 root-cause analysis (§2.2 of that report): the old `migrate_db()` **crashed** on a PostgreSQL deployment (PostgreSQL DDL executed against SQLite), so the Phase 14 columns were never applied to Neon — while the new product queries, introduced by the same Phase 14 work, do reference them. The consequence is a 500 on the catalogue endpoints of the deployed staging service.

The Stage 2.5 engine-aware migration runner (`_migrate_postgres_schema()`) issues exactly the DDL needed to repair this (`ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE` plus the image columns) and will apply it at the next start-up. **This repair is therefore expected but NOT VERIFIED** — it can only be confirmed on staging after deployment, which is out of scope for this audit.

*Recommended (not performed):* before deploying, take the §9.4 `pg_dump` backup; after deploying, confirm `GET /api/products` returns 200 and then run the §9.3 archival step.*

---

## 7. BACKUP EXISTENCE AND CHECKSUM — ✅ PASS

```
$ ls -la data/backups/
-rw------- 1 u0_a217 u0_a217  667648 Nov 10 16:24 pricewise_pre_stage2_5_backup_20261110_162428.db
```

| Attribute | Recorded in the Stage 2.5 report | Independently recomputed | Match |
|---|---|---|---|
| Path | `data/backups/pricewise_pre_stage2_5_backup_20261110_162428.db` | present | ✅ |
| Size (bytes) | 667,648 | 667,648 | ✅ |
| SHA-256 | `1808bd7438707ed2eac2ea6f3dc4172cc67b028163184310cfc3fc3839995970` | `1808bd7438707ed2eac2ea6f3dc4172cc67b028163184310cfc3fc3839995970` | ✅ **exact** |

The backup is correctly excluded from version control:

```
$ git check-ignore -v data/backups/pricewise_pre_stage2_5_backup_20261110_162428.db
.gitignore:51:data/backups/   data/backups/pricewise_pre_stage2_5_backup_20261110_162428.db
$ git ls-files data/backups | wc -l
0
```

**Observation O-03:** the directory also contains three additional backup artefacts (`pricewise_backup_20261110_164001.db`, `…_164138.db`, `…_164259.db` with matching `.sha256` files). These were created during the **Stage 2.5** test run by `tests/test_phase12_production_security.py`, which imports `scripts.backup_restore_db.py`; that module writes real files into `data/backups/`. They are git-ignored and harmless, but they are another instance of the test suite writing into the working tree (see §8, Finding O-04).

---

## 8. TEST ISOLATION — ✅ PASS (issue identified) / ⚠️ findings

### 8.1 Which tests modify the shared development database

Every test module was scanned with a call-expression parser (not a naive line grep, so multi-line calls were classified correctly). Result: **four modules write to the shared database `data/pricewise.db`**, and one module executes DDL against it.

| Module | Shared-DB writes | Mechanism |
|---|---|---|
| `tests/test_phase7_api_and_services.py` | **21** HTTP write verbs | `TestClient` POST/PUT/DELETE against the FastAPI app, which resolves the default database path internally. Observed effect: 21 `users`, 21 `user_preferences`, 6 `user_profiles`, 3 `wishlist` rows created during the Stage 2.5 run. |
| `tests/test_phase9_price_intelligence.py` | **9** | `register_user()` ×2, `add_tracked_product()` ×4, `remove_tracking()` ×3 — all without `custom_path`; plus `get_connection()` (no path) at line 228. |
| `tests/test_phase8e_beauty_intelligence.py` | **4** | `INSERT OR REPLACE INTO products` (lines 39, 132) and `INSERT OR REPLACE INTO offers` (lines 46, 137), plus 8 `get_connection()` calls (no path). **This module is the one that un-archived products 998/999** before Stage 2.5 fixed it by setting `is_active = 0` explicitly. |
| `tests/test_phase11b_hybrid_intelligence.py` | **3** | `record_evidence_reference()` (line 372), `approve_manual_verification()` (line 410), `INSERT INTO manual_verification_requests` (line 401). **This module is the source of the two remaining test failures** (hardcoded `user_id=1` / `uploaded_by=1`). |
| `tests/test_phase14_stage2_database_recovery.py` | DDL only | An autouse fixture calls `migrate_db()` against the shared database. After Stage 2.5 this is schema-only and idempotent (no business-data effect), but it still opens a write transaction on the shared file. |

Modules that are **already correctly isolated** (verified by the refined scan — all writes carry `custom_path=`): `test_phase2_*`, `test_phase3_product_pages_and_tracking.py`, `test_phase4_reviews_and_intelligence.py`, `test_phase5_*`, `test_phase6_price_tracking.py`, `test_phase7_auth.py`, `test_phase7_wishlist.py`, `test_phase8_integration.py`, `test_phase12_1_postgres_staging.py`, `test_phase14_stage2_5_security_and_integrity.py` (scratch databases under `tmp_path`).

Modules that are **read-only** against the shared database: `test_phase11c_expanded_catalog.py` (5 × `get_connection()`), `test_phase6_live_price_engine.py`, `test_phase6a_foundation.py`, `test_phase12_production_security.py` (reads `data/pricewise.db` to generate DDL).

### 8.2 Can they run against temporary test databases? — YES

**There is no `conftest.py` anywhere in the repository** — confirmed:

```
$ ls tests/conftest.py conftest.py
ls: cannot access 'tests/conftest.py': No such file or directory
ls: cannot access 'conftest.py': No such file or directory
```

That absence is the root cause of the shared-database pollution: there is no session-level redirect of the default database path.

A single change would isolate **all five** offenders at once, because the default path is resolved from one environment variable at import time:

```python
# src/config.py:11
DATABASE_PATH = os.environ.get("PRICEWISE_DB_PATH", str(DATA_DIR / "pricewise.db"))
```

and is consumed in exactly three places:

```
src/database/connection.py:121   get_db_path()      -> Path(custom_path) if custom_path else Path(DATABASE_PATH)
src/database/connection.py:773   _migration_target_key()
src/database/connection.py:788   _migration_signature()
app.py:52                         Path(DATABASE_PATH)
```

**Recommended remedy (not applied — audit is read-only):** add `tests/conftest.py` that, at import time (before any test module imports `src.config`), sets `PRICEWISE_DB_PATH` to a temporary copy of `data/pricewise.db`. pytest imports `conftest.py` before test modules, so `src.config` resolves the temporary path for every default-path access — including the FastAPI `TestClient` used by `test_phase7_api_and_services.py`, which cannot be redirected per call. Copying the live file preserves every read expectation (113 products, 494 offers, 1,360 price-history rows) while confining all writes to the temporary copy.

A per-module alternative also exists for the service-level offenders (`custom_path` is already supported and used by the isolated modules), but it does not cover the `TestClient` module, so the `conftest.py` redirect is the higher-leverage fix.

**Observation O-04:** `tests/test_phase12_production_security.py` also writes real backup files into `data/backups/` during a run (Finding O-03). A `conftest.py` redirect does not cover filesystem artefacts; that module should use a temporary backup directory.

### 8.3 Independent confirmation that the failures are order-dependent

The two `test_phase11b` failures are a direct consequence of §8.1: the module hardcodes `user_id = 1` / `uploaded_by = 1`, and only passes when another module (e.g. `test_phase7_api_and_services.py`) has already created that user in the shared database. On a clean shared database — the state the working copy is in now (0 users) — the foreign key constraint fails. This is a pre-existing test-design defect, **not** a product defect and **not** a Stage 2.5 regression.

---

## 9. THE SIX TEST FAILURES AND THE BASELINE COMPARISON — ✅ PASS

### 9.1 The failing tests are untouched by the audited commit — ✅ PASS

```
$ git diff --numstat 83e2267 474aacd -- tests/test_phase11b_hybrid_intelligence.py | wc -l   -> 0
$ git diff --numstat 83e2267 474aacd -- tests/test_phase6_live_price_engine.py   | wc -l   -> 0
$ git diff --numstat 83e2267 474aacd -- tests/test_phase6a_foundation.py          | wc -l   -> 0
```

The three files containing all six failures are **byte-identical** between the baseline commit (`83e2267`) and the audited commit (`474aacd`). The commit's only test-tree changes are the new Stage 2.5 test module (+570) and the 4-line `is_active = 0` correction in `test_phase8e_beauty_intelligence.py`.

Consequently the six failures must reproduce identically on the baseline, which is exactly what the Stage 2.5 report recorded (**331 passed / 7 failed / 11 skipped** baseline vs **360 passed / 6 failed / 11 skipped** with the fix; the delta is +28 new tests plus one order-dependent flake that flips to passing).

### 9.2 Failure causes — 4 re-executed, 2 confirmed statically

| # | Failing test | Cause | Verification method | Result |
|---|---|---|---|---|
| 1 | `test_phase6a_foundation.py::TestDatabaseIntegrity::test_backup_file_exists` | Asserts `data/pricewise.db.backup_phase6a` exists; that file has never existed in the repository (only `…backup_phase2` is tracked) | **Re-executed** (pure filesystem assertion, no DB access) → `AssertionError: False is not true` | ✅ cause confirmed |
| 2 | `test_phase6a_foundation.py::TestBrowserManagerLifecycle::test_browser_lifecycle_and_test_navigation` | Playwright driver/browser bundle not installed | **Re-executed** (class touches no DB) → `playwright._impl._errors.Error: This installation of Playwright does not include Node.js.` | ✅ cause confirmed |
| 3 | `test_phase6a_foundation.py::TestBrowserManagerLifecycle::test_safe_navigate_blocks_disallowed_urls` | Same as #2 | **Re-executed** (no DB access) → same Playwright error | ✅ cause confirmed |
| 4 | `test_phase6_live_price_engine.py::TestPhase6LivePriceEngine::test_audit_logs_persisted` | Asserts `price_check_logs` contains ≥1 row; the table is empty because the live-check path that writes it needs a real browser run (the API tests mock the engine) | **Re-executed** (single `SELECT`) → `AssertionError: 0 not greater than or equal to 1` | ✅ cause confirmed |
| 5 | `test_phase11b_hybrid_intelligence.py::TestPriceVerificationService::test_evidence_reference_recording_and_retrieval` | `record_evidence_reference(uploaded_by=1)` → `sqlite3.IntegrityError: FOREIGN KEY constraint failed` — user id 1 does not exist in the shared database | **NOT EXECUTED** — it `INSERT`s into the shared database | ✅ cause confirmed statically (see §8.3) |
| 6 | `test_phase11b_hybrid_intelligence.py::TestPriceVerificationService::test_admin_approval_and_rejection_workflow` | `INSERT INTO manual_verification_requests (user_id=1, product_id=1, …)` → same FK violation | **NOT EXECUTED** — it `INSERT`s into the shared database | ✅ cause confirmed statically |

```
4 failed, 1 warning in 1.53s      # the 4 re-executed failures
```

### 9.3 What was deliberately not re-run, and why

The **full suite was not re-executed** during this audit. Running it would recreate the 21 users / 21 preferences / 6 profiles / 3 wishlist rows, un-archive fixtures 998/999 and rewrite four offer/product rows in the shared development database — precisely the mutation the audit forbids. Instead:

* the 4 safe failures were re-executed and reproduce with identical causes;
* the 2 unsafe failures were confirmed statically and are byte-identical to the baseline versions;
* the shared database was verified unchanged afterwards via a read-only connection:

```
products 113 | offers 494 | price_history 1360 | stores 10 | users 0 | wishlist 0
price_check_logs 0 | manual_verification_requests 0 | evidence_references 0
active/archived products 100 / 13
```

This matches the state recorded at the end of Stage 2.5, so the working copy is intact.

---

## 10. CONSOLIDATED RESULT TABLE

| # | Audit item | Classification | Key evidence |
|---|---|---|---|
| 1 | Branch is `phase-14-stage-2-5-recovery` | **PASS** | `git branch --show-current` |
| 2 | Commit `474aacd` exists and contains the reported changes | **PASS** | 16 files, +1771/−55, matches the report manifest; `main`/`origin/main` still at `83e2267` |
| 3 | Working tree is clean | **PASS** | `git status --porcelain` empty |
| 4a | Production/staging fail safely without `AUTH_SECRET_KEY` | **PASS** | `MissingSessionSecretError` raised in 4/4 runtime probes; enforced at FastAPI lifespan and Streamlit start-up |
| 4b | Development fallback unreachable in production | **PASS** | Guard raises before the ephemeral branch; probe confirms a 64-char random value in dev only |
| 4c | Signing and verification use the same resolver | **PASS** | `auth_service.py:393` and `:415` → `get_session_secret()`; no other key source exists |
| 4d | No committed public fallback secret remains | **PASS** (functional) | No `getenv(..., literal)` in the signing path. Observation O-02: literals still appear in the report and the guard-test list |
| 5a | `migrate_db()` does not reactivate archived products | **PASS** | No `is_active` write in `connection.py`; scratch-DB probe preserves `{13:0, 5:1, 12:1, 500:1}` across 3 forced migrations |
| 5b | Schema migrations are idempotent | **PASS** | Column set stable across repeated forced migrations; runner executes once per database per process |
| 5c | Archival is controlled through explicit product IDs | **PASS** | `id IN (...)` only; no range comparisons; migration + rollback SQL amended accordingly |
| 5d | PostgreSQL and SQLite paths correctly separated | **PASS** | Two dedicated runners, engine dispatch, `init_db()` refuses PostgreSQL, URL never exposed in keys/logs |
| 6 | Neon staging instructions verified without touching production | **PASS** (instructions) / **NOT VERIFIED** (Neon DB state) | Every instruction cross-checked against the repo; no DB credential present; production branch never contacted |
| 7 | Local backup exists and SHA-256 matches | **PASS** | `1808bd74…9995970` recomputed, size 667,648 — exact match; git-ignored |
| 8 | Test isolation issue identified; temp-DB feasibility determined | **PASS** | 4 modules write to the shared DB (+1 DDL-only); no `conftest.py`; a single `PRICEWISE_DB_PATH` redirect in `tests/conftest.py` isolates all of them |
| 9 | Six failures and baseline comparison confirmed | **PASS** | 4 re-executed with identical causes, 2 confirmed statically; all 3 affected files byte-identical between `83e2267` and `474aacd` |

**Overall: PASS — 16/16 audited checks pass.** No FAIL was recorded against the Stage 2.5 implementation.

---

## 11. ADDITIONAL FINDINGS (not part of the two fixes; not actioned)

| ID | Severity | Finding | Recommended owner action |
|---|---|---|---|
| **F-01** | High (operational) | The **live staging deployment returns HTTP 500 on `/api/products`** while health/retailer-status/climate-profile endpoints return 200. Evidence points to the Phase 14 `is_active` column never having been applied to Neon, because the pre-Stage-2.5 `migrate_db()` crashed on PostgreSQL. The new engine-aware runner should repair it on the next start-up, but this is **unverified**. | Back up with `pg_dump` (§9.4), deploy, confirm `GET /api/products` → 200, then run the explicit archival (§9.3). |
| **O-01** | Low | Fail-closed secret behaviour depends on `ENVIRONMENT` being set correctly. An unset `ENVIRONMENT` is treated as `development` and yields an *ephemeral* (not published) secret — tokens are not forgeable, but sessions reset on each restart. | Add an explicit `ENVIRONMENT` assertion to deployment runbooks. |
| **O-02** | Low | The two previously published secret literals still appear verbatim in the tracked tree — in the Stage 2.5 report narrative and in the `LEGACY_PUBLIC_SECRETS` guard list. Not executable, but still publicly known. | Optionally assemble the literals at runtime in the guard test. |
| **O-03** | Low | `tests/test_phase12_production_security.py` writes real backup files into `data/backups/` during a run (3 artefacts observed from the Stage 2.5 run). | Point the backup script at a temporary directory in tests. |
| **O-04** | Medium (process) | No `conftest.py` exists, so 4 test modules write to the shared development database and the suite is order-dependent (the direct cause of the 2 remaining failures). | Add `tests/conftest.py` redirecting `PRICEWISE_DB_PATH` to a temporary copy — one file, isolates every offender. |
| **O-05** | Trivial | `src/config.py:24` `REQUIRES_CONFIGURED_SECRET` is now a dead constant: the resolver uses the dynamic `_secret_is_required()` helper instead. | Remove the constant or make the resolver use it. |

---

## 12. AUDIT VERDICT

The Stage 2.5 implementation is **accurate as reported** on every audited dimension:

* the branch, commit and tree state are exactly as described;
* the authentication secret is genuinely single-sourced, fail-closed in production/staging, and free of a functional published fallback;
* `migrate_db()` is genuinely schema-only, idempotent, engine-aware, and no longer able to reactivate an archived product by ID threshold;
* archival is genuinely explicit-ID-only, in both code and SQL;
* the backup exists with an exactly matching checksum;
* the six remaining failures are byte-identical to the baseline and are environmental or pre-existing, with no regressions introduced.

**Nothing in the two fixes was found to be defective, incomplete or overstated.**

Two items require operator attention and are **not** defects in this commit:

1. **F-01** — the staging catalogue endpoint is currently returning 500; the fix should resolve it on the next deployment, but that outcome is unverified and must be confirmed on staging after a backup and deploy.
2. **O-04** — the test-suite isolation defect remains open; a one-file `tests/conftest.py` resolves it.

The pending findings listed in §10 of the Stage 2.5 report (secure cookies, HTTP rate limiting, admin authorisation rules, the oversized API module, stale README) were confirmed as still open and remain unfixed, as instructed.

**No deployment, environment-variable change, archival command or Stage 3 work was performed. This audit stops here and waits for approval.**
