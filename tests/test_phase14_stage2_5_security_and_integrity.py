"""Phase 14 Stage 2.5: Security and database integrity recovery tests.

Covers the two critical issues fixed in Stage 2.5:

FIX 1 — Authentication secret
  * No publicly known fallback secret survives anywhere in the source tree.
  * Token signing and verification use ONE consistently configured secret.
  * A missing secret in a secured environment (production / staging) fails
    closed instead of silently using a default.
  * Rotating the secret invalidates previously issued sessions.
  * Secret values are never logged, printed or returned by the API layer.

FIX 2 — Product archival integrity
  * Schema migrations never reactivate or archive a product.
  * Archived products stay archived; active beauty products stay active.
  * Repeated migration calls do not change archival status.
  * Migrations are idempotent and run at most once per database per process,
    so authenticated requests do not repeatedly execute DDL.
  * Existing offers, price history and user references remain intact.

Run with:
    python -m pytest tests/test_phase14_stage2_5_security_and_integrity.py -v
"""

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

import src.config as config
from src.config import (
    MissingSessionSecretError,
    get_session_secret,
    is_session_secret_configured,
    validate_session_secret_configuration,
)
from src.services.auth_service import generate_session_token, verify_session_token
from src.database import connection as db_connection
from src.database.connection import get_connection, init_db, migrate_db
from src.database.product_archival import (
    DEFAULT_ARCHIVED_PRODUCT_IDS,
    apply_default_archival,
    archive_products,
    get_archival_summary,
    restore_products,
)

# Secrets that were previously published in the repository. They must never
# appear in the source tree again.
LEGACY_PUBLIC_SECRETS = (
    "pricewise_beauty_super_secret_session_key_2026",
    "pricewise-dev-secret-key-phase12-change-in-prod",
)


# ==============================================================================
# FIX 1 — Authentication secret
# ==============================================================================


def test_no_publicly_known_fallback_secret_remains_in_source():
    """No previously published default secret may survive anywhere in src/."""
    offenders = []
    for path in (BASE_DIR / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for secret in LEGACY_PUBLIC_SECRETS:
            if secret in text:
                offenders.append(f"{path.relative_to(BASE_DIR)} contains a published secret")
    assert not offenders, "Published fallback secrets still present: " + "; ".join(offenders)


def test_session_secret_prefers_canonical_auth_secret_key(monkeypatch):
    """AUTH_SECRET_KEY is the canonical variable and takes precedence."""
    monkeypatch.setenv("AUTH_SECRET_KEY", "canonical-secret-value")
    monkeypatch.setenv("SECRET_KEY", "legacy-secret-value")
    assert get_session_secret() == "canonical-secret-value"
    assert is_session_secret_configured() is True


def test_session_secret_accepts_legacy_alias(monkeypatch):
    """SECRET_KEY remains honoured as a backwards-compatible alias."""
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY", "legacy-secret-value")
    assert get_session_secret() == "legacy-secret-value"
    assert is_session_secret_configured() is True


def test_missing_secret_fails_closed_in_staging(monkeypatch):
    """Staging must refuse to operate without an operator-supplied secret."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(MissingSessionSecretError):
        get_session_secret()
    with pytest.raises(MissingSessionSecretError):
        validate_session_secret_configuration()


def test_missing_secret_fails_closed_in_production(monkeypatch):
    """Production must refuse to operate without an operator-supplied secret."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(MissingSessionSecretError):
        get_session_secret()


def test_missing_secret_error_does_not_leak_a_secret_value(monkeypatch):
    """The failure message must not contain any secret material."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    try:
        get_session_secret()
    except MissingSessionSecretError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive
        pytest.fail("MissingSessionSecretError was not raised")

    for secret in LEGACY_PUBLIC_SECRETS:
        assert secret not in message
    assert "AUTH_SECRET_KEY" in message


def test_development_environment_uses_ephemeral_secret(monkeypatch):
    """Development must not fall back to a published constant."""
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)

    secret = get_session_secret()
    assert secret, "development secret must not be empty"
    for published in LEGACY_PUBLIC_SECRETS:
        assert published not in secret
    # The ephemeral secret is stable for the lifetime of the process so that
    # tokens issued in one call can be verified in another.
    assert get_session_secret() == secret


def test_token_round_trip_uses_the_configured_secret(monkeypatch):
    """A token signed with the configured secret verifies successfully."""
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-signing-secret")
    monkeypatch.delenv("SECRET_KEY", raising=False)

    token = generate_session_token(user_id=7, email="User@Example.com")
    payload = verify_session_token(token)

    assert payload is not None, "a freshly issued token must verify"
    assert payload["user_id"] == 7
    assert payload["email"] == "user@example.com"


def test_rotating_the_secret_invalidates_existing_sessions(monkeypatch):
    """Rotating the signing secret must invalidate previously issued tokens."""
    monkeypatch.setenv("AUTH_SECRET_KEY", "secret-before-rotation")
    token = generate_session_token(user_id=42, email="user@example.com")
    assert verify_session_token(token) is not None

    monkeypatch.setenv("AUTH_SECRET_KEY", "secret-after-rotation")
    assert verify_session_token(token) is None, (
        "a token signed with the previous secret must not validate after rotation"
    )

    # New tokens signed with the rotated secret work normally.
    new_token = generate_session_token(user_id=42, email="user@example.com")
    assert verify_session_token(new_token) is not None


def test_tampered_token_is_rejected(monkeypatch):
    """A tampered token must never validate."""
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-signing-secret")
    token = generate_session_token(user_id=1, email="user@example.com")
    tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
    assert verify_session_token(tampered) is None


def test_expired_token_is_rejected(monkeypatch):
    """An expired token must never validate."""
    monkeypatch.setenv("AUTH_SECRET_KEY", "unit-test-signing-secret")
    token = generate_session_token(
        user_id=1, email="user@example.com", expires_in_seconds=-10
    )
    assert verify_session_token(token) is None


def test_verification_fails_loudly_when_secret_is_missing(monkeypatch):
    """A missing secret must not be mistaken for "token rejected"."""
    monkeypatch.setenv("ENVIRONMENT", "staging")
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(MissingSessionSecretError):
        verify_session_token("any.token.value")


def test_signing_fails_loudly_when_secret_is_missing(monkeypatch):
    """Tokens must never be signed without a configured secret."""
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.delenv("AUTH_SECRET_KEY", raising=False)
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(MissingSessionSecretError):
        generate_session_token(user_id=1, email="user@example.com")


# ==============================================================================
# FIX 2 — Product archival integrity
# ==============================================================================


def _scratch_db(tmp_path, products):
    """Create a scratch SQLite database seeded with the given product rows.

    products: iterable of (id, title, is_active)
    """
    path = tmp_path / "scratch.db"
    init_db(str(path))
    migrate_db(str(path), force=True)

    with sqlite3.connect(str(path)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for product_id, title, is_active in products:
            conn.execute(
                "INSERT INTO products (id, sku, title, brand, category, description, "
                "specs_json, image_url, created_at, is_active) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)",
                (
                    product_id,
                    f"SKU-{product_id}",
                    title,
                    "TestBrand",
                    "Serum",
                    "Scratch product",
                    "{}",
                    None,
                    1 if is_active else 0,
                ),
            )
        conn.commit()
    return str(path)


def _archival_state(path):
    """Return {product_id: is_active} for the given database."""
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT id, is_active FROM products ORDER BY id").fetchall()
    return {int(r["id"]): int(r["is_active"]) for r in rows}


def test_migration_does_not_reactivate_archived_products(tmp_path):
    """FIX 2: a migration must never bring an archived product back."""
    path = _scratch_db(
        tmp_path,
        [
            (12, "Active Beauty Serum", True),
            (13, "Archived Beauty Cream", False),
            (998, "Archived Fixture", False),
        ],
    )

    before = _archival_state(path)
    migrate_db(path, force=True)
    after = _archival_state(path)

    assert after == before
    assert after[13] == 0, "archived product was reactivated by the migration"
    assert after[998] == 0, "archived fixture was reactivated by the migration"
    assert after[12] == 1, "active beauty product was archived by the migration"


def test_migration_never_archives_or_activates_by_id_threshold(tmp_path):
    """FIX 2: archival must not be driven by numeric ID ranges."""
    path = _scratch_db(
        tmp_path,
        [
            (5, "Low Id But Active", True),      # below the legacy threshold
            (12, "Threshold Id Active", True),   # exactly on the threshold
            (500, "High Id Active", True),       # far above the threshold
            (9000, "Very High Id Active", True),
        ],
    )

    before = _archival_state(path)
    migrate_db(path, force=True)
    after = _archival_state(path)

    assert after == before, "migration changed archival state based on ID ranges"
    assert all(after[pid] == 1 for pid in (5, 12, 500, 9000))


def test_repeated_migrations_do_not_change_archival_status(tmp_path):
    """FIX 2: repeated migration calls must be a no-op for business data."""
    path = _scratch_db(
        tmp_path,
        [
            (12, "Active Beauty Serum", True),
            (13, "Archived Beauty Cream", False),
            (999, "Archived Fixture", False),
        ],
    )

    baseline = _archival_state(path)
    for _ in range(5):
        migrate_db(path, force=True)
        assert _archival_state(path) == baseline, (
            "repeated migration changed the archival status of a product"
        )


def test_migration_is_idempotent_for_schema(tmp_path):
    """FIX 2: the schema itself must converge and stay converged."""
    path = _scratch_db(tmp_path, [(12, "Active Beauty Serum", True)])

    def columns():
        with sqlite3.connect(path) as conn:
            return {r[1] for r in conn.execute("PRAGMA table_info(products)")}

    migrate_db(path, force=True)
    first = columns()
    migrate_db(path, force=True)
    second = columns()

    assert first == second
    assert "is_active" in first
    assert "image_status" in first


def test_migration_runs_once_per_database_per_process(tmp_path):
    """FIX 2: authenticated requests must not repeatedly execute DDL."""
    path = _scratch_db(tmp_path, [(12, "Active Beauty Serum", True)])

    calls = []
    original = db_connection._migrate_sqlite_schema

    def counting_migrate(custom_path=None):
        calls.append(custom_path)
        return original(custom_path)

    db_connection._migrate_sqlite_schema = counting_migrate
    try:
        db_connection._MIGRATION_SIGNATURES.pop(db_connection._migration_target_key(path), None)
        migrate_db(path)
        migrate_db(path)
        migrate_db(path)
    finally:
        db_connection._migrate_sqlite_schema = original

    assert len(calls) == 1, (
        f"the migration executed {len(calls)} times for a single database; "
        "expected exactly one execution per process"
    )


def test_authenticated_request_paths_do_not_re_run_migrations(tmp_path):
    """FIX 2: the auth service layer must not trigger DDL per request."""
    from src.services.auth_service import (
        authenticate_user,
        get_user_by_id,
        register_user,
    )

    path = _scratch_db(tmp_path, [(12, "Active Beauty Serum", True)])

    calls = []
    original = db_connection._migrate_sqlite_schema

    def counting_migrate(custom_path=None):
        calls.append(custom_path)
        return original(custom_path)

    db_connection._migrate_sqlite_schema = counting_migrate
    try:
        db_connection._MIGRATION_SIGNATURES.pop(db_connection._migration_target_key(path), None)

        ok, _msg, user = register_user(
            email="stage25@example.com",
            password="Stage25Pass!",
            display_name="Stage 25 User",
            custom_path=path,
        )
        assert ok, "registration must succeed on a migrated scratch database"

        ok, _msg, authed = authenticate_user(
            email="stage25@example.com",
            password="Stage25Pass!",
            custom_path=path,
        )
        assert ok, "authentication must succeed"

        for _ in range(5):
            assert get_user_by_id(user.id, custom_path=path) is not None
    finally:
        db_connection._migrate_sqlite_schema = original

    assert len(calls) <= 1, (
        f"the schema migration executed {len(calls)} times across the auth "
        "request path; expected at most one execution per process"
    )


def test_explicit_archival_only_touches_listed_ids(tmp_path):
    """FIX 2: archival tooling must operate on explicit IDs only."""
    path = _scratch_db(
        tmp_path,
        [(12, "Beauty A", True), (13, "Beauty B", True), (14, "Beauty C", True)],
    )

    summary = archive_products([13], custom_path=path)
    state = _archival_state(path)

    assert state[13] == 0
    assert state[12] == 1
    assert state[14] == 1
    assert summary["changed_ids"] == [13]


def test_default_archival_application_is_idempotent(tmp_path):
    """FIX 2: applying the default archival set twice changes nothing."""
    path = _scratch_db(
        tmp_path,
        [(1, "Legacy Tech", True), (12, "Beauty A", True), (998, "Fixture", True)],
    )

    first = apply_default_archival(custom_path=path)
    state_after_first = _archival_state(path)
    second = apply_default_archival(custom_path=path)
    state_after_second = _archival_state(path)

    assert state_after_first == state_after_second
    assert state_after_first[1] == 0
    assert state_after_first[998] == 0
    assert state_after_first[12] == 1
    assert second["changed_ids"] == [], "second application must be a no-op"
    assert first["changed_ids"] == [1, 998]


def test_restore_only_restores_listed_ids(tmp_path):
    """FIX 2: restoring must never reactivate everything."""
    path = _scratch_db(
        tmp_path,
        [(12, "Beauty A", False), (13, "Beauty B", False), (14, "Beauty C", False)],
    )

    restore_products([13], custom_path=path)
    state = _archival_state(path)

    assert state[13] == 1
    assert state[12] == 0
    assert state[14] == 0


def test_default_archived_set_contains_no_ranges():
    """FIX 2: the archival set must be an explicit list, not a rule."""
    assert isinstance(DEFAULT_ARCHIVED_PRODUCT_IDS, tuple)
    assert all(isinstance(pid, int) for pid in DEFAULT_ARCHIVED_PRODUCT_IDS)
    assert len(set(DEFAULT_ARCHIVED_PRODUCT_IDS)) == len(DEFAULT_ARCHIVED_PRODUCT_IDS)


def test_migration_sql_files_contain_no_threshold_reactivation():
    """FIX 2: no migration script may reactivate products by ID threshold."""
    migrations_dir = BASE_DIR / "data" / "migrations"
    offenders = []
    for path in sorted(migrations_dir.glob("*.sql")):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.upper().startswith("UPDATE PRODUCTS SET IS_ACTIVE = TRUE"):
                continue
            lowered = stripped.lower()
            if ">=" in lowered or "<=" in lowered or "not in" in lowered:
                offenders.append(f"{path.name}: {stripped}")
    assert not offenders, "Threshold-based reactivation still present: " + "; ".join(offenders)


# ==============================================================================
# Live database integrity (the working copy used for Phase 14 recovery)
# ==============================================================================


def _live_db_path():
    return str(BASE_DIR / "data" / "pricewise.db")


def _live_reference_counts():
    counts = {}
    with sqlite3.connect(_live_db_path()) as conn:
        for table in ("products", "offers", "price_history", "stores", "users", "wishlist"):
            try:
                counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except sqlite3.Error:
                counts[table] = None
    return counts


def test_live_database_archived_products_remain_archived():
    """FIX 2: the real catalogue keeps its archived products after migration."""
    before = _archival_state(_live_db_path())
    archived_before = sorted(pid for pid, active in before.items() if active == 0)
    assert archived_before, "expected the live catalogue to contain archived products"

    migrate_db(force=True)
    after = _archival_state(_live_db_path())
    archived_after = sorted(pid for pid, active in after.items() if active == 0)

    assert archived_after == archived_before, (
        "the live catalogue lost or gained archived products across a migration"
    )


def test_live_database_active_beauty_products_remain_active():
    """FIX 2: active beauty products are untouched by migration."""
    before = _archival_state(_live_db_path())
    migrate_db(force=True)
    after = _archival_state(_live_db_path())

    assert after == before
    active_ids = [pid for pid, active in after.items() if active == 1]
    assert len(active_ids) == 100, (
        f"expected 100 active beauty products, found {len(active_ids)}"
    )


def test_live_database_references_remain_intact_across_migration():
    """FIX 2: offers, price history and user references survive migration."""
    counts_before = _live_reference_counts()

    migrate_db(force=True)
    migrate_db(force=True)

    counts_after = _live_reference_counts()
    assert counts_after == counts_before, (
        f"row counts changed across migration: {counts_before} -> {counts_after}"
    )

    with sqlite3.connect(_live_db_path()) as conn:
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        assert not violations, f"foreign key violations found: {violations}"

        orphaned_offers = conn.execute(
            "SELECT COUNT(*) FROM offers o LEFT JOIN products p ON o.product_id = p.id "
            "WHERE p.id IS NULL"
        ).fetchone()[0]
        assert orphaned_offers == 0, "orphaned offers detected"

        orphaned_history = conn.execute(
            "SELECT COUNT(*) FROM price_history ph LEFT JOIN offers o ON ph.offer_id = o.id "
            "WHERE o.id IS NULL"
        ).fetchone()[0]
        assert orphaned_history == 0, "orphaned price history detected"


def test_live_database_summary_reports_consistent_state():
    """FIX 2: the archival summary agrees with the raw table state."""
    summary = get_archival_summary()
    raw = _archival_state(_live_db_path())

    assert summary["total_products"] == len(raw)
    assert summary["active_count"] == sum(1 for active in raw.values() if active == 1)
    assert summary["archived_count"] == sum(1 for active in raw.values() if active == 0)
    assert set(summary["archived_ids"]) == {pid for pid, a in raw.items() if a == 0}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
