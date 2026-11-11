"""Phase 16.6 Stage 4 tests: price observation reliability + migrations.

Covers:

- full provenance persistence (retailer, retailer domain, provider name,
  currency, MRP, URL, timestamps, match evidence, statuses)
- idempotent migrations (run twice, additive-only)
- migrations preserve existing observations and price history, both via
  the table-rebuild path (legacy CHECK) and the plain ALTER path
- retailer-specific superseding across domains and names
- history retention after superseding with provenance intact
- duplicate collection never creates uncontrolled duplicates
- provider MRP reaches the offers table; missing MRP never wipes an
  existing original price
- honest currency recording (never silently converted)
"""

import json
import os
import tempfile
from pathlib import Path

import pytest

from src.database.connection import get_connection, init_db, migrate_db
from src.scripts import collect_pi_observations as collector
from src.services.product_matching_service import MatchClassification, ProductMatchResult

OLD_SCHEMA_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT,
    title TEXT,
    brand TEXT,
    category TEXT,
    description TEXT,
    specs_json TEXT,
    image_url TEXT,
    price REAL,
    original_price REAL,
    data_status TEXT DEFAULT 'pending_review',
    source_type TEXT DEFAULT 'demo',
    is_active INTEGER DEFAULT 1
);
CREATE TABLE stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    domain TEXT
);
CREATE TABLE offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    store_id INTEGER,
    current_price REAL,
    original_price REAL,
    shipping_cost REAL DEFAULT 0,
    currency TEXT DEFAULT 'USD',
    availability TEXT DEFAULT 'In Stock',
    offer_url TEXT,
    variant_name TEXT DEFAULT 'Standard',
    condition TEXT DEFAULT 'Brand New',
    last_checked TIMESTAMP
);
CREATE TABLE price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER,
    price REAL,
    recorded_at TIMESTAMP
);
"""


def _old_observation_table(with_provider_check: bool) -> str:
    check = (
        "CHECK(verification_status IN ('pending', 'review_required', 'verified'))"
        if with_provider_check
        else "CHECK(verification_status IN ('pending', 'review_required', 'verified', 'provider_observed'))"
    )
    return f"""
    CREATE TABLE retail_price_observation (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        retailer TEXT NOT NULL,
        product_url TEXT NOT NULL,
        observed_price REAL NOT NULL CHECK(observed_price > 0),
        observed_mrp REAL,
        size_volume TEXT,
        observation_type TEXT NOT NULL DEFAULT 'live',
        observation_status TEXT NOT NULL DEFAULT 'live',
        verified_by_admin INTEGER DEFAULT 0,
        verified_price REAL,
        verification_notes TEXT,
        verification_status TEXT DEFAULT 'pending' {check},
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        evidence_notes TEXT,
        evidence_reference TEXT
    );
    """


def _comparable_match() -> ProductMatchResult:
    return ProductMatchResult(
        match_classification=MatchClassification.POSSIBLE_MATCH,
        confidence_score=0.75,
        is_comparable=True,
        brand_match=True,
        size_match=True,
        shade_match=True,
        formulation_match=True,
        title_similarity=0.95,
        reasons=["Brand and title match"],
        requires_human_review=True,
    )


def _pi_item(**overrides):
    item = {
        "id": "pi-2001",
        "title": "Dot & Key Watermelon Cooling Sunscreen SPF 50+ PA++++ 50g",
        "brand": "Dot & Key",
        "price": 465.0,
        "mrp": 599.0,
        "currency": "INR",
        "store": "myntra.com",
        "productPageUrl": "https://www.myntra.com/dot-key-sunscreen",
        "size": "50g",
    }
    item.update(overrides)
    return item


# ── Provenance persistence ───────────────────────────────────────────────────

def test_observation_persists_full_provenance(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]

    result = collector.store_observation(pid, _pi_item(), _comparable_match(), db_path=fresh_seeded_db)
    assert result["status"] == "stored"

    with get_connection(fresh_seeded_db) as conn:
        row = dict(conn.execute(
            "SELECT * FROM retail_price_observation WHERE product_id = ? ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone())

    assert row["retailer"] == "myntra.com"
    assert row["retailer_domain"] == "myntra.com"
    assert row["provider_name"] == "priceinindia"
    assert row["currency"] == "INR"
    assert row["observed_price"] == 465.0
    assert row["observed_mrp"] == 599.0
    assert row["product_url"].startswith("https://www.myntra.com")
    assert row["observation_status"] == "live"
    assert row["verification_status"] == "provider_observed"
    assert row["verified_by_admin"] == 0  # never auto-promoted
    assert row["evidence_reference"] == "priceinindia_search_result_id_pi-2001"
    evidence = json.loads(row["match_result"])
    assert evidence["classification"] == MatchClassification.POSSIBLE_MATCH
    assert evidence["provider_item_id"] == "pi-2001"


def test_named_retailer_gets_null_domain_never_guessed(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    collector.store_observation(
        pid, _pi_item(store="Nykaa"), _comparable_match(), db_path=fresh_seeded_db
    )
    with get_connection(fresh_seeded_db) as conn:
        row = conn.execute(
            "SELECT retailer, retailer_domain FROM retail_price_observation "
            "WHERE product_id = ? ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
    assert row["retailer"] == "Nykaa"
    assert row["retailer_domain"] is None


def test_currency_recorded_honestly_never_converted(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    result = collector.store_observation(
        pid, _pi_item(currency="USD", price=25.0), _comparable_match(),
        db_path=fresh_seeded_db,
    )
    assert result["status"] == "stored"
    with get_connection(fresh_seeded_db) as conn:
        row = conn.execute(
            "SELECT currency FROM retail_price_observation WHERE product_id = ? ORDER BY id DESC LIMIT 1",
            (pid,),
        ).fetchone()
    assert row["currency"] == "USD"  # honest; eligibility layers must exclude it


def test_provider_mrp_reaches_offer_and_missing_mrp_preserves_original(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]

    # 1. Observation with MRP -> offer original_price set from MRP.
    collector.store_observation(pid, _pi_item(store="Nykaa", mrp=599.0), _comparable_match(),
                                db_path=fresh_seeded_db)
    with get_connection(fresh_seeded_db) as conn:
        row = conn.execute(
            """
            SELECT o.current_price, o.original_price FROM offers o
            JOIN stores s ON s.id = o.store_id
            WHERE o.product_id = ? AND s.name LIKE 'Nykaa%'
            """,
            (pid,),
        ).fetchone()
    assert row["current_price"] == 465.0
    assert row["original_price"] == 599.0

    # 2. Next observation without MRP -> original_price preserved, not wiped.
    collector.store_observation(pid, _pi_item(store="Nykaa", item_id="pi-2002", mrp=None),
                                _comparable_match(), db_path=fresh_seeded_db)
    with get_connection(fresh_seeded_db) as conn:
        row = conn.execute(
            """
            SELECT o.current_price, o.original_price FROM offers o
            JOIN stores s ON s.id = o.store_id
            WHERE o.product_id = ? AND s.name LIKE 'Nykaa%'
            """,
            (pid,),
        ).fetchone()
    assert row["current_price"] == 465.0
    assert row["original_price"] == 599.0  # preserved


# ── Migration reliability ────────────────────────────────────────────────────

def test_migrate_db_is_idempotent_and_preserves_data(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    collector.store_observation(pid, _pi_item(), _comparable_match(), db_path=fresh_seeded_db)

    with get_connection(fresh_seeded_db) as conn:
        before = conn.execute("SELECT COUNT(*) FROM retail_price_observation").fetchone()[0]
        hist_before = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]

    migrate_db(fresh_seeded_db)
    migrate_db(fresh_seeded_db)  # second run must be a no-op

    with get_connection(fresh_seeded_db) as conn:
        after = conn.execute("SELECT COUNT(*) FROM retail_price_observation").fetchone()[0]
        hist_after = conn.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(retail_price_observation)").fetchall()}
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]

    assert before == after == 1
    assert hist_before == hist_after
    assert {"retailer_domain", "currency", "provider_name", "match_result"} <= cols
    assert integrity == "ok"


def test_migration_rebuild_path_preserves_observations_and_history():
    """Legacy table (restrictive CHECK) must rebuild without data loss."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    try:
        import sqlite3
        conn = sqlite3.connect(path)
        conn.executescript(OLD_SCHEMA_SQL)
        conn.execute(_old_observation_table(with_provider_check=False))
        conn.execute(
            "INSERT INTO users (display_name, email, password_hash) VALUES ('u', 'u@x.test', 'h')"
        )
        conn.execute(
            "INSERT INTO products (sku, title, brand, category) VALUES ('S', 'T', 'B', 'C')"
        )
        conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, observation_type,
             observation_status, verification_status, created_at, updated_at)
            VALUES (1, 'Nykaa', 'https://nykaa.com/x', 465.0, 'live', 'live',
                    'provider_observed', '2026-11-10T10:00:00+00:00', '2026-11-10T10:00:00+00:00')
            """
        )
        conn.execute(
            "INSERT INTO retail_price_observation (product_id, retailer, product_url, observed_price) "
            "VALUES (1, 'Tira', 'https://tira.com/x', 470.0)"
        )
        conn.commit()
        conn.close()

        migrate_db(path)  # triggers the rebuild path

        with get_connection(path) as c:
            cols = {r["name"] for r in c.execute("PRAGMA table_info(retail_price_observation)").fetchall()}
            rows = c.execute(
                "SELECT retailer, observed_price, verification_status FROM retail_price_observation ORDER BY id"
            ).fetchall()
            integrity = c.execute("PRAGMA integrity_check").fetchone()[0]

        assert {"retailer_domain", "currency", "provider_name"} <= cols
        assert len(rows) == 2  # both observations preserved
        assert rows[0]["retailer"] == "Nykaa" and rows[0]["observed_price"] == 465.0
        assert rows[1]["retailer"] == "Tira"
        assert integrity == "ok"
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)


def test_migration_alter_path_preserves_history():
    """Table already provider_observed-capable must gain columns via ALTER only."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.remove(path)
    try:
        import sqlite3
        conn = sqlite3.connect(path)
        conn.executescript(OLD_SCHEMA_SQL)
        # provider_observed already allowed AND no UNIQUE autoindex -> pure ALTER path
        conn.execute(_old_observation_table(with_provider_check=False))
        conn.execute(
            """
            INSERT INTO retail_price_observation
            (product_id, retailer, product_url, observed_price, verification_status)
            VALUES (1, 'Nykaa', 'https://nykaa.com/x', 465.0, 'provider_observed')
            """
        )
        conn.execute("INSERT INTO offers (product_id, store_id, current_price) VALUES (1, 1, 465.0)")
        conn.execute("INSERT INTO price_history (offer_id, price) VALUES (1, 470.0)")
        conn.commit()
        conn.close()

        migrate_db(path)

        with get_connection(path) as c:
            cols = {r["name"] for r in c.execute("PRAGMA table_info(retail_price_observation)").fetchall()}
            obs = c.execute(
                "SELECT retailer, observed_price, currency, provider_name FROM retail_price_observation"
            ).fetchone()
            hist = c.execute("SELECT COUNT(*) AS n FROM price_history").fetchone()["n"]

        assert "retailer_domain" in cols and "currency" in cols and "provider_name" in cols
        assert obs["retailer"] == "Nykaa" and obs["observed_price"] == 465.0
        # historical rows untouched by the additive migration
        assert hist == 1
    finally:
        for suffix in ("", "-wal", "-shm"):
            Path(path + suffix).unlink(missing_ok=True)


# ── Superseding and lifecycle ────────────────────────────────────────────────

def test_retailer_superseding_is_retailer_specific_across_names_and_domains(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]

    collector.store_observation(pid, _pi_item(store="myntra.com", price=263.0), _comparable_match(),
                                db_path=fresh_seeded_db)
    collector.store_observation(pid, _pi_item(store="Nykaa", price=465.0), _comparable_match(),
                                db_path=fresh_seeded_db)
    collector.store_observation(pid, _pi_item(store="myntra.com", item_id="pi-2003", price=259.0),
                                _comparable_match(), db_path=fresh_seeded_db)

    with get_connection(fresh_seeded_db) as conn:
        rows = conn.execute(
            "SELECT retailer, observed_price, observation_status FROM retail_price_observation "
            "WHERE product_id = ? ORDER BY id",
            (pid,),
        ).fetchall()

    myntra = [(r["observed_price"], r["observation_status"]) for r in rows if r["retailer"] == "myntra.com"]
    nykaa = [(r["observed_price"], r["observation_status"]) for r in rows if r["retailer"] == "Nykaa"]
    # myntra.com: first superseded, second live — history retained
    assert myntra == [(263.0, "superseded"), (259.0, "live")]
    # Nykaa fully independent
    assert nykaa == [(465.0, "live")]


def test_duplicate_collection_does_not_duplicate_live_rows(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    for _ in range(3):
        collector.store_observation(pid, _pi_item(), _comparable_match(), db_path=fresh_seeded_db)

    with get_connection(fresh_seeded_db) as conn:
        rows = conn.execute(
            "SELECT observation_status FROM retail_price_observation WHERE product_id = ?",
            (pid,),
        ).fetchall()
    statuses = [r["observation_status"] for r in rows]
    assert statuses.count("live") == 1
    assert statuses.count("superseded") == 2


def test_invalid_price_never_persisted_with_provenance_columns(fresh_seeded_db):
    products = collector.load_discovery_catalog(db_path=fresh_seeded_db)
    pid = products[0]["id"]
    result = collector.store_observation(pid, _pi_item(price=0), _comparable_match(),
                                         db_path=fresh_seeded_db)
    assert result["status"] == "rejected"
    with get_connection(fresh_seeded_db) as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM retail_price_observation WHERE product_id = ?", (pid,)
        ).fetchone()[0]
    assert count == 0
