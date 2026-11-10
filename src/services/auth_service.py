"""Authentication and User Account Service for PriceWise AI (Phase 7).

Provides:
- Secure password hashing using PBKDF2-HMAC-SHA256 (NIST/OWASP standard, salted)
- Constant-time password verification to prevent timing attacks
- User registration with normalized email and input validation
- User login with status check and generic credential error messaging
- Profile update and password change operations
- Session state management helpers for Streamlit
"""

from datetime import datetime, timezone
import hashlib
import os
import re
import secrets
from typing import Optional

from src.database.connection import get_connection, migrate_db
from src.database.models import User

# PBKDF2 parameters (OWASP recommended baseline)
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 260_000
SALT_BYTES = 16

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def hash_password(password: str) -> str:
    """
    Hash a plaintext password using salted PBKDF2-HMAC-SHA256.
    Returns: 'pbkdf2:sha256:260000$<salt_hex>$<hash_hex>'
    """
    if not password:
        raise ValueError("Password cannot be empty.")
    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM,
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2:{PBKDF2_ALGORITHM}:{PBKDF2_ITERATIONS}${salt.hex()}${derived.hex()}"


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """
    Verify a plaintext password against a stored PBKDF2 hash using constant-time comparison.
    """
    if not plain_password or not stored_hash:
        return False

    try:
        parts = stored_hash.split("$")
        if len(parts) != 3:
            return False

        header, salt_hex, expected_hex = parts
        _, algo, iters_str = header.split(":")
        iterations = int(iters_str)
        salt = bytes.fromhex(salt_hex)

        derived = hashlib.pbkdf2_hmac(
            algo,
            plain_password.encode("utf-8"),
            salt,
            iterations,
        )
        return secrets.compare_digest(derived.hex(), expected_hex)
    except Exception:
        return False


def normalize_email(email: str) -> str:
    """Normalize email address by trimming whitespace and lowercasing."""
    return email.strip().lower() if email else ""


def validate_email_format(email: str) -> bool:
    """Validate standard email structure."""
    if not email:
        return False
    return bool(EMAIL_REGEX.match(email.strip()))


def register_user(
    email: str,
    password: str,
    display_name: str,
    custom_path: Optional[str] = None,
) -> tuple[bool, str, Optional[User]]:
    """
    Register a new user account with hashed password and normalized email.
    
    Returns:
        (success: bool, message: str, user: Optional[User])
    """
    clean_name = (display_name or "").strip()
    clean_email = normalize_email(email)

    # 1. Validation
    if not clean_name:
        return False, "Display name is required.", None
    if len(clean_name) < 2:
        return False, "Display name must be at least 2 characters.", None

    if not clean_email or not validate_email_format(clean_email):
        return False, "Please enter a valid email address.", None

    if not password:
        return False, "Password is required.", None
    if len(password) < 6:
        return False, "Password must be at least 6 characters long.", None

    migrate_db(custom_path)

    pwd_hash = hash_password(password)
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()

        # 2. Check for duplicate email
        cursor.execute("SELECT id FROM users WHERE email = ?", (clean_email,))
        if cursor.fetchone():
            return False, "An account with this email address already exists.", None

        # 3. Insert user
        cursor.execute(
            """
            INSERT INTO users (display_name, email, password_hash, created_at, status)
            VALUES (?, ?, ?, ?, 'active')
            """,
            (clean_name, clean_email, pwd_hash, now_str),
        )
        user_id = cursor.lastrowid

        # 4. Initialize default user preferences row
        cursor.execute(
            """
            INSERT INTO user_preferences (user_id, preferred_categories, preferred_brands, updated_at)
            VALUES (?, '[]', '[]', ?)
            """,
            (user_id, now_str),
        )

        user = User(
            id=user_id,
            display_name=clean_name,
            email=clean_email,
            password_hash=pwd_hash,
            created_at=now_str,
            status="active",
            is_admin=False,
            token_version=0,
        )

    return True, "Account registered successfully.", user


def authenticate_user(
    email: str,
    password: str,
    custom_path: Optional[str] = None,
) -> tuple[bool, str, Optional[User]]:
    """
    Authenticate a user by email and password.
    Returns:
        (success: bool, message: str, user: Optional[User])
    """
    clean_email = normalize_email(email)
    if not clean_email or not password:
        return False, "Please provide both email and password.", None

    migrate_db(custom_path)

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, display_name, email, password_hash, created_at, status, is_admin, token_version
            FROM users
            WHERE email = ?
            """,
            (clean_email,),
        )
        row = cursor.fetchone()

        if not row:
            # Generic error to prevent account enumeration
            return False, "Invalid email address or password.", None

        stored_hash = str(row["password_hash"])
        if not verify_password(password, stored_hash):
            return False, "Invalid email address or password.", None

        if row["status"] != "active":
            return False, "Account is currently suspended or inactive.", None

        user = User(
            id=row["id"],
            display_name=str(row["display_name"]),
            email=str(row["email"]),
            password_hash=stored_hash,
            created_at=str(row["created_at"]),
            status=str(row["status"]),
            is_admin=bool(row["is_admin"]),
            token_version=int(row["token_version"] or 0),
        )

    return True, "Authentication successful.", user


def get_user_by_id(
    user_id: int,
    custom_path: Optional[str] = None,
) -> Optional[User]:
    """Retrieve user by primary key ID."""
    migrate_db(custom_path)

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, display_name, email, password_hash, created_at, status, is_admin, token_version FROM users WHERE id = ?",
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return User(
            id=row["id"],
            display_name=str(row["display_name"]),
            email=str(row["email"]),
            password_hash=str(row["password_hash"]),
            created_at=str(row["created_at"]),
            status=str(row["status"]),
            is_admin=bool(row["is_admin"]),
            token_version=int(row["token_version"] or 0),
        )


def get_user_by_email(
    email: str,
    custom_path: Optional[str] = None,
) -> Optional[User]:
    """Retrieve user by normalized email address."""
    clean_email = normalize_email(email)
    if not clean_email:
        return None

    migrate_db(custom_path)

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, display_name, email, password_hash, created_at, status, is_admin, token_version FROM users WHERE email = ?",
            (clean_email,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        return User(
            id=row["id"],
            display_name=str(row["display_name"]),
            email=str(row["email"]),
            password_hash=str(row["password_hash"]),
            created_at=str(row["created_at"]),
            status=str(row["status"]),
            is_admin=bool(row["is_admin"]),
            token_version=int(row["token_version"] or 0),
        )


def update_user_profile(
    user_id: int,
    display_name: str,
    custom_path: Optional[str] = None,
) -> tuple[bool, str]:
    """Update user's display name."""
    clean_name = (display_name or "").strip()
    if not clean_name:
        return False, "Display name cannot be empty."
    if len(clean_name) < 2:
        return False, "Display name must be at least 2 characters."

    migrate_db(custom_path)

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            (clean_name, user_id),
        )
        if cursor.rowcount == 0:
            return False, "User account not found."

    return True, "Profile updated successfully."


def change_password(
    user_id: int,
    current_password: str,
    new_password: str,
    custom_path: Optional[str] = None,
) -> tuple[bool, str]:
    """Change a user's password with current password verification."""
    if not current_password or not new_password:
        return False, "Both current and new passwords are required."
    if len(new_password) < 6:
        return False, "New password must be at least 6 characters long."

    user = get_user_by_id(user_id, custom_path=custom_path)
    if not user:
        return False, "User account not found."

    if not verify_password(current_password, user.password_hash):
        return False, "Current password is incorrect."

    new_hash = hash_password(new_password)

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE users SET password_hash = ?, token_version = token_version + 1 WHERE id = ?",
            (new_hash, user_id),
        )

    return True, "Password changed successfully."


# =====================================================================
# Phase 7: Cryptographically Signed Session Token Management
# =====================================================================

import base64
import json
import time

from src.config import MissingSessionSecretError, get_session_secret

DEFAULT_SESSION_DURATION_SECONDS = 7 * 24 * 3600  # 7 days

# Phase 14 Stage 2.5 (FIX 1): the signing secret is resolved centrally by
# src.config.get_session_secret(). There is no hardcoded fallback value here,
# so a publicly known secret can never be used to sign or verify tokens.
#
# The secret is read from AUTH_SECRET_KEY (canonical) or SECRET_KEY (legacy
# alias). In production/staging a missing secret raises
# MissingSessionSecretError; in development an ephemeral per-process secret is
# generated instead. Rotating the secret invalidates all issued sessions.


def _base64url_encode(data: bytes) -> str:
    """Encode bytes to base64url string without trailing padding."""
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(s: str) -> bytes:
    """Decode base64url string with reinstated padding."""
    rem = len(s) % 4
    if rem:
        s += "=" * (4 - rem)
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def _sign_payload(payload_b64: str, secret: str) -> str:
    """Compute the base64url HMAC-SHA256 signature for a payload segment.

    The secret is supplied by the caller (resolved through
    src.config.get_session_secret) so that a missing secret is detected once,
    up-front, instead of being silently interpreted as a rejected token.
    """
    sig = hashlib.pbkdf2_hmac("sha256", payload_b64.encode("utf-8"), secret.encode("utf-8"), 1)
    return _base64url_encode(sig)


def generate_session_token(
    user_id: int,
    email: str,
    expires_in_seconds: int = DEFAULT_SESSION_DURATION_SECONDS,
    token_version: int = 0,
) -> str:
    """
    Generate an HMAC-SHA256 signed session token for authenticated user.
    Token format: base64url(payload).base64url(signature)

    ``token_version`` is embedded in the payload. Incrementing the stored
    value invalidates every previously issued token (used when credentials
    change).
    """
    now = int(time.time())
    payload = {
        "user_id": user_id,
        "email": normalize_email(email),
        "iat": now,
        "exp": now + expires_in_seconds,
        "ver": int(token_version or 0),
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _base64url_encode(payload_bytes)

    # Resolve the signing secret up-front: signing must never happen with an
    # unconfigured secret.
    secret = get_session_secret()

    # Compute HMAC-SHA256 signature
    sig_b64 = _sign_payload(payload_b64, secret)

    return f"{payload_b64}.{sig_b64}"


def verify_session_token(token: str) -> Optional[dict]:
    """
    Verify signature and expiration of an HMAC-SHA256 signed session token.
    Returns payload dictionary if valid, or None if expired / tampered.

    Raises MissingSessionSecretError when the signing secret is not configured
    in a secured environment: a configuration fault must be reported as such
    instead of masquerading as a rejected session.
    """
    if not token or not isinstance(token, str):
        return None

    # Resolve the signing secret before parsing the token so that a missing
    # secret fails loudly for every verification attempt.
    secret = get_session_secret()

    try:
        parts = token.strip().split(".")
        if len(parts) != 2:
            return None

        payload_b64, sig_b64 = parts
        expected_b64 = _sign_payload(payload_b64, secret)

        # Constant-time comparison prevents timing attacks
        if not secrets.compare_digest(sig_b64, expected_b64):
            return None

        payload_bytes = _base64url_decode(payload_b64)
        payload = json.loads(payload_bytes.decode("utf-8"))

        now = int(time.time())
        if payload.get("exp", 0) < now:
            return None  # Expired token

        return payload
    except MissingSessionSecretError:
        # Fail closed and loudly: an unconfigured secret in a secured
        # environment must not be mistaken for "token rejected".
        raise
    except Exception:
        return None


def get_authenticated_user_from_token(
    token: str,
    custom_path: Optional[str] = None,
) -> Optional[User]:
    """Verify session token and retrieve active User object from database."""
    payload = verify_session_token(token)
    if not payload:
        return None

    user_id = payload.get("user_id")
    if not user_id:
        return None

    user = get_user_by_id(user_id, custom_path=custom_path)
    if not user or not user.is_active:
        return None

    # Phase 14 Stage B: a token whose embedded version no longer matches the
    # stored value has been revoked (for example because the password changed).
    if int(payload.get("ver", 0)) != int(user.token_version or 0):
        return None

    return user


