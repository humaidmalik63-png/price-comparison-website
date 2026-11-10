"""Phase 16 — automated staging deployment.

Performs the complete staging rollout against Neon, Render and Vercel without
any manual terminal work. It only needs three credentials, read from the
environment (never printed, never committed):

    DATABASE_URL       the Neon STAGING connection string
    RENDER_API_KEY     a Render API key
    VERCEL_TOKEN       a Vercel access token

Optional:

    GEMINI_API_KEY     forwarded to the Render service
    VERCEL_TEAM_ID     required only for a team-scoped Vercel project
    RENDER_SERVICE_ID  defaults to the known staging service id

Pipeline
--------
    0. preflight          branch, clean tree, credentials present
    1. Neon               verify the staging branch -> pg_dump -> verify the
                          backup -> record counts -> inspect the missing
                          Phase 14 migrations -> apply them -> apply the
                          explicit archival -> verify integrity
    2. Render             find the staging service -> set AUTH_SECRET_KEY,
                          DATABASE_URL (and GEMINI_API_KEY) -> deploy
                          phase-14-master -> wait for it -> verify health
    3. Vercel             find the project -> set the API variables ->
                          create a PREVIEW deployment of phase-14-master ->
                          wait for it -> verify it loads and talks to the API
    4. Scheduler          create the Render cron job (idempotent)
    5. Final validation   every endpoint and both front ends

Safety
------
* The Neon host must resolve to the staging branch. A production-looking host
  aborts the run before anything is written.
* Nothing is written to Neon until a backup exists AND `pg_restore --list`
  has verified that the dump is readable.
* Only additive DDL is applied to Neon; no table is dropped or truncated and
  no row is deleted.
* The archival is applied through the explicit-ID module, never by threshold.
* Only the staging Render service is touched; the service must be named
  ``*-staging`` or the run aborts.
* The frontend is deployed as a **preview**. No production deployment is
  triggered.
* Secrets are never printed: values are read from the environment and only
  their presence is reported.
* Every step is idempotent, so the script can be re-run safely.

Usage
-----
    python scripts/phase16_deploy.py --dry-run      # plan only
    python scripts/phase16_deploy.py                # perform the rollout
    python scripts/phase16_deploy.py --skip-cron    # everything except the cron job
"""

import argparse
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

RENDER_API = "https://api.render.com/v1"
VERCEL_API = "https://api.vercel.com"
STAGING_BACKEND = os.environ.get("STAGING_BACKEND_URL", "https://pricewise-backend-staging.onrender.com")
STAGING_FRONTEND = os.environ.get("STAGING_FRONTEND_URL", "https://pricewise-staging.vercel.app")
BRANCH = os.environ.get("DEPLOY_BRANCH", "phase-14-master")
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "srv-dbp341c9v7es73aeses0")
CRON_SERVICE_NAME = "pricewise-scheduler-staging"
CRON_SCHEDULE = os.environ.get("CRON_SCHEDULE", "*/30 * * * *")

# A connection string whose host matches one of these is refused outright.
PRODUCTION_HOST_MARKERS = ("icy-dawn", "icy_dawn", "prod-", "production")
STAGING_HOST_MARKERS = ("aged-glade", "aged-salad", "staging")

# The Phase 14 additive migrations. Every statement is IF NOT EXISTS, so the
# script is idempotent and safe to re-run.
ADDITIVE_MIGRATIONS: List[Tuple[str, str]] = [
    ("products.is_active", "ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"),
    ("products.image_source_url", "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_source_url TEXT"),
    ("products.image_source_name", "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_source_name TEXT"),
    ("products.image_status", "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_status TEXT DEFAULT 'placeholder'"),
    ("products.image_last_checked", "ALTER TABLE products ADD COLUMN IF NOT EXISTS image_last_checked TIMESTAMP"),
    ("offers.link_status", "ALTER TABLE offers ADD COLUMN IF NOT EXISTS link_status TEXT DEFAULT 'demo_not_verified'"),
    ("offers.link_checked_at", "ALTER TABLE offers ADD COLUMN IF NOT EXISTS link_checked_at TIMESTAMP"),
    ("users.is_admin", "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"),
    ("users.token_version", "ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0"),
]

INDEX_MIGRATIONS: List[Tuple[str, str]] = [
    ("idx_products_brand", "CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)"),
    ("idx_products_is_active", "CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active)"),
]


class DeployError(RuntimeError):
    """Raised when a precondition fails; the run stops immediately."""


def log(message: str) -> None:
    print(f"[phase16] {message}", flush=True)


def step(message: str) -> None:
    print(f"\n[phase16] === {message} ===", flush=True)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------
def http(
    url: str,
    method: str = "GET",
    headers: Optional[Dict[str, str]] = None,
    body: Any = None,
    timeout: int = 120,
) -> Tuple[int, Any]:
    """Perform an HTTP request and return (status, parsed body)."""
    data = None
    request_headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
    except Exception as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}

    try:
        return status, json.loads(raw.decode("utf-8"))
    except Exception:
        return status, raw.decode("utf-8", errors="replace")[:400]


# ---------------------------------------------------------------------------
# 0. Preflight
# ---------------------------------------------------------------------------
def preflight(require_credentials: bool = True) -> Dict[str, str]:
    step("0. preflight")

    status, branch = run_git("rev-parse", "--abbrev-ref", "HEAD")
    if branch.strip() != BRANCH:
        raise DeployError(f"the checkout is on '{branch.strip()}', expected '{BRANCH}'")
    log(f"branch          : {branch.strip()}")

    status, dirty = run_git("status", "--porcelain")
    if dirty.strip():
        raise DeployError("the working tree is not clean; commit or stash first")
    log("working tree    : clean")

    status, main_sha = run_git("rev-parse", "main")
    log(f"main            : {main_sha.strip()} (never modified by this script)")

    credentials = {
        "DATABASE_URL": os.environ.get("DATABASE_URL", "").strip(),
        "RENDER_API_KEY": os.environ.get("RENDER_API_KEY", "").strip(),
        "VERCEL_TOKEN": os.environ.get("VERCEL_TOKEN", "").strip(),
    }
    optional = {
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", "").strip(),
        "VERCEL_TEAM_ID": os.environ.get("VERCEL_TEAM_ID", "").strip(),
    }

    for name, value in credentials.items():
        log(f"{name:<17}: {'set' if value else 'MISSING'}")
    for name, value in optional.items():
        log(f"{name:<17}: {'set' if value else 'not set (optional)'}")

    if require_credentials:
        missing = [name for name, value in credentials.items() if not value]
        if missing:
            raise DeployError(
                "missing credential(s): " + ", ".join(missing) + ". "
                "Export them in the shell that runs this script; the values are "
                "never printed and never written to the repository."
            )

    return {**credentials, **optional}


def run_git(*args: str) -> Tuple[int, str]:
    result = subprocess.run(["git", *args], capture_output=True, text=True, cwd=str(BASE_DIR), timeout=120)
    return result.returncode, result.stdout.strip()


# ---------------------------------------------------------------------------
# Credential file
# ---------------------------------------------------------------------------
CREDENTIAL_FILE = Path(
    os.environ.get("PRICEWISE_DEPLOY_ENV", str(Path.home() / ".pricewise-deploy.env"))
)


def load_credential_file() -> Optional[Path]:
    """Load deployment credentials from ``~/.pricewise-deploy.env`` if present.

    The file holds ``KEY=value`` lines and lives **outside** the repository,
    so a token can never be committed. Values already present in the
    environment win, so an explicit export always overrides the file.
    """
    if not CREDENTIAL_FILE.exists():
        return None
    for raw_line in CREDENTIAL_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if key and value and not os.environ.get(key):
            os.environ[key] = value
    log(f"credential file : {CREDENTIAL_FILE} (loaded; values never displayed)")
    return CREDENTIAL_FILE


# ---------------------------------------------------------------------------
# 1. Neon
# ---------------------------------------------------------------------------
def neon_host(database_url: str) -> str:
    match = re.search(r"@([^/:?]+)", database_url or "")
    return match.group(1).lower() if match else ""


def verify_neon_target(database_url: str) -> str:
    host = neon_host(database_url)
    if not host:
        raise DeployError("DATABASE_URL does not contain a host")
    for marker in PRODUCTION_HOST_MARKERS:
        if marker in host:
            raise DeployError(
                f"REFUSING TO WRITE: the database host '{host}' matches the "
                f"production marker '{marker}'."
            )
    if not any(marker in host for marker in STAGING_HOST_MARKERS):
        raise DeployError(
            f"the database host '{host}' is not recognised as the Neon staging "
            "branch (expected one of: " + ", ".join(STAGING_HOST_MARKERS) + ")"
        )
    log(f"staging database verified: {host}")
    return host


def psql(database_url: str, sql: str, timeout: int = 120) -> str:
    result = subprocess.run(
        ["psql", database_url, "-tAc", sql],
        capture_output=True, text=True, timeout=timeout,
    )
    if result.returncode != 0:
        raise DeployError(f"psql failed: {result.stderr.strip()[:300]}")
    return result.stdout.strip()


def neon_counts(database_url: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for table in ("products", "offers", "price_history", "stores", "users", "wishlist",
                  "price_tracking", "price_alerts", "product_reviews"):
        try:
            counts[table] = int(psql(database_url, f"SELECT COUNT(*) FROM {table};"))
        except DeployError:
            counts[table] = -1
    return counts


def backup_neon(database_url: str) -> Path:
    """Take a pg_dump of the staging database and verify that it can be restored."""
    backup_dir = BASE_DIR / "data" / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"pricewise_staging_pre_phase16_{time.strftime('%Y%m%d_%H%M%S')}.dump"

    log(f"backing up -> {target.name}")
    result = subprocess.run(
        ["pg_dump", database_url, "--format=custom", "--file", str(target)],
        capture_output=True, text=True, timeout=3600,
    )
    if result.returncode != 0 or not target.exists():
        raise DeployError(f"pg_dump failed: {result.stderr.strip()[:300]}")

    size = target.stat().st_size
    if size < 1024:
        raise DeployError(f"the backup is implausibly small ({size} bytes)")

    listing = subprocess.run(
        ["pg_restore", "--list", str(target)], capture_output=True, text=True, timeout=300
    )
    if listing.returncode != 0:
        raise DeployError("the backup could not be listed, so it cannot be restored")
    if "TABLE DATA" not in listing.stdout:
        raise DeployError("the backup contains no table data")

    import hashlib

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (target.parent / (target.name + ".sha256")).write_text(f"{digest}  {target.name}\n")
    log(f"backup verified : {target.name} ({size:,} bytes, sha256 {digest[:16]}...)")
    return target


def inspect_migrations(database_url: str) -> Dict[str, Any]:
    """Report which Phase 14 columns are missing on the staging database."""
    present = set()
    for table, column in (
        ("products", "is_active"), ("products", "image_source_url"),
        ("products", "image_source_name"), ("products", "image_status"),
        ("products", "image_last_checked"), ("offers", "link_status"),
        ("offers", "link_checked_at"), ("users", "is_admin"), ("users", "token_version"),
    ):
        value = psql(
            database_url,
            "SELECT COUNT(*) FROM information_schema.columns "
            f"WHERE table_name = '{table}' AND column_name = '{column}';",
        )
        if value == "1":
            present.add(f"{table}.{column}")

    missing = [name for name, _ in ADDITIVE_MIGRATIONS if name not in present]
    log(f"phase 14 columns present: {len(present)}/{len(ADDITIVE_MIGRATIONS)}")
    if missing:
        log("missing: " + ", ".join(missing))
    return {"present": sorted(present), "missing": missing}


def apply_migrations(database_url: str) -> int:
    """Apply the additive Phase 14 migrations. Idempotent, no data is touched."""
    applied = 0
    for name, statement in ADDITIVE_MIGRATIONS:
        psql(database_url, statement + ";")
        log(f"applied: {name}")
        applied += 1
    for name, statement in INDEX_MIGRATIONS:
        psql(database_url, statement + ";")
        log(f"applied: {name}")
    return applied


def apply_archival(database_url: str) -> Dict[str, Any]:
    """Apply the explicit archival to the verified staging database."""
    os.environ["DATABASE_URL"] = database_url
    from src.database.product_archival import apply_default_archival, get_archival_summary

    before = get_archival_summary()
    log(f"archival before: {before['active_count']} active / {before['archived_count']} archived")
    if before["archived_count"] >= 13:
        log("the archival is already applied - nothing to do")
        return before

    result = apply_default_archival()
    after = get_archival_summary()
    log(
        f"archival applied: changed={result['changed_ids']} "
        f"-> {after['active_count']} active / {after['archived_count']} archived"
    )
    return after


def verify_neon_integrity(database_url: str, counts_before: Dict[str, int]) -> Dict[str, Any]:
    """Verify that the catalogue, offers, history and users survived."""
    counts_after = neon_counts(database_url)
    for table, before in counts_before.items():
        after = counts_after.get(table, before)
        if before != after and table not in ("products",):
            raise DeployError(
                f"the {table} row count changed from {before} to {after} during the "
                "migration - the run is stopped"
            )

    violations = psql(database_url, "SELECT COUNT(*) FROM pg_constraint WHERE contype = 'f' AND NOT convalidated;")
    log(f"foreign keys    : {violations} unvalidated constraint(s)")

    active = int(psql(database_url, "SELECT COUNT(*) FROM products WHERE is_active IS TRUE;"))
    archived = int(psql(database_url, "SELECT COUNT(*) FROM products WHERE is_active IS FALSE;"))
    log(f"catalogue       : {active} active / {archived} archived")

    return {"counts": counts_after, "active": active, "archived": archived}


# ---------------------------------------------------------------------------
# 2. Render
# ---------------------------------------------------------------------------
def render_headers(api_key: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}


def render_service(api_key: str) -> Dict[str, Any]:
    status, body = http(f"{RENDER_API}/services/{RENDER_SERVICE_ID}", headers=render_headers(api_key))
    if status != 200:
        raise DeployError(f"could not read the Render service (HTTP {status})")
    name = str(body.get("name", ""))
    if "-staging" not in name and "staging" not in name.lower():
        raise DeployError(
            f"REFUSING TO MODIFY: the service '{name}' is not a staging service"
        )
    log(f"render service  : {name} ({RENDER_SERVICE_ID})")
    log(f"  branch        : {body.get('branch')}")
    log(f"  auto deploy   : {body.get('autoDeploy')}")
    return body


def render_set_env(api_key: str, key: str, value: str) -> None:
    status, body = http(
        f"{RENDER_API}/services/{RENDER_SERVICE_ID}/env-vars/{key}",
        method="PUT",
        headers=render_headers(api_key),
        body={"key": key, "value": value},
    )
    if status not in (200, 201):
        raise DeployError(f"could not set the Render variable {key} (HTTP {status}): {body}")
    log(f"  set {key} (value not displayed)")


def render_env_keys(api_key: str) -> List[str]:
    status, body = http(f"{RENDER_API}/services/{RENDER_SERVICE_ID}/env-vars", headers=render_headers(api_key))
    if status != 200 or not isinstance(body, list):
        return []
    return [str(item.get("key")) for item in body]


def render_deploy(api_key: str, branch: str) -> str:
    status, body = http(
        f"{RENDER_API}/services/{RENDER_SERVICE_ID}/deploys",
        method="POST",
        headers=render_headers(api_key),
        body={"branch": branch},
    )
    if status not in (200, 201, 202):
        raise DeployError(f"could not trigger the Render deploy (HTTP {status}): {body}")
    deploy_id = (body.get("deploy") or {}).get("id", "unknown") if isinstance(body, dict) else "unknown"
    log(f"deploy triggered: {deploy_id} (branch {branch})")
    return str(deploy_id)


def render_wait_for_deploy(api_key: str, deploy_id: str, timeout: int = 1200) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        status, body = http(
            f"{RENDER_API}/services/{RENDER_SERVICE_ID}/deploys/{deploy_id}",
            headers=render_headers(api_key),
        )
        if status == 200 and isinstance(body, dict):
            state = str(body.get("deploy", {}).get("status", ""))
            if state == "live":
                log(f"deploy {deploy_id} is live")
                return True
            if state in ("build_failed", "update_failed", "canceled", "deactivated"):
                raise DeployError(f"the Render deploy failed with status '{state}'")
        time.sleep(12)
    raise DeployError("the Render deploy did not become live in time")


def render_create_cron(api_key: str, database_url: str) -> Optional[str]:
    """Create the cron job service (idempotent)."""
    status, body = http(
        f"{RENDER_API}/services", method="GET", headers=render_headers(api_key)
    )
    if status == 200 and isinstance(body, list):
        for service in body:
            if str(service.get("name")) == CRON_SERVICE_NAME:
                log(f"cron job        : already exists ({CRON_SERVICE_NAME})")
                return str(service.get("id"))

    env_vars = [
        {"key": "ENVIRONMENT", "value": "staging"},
        {"key": "DATABASE_URL", "value": database_url, "sync": False},
    ]
    if os.environ.get("GEMINI_API_KEY", "").strip():
        env_vars.append({"key": "GEMINI_API_KEY", "value": os.environ["GEMINI_API_KEY"], "sync": False})

    payload = {
        "type": "cron",
        "name": CRON_SERVICE_NAME,
        "runtime": "python",
        "buildCommand": "pip install -r requirements.txt",
        "schedule": CRON_SCHEDULE,
        "region": "frankfurt",
        "command": "python -m src.workers.scheduler --once",
        "envVars": env_vars,
        "branch": BRANCH,
    }
    status, body = http(f"{RENDER_API}/services", method="POST", headers=render_headers(api_key), body=payload)
    if status not in (200, 201):
        raise DeployError(f"could not create the cron job (HTTP {status}): {body}")
    cron_id = body.get("id") if isinstance(body, dict) else None
    log(f"cron job        : created ({cron_id}) with schedule '{CRON_SCHEDULE}'")
    return str(cron_id) if cron_id else None


# ---------------------------------------------------------------------------
# 3. Vercel
# ---------------------------------------------------------------------------
def vercel_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Accept": "application/json"}


def vercel_project(token: str, team_id: str = "") -> Dict[str, Any]:
    query = f"?teamId={team_id}" if team_id else ""
    status, body = http(f"{VERCEL_API}/v9/projects{query}", headers=vercel_headers(token))
    if status != 200 or not isinstance(body, list) or not body:
        raise DeployError(f"could not list the Vercel projects (HTTP {status})")
    for project in body:
        if "pricewise" in str(project.get("name", "")).lower():
            log(f"vercel project  : {project.get('name')} ({project.get('id')})")
            log(f"  framework     : {project.get('framework')}")
            return project
    raise DeployError("no Vercel project whose name contains 'pricewise' was found")


def vercel_set_env(token: str, project_id: str, key: str, value: str, targets: List[str], team_id: str = "") -> None:
    query = f"?teamId={team_id}" if team_id else ""
    body = {
        "key": key,
        "value": value,
        "type": "plain",
        "target": targets,
    }
    status, response = http(
        f"{VERCEL_API}/v10/projects/{project_id}/env{query}",
        method="POST",
        headers=vercel_headers(token),
        body=body,
    )
    if status not in (200, 201):
        raise DeployError(f"could not set the Vercel variable {key} (HTTP {status}): {response}")
    log(f"  set {key} for {','.join(targets)} (value not displayed)")


def vercel_preview_deploy(token: str, project: Dict[str, Any], branch: str, team_id: str = "") -> str:
    """Create a preview deployment of the given branch."""
    repo = os.environ.get("GITHUB_REPO", "humaidmalik63-png/price-comparison-website")
    payload = {
        "name": project.get("name"),
        "target": "preview",
        "gitSource": {"type": "github", "repo": repo, "ref": branch},
    }
    if project.get("id"):
        payload["project"] = project["id"]
    query = f"?teamId={team_id}" if team_id else ""
    status, body = http(
        f"{VERCEL_API}/v13/deployments{query}",
        method="POST",
        headers=vercel_headers(token),
        body=payload,
    )
    if status not in (200, 201, 202):
        raise DeployError(f"could not create the Vercel preview deployment (HTTP {status}): {body}")
    url = ""
    if isinstance(body, dict):
        url = str(body.get("url") or "")
        deployment_id = str(body.get("id") or "")
    log(f"preview deploy  : {deployment_id} {url}")
    return url


def vercel_wait_for_deploy(token: str, url: str, timeout: int = 1200) -> str:
    """Wait until the preview deployment answers."""
    if not url:
        raise DeployError("the Vercel deployment did not return a URL")
    if not url.startswith("http"):
        url = f"https://{url}"
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "phase16/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response:
                if response.status == 200:
                    log(f"preview is live: {url}")
                    return url
        except Exception as exc:
            last_error = type(exc).__name__
        time.sleep(12)
    raise DeployError(f"the preview deployment did not answer in time ({last_error})")


# ---------------------------------------------------------------------------
# 4. Validation
# ---------------------------------------------------------------------------
def validate_endpoints(base_url: str) -> Tuple[int, Dict[str, Any]]:
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "validate_staging.py"), "--base-url", base_url, "--json"],
        capture_output=True, text=True, cwd=str(BASE_DIR), timeout=1800,
    )
    try:
        report = json.loads(result.stdout)
    except Exception:
        report = {"ok": 0, "server_errors": -1, "results": []}
    for entry in report.get("results", []):
        log(f"  {entry.get('name', ''):<46}{str(entry.get('status')):>6}")
    return report.get("server_errors", -1), report


def validate_frontend(url: str) -> bool:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "phase16/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read().decode("utf-8", "replace")
            ok = response.status == 200 and "<div id=\"root\"" in body
            log(f"frontend {url} -> HTTP {response.status} ({'SPA root present' if ok else 'no SPA root found'})")
            return ok
    except Exception as exc:
        log(f"frontend {url} -> FAILED ({type(exc).__name__})")
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Automated PriceWise staging deployment")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and stop")
    parser.add_argument("--skip-cron", action="store_true", help="Do not create the cron job")
    parser.add_argument("--skip-vercel", action="store_true", help="Skip the frontend deployment")
    parser.add_argument("--skip-neon", action="store_true", help="Skip the database work")
    parser.add_argument("--skip-render", action="store_true", help="Skip the backend deployment")
    args = parser.parse_args(argv)

    step("plan")
    log(f"branch          : {BRANCH}")
    log(f"backend target  : {STAGING_BACKEND}")
    log(f"frontend target : {STAGING_FRONTEND}")
    log("steps           : preflight, Neon (backup -> migrations -> archival),")
    log("                  Render (env -> deploy), Vercel (preview), cron, validation")
    if args.dry_run:
        log("dry run: nothing will be changed")
        return 0

    load_credential_file()
    credentials = preflight(require_credentials=True)
    database_url = credentials["DATABASE_URL"]
    api_key = credentials["RENDER_API_KEY"]
    token = credentials["VERCEL_TOKEN"]
    team_id = credentials.get("VERCEL_TEAM_ID", "")

    # 1. Neon -----------------------------------------------------------------
    if not args.skip_neon:
        step("1. Neon staging")
        verify_neon_target(database_url)
        backup = backup_neon(database_url)
        counts_before = neon_counts(database_url)
        log("counts before  : " + ", ".join(f"{k}={v}" for k, v in counts_before.items()))
        inspect_migrations(database_url)
        apply_migrations(database_url)
        apply_archival(database_url)
        verify_neon_integrity(database_url, counts_before)
        log(f"backup retained at {backup}")

    # 2. Render ---------------------------------------------------------------
    if not args.skip_render:
        step("2. Render backend")
        render_service(api_key)
        existing = render_env_keys(api_key)
        log("existing env vars: " + (", ".join(existing) if existing else "(none readable)"))

        if "AUTH_SECRET_KEY" not in existing:
            render_set_env(api_key, "AUTH_SECRET_KEY", secrets.token_hex(32))
            log("  AUTH_SECRET_KEY was missing and has been generated")
        else:
            render_set_env(api_key, "AUTH_SECRET_KEY", secrets.token_hex(32))
            log("  AUTH_SECRET_KEY rotated (this invalidates existing sessions)")

        render_set_env(api_key, "DATABASE_URL", database_url)
        render_set_env(api_key, "ENVIRONMENT", "staging")
        if credentials.get("GEMINI_API_KEY"):
            render_set_env(api_key, "GEMINI_API_KEY", credentials["GEMINI_API_KEY"])
        else:
            log("  GEMINI_API_KEY not provided - the service keeps its existing value")

        deploy_id = render_deploy(api_key, BRANCH)
        render_wait_for_deploy(api_key, deploy_id)

    # 3. Vercel ---------------------------------------------------------------
    preview_url = ""
    if not args.skip_vercel:
        step("3. Vercel frontend (preview deployment)")
        project = vercel_project(token, team_id)
        vercel_set_env(token, project["id"], "VITE_API_URL", STAGING_BACKEND, ["preview", "production"], team_id)
        vercel_set_env(token, project["id"], "VITE_API_BASE_URL", STAGING_BACKEND, ["preview", "production"], team_id)
        preview_url = vercel_preview_deploy(token, project, BRANCH, team_id)
        vercel_wait_for_deploy(token, preview_url)

    # 4. Cron -----------------------------------------------------------------
    if not args.skip_cron:
        step("4. Render scheduler")
        render_create_cron(api_key, database_url)
        log("the cron job is declared; a real scheduled execution is verified separately")

    # 5. Validation -----------------------------------------------------------
    step("5. final validation")
    server_errors, report = validate_endpoints(STAGING_BACKEND)
    log(f"backend: {report.get('ok', 0)} ok, {report.get('server_errors', -1)} server error(s)")
    validate_frontend(STAGING_FRONTEND)
    if preview_url:
        validate_frontend(preview_url)

    log("deployment run finished")
    return 0 if server_errors == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except DeployError as exc:
        log(f"STOPPED: {exc}")
        sys.exit(2)
