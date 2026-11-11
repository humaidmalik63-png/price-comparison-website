#!/usr/bin/env python
"""Phase 16.6 Stage 1: Beauty catalogue coverage audit.

Produces a per-product coverage classification over the canonical seeded
catalogue (or any supplied database) without touching the application
database. Never calls the PriceInIndia network: Stage 1 is inspection only.

Categories (mutually exclusive, evaluated in this precedence order):

- PROVIDER_OBSERVED      at least one live provider_observed observation
                         usable as a current price
- MATCH_REVIEW_REQUIRED  provider candidates exist but every live candidate is
                         flagged / pending review (ambiguous or conflicting)
- MANUAL_VERIFIED_ONLY   a manually entered observation verified by an admin,
                         no provider observation
- CATALOG_VERIFIED_ONLY  catalog-verified (OBF) product without any
                         observation; catalog verification does NOT imply a
                         current retailer price
- DEMO_ONLY              only demo-priced offers exist
- NO_PRICE_AVAILABLE     no usable offer or observation at all

Usage:
    python -m src.scripts.coverage_audit [--db PATH] [--json PATH] [--markdown PATH]

With no --db, a freshly seeded temporary database is created and removed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.adapters.mcp_adapters.priceinindia_adapter import PriceInIndiaAdapter
from src.database.connection import get_connection
from src.database.seed import DEMO_PRODUCTS, seed_database
from src.services import freshness_service as freshness_svc
from src.services.cheapest_offer_service import evaluate_eligibility
from src.services.product_matching_service import (
    MatchClassification,
    parse_concentration,
    parse_formulation,
    parse_quantity_volume,
    parse_shade,
)

ELECTRONICS_CATEGORIES = {p.get("category", "") for p in DEMO_PRODUCTS}

# Order defines evaluation precedence.
CATEGORY_PRECEDENCE = (
    "PROVIDER_OBSERVED",
    "MATCH_REVIEW_REQUIRED",
    "MANUAL_VERIFIED_ONLY",
    "CATALOG_VERIFIED_ONLY",
    "DEMO_ONLY",
    "NO_PRICE_AVAILABLE",
)

CATEGORY_DESCRIPTIONS = {
    "PROVIDER_OBSERVED": (
        "Has a live, provider_observed PriceInIndia observation that is eligible "
        "as a current price. Not independently verified."
    ),
    "MATCH_REVIEW_REQUIRED": (
        "Provider candidates exist but every live candidate is flagged or pending "
        "review; no usable current provider price."
    ),
    "MANUAL_VERIFIED_ONLY": (
        "Price verified by an admin manual entry; no live provider observation. "
        "Not a live retailer price."
    ),
    "CATALOG_VERIFIED_ONLY": (
        "Product identity verified in catalog (Open Beauty Facts); no current "
        "retailer observation. Catalog verification does not imply live pricing."
    ),
    "DEMO_ONLY": (
        "Only seeded demo prices exist; clearly labelled demo data, not real "
        "retailer prices."
    ),
    "NO_PRICE_AVAILABLE": (
        "No usable offer or observation of any kind."
    ),
}


def _beauty_rows(conn) -> list:
    """Beauty products = every active product outside the electronics demo set."""
    rows = conn.execute(
        """
        SELECT id, sku, title, brand, category, specs_json, data_status, source_type, is_active
        FROM products WHERE is_active = 1 ORDER BY id
        """
    ).fetchall()
    return [r for r in rows if r["category"] not in ELECTRONICS_CATEGORIES]


def _product_attributes(row) -> dict[str, Any]:
    specs = json.loads(row["specs_json"]) if row["specs_json"] else {}
    title = row["title"]
    qty_val, qty_unit = parse_quantity_volume(
        str(specs.get("Net Quantity") or specs.get("Size") or "")
    )
    return {
        "id": row["id"],
        "sku": row["sku"],
        "title": title,
        "brand": row["brand"],
        "category": row["category"],
        "data_status": row["data_status"],
        "source_type": row["source_type"],
        "net_quantity": str(specs.get("Net Quantity") or specs.get("Size") or "") or None,
        "formulation": parse_formulation(title, specs),
        "concentration": sorted(parse_concentration(title, specs) or []),
        "shade": parse_shade(title, specs),
        "qty_value": qty_val,
        "qty_unit": qty_unit,
        "specs_keys": sorted(specs.keys()),
    }


def _parse_stored_match(raw: Any) -> dict[str, Any]:
    """Parse a stored match_result JSON blob; {} when absent/unparsable."""
    if not raw:
        return {}
    try:
        import json as _json
        data = _json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def audit_database(db_path: str) -> dict[str, Any]:
    adapter = PriceInIndiaAdapter()
    with get_connection(db_path) as conn:
        beauty = [_product_attributes(r) for r in _beauty_rows(conn)]

        stores = {
            row["id"]: {"name": row["name"], "domain": row["domain"]}
            for row in conn.execute("SELECT id, name, domain FROM stores")
        }

        offer_rows = conn.execute(
            """
            SELECT o.product_id, o.store_id, o.current_price, o.original_price,
                   o.currency, o.availability, o.offer_url, o.last_checked,
                   s.name AS store_name
            FROM offers o JOIN stores s ON s.id = o.store_id
            ORDER BY o.product_id, o.current_price
            """
        ).fetchall()
        offers_by_product: dict[int, list[dict]] = defaultdict(list)
        for o in offer_rows:
            offers_by_product[o["product_id"]].append(
                {
                    "store": o["store_name"],
                    "price": o["current_price"],
                    "original_price": o["original_price"],
                    "currency": o["currency"],
                    "availability": o["availability"],
                    "offer_url": o["offer_url"],
                    "last_checked": o["last_checked"],
                }
            )

        obs_rows = conn.execute(
            """
            SELECT id, product_id, retailer, product_url, observed_price, observed_mrp,
                   observation_type, observation_status, verified_by_admin,
                   verification_status, created_at, evidence_notes, size_volume,
                   match_result, currency
            FROM retail_price_observation ORDER BY product_id, created_at
            """
        ).fetchall()
        obs_by_product: dict[int, list[dict]] = defaultdict(list)
        for o in obs_rows:
            obs_by_product[o["product_id"]].append(
                {
                    "id": o["id"],
                    "retailer": o["retailer"],
                    "product_url": o["product_url"],
                    "price": o["observed_price"],
                    # evaluate_eligibility expects the canonical column name
                    "observed_price": o["observed_price"],
                    "observed_mrp": o["observed_mrp"],
                    "observation_type": o["observation_type"],
                    "observation_status": o["observation_status"],
                    "verified_by_admin": o["verified_by_admin"],
                    "verification_status": o["verification_status"],
                    "created_at": o["created_at"],
                    "evidence_notes": o["evidence_notes"],
                    "size_volume": o["size_volume"],
                    "currency": o["currency"],
                    "match_result": o["match_result"],
                }
            )

    products_out = []
    for p in beauty:
        offers = offers_by_product.get(p["id"], [])
        observations = obs_by_product.get(p["id"], [])
        live_provider = [
            o for o in observations
            if o["observation_status"] == "live"
            and o["verification_status"] == "provider_observed"
            and (o["price"] or 0) > 0
        ]
        review_pending = [
            o for o in observations
            if o["observation_status"] in ("flagged",)
            or o["verification_status"] in ("pending", "review_required")
        ]
        manual_verified = [
            o for o in observations
            if o["verified_by_admin"] == 1 or o["verification_status"] == "verified"
        ]
        demo_offers = [o for o in offers if "demo" in (o["store"] or "").lower()]

        # ── Phase 16.7 Stage 6: match-strength / freshness / eligibility detail ──
        exact_matches = strong_matches = possible_matches = 0
        rejected_matches = 0
        fresh_obs = stale_obs = 0
        verified_usable = 0
        last_obs_at = None
        for o in observations:
            evidence = _parse_stored_match(o.get("match_result"))
            cls = evidence.get("classification")
            if cls == MatchClassification.VERIFIED_MATCH:
                if evidence.get("match_strength") == "exact":
                    exact_matches += 1
                else:
                    strong_matches += 1
            elif cls == MatchClassification.POSSIBLE_MATCH:
                possible_matches += 1
            elif cls in (
                MatchClassification.INCOMPATIBLE_MISMATCH,
                MatchClassification.AMBIGUOUS_MATCH,
            ):
                rejected_matches += 1
            age = freshness_svc.observation_age_hours(o.get("created_at"))
            bucket = freshness_svc.classify_freshness(age)
            if bucket in (freshness_svc.FRESH, freshness_svc.AGING):
                fresh_obs += 1
            elif bucket == freshness_svc.STALE:
                stale_obs += 1
            if o.get("created_at"):
                current = str(o["created_at"])
                if last_obs_at is None or current > last_obs_at:
                    last_obs_at = current
        for o in observations:
            ok, _reasons = evaluate_eligibility(o)
            if ok:
                verified_usable += 1

        if live_provider:
            category = "PROVIDER_OBSERVED"
        elif review_pending and any(
            o["verification_status"] == "provider_observed" or o["evidence_notes"]
            for o in observations
        ):
            category = "MATCH_REVIEW_REQUIRED"
        elif manual_verified:
            category = "MANUAL_VERIFIED_ONLY"
        elif p["source_type"] == "catalog_verified":
            category = "CATALOG_VERIFIED_ONLY"
        elif demo_offers:
            category = "DEMO_ONLY"
        else:
            category = "NO_PRICE_AVAILABLE"

        # Honest per-product reason why a verified usable live offer is absent.
        coverage_unavailable_reason = None
        if verified_usable == 0:
            if not observations:
                coverage_unavailable_reason = "no_observations"
            elif stale_obs and not fresh_obs:
                coverage_unavailable_reason = "stale_observations_only"
            elif possible_matches and not rejected_matches:
                coverage_unavailable_reason = "possible_matches_awaiting_review"
            elif rejected_matches and not (exact_matches or strong_matches or possible_matches):
                coverage_unavailable_reason = "all_matches_rejected"
            else:
                coverage_unavailable_reason = "observations_present_but_not_eligible"

        products_out.append(
            {
                **p,
                "offers_count": len(offers),
                "demo_offers_count": len(demo_offers),
                "offers": offers,
                "observations_count": len(observations),
                "live_provider_observations": len(live_provider),
                "review_pending_observations": len(review_pending),
                "manual_verified_observations": len(manual_verified),
                "observations": observations,
                "coverage_category": category,
                # Phase 16.7 Stage 6 fields:
                "exact_matches": exact_matches,
                "strong_matches": strong_matches,
                "possible_matches": possible_matches,
                "rejected_matches": rejected_matches,
                "fresh_observations": fresh_obs,
                "stale_observations": stale_obs,
                "verified_usable_offers": verified_usable,
                "last_observation_at": last_obs_at,
                "coverage_unavailable_reason": coverage_unavailable_reason,
            }
        )

    counts = Counter(p["coverage_category"] for p in products_out)

    # ── Phase 16.7 Stage 6 aggregate metrics ─────────────────────────────────
    total_evaluated = sum(
        p["exact_matches"] + p["strong_matches"] + p["possible_matches"] + p["rejected_matches"]
        for p in products_out
    )
    total_exact = sum(p["exact_matches"] for p in products_out)
    total_strong = sum(p["strong_matches"] for p in products_out)
    total_possible = sum(p["possible_matches"] for p in products_out)
    total_rejected = sum(p["rejected_matches"] for p in products_out)
    verified_rate = (
        round((total_exact + total_strong) / total_evaluated, 4)
        if total_evaluated else None
    )
    rejection_rate = (
        round(total_rejected / total_evaluated, 4)
        if total_evaluated else None
    )

    phase16_7_metrics = {
        "products_with_verified_usable_offers": sum(
            1 for p in products_out if p["verified_usable_offers"] > 0
        ),
        "products_with_possible_matches_only": sum(
            1 for p in products_out
            if p["observations_count"] > 0
            and p["possible_matches"] > 0
            and p["exact_matches"] == 0 and p["strong_matches"] == 0
            and p["verified_usable_offers"] == 0
        ),
        "products_with_stale_observations_only": sum(
            1 for p in products_out
            if p["observations_count"] > 0
            and p["stale_observations"] > 0
            and p["fresh_observations"] == 0
        ),
        "products_without_observations": sum(
            1 for p in products_out if p["observations_count"] == 0
        ),
        "products_with_verified_matches_only_pending": sum(
            1 for p in products_out
            if (p["exact_matches"] + p["strong_matches"]) > 0
            and p["verified_usable_offers"] == 0
        ),
        "total_exact_matches": total_exact,
        "total_strong_matches": total_strong,
        "total_possible_matches": total_possible,
        "total_rejected_matches": total_rejected,
        "verified_match_rate": verified_rate,
        "exact_match_rate": (
            round(total_exact / total_evaluated, 4) if total_evaluated else None
        ),
        "rejection_rate": rejection_rate,
        "total_fresh_observations": sum(p["fresh_observations"] for p in products_out),
        "total_stale_observations": sum(p["stale_observations"] for p in products_out),
        "total_verified_usable_offers": sum(p["verified_usable_offers"] for p in products_out),
        # Honest placeholder: this audit performs no provider calls, so a real
        # provider failure rate can only come from a collection stats artifact.
        "provider_failure_rate": None,
        "provider_failure_rate_note": (
            "Not computable by this offline audit; derive from "
            "phase16_6_collection_stats.json error_counts after a collection run."
        ),
        "policy_disclosure": {
            "freshness": {
                "fresh_hours": freshness_svc.DEFAULT_POLICY.fresh_hours,
                "aging_hours": freshness_svc.DEFAULT_POLICY.aging_hours,
                "note": "fresh counts include the aging bucket; stale counts are older than the aging threshold",
            },
            "possible_matches_are_not_verified_offers": True,
        },
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_path": db_path,
        "electronics_categories_excluded": sorted(ELECTRONICS_CATEGORIES),
        "totals": {
            "beauty_products": len(products_out),
            **{cat: counts.get(cat, 0) for cat in CATEGORY_PRECEDENCE},
        },
        "metrics": {
            "products_searched": 0,          # Stage 1 performs no provider calls
            "products_with_provider_results": sum(
                1 for p in products_out if p["observations"]
            ),
            "products_with_accepted_matches": sum(
                1 for p in products_out if p["live_provider_observations"]
            ),
            "products_with_rejected_matches": sum(
                1 for p in products_out if p["review_pending_observations"]
            ),
            "products_requiring_manual_review": sum(
                1 for p in products_out if p["review_pending_observations"]
            ),
            "products_without_any_usable_price": sum(
                1 for p in products_out
                if p["coverage_category"] in ("DEMO_ONLY", "NO_PRICE_AVAILABLE")
            ),
        },
        "phase16_7_metrics": phase16_7_metrics,
        "stores": list(stores.values()),
        "adapter_health": {
            "name": adapter.name,
            "endpoint": adapter.mcp_endpoint,
            "is_configured": adapter.health.is_configured,
            "status": adapter.status,
            "rate_limit_per_minute": adapter.rate_limit_per_minute,
            "timeout_seconds": adapter.timeout_seconds,
            "max_retries": adapter.max_retries,
            "total_requests": adapter.health.total_requests,
            "failed_requests": adapter.health.failed_requests,
            "note": "Stage 1 performs no provider requests; health is a configuration snapshot.",
        },
        "products": products_out,
    }


def write_markdown(report: dict, path: Path) -> None:
    lines: list[str] = []
    t = report["totals"]
    m = report["metrics"]
    ah = report["adapter_health"]

    lines.append("# Phase 16.6 — Stage 1: Beauty Catalogue Coverage Audit")
    lines.append("")
    lines.append(f"**Generated:** {report['generated_at']}")
    lines.append(f"**Audited database:** `{report['database_path']}`")
    lines.append(
        "**Method:** offline inspection of the canonical seeded catalogue and its "
        "offers/observations. No provider requests were made in this stage."
    )
    lines.append("")
    lines.append("## Category definitions (mutually exclusive, precedence order)")
    lines.append("")
    for cat in CATEGORY_PRECEDENCE:
        lines.append(f"- **{cat}** — {CATEGORY_DESCRIPTIONS[cat]}")
    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    lines.append(f"| Beauty products (non-electronics, active) | {t['beauty_products']} |")
    for cat in CATEGORY_PRECEDENCE:
        lines.append(f"| {cat} | {t[cat]} |")
    lines.append("")
    lines.append("## Pipeline metrics")
    lines.append("")
    lines.append("| Metric | Count |")
    lines.append("|---|---|")
    lines.append(f"| Products searched (this stage) | {m['products_searched']} |")
    lines.append(f"| Products with provider results | {m['products_with_provider_results']} |")
    lines.append(f"| Products with accepted matches | {m['products_with_accepted_matches']} |")
    lines.append(f"| Products with rejected matches | {m['products_with_rejected_matches']} |")
    lines.append(f"| Products requiring manual review | {m['products_requiring_manual_review']} |")
    lines.append(f"| Products without any usable price | {m['products_without_any_usable_price']} |")
    lines.append("")
    lines.append("## Phase 16.7 coverage metrics")
    lines.append("")
    p7 = report.get("phase16_7_metrics", {})
    lines.append("| Metric | Value |")
    lines.append("|---|---|")
    lines.append(f"| Products with verified usable live offers | {p7.get('products_with_verified_usable_offers', 0)} |")
    lines.append(f"| Products with possible matches only | {p7.get('products_with_possible_matches_only', 0)} |")
    lines.append(f"| Products with stale observations only | {p7.get('products_with_stale_observations_only', 0)} |")
    lines.append(f"| Products without observations | {p7.get('products_without_observations', 0)} |")
    lines.append(f"| Products with verified matches still not usable | {p7.get('products_with_verified_matches_only_pending', 0)} |")
    lines.append(f"| Total exact matches | {p7.get('total_exact_matches', 0)} |")
    lines.append(f"| Total strong matches | {p7.get('total_strong_matches', 0)} |")
    lines.append(f"| Total possible matches | {p7.get('total_possible_matches', 0)} |")
    lines.append(f"| Total rejected matches | {p7.get('total_rejected_matches', 0)} |")
    lines.append(f"| Exact-match rate | {p7.get('exact_match_rate') if p7.get('exact_match_rate') is not None else 'n/a'} |")
    lines.append(f"| Verified-match rate | {p7.get('verified_match_rate') if p7.get('verified_match_rate') is not None else 'n/a'} |")
    lines.append(f"| Rejection rate | {p7.get('rejection_rate') if p7.get('rejection_rate') is not None else 'n/a'} |")
    lines.append(f"| Fresh observations | {p7.get('total_fresh_observations', 0)} |")
    lines.append(f"| Stale observations | {p7.get('total_stale_observations', 0)} |")
    lines.append(f"| Verified usable offers | {p7.get('total_verified_usable_offers', 0)} |")
    lines.append(f"| Provider failure rate | {p7.get('provider_failure_rate') if p7.get('provider_failure_rate') is not None else 'not computable offline'} |")
    lines.append("")
    lines.append("_Possible matches are never counted as verified offers. Rates are over evaluated matches only._")
    lines.append("")
    lines.append("## PriceInIndia adapter health (configuration snapshot)")
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Name | {ah['name']} |")
    lines.append(f"| Endpoint | `{ah['endpoint']}` |")
    lines.append(f"| Configured | {ah['is_configured']} |")
    lines.append(f"| Status | {ah['status']} |")
    lines.append(f"| Rate limit | {ah['rate_limit_per_minute']} req/min |")
    lines.append(f"| Timeout | {ah['timeout_seconds']}s |")
    lines.append(f"| Max retries | {ah['max_retries']} |")
    lines.append(f"| Requests made (stage 1) | {ah['total_requests']} |")
    lines.append("")
    lines.append("## Per-product coverage")
    lines.append("")
    lines.append("| ID | Title | Brand | Category | Size | Formulation | Concentration | "
                 "Shade | Offers | Observations | Coverage |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for p in report["products"]:
        conc = ", ".join(p["concentration"]) or "—"
        lines.append(
            f"| {p['id']} | {p['title'][:58]} | {p['brand']} | {p['category']} "
            f"| {p['net_quantity'] or '—'} | {p['formulation'] or '—'} | {conc} "
            f"| {p['shade'] or '—'} | {p['offers_count']} ({p['demo_offers_count']} demo) "
            f"| {p['observations_count']} | {p['coverage_category']} |"
        )
    lines.append("")
    lines.append("## Observation detail (non-empty only)")
    lines.append("")
    any_obs = False
    for p in report["products"]:
        if not p["observations"]:
            continue
        any_obs = True
        lines.append(f"### {p['id']} — {p['title']}")
        lines.append("")
        lines.append("| Obs ID | Retailer | Status | Verification | Price | Type | Created |")
        lines.append("|---|---|---|---|---|---|---|")
        for o in p["observations"]:
            lines.append(
                f"| {o['id']} | {o['retailer']} | {o['observation_status']} "
                f"| {o['verification_status']} | {o['price']} | {o['observation_type']} "
                f"| {o['created_at']} |"
            )
        lines.append("")
    if not any_obs:
        lines.append("_No observations exist in the audited database._")
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 16.6 Stage 1 coverage audit")
    parser.add_argument("--db", help="Audit an existing database instead of a fresh seed")
    parser.add_argument("--json", dest="json_path", default=str(REPO_ROOT / "data" / "phase16_6_coverage.json"))
    parser.add_argument("--markdown", default=str(REPO_ROOT / "PHASE_16_6_STAGE_1_COVERAGE_AUDIT.md"))
    args = parser.parse_args()

    temp_db: str | None = None
    if args.db:
        db_path = args.db
    else:
        fd, temp_db = tempfile.mkstemp(suffix=".db", prefix="pricewise-audit-")
        os.close(fd)
        os.remove(temp_db)
        seed_database(custom_path=temp_db, force=True)
        db_path = temp_db

    try:
        report = audit_database(db_path)
        Path(args.json_path).write_text(
            json.dumps(report, indent=2, default=str), encoding="utf-8"
        )
        write_markdown(report, Path(args.markdown))
        print(json.dumps({"totals": report["totals"], "metrics": report["metrics"]}, indent=2))
        print(f"json -> {args.json_path}")
        print(f"markdown -> {args.markdown}")
    finally:
        if temp_db:
            Path(temp_db).unlink(missing_ok=True)
            Path(temp_db + "-wal").unlink(missing_ok=True)
            Path(temp_db + "-shm").unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
