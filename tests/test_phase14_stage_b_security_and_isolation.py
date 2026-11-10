"""Phase 14 Stage B — security hardening and test-isolation regression tests.

Covers:

1. Test isolation
   * the shared development database is never modified by the suite
   * the default database path is redirected to a temporary copy
2. Explicit administrator authorization
   * a self-registered ``@pricewise.ai`` account is NOT an administrator
   * the seeded demo account IS an administrator
   * non-administrators cannot reach the review endpoints
3. Session cookie hardening
   * the Secure attribute is set in production / staging
4. HTTP rate limiting
   * the configured budget is actually enforced
   * health probes are exempt
   * a rejected request returns 429 with Retry-After
5. Upload validation
   * the file signature is verified, not the client supplied content type
   * a disguised non-image is rejected
6. Session invalidation
   * changing the password revokes previously issued tokens
"""

import os
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi.testclient import TestClient

from src.api import rate_limit
from src.api.main import app, is_admin_user
from src.database.connection import get_connection
from src.services.auth_service import (
    change_password,
    generate_session_token,
    get_authenticated_user_from_token,
    register_user,
)


@pytest.fixture(scope="module")
def client():
    """API client bound to the isolated test database."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_limiter():
    rate_limit.reset_rate_limiter()
    yield
    rate_limit.reset_rate_limiter()


# ==============================================================================
# 1. Test isolation
# ==============================================================================


def test_default_database_path_is_redirected_to_a_temporary_copy():
    """The suite must never resolve the shared development database."""
    import src.database.connection as connection

    resolved = str(connection.DATABASE_PATH)
    shared = str((BASE_DIR / "data" / "pricewise.db").resolve())

    assert resolved != shared, (
        "the default database path still points at the shared development "
        f"database ({resolved})"
    )
    assert "pricewise_pytest_" in resolved or resolved.endswith("pricewise_test.db"), (
        f"unexpected test database path: {resolved}"
    )


def test_shared_development_database_is_not_written_by_this_module():
    """A write through the default path must land in the temporary copy."""
    import src.database.connection as connection

    ok, _msg, user = register_user(
        email="stage13_isolation_probe@example.com",
        password="IsolationPass!",
        display_name="Isolation Probe",
    )
    assert ok

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM users WHERE email = ?",
            ("stage13_isolation_probe@example.com",),
        )
        assert cursor.fetchone()[0] == 1

    # ...and the shared file itself is untouched.
    shared_path = BASE_DIR / "data" / "pricewise.db"
    if shared_path.exists():
        with get_connection(str(shared_path)) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE email = ?",
                ("stage13_isolation_probe@example.com",),
            )
            assert cursor.fetchone()[0] == 0, (
                "the test wrote directly into the shared development database"
            )


# ==============================================================================
# 2. Explicit administrator authorization
# ==============================================================================


def test_self_registered_pricewise_address_is_not_an_administrator():
    """A self-registered @pricewise.ai address must not gain review rights."""
    ok, _msg, user = register_user(
        email="intruder@pricewise.ai",
        password="IntruderPass!",
        display_name="Not An Admin",
    )
    assert ok, "registration must succeed for a non-privileged address"

    assert is_admin_user(user) is False, (
        "a self-registered @pricewise.ai account was granted administrator rights"
    )


def test_ordinary_user_is_not_an_administrator():
    ok, _msg, user = register_user(
        email="ordinary_shopper@example.com",
        password="ShopperPass!",
        display_name="Ordinary Shopper",
    )
    assert ok
    assert is_admin_user(user) is False


def test_administrator_flag_is_persisted_and_honoured():
    """The administrator flag is an explicit, persisted column."""
    ok, _msg, user = register_user(
        email="promoted_admin@example.com",
        password="AdminPass!",
        display_name="Promoted Admin",
    )
    assert ok

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user.id,))
        cursor.execute(
            "SELECT is_admin FROM users WHERE id = ?", (user.id,)
        )
        assert bool(cursor.fetchone()["is_admin"]) is True

    from src.services.auth_service import get_user_by_id

    reloaded = get_user_by_id(user.id)
    assert reloaded is not None
    assert reloaded.is_admin is True
    assert is_admin_user(reloaded) is True


def test_admin_queue_endpoint_rejects_non_administrators(client):
    """Non-administrators receive 403 from the review queue."""
    ok, _msg, user = register_user(
        email="queue_denied@example.com",
        password="QueuePass!",
        display_name="Queue Denied",
    )
    assert ok

    token = generate_session_token(user.id, user.email, token_version=user.token_version)
    response = client.get(
        "/api/admin/verifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403, (
        f"expected 403 for a non-administrator, got {response.status_code}"
    )


# ==============================================================================
# 3. Session cookie hardening
# ==============================================================================


def test_session_cookie_is_secure_in_production(monkeypatch):
    """In production the session cookie must carry the Secure attribute."""
    import importlib

    import src.config as config

    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_SECRET_KEY", "stage13-cookie-secret")

    reloaded = importlib.reload(config)
    try:
        assert reloaded.SESSION_COOKIE_SECURE is True
    finally:
        monkeypatch.undo()
        importlib.reload(config)


def test_session_cookie_is_not_secure_in_local_development(monkeypatch):
    """Plain-HTTP local development keeps the cookie usable."""
    import importlib

    import src.config as config

    monkeypatch.setenv("ENVIRONMENT", "development")
    reloaded = importlib.reload(config)
    try:
        assert reloaded.SESSION_COOKIE_SECURE is False
    finally:
        monkeypatch.undo()
        importlib.reload(config)


# ==============================================================================
# 4. HTTP rate limiting
# ==============================================================================


def test_rate_limit_budget_is_enforced(client, monkeypatch):
    """The configured per-minute budget is actually applied."""
    import src.api.rate_limit as rl

    monkeypatch.setattr(rl.rate_limiter, "requests_per_minute", 5)

    statuses = [
        client.get("/api/products").status_code for _ in range(9)
    ]

    assert 429 in statuses, (
        f"the rate limit was never enforced (statuses={statuses})"
    )
    # The first requests must still succeed.
    assert statuses[0] == 200


def test_rate_limited_response_contains_retry_after(client, monkeypatch):
    """A rejected request tells the client when to retry."""
    import src.api.rate_limit as rl

    monkeypatch.setattr(rl.rate_limiter, "requests_per_minute", 2)

    for _ in range(2):
        client.get("/api/products")

    response = client.get("/api/products")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert int(response.headers["Retry-After"]) >= 1
    assert response.json()["retry_after_seconds"] >= 1


def test_health_probes_are_exempt_from_rate_limiting(client, monkeypatch):
    """Orchestrator health probes must never be throttled."""
    import src.api.rate_limit as rl

    monkeypatch.setattr(rl.rate_limiter, "requests_per_minute", 1)

    for _ in range(6):
        response = client.get("/api/health/ready")
        assert response.status_code == 200, "health probe was throttled"


def test_rate_limit_headers_are_present(client, monkeypatch):
    """Successful responses advertise the remaining budget."""
    import src.api.rate_limit as rl

    monkeypatch.setattr(rl.rate_limiter, "requests_per_minute", 50)
    response = client.get("/api/products")
    assert "X-RateLimit-Limit" in response.headers
    assert "X-RateLimit-Remaining" in response.headers


# ==============================================================================
# 5. Upload validation
# ==============================================================================


def test_upload_rejects_a_disguised_non_image(client):
    """A non-image with an image content type must be rejected."""
    ok, _msg, user = register_user(
        email="upload_probe@example.com",
        password="UploadPass!",
        display_name="Upload Probe",
    )
    assert ok
    token = generate_session_token(user.id, user.email, token_version=user.token_version)

    payload = b"<?php echo 'not an image'; ?>"
    response = client.post(
        "/api/verification/upload-evidence",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("proof.png", payload, "image/png")},
    )
    assert response.status_code == 400, (
        f"a disguised non-image was accepted (status={response.status_code})"
    )


def test_upload_accepts_a_genuine_png(client):
    """A real PNG is accepted and stored under a high-entropy name."""
    ok, _msg, user = register_user(
        email="upload_ok@example.com",
        password="UploadOkPass!",
        display_name="Upload Ok",
    )
    assert ok
    token = generate_session_token(user.id, user.email, token_version=user.token_version)

    png = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
        b"\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    response = client.post(
        "/api/verification/upload-evidence",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": ("proof.png", png, "image/png")},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["filename"].startswith("evidence_")
    # High entropy: uuid4 hex (32 characters) instead of the previous 12.
    assert len(body["filename"]) == len("evidence_") + 32 + len(".png")


# ==============================================================================
# 6. Session invalidation
# ==============================================================================


def test_password_change_invalidates_existing_sessions():
    """Changing the password revokes previously issued session tokens."""
    ok, _msg, user = register_user(
        email="rotate_me@example.com",
        password="OriginalPass!",
        display_name="Rotate Me",
    )
    assert ok

    token = generate_session_token(user.id, user.email, token_version=user.token_version)
    assert get_authenticated_user_from_token(token) is not None

    changed, msg = change_password(user.id, "OriginalPass!", "ReplacementPass!")
    assert changed, msg

    assert get_authenticated_user_from_token(token) is None, (
        "a session token survived a password change"
    )

    # A freshly issued token works again.
    from src.services.auth_service import get_user_by_id

    fresh_user = get_user_by_id(user.id)
    fresh_token = generate_session_token(
        fresh_user.id, fresh_user.email, token_version=fresh_user.token_version
    )
    assert get_authenticated_user_from_token(fresh_token) is not None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
