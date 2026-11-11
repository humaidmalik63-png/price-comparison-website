import os
from pathlib import Path

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = os.environ.get("PRICEWISE_DB_PATH", str(DATA_DIR / "pricewise.db"))
SCHEMA_PATH = DATA_DIR / "schema.sql"

# Application Metadata
APP_NAME = "PriceWise AI Beauty"
APP_TAGLINE = "Your beauty. Your budget. Your best match."
APP_VERSION = "1.0.0"
IS_DEMO_DATA = True
DEMO_BADGE_LABEL = "DEMO DATASET - ACADEMIC BEAUTY PROTOTYPE"
DEFAULT_CURRENCY = "₹"
DEMO_USER_EMAIL = "demo@pricewise.ai"
# Demo-user password is NEVER hardcoded. It must be supplied through the
# PRICEWISE_DEMO_USER_PASSWORD environment variable; when it is absent the
# demo account is simply not seeded and the demo-login shortcut is disabled.
DEMO_USER_PASSWORD = os.environ.get("PRICEWISE_DEMO_USER_PASSWORD")

# Price freshness policy (Phase 16.6 Stage 5) — configurable thresholds, hours.
# fresh: observed within FRESHNESS_FRESH_HOURS (default 24h)
# aging: older than fresh threshold, within FRESHNESS_AGING_HOURS (default 72h)
# stale: older than the aging threshold
FRESHNESS_FRESH_HOURS = float(os.environ.get("PRICEWISE_FRESH_HOURS", "24"))
FRESHNESS_AGING_HOURS = float(os.environ.get("PRICEWISE_AGING_HOURS", "72"))

# Clean SVG placeholder data URI for offline / fallback rendering
PRODUCT_IMAGE_FALLBACK = (
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='200' "
    "viewBox='0 0 300 200'><rect width='300' height='200' fill='%23FAF7F2'/><text x='50%25' "
    "y='45%25' dominant-baseline='middle' text-anchor='middle' font-size='42'>✨</text><text "
    "x='50%25' y='72%25' dominant-baseline='middle' text-anchor='middle' font-size='12' "
    "fill='%234A1D2F' font-family='sans-serif' font-weight='bold'>BEAUTY PRODUCT</text></svg>"
)

