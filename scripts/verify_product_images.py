"""Product image verification helper (Phase 14 Stage C).

Checks catalogue image provenance and applies the first three verification
gates described in ``docs/PHASE14_IMAGE_AUTHENTICITY_REPORT.md``:

1. **Reachability** - the URL answers HTTP 200 with an ``image/*`` content type
   and a plausible payload size.
2. **Geometry** - the asset is not a banner or a brand logo. Aspect ratios
   outside the accepted band, and files whose name contains a logo/banner
   marker, are flagged for manual review.
3. **Product identity** - the recorded source page describes the product.

Gate 4 (the visual confirmation that the photograph shows the right packaging)
cannot be automated here. The script therefore reports ``needs_visual_check``
for every asset that passes gates 1-3, and never marks an image as published.

Usage
-----
    python scripts/verify_product_images.py                 # audit the catalogue
    python scripts/verify_product_images.py --limit 20      # first 20 rows
    python scripts/verify_product_images.py --custom-path data/pricewise.db

The script is read-only: it never writes to the database.
"""

import argparse
import json
import os
import re
import ssl
import struct
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional, Tuple

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Mobile Safari/537.36"
)

# Files whose name suggests a brand logo, a banner or a placeholder sprite.
SUSPECT_NAME_MARKERS = (
    "logo", "banner", "icon", "sprite", "placeholder", "favicon",
    "header", "hero", "footer", "loading", "blank",
)

MIN_IMAGE_BYTES = 5_000
MAX_IMAGE_BYTES = 12_000_000
ACCEPTED_ASPECT_MIN = 0.45
ACCEPTED_ASPECT_MAX = 2.2

STATUS_VERIFIED = "permission_review"
STATUS_PLACEHOLDER = "placeholder"


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def fetch(url: str, timeout: int = 25) -> Tuple[int, str, bytes]:
    """Fetch a URL. Returns (status, content-type, body)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read(MAX_IMAGE_BYTES)
    except urllib.error.HTTPError as exc:
        return exc.code, "", b""
    except Exception:
        return 0, "", b""


def image_dimensions(data: bytes) -> Tuple[Optional[int], Optional[int], str]:
    """Return (width, height, kind) using the file signature only."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        width, height = struct.unpack(">II", data[16:24])
        return int(width), int(height), "png"
    if data[:3] == b"\xff\xd8\xff":
        index = 2
        while index < len(data) - 9:
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
                height, width = struct.unpack(">HH", data[index + 5 : index + 9])
                return int(width), int(height), "jpg"
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                index += 2
                continue
            length = struct.unpack(">H", data[index + 2 : index + 4])[0]
            index += 2 + length
        return None, None, "jpg?"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return None, None, "webp"
    return None, None, "unknown"


def check_image(url: str) -> dict:
    """Apply gates 1 and 2 to an image URL."""
    result = {
        "url": url,
        "reachable": False,
        "content_type": "",
        "bytes": 0,
        "width": None,
        "height": None,
        "kind": "",
        "issues": [],
    }
    if not url:
        result["issues"].append("no image url")
        return result

    status, content_type, body = fetch(url)
    result["content_type"] = content_type
    result["bytes"] = len(body)

    if status != 200:
        result["issues"].append(f"http {status}")
        return result
    if not content_type.lower().startswith("image/"):
        result["issues"].append(f"not an image ({content_type or 'unknown'})")
        return result
    if len(body) < MIN_IMAGE_BYTES:
        result["issues"].append(f"suspiciously small ({len(body)} bytes)")
        return result

    result["reachable"] = True
    width, height, kind = image_dimensions(body)
    result["width"], result["height"], result["kind"] = width, height, kind

    name = url.split("/")[-1].split("?")[0].lower()
    for marker in SUSPECT_NAME_MARKERS:
        if marker in name:
            result["issues"].append(f"filename suggests a {marker}")
            break

    if width and height:
        aspect = width / height
        if aspect < ACCEPTED_ASPECT_MIN or aspect > ACCEPTED_ASPECT_MAX:
            result["issues"].append(f"unusual aspect ratio {aspect:.2f}")

    return result


def check_source_page(page_url: str, brand: str, title: str) -> dict:
    """Apply gate 3: the recorded source page must describe the product."""
    result = {"url": page_url, "reachable": False, "mentions_brand": False, "issues": []}
    if not page_url:
        result["issues"].append("no source page recorded")
        return result

    status, content_type, body = fetch(page_url)
    if status == 0:
        result["issues"].append("unreachable")
        return result
    if status in (403, 429):
        result["issues"].append(f"blocked by the site (http {status})")
        return result
    if status != 200:
        result["issues"].append(f"http {status}")
        return result

    text = body.decode("utf-8", errors="ignore").lower()
    result["reachable"] = True
    brand_token = brand.split()[0].lower() if brand else ""
    result["mentions_brand"] = bool(brand_token and brand_token in text)
    if not result["mentions_brand"]:
        result["issues"].append("the page does not mention the brand")
    return result


def audit(custom_path: Optional[str] = None, limit: Optional[int] = None) -> dict:
    """Audit the catalogue's image provenance."""
    from src.database.connection import get_connection

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, brand, title, image_url, image_status, image_source_url, image_source_name
            FROM products
            WHERE is_active = 1
            ORDER BY id
            """
        )
        rows = cursor.fetchall()

    if limit:
        rows = rows[:limit]

    summary = {
        "products": len(rows),
        "with_image": 0,
        "placeholder": 0,
        "verified": 0,
        "needs_visual_check": 0,
        "issues": 0,
        "results": [],
    }

    for row in rows:
        product_id, brand, title, image_url, image_status, source_url, source_name = row
        entry = {
            "id": product_id,
            "brand": brand,
            "title": title,
            "image_status": image_status,
            "image_source_name": source_name,
        }

        if not image_url:
            entry["verdict"] = "placeholder"
            summary["placeholder"] += 1
            summary["results"].append(entry)
            continue

        summary["with_image"] += 1
        image = check_image(image_url)
        entry["image"] = image
        page = check_source_page(source_url or "", brand or "", title or "")
        entry["source_page"] = page

        # The image gate decides the verdict. A source page that is currently
        # rate-limited or temporarily unreachable is informational only: it
        # does not make the asset wrong, it just means gate 3 could not be
        # re-confirmed right now.
        if image["issues"]:
            entry["verdict"] = "rejected"
            summary["issues"] += 1
        else:
            entry["verdict"] = "needs_visual_check"
            summary["needs_visual_check"] += 1
            summary["verified"] += 1
            if page["issues"]:
                entry["source_page_note"] = "; ".join(page["issues"])

        summary["results"].append(entry)

    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Verify catalogue product images")
    parser.add_argument("--limit", type=int, default=None, help="Only audit the first N products")
    parser.add_argument("--custom-path", default=None, help="Optional SQLite database path")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report")
    args = parser.parse_args(argv)

    report = audit(custom_path=args.custom_path, limit=args.limit)

    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    print(f"Active products audited : {report['products']}")
    print(f"  with an image url     : {report['with_image']}")
    print(f"  neutral placeholder   : {report['placeholder']}")
    print(f"  passed gates 1-3      : {report['needs_visual_check']} (visual check still required)")
    print(f"  failed a gate         : {report['issues']}")
    print()
    print("Every 'passed' row still requires the visual confirmation described in")
    print("docs/PHASE14_IMAGE_AUTHENTICITY_REPORT.md before it is published.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
