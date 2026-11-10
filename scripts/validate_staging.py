"""Staging endpoint validation (Phase 15).

Runs the complete endpoint matrix against a deployed PriceWise staging API and
reports, for every endpoint, the HTTP status and a short diagnosis. It is the
verification step of ``docs/PHASE14_STAGING_DEPLOYMENT_RUNBOOK.md`` and can be
re-run at any time against any deployment.

Usage
-----
    python scripts/validate_staging.py --base-url https://pricewise-backend-staging.onrender.com
    python scripts/validate_staging.py --base-url http://127.0.0.1:8010 --json

The script is read-only apart from a registration / login pair it performs to
exercise the authentication endpoints. It never prints a secret, a token or a
session cookie.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_BASE_URL = "https://pricewise-backend-staging.onrender.com"
TIMEOUT = 60


def request(
    base_url: str,
    path: str,
    method: str = "GET",
    body: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
) -> Tuple[int, Any, Dict[str, str]]:
    """Perform an HTTP request and return (status, parsed_body, headers)."""
    url = f"{base_url.rstrip('/')}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req_headers = {"User-Agent": "PriceWise-Audit/1.0", "Accept": "application/json"}
    if data is not None:
        req_headers["Content-Type"] = "application/json"
    if headers:
        req_headers.update(headers)

    request_obj = urllib.request.Request(url, data=data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(request_obj, timeout=TIMEOUT) as response:
            raw = response.read()
            status = response.status
            resp_headers = dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = exc.code
        resp_headers = dict(exc.headers)
    except Exception as exc:
        return 0, {"error": f"{type(exc).__name__}: {exc}"}, {}

    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        parsed = raw.decode("utf-8", errors="replace")[:400]

    return status, parsed, resp_headers


def diagnose(path: str, status: int, payload: Any) -> str:
    """Return a short diagnosis for a non-200 response."""
    if status == 0:
        return "unreachable (network / DNS / TLS)"
    if status == 200:
        return "ok"
    if status == 401:
        return "authentication required (expected for a protected endpoint without a session)"
    if status == 403:
        return "forbidden (expected for an administrator endpoint without an admin session)"
    if status == 404:
        return "not found (check the resource id / slug)"
    if status == 429:
        return "rate limited (the configured budget was enforced)"
    if status == 500:
        detail = ""
        if isinstance(payload, dict):
            detail = str(payload.get("detail") or payload.get("error") or "")[:160]
        return (
            "server error - the deployed code or the database schema is out of date. "
            f"Check the service logs. {detail}"
        )
    return f"unexpected status {status}"


def run(base_url: str, read_only: bool = False) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []

    def record(name: str, path: str, method: str = "GET", body=None, headers=None, expect=None):
        started = time.perf_counter()
        status, payload, resp_headers = request(base_url, path, method, body, headers)
        elapsed = round((time.perf_counter() - started) * 1000, 1)
        entry = {
            "name": name,
            "path": path,
            "method": method,
            "status": status,
            "ms": elapsed,
            "diagnosis": diagnose(path, status, payload),
            "rate_limit_limit": resp_headers.get("X-RateLimit-Limit"),
            "rate_limit_remaining": resp_headers.get("X-RateLimit-Remaining"),
            "has_retry_after": "Retry-After" in resp_headers,
        }
        if expect == "json" and isinstance(payload, list):
            entry["count"] = len(payload)
        results.append(entry)
        return status, payload, resp_headers

    # --- health -----------------------------------------------------------
    record("health (live)", "/api/health/live")
    status, ready, _ = record("health (ready)", "/api/health/ready")
    record("health (summary)", "/api/health")

    # --- catalogue --------------------------------------------------------
    status, products, _ = record("product discovery", "/api/products", expect="json")
    first = products[0] if isinstance(products, list) and products else None
    if first:
        record("product detail (by slug)", f"/api/products/{first.get('slug')}")
    else:
        results.append({
            "name": "product detail (by slug)",
            "path": "(skipped - no products returned)",
            "method": "GET",
            "status": 0,
            "ms": 0,
            "rate_limit_limit": None,
            "rate_limit_remaining": None,
            "has_retry_after": False,
            "diagnosis": "skipped",
        })
    record("archived product is not addressable", "/api/products/1")

    # --- price intelligence ------------------------------------------------
    record("retailer status", "/api/prices/retailer-status")
    record("live comparison", "/api/compare/auto?product_id=12")
    record("price history", "/api/products/12/price-history?window_days=30")
    record("deal intelligence", "/api/products/12/deal-intelligence")
    record("total cost", "/api/products/12/total-cost", method="POST", body={})

    # --- catalogue content -------------------------------------------------
    record("reviews (database-backed)", "/api/products/12/reviews")
    record("beauty: climate profiles", "/api/beauty/climate-profiles")
    record("beauty: ingredients", "/api/beauty/ingredients")

    # --- authentication ----------------------------------------------------
    # Read-only mode skips every mutating call, so the target database is not
    # written to. Use it whenever the database has not been backed up and
    # verified first.
    token = None
    if read_only:
        results.append({
            "name": "authentication: register / login (read-only mode)",
            "path": "/api/auth/register",
            "method": "POST",
            "status": 0,
            "ms": 0,
            "rate_limit_limit": None,
            "rate_limit_remaining": None,
            "has_retry_after": False,
            "diagnosis": "skipped - read-only mode does not write to the target database",
        })
        auth_headers = None
    else:
        stamp = int(time.time())
        email = f"phase15_probe_{stamp}@example.com"
        password = "Phase15Probe!123"
        status, register, _ = record(
            "authentication: register", "/api/auth/register", method="POST",
            body={"name": "Phase 15 Probe", "email": email, "password": password},
        )
        token = register.get("token") if isinstance(register, dict) else None
        record(
            "authentication: login", "/api/auth/login", method="POST",
            body={"email": email, "password": password},
        )
        record("authentication: wrong password is rejected", "/api/auth/login", method="POST",
               body={"email": email, "password": "definitely-wrong"})
        auth_headers = {"Authorization": f"Bearer {token}"} if token else None

    record("authentication: me without a session", "/api/auth/me")

    # --- authenticated features --------------------------------------------
    record("authentication: me with a session", "/api/auth/me", headers=auth_headers)
    if auth_headers:
        record("watchlist", "/api/watchlist", headers=auth_headers)
        record("profile", "/api/profile", headers=auth_headers)
        record("routines", "/api/routines", headers=auth_headers)
        record("beauty assistant: skin concern match", "/api/beauty/match-skin-concerns",
               method="POST", body={"skin_type": "oily", "concerns": ["acne"]}, headers=auth_headers)
        record("beauty: usage quota", "/api/beauty/usage", headers=auth_headers)
        record("admin queue (expect 403 for a non-admin)", "/api/admin/verifications",
               headers=auth_headers)
    else:
        for name, path in (("watchlist", "/api/watchlist"), ("profile", "/api/profile"),
                           ("routines", "/api/routines"),
                           ("beauty: usage quota", "/api/beauty/usage"),
                           ("admin queue (expect 403 for a non-admin)", "/api/admin/verifications")):
            results.append({
                "name": name, "path": path, "method": "GET", "status": 0, "ms": 0,
                "rate_limit_limit": None, "rate_limit_remaining": None,
                "has_retry_after": False,
                "diagnosis": "skipped - no session (read-only mode)",
            })

    summary = {
        "base_url": base_url,
        "total": len(results),
        "ok": sum(1 for r in results if r["status"] == 200),
        "server_errors": sum(1 for r in results if r["status"] == 500),
        "unreachable": sum(1 for r in results if r["status"] == 0),
        "results": results,
    }
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate a deployed PriceWise staging API")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Skip every mutating endpoint (no writes to the target database).",
    )
    args = parser.parse_args(argv)

    report = run(args.base_url, read_only=args.read_only)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 1 if report["server_errors"] or report["unreachable"] else 0

    print(f"Target: {report['base_url']}")
    print(f"{'endpoint':<46}{'status':>7}{'ms':>8}  diagnosis")
    print("-" * 118)
    for entry in report["results"]:
        print(f"{entry['name']:<46}{str(entry.get('status')):>7}{str(entry.get('ms', '-')):>8}  {entry.get('diagnosis', '')}")
    print("-" * 118)
    print(f"ok: {report['ok']}   server errors: {report['server_errors']}   unreachable: {report['unreachable']}")
    return 1 if report["server_errors"] or report["unreachable"] else 0


if __name__ == "__main__":
    sys.exit(main())
