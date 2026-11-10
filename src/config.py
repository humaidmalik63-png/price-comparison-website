import logging
import os
import secrets
from pathlib import Path

logger = logging.getLogger("pricewise.config")

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATABASE_PATH = os.environ.get("PRICEWISE_DB_PATH", str(DATA_DIR / "pricewise.db"))
DATABASE_URL = os.environ.get("DATABASE_URL")
SCHEMA_PATH = DATA_DIR / "schema.sql"

# Environment & Security Configuration (Phase 12)
ENVIRONMENT = os.environ.get("ENVIRONMENT", "development").lower()
IS_PRODUCTION = ENVIRONMENT in ("production", "prod")

# Phase 14 Stage 2.5 (FIX 1): environments where the session signing secret
# MUST be supplied by the operator via the environment.
# "staging" is included because it holds real accounts, wishlists and a live
# catalogue, so it must never fall back to a well-known secret.
SECRET_REQUIRED_ENVIRONMENTS = ("production", "prod", "staging")
REQUIRES_CONFIGURED_SECRET = ENVIRONMENT in SECRET_REQUIRED_ENVIRONMENTS

# Backwards-compatible alias for the session signing secret.
# It deliberately has NO built-in default value: a published default secret
# would let anyone with repository access forge arbitrary session tokens.
SECRET_KEY = (os.environ.get("SECRET_KEY") or "").strip()

RATE_LIMIT_PER_MINUTE = int(os.environ.get("RATE_LIMIT_PER_MINUTE", "120"))
MAX_UPLOAD_SIZE_BYTES = int(os.environ.get("MAX_UPLOAD_SIZE_BYTES", str(5 * 1024 * 1024)))  # 5 MB

# CORS Allowed Origins
RAW_CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "")
CORS_ORIGINS = [o.strip() for o in RAW_CORS_ORIGINS.split(",") if o.strip()]

# Gemini Configuration
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# ==============================================================================
# Session Token Signing Secret (Phase 14 Stage 2.5 — FIX 1)
# ==============================================================================
# Session tokens are signed with a single HMAC-SHA256 secret. Resolution order:
#   1. AUTH_SECRET_KEY  (canonical variable, preferred)
#   2. SECRET_KEY       (legacy alias, still honoured for backwards compatibility)
#
# There is intentionally NO built-in fallback secret:
#   * in production / staging a missing secret is a fatal configuration error
#     (MissingSessionSecretError) so the service refuses to run rather than
#     signing tokens with a value that is published in the repository;
#   * in development an ephemeral random secret is generated per process, so no
#     well-known value is ever used and restarting the process simply
#     invalidates previous development sessions.
#
# Rotating the secret invalidates every previously issued session token.

SESSION_SECRET_ENV_VARS = ("AUTH_SECRET_KEY", "SECRET_KEY")

# Process-local ephemeral secret used only when no secret is configured and the
# environment does not require one (development / test).
_EPHEMERAL_DEV_SESSION_SECRET: str | None = None


class MissingSessionSecretError(RuntimeError):
    """Raised when no session signing secret is configured in a secured environment."""


def _secret_is_required() -> bool:
    """Return True when the current environment requires an operator-supplied secret.

    Evaluated dynamically so that the requirement always reflects the live
    ENVIRONMENT value rather than the value seen at import time.
    """
    current_env = (os.environ.get("ENVIRONMENT") or "development").strip().lower()
    return current_env in SECRET_REQUIRED_ENVIRONMENTS


def get_session_secret() -> str:
    """Return the session token signing secret.

    Resolution order:
        1. ``AUTH_SECRET_KEY`` environment variable (canonical)
        2. ``SECRET_KEY`` environment variable (legacy alias)
        3. In development/test: an ephemeral random secret generated once per
           process.
        4. In production/staging: raises ``MissingSessionSecretError`` (fail
           closed) instead of falling back to a publicly known value.

    The secret value is never logged or returned in API responses.
    """
    for env_var in SESSION_SECRET_ENV_VARS:
        value = (os.environ.get(env_var) or "").strip()
        if value:
            return value

    if _secret_is_required():
        raise MissingSessionSecretError(
            "No session signing secret is configured. Set the AUTH_SECRET_KEY "
            "environment variable (or the legacy alias SECRET_KEY) before "
            f"starting the service in the '{ENVIRONMENT}' environment. "
            "Refusing to sign session tokens with an unconfigured secret."
        )

    global _EPHEMERAL_DEV_SESSION_SECRET
    if _EPHEMERAL_DEV_SESSION_SECRET is None:
        _EPHEMERAL_DEV_SESSION_SECRET = secrets.token_urlsafe(48)
        logger.warning(
            "AUTH_SECRET_KEY / SECRET_KEY are not set. Generated an ephemeral "
            "development-only session secret; sessions will be invalidated when "
            "the process restarts."
        )
    return _EPHEMERAL_DEV_SESSION_SECRET


def validate_session_secret_configuration() -> None:
    """Fail fast when the session signing secret is missing in a secured environment.

    Safe to call at application start-up. Raises ``MissingSessionSecretError``
    when the environment requires an operator-supplied secret and none is set.
    """
    get_session_secret()


def is_session_secret_configured() -> bool:
    """Return True when an operator-supplied session secret is present."""
    return any((os.environ.get(name) or "").strip() for name in SESSION_SECRET_ENV_VARS)


# Application Metadata
APP_NAME = "PriceWise AI Beauty"
APP_TAGLINE = "Your beauty. Your budget. Your best match."
APP_VERSION = "1.0.0"
IS_DEMO_DATA = True
DEMO_BADGE_LABEL = "DEMO DATASET - ACADEMIC BEAUTY PROTOTYPE"
DEFAULT_CURRENCY = "₹"
DEMO_USER_EMAIL = "demo@pricewise.ai"
DEMO_USER_PASSWORD = "DemoPass123!"

# Clean SVG placeholder data URI for offline / fallback rendering
PRODUCT_IMAGE_FALLBACK = (
    "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='300' height='200' "
    "viewBox='0 0 300 200'><rect width='300' height='200' fill='%23FAF7F2'/><text x='50%25' "
    "y='45%25' dominant-baseline='middle' text-anchor='middle' font-size='42'>✨</text><text "
    "x='50%25' y='72%25' dominant-baseline='middle' text-anchor='middle' font-size='12' "
    "fill='%234A1D2F' font-family='sans-serif' font-weight='bold'>BEAUTY PRODUCT</text></svg>"
)
