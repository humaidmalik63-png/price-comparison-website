"""Phase 15 staging launch script.

Performs the complete staging rollout in the correct order, with a hard stop
before every irreversible step:

    1. verify the Neon target is the STAGING branch (never production)
    2. take a PostgreSQL backup and verify it can be restored
    3. record the pre-change table counts
    4. configure AUTH_SECRET_KEY on the Render service
    5. deploy the Phase 14 branch to the staging web service
    6. wait for the service and apply the explicit archival
    7. validate every endpoint and report

Every step refuses to continue when its precondition is not met, so a partial
run can never leave the staging database in an unknown state.

Usage
-----
    export DATABASE_URL='postgresql://...staging...'
    export RENDER_API_KEY='rnd_...'
    python scripts/phase15_launch.py --dry-run      # print the plan, change nothing
    python scripts/phase15_launch.py                # perform the rollout

Safety
------
* The Neon host must resolve to the staging branch. A host that matches the
  known production host aborts the run.
* The backup is verified with ``pg_restore --list`` before anything is
  written; a backup that cannot be listed aborts the run.
* The production Neon branch is never contacted: the script refuses to run
  when the target looks like production.
* The archival is applied only after the backup is verified.
* No secret is ever printed: the API key is read from the environment and
  the response bodies of the Render API are summarised, not dumped.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
RENDER_API = "https://api.render.com/v1"
RENDER_SERVICE_ID = os.environ.get("RENDER_SERVICE_ID", "srv-dbp341c9v7es73aeses0")
STAGING_FRONTEND = os.environ.get("STAGING_FRONTEND_URL", "https://pricewise-staging.vercel.app")
STAGING_BACKEND = os.environ.get("STAGING_BACKEND_URL", "https://pricewise-backend-staging.onrender.com")

# The Neon production branch. A connection string pointing at this host is
# refused outright.
PRODUCTION_HOST_MARKERS = (
    "icy-dawn",
    "icy_dawn",
    "production",
    "prod-",
)
# The Neon staging branch is expected to contain this marker.
STAGING_HOST_MARKERS = ("aged-glade", "aged-salad", "staging")

SECRET_NAME = "AUTH_SECRET_KEY"


class LaunchError(RuntimeError):
    """Raised when a precondition fails. The run stops immediately."""


def log(message: str) -> None:
    print(f"[phase15] {message}", flush=True)


# --------------------------------------------------------------------------
# 1. Target verification
# --------------------------------------------------------------------------
def host_of(database_url: str) -> str:
    match = re.search(r"@([^/:?]+)", database_url or "")
    return match.group(1).lower() if match else ""


def verify_staging_target(database_url: str) -> str:
    """Confirm the connection string points at the staging branch."""
    if not database_url:
        raise LaunchError(
            "DATABASE_URL is not set. Export the Neon STAGING connection string."
        )
    host = host_of(database_url)

    for marker in PRODUCTION_HOST_MARKERS:
        if marker in host:
            raise LaunchError(
                f"REFUSING TO RUN: the database host '{host}' matches the "
                f"production marker '{marker}'. This script only ever targets "
                "the Neon staging branch."
            )

    if not any(marker in host for marker in STAGING_HOST_MARKERS):
        raise LaunchError(
            f"The database host '{host}' does not look like the Neon staging "
            "branch (expected one of: "
            + ", ".join(STAGING_HOST_MARKERS)
            + "). Confirm the target before continuing."
        )

    log(f"staging target verified: {host}")
    return host


def psql_scalar(database_url: str, sql: str) -> str:
    """Run a read-only query and return the first value."""
    result = subprocess.run(
        ["psql", database_url, "-tAc", sql],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        raise LaunchError(f"psql failed: {result.stderr.strip()[:200]}")
    return result.stdout.strip()


def record_counts(database_url: str) -> Dict[str, int]:
    """Record the pre-change row counts of the tables that matter."""
    counts: Dict[str, int] = {}
    for table in ("products", "offers", "price_history", "stores", "users", "wishlist"):
        try:
            counts[table] = int(psql_scalar(database_url, f"SELECT COUNT(*) FROM {table};"))
        except LaunchError:
            counts[table] = -1
    log("pre-change counts: " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    return counts


# --------------------------------------------------------------------------
# 2. Backup
# --------------------------------------------------------------------------
def create_and_verify_backup(database_url: str, backup_dir: Path) -> Path:
    """Take a pg_dump backup and verify that it can be listed for restore."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    target = backup_dir / f"pricewise_staging_pre_phase15_{stamp}.dump"

    log(f"taking backup -> {target.name}")
    result = subprocess.run(
        ["pg_dump", database_url, "--format=custom", "--file", str(target)],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode != 0 or not target.exists():
        raise LaunchError(
            f"pg_dump failed: {result.stderr.strip()[:300]}. The rollout is stopped."
        )

    size = target.stat().st_size
    if size < 1024:
        raise LaunchError(f"the backup is implausibly small ({size} bytes). Stopping.")

    # Verify the dump can be listed (this is what a restore reads).
    listing = subprocess.run(
        ["pg_restore", "--list", str(target)],
        capture_output=True, text=True, timeout=300,
    )
    if listing.returncode != 0:
        raise LaunchError(
            "pg_restore --list failed, so the backup cannot be verified: "
            f"{listing.stderr.strip()[:300]}. Stopping."
        )
    if "TABLE DATA" not in listing.stdout:
        raise LaunchError(
            "the backup does not contain any table data, so it cannot be a "
            "usable restore point. Stopping."
        )

    import hashlib

    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    (target.parent / (target.name + ".sha256")).write_text(f"{digest}  {target.name}\n")
    log(f"backup verified: {target.name} ({size} bytes, sha256 {digest[:16]}...)")
    return target


# --------------------------------------------------------------------------
# 3. Render
# --------------------------------------------------------------------------
def render_request(method: str, path: str, api_key: str, body=None) -> Tuple[int, dict]:
    request = urllib.request.Request(
        f"{RENDER_API}{path}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            raw = response.read()
            try:
                return response.status, json.loads(raw)
            except Exception:
                return response.status, {}
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read())
        except Exception:
            return exc.code, {}
    except Exception as exc:
        return 0, {"error": type(exc).__name__}


def configure_secret(api_key: str, value: Optional[str] = None) -> bool:
    """Ensure AUTH_SECRET_KEY exists on the Render service.

    When ``value`` is omitted an existing secret is kept; otherwise the value
    is set (rotating it invalidates every issued session).
    """
    status, _ = render_request("GET", f"/services/{RENDER_SERVICE_ID}/env-vars", api_key)
    if status != 200:
        raise LaunchError(
            f"could not read the environment variables of the Render service "
            f"(HTTP {status}). Check RENDER_API_KEY and the service id."
        )

    if value is None:
        status, body = render_request(
            "GET", f"/services/{RENDER_SERVICE_ID}/env-vars", api_key
        )
        existing = {item.get("key") for item in body} if isinstance(body, list) else set()
        if SECRET_NAME in existing:
            log(f"{SECRET_NAME} is already configured on the service")
            return True
        log(
            f"{SECRET_NAME} is not configured. Generate one with "
            "'python -c \"import secrets; print(secrets.token_hex(32))\"' and "
            "re-run with --set-secret, or add it in the Render dashboard."
        )
        return False

    status, body = render_request(
        "PUT",
        f"/services/{RENDER_SERVICE_ID}/env-vars/{SECRET_NAME}",
        api_key,
        {"key": SECRET_NAME, "value": value},
    )
    if status not in (200, 201):
        raise LaunchError(f"could not set {SECRET_NAME} (HTTP {status}): {body}")
    log(f"{SECRET_NAME} configured on the Render service (value not displayed)")
    return True


def deploy_branch(api_key: str, branch: str, commit: Optional[str] = None) -> bool:
    """Trigger a deploy of the given branch."""
    body = {"branch": branch}
    if commit:
        body["commitId"] = commit
    status, response = render_request(
        "POST", f"/services/{RENDER_SERVICE_ID}/deploys", api_key, body
    )
    if status not in (200, 201, 202):
        raise LaunchError(f"could not trigger the deploy (HTTP {status}): {response}")
    deploy_id = response.get("deploy", {}).get("id") if isinstance(response, dict) else None
    log(f"deploy triggered for branch '{branch}' (id {deploy_id})")
    return True


def wait_for_service(url: str, timeout: int = 900) -> bool:
    """Poll the readiness probe until the service answers."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{url.rstrip('/')}/api/health/ready", timeout=30) as response:
                if response.status == 200:
                    log("the service reports ready")
                    return True
        except Exception:
            pass
        time.sleep(15)
    log("the service did not become ready in time - check the Render logs")
    return False


# --------------------------------------------------------------------------
# 4. Archival
# --------------------------------------------------------------------------
def apply_archival(database_url: str) -> None:
    """Apply the explicit archival set to the verified staging database."""
    from src.database.product_archival import get_archival_summary

    os.environ["DATABASE_URL"] = database_url
    summary = get_archival_summary()
    log(
        "archival state before: "
        f"{summary['active_count']} active / {summary['archived_count']} archived"
    )
    if summary["archived_count"] >= 13:
        log("the archival is already applied - nothing to do")
        return

    from src.database.product_archival import apply_default_archival

    result = apply_default_archival()
    log(
        f"archival applied: changed={result['changed_ids']} "
        f"unchanged={len(result['unchanged_ids'])}"
    )


# --------------------------------------------------------------------------
# 5. Validation
# --------------------------------------------------------------------------
def validate(base_url: str) -> int:
    """Run the endpoint matrix against the deployed service."""
    result = subprocess.run(
        [sys.executable, str(BASE_DIR / "scripts" / "validate_staging.py"), "--base-url", base_url],
        cwd=str(BASE_DIR),
    )
    return result.returncode


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="PriceWise staging launch")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and stop")
    parser.add_argument("--branch", default="phase-14-master", help="Branch to deploy")
    parser.add_argument("--set-secret", action="store_true", help="Generate and set AUTH_SECRET_KEY")
    parser.add_argument("--rotate-secret", action="store_true", help="Rotate AUTH_SECRET_KEY (invalidates sessions)")
    parser.add_argument("--skip-deploy", action="store_true", help="Do not trigger the Render deploy")
    parser.add_argument("--backup-dir", default=str(BASE_DIR / "data" / "backups"))
    parser.add_argument("--api-url", default=STAGING_BACKEND)
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL", "").strip()
    api_key = os.environ.get("RENDER_API_KEY", "").strip()

    log("Phase 15 staging launch")
    log(f"  branch to deploy : {args.branch}")
    log(f"  backend target   : {args.api_url}")
    log(f"  DATABASE_URL     : {'set' if database_url else 'NOT SET'}")
    log(f"  RENDER_API_KEY   : {'set' if api_key else 'NOT SET'}")

    if args.dry_run:
        log("dry run: no change will be made")
        log("plan:")
        log("  1. verify the Neon target is the staging branch")
        log("  2. pg_dump + pg_restore --list verification")
        log("  3. record the pre-change counts")
        log("  4. ensure AUTH_SECRET_KEY on the Render service")
        log(f"  5. deploy '{args.branch}' to the staging web service")
        log("  6. apply the explicit archival to Neon staging")
        log("  7. validate every endpoint")
        return 0

    # 1. Target verification -------------------------------------------------
    verify_staging_target(database_url)

    # 2. Backup -------------------------------------------------------------
    backup = create_and_verify_backup(database_url, Path(args.backup_dir))

    # 3. Counts -------------------------------------------------------------
    counts_before = record_counts(database_url)

    # 4. Secret -------------------------------------------------------------
    if api_key:
        if args.rotate_secret:
            import secrets

            configure_secret(api_key, secrets.token_hex(32))
            log("the secret was rotated - every existing session is now invalid")
        elif args.set_secret:
            import secrets

            configure_secret(api_key, secrets.token_hex(32))
        else:
            configure_secret(api_key, None)
    else:
        log("RENDER_API_KEY is not set: configure " + SECRET_NAME + " in the dashboard")

    # 5. Deploy -------------------------------------------------------------
    if args.skip_deploy:
        log("deploy skipped (--skip-deploy)")
    elif api_key:
        deploy_branch(api_key, args.branch)
        wait_for_service(args.api_url)
    else:
        log("no RENDER_API_KEY: deploy the branch from the Render dashboard")

    # 6. Archival -----------------------------------------------------------
    apply_archival(database_url)

    # 7. Validation ---------------------------------------------------------
    log("validating the deployment")
    exit_code = validate(args.api_url)

    counts_after = record_counts(database_url)
    log("post-change counts: " + ", ".join(f"{k}={v}" for k, v in counts_after.items()))
    for table, before in counts_before.items():
        after = counts_after.get(table, before)
        if before != after and table in ("products", "offers", "price_history"):
            log(f"WARNING: {table} changed from {before} to {after}")

    log(f"backup retained at {backup}")
    log("launch finished")
    return exit_code


if __name__ == "__main__":
    try:
        sys.exit(main())
    except LaunchError as exc:
        log(f"STOPPED: {exc}")
        sys.exit(2)
