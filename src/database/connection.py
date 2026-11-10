import hashlib
import logging
import os
import sqlite3
from contextlib import contextmanager
from typing import Generator, Any
from pathlib import Path
from src.config import DATABASE_PATH, DATABASE_URL, SCHEMA_PATH

logger = logging.getLogger("pricewise.db")


def get_database_engine_type() -> str:
    """Return 'postgresql' if DATABASE_URL is configured for postgres, else 'sqlite'."""
    url = (os.environ.get("DATABASE_URL") or DATABASE_URL or "").strip()
    if url.startswith("postgres://") or url.startswith("postgresql://"):
        return "postgresql"
    return "sqlite"


class DualRow(dict):
    """Row wrapper supporting both column name indexing and integer position indexing."""
    def __init__(self, cols, vals):
        super().__init__(zip(cols, vals))
        self._vals = tuple(vals)

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._vals[key]
        return super().__getitem__(key)


def dual_row_factory(cursor):
    if cursor.description is None:
        return lambda vals: vals
    cols = [d.name for d in cursor.description]
    def make_row(vals):
        return DualRow(cols, vals)
    return make_row


class PostgresCompatCursor:
    """Cursor wrapper adapting SQLite qmark '?' parameter style and lastrowid to PostgreSQL."""
    def __init__(self, raw_cur, raw_conn):
        self._cur = raw_cur
        self._conn = raw_conn

    def execute(self, query: str, params=None):
        clean_q = query
        if params is not None and "?" in clean_q:
            clean_q = clean_q.replace("?", "%s")
        if params is not None:
            return self._cur.execute(clean_q, params)
        return self._cur.execute(clean_q)

    def executemany(self, query: str, params_seq):
        clean_q = query
        if "?" in clean_q:
            clean_q = clean_q.replace("?", "%s")
        return self._cur.executemany(clean_q, params_seq)

    @property
    def lastrowid(self):
        try:
            with self._conn.cursor() as cur:
                cur.execute("SELECT lastval();")
                row = cur.fetchone()
                return row[0] if row else None
        except Exception:
            return None

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        return self._cur.fetchmany(size) if size else self._cur.fetchmany()

    @property
    def description(self):
        return self._cur.description

    @property
    def rowcount(self):
        return self._cur.rowcount

    def close(self):
        return self._cur.close()

    def __iter__(self):
        return iter(self._cur)


class PostgresCompatConnection:
    """Connection wrapper adapting psycopg to standard DB-API row factory & cursor behavior."""
    def __init__(self, raw_conn):
        self._conn = raw_conn

    def cursor(self):
        raw_cur = self._conn.cursor(row_factory=dual_row_factory)
        return PostgresCompatCursor(raw_cur, self._conn)

    def commit(self):
        return self._conn.commit()

    def rollback(self):
        return self._conn.rollback()

    def close(self):
        return self._conn.close()

    def execute(self, query: str, params=None):
        cur = self.cursor()
        return cur.execute(query, params)


def get_db_path(custom_path: str | None = None) -> Path:
    """Return the resolved database path."""
    target = Path(custom_path) if custom_path else Path(DATABASE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@contextmanager
def get_connection(custom_path: str | None = None) -> Generator[Any, None, None]:
    """Provide a transactional database connection with row factory enabled (SQLite or PostgreSQL)."""
    db_engine = get_database_engine_type()
    if db_engine == "postgresql" and not custom_path:
        db_url = (os.environ.get("DATABASE_URL") or DATABASE_URL).strip()
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        try:
            import psycopg
            raw_conn = psycopg.connect(db_url)
            conn = PostgresCompatConnection(raw_conn)
        except ImportError:
            try:
                import psycopg2
                from psycopg2.extras import RealDictCursor
                raw_conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
                conn = PostgresCompatConnection(raw_conn)
            except ImportError:
                raise RuntimeError(
                    "PostgreSQL DATABASE_URL is configured, but neither 'psycopg' nor 'psycopg2' is installed. "
                    "Install 'psycopg' for production PostgreSQL connectivity."
                )
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        db_path = get_db_path(custom_path)
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _table_exists(cursor, table_name: str) -> bool:
    """Return True when a table is present in the current connection."""
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    )
    return cursor.fetchone() is not None


def _migrate_sqlite_schema(custom_path: str | None = None) -> None:
    """Apply idempotent SQLite schema migrations.

    Schema only: this function performs additive DDL (columns, indexes and
    tables). It never creates, archives, restores or otherwise rewrites
    business records. The archival state of individual products is business
    data and is owned by src.database.product_archival.
    """
    db_path = get_db_path(custom_path)
    with get_connection(str(db_path)) as conn:
        cursor = conn.cursor()
        # 1. Check offers table columns
        cursor.execute("PRAGMA table_info(offers)")
        existing_offer_cols = {row["name"] for row in cursor.fetchall()}
        if existing_offer_cols:
            if "variant_name" not in existing_offer_cols:
                cursor.execute("ALTER TABLE offers ADD COLUMN variant_name TEXT DEFAULT 'Standard'")
            if "condition" not in existing_offer_cols:
                cursor.execute("ALTER TABLE offers ADD COLUMN condition TEXT DEFAULT 'Brand New'")

        # 2. Check price_history table columns
        cursor.execute("PRAGMA table_info(price_history)")
        existing_hist_cols = {row["name"] for row in cursor.fetchall()}
        if existing_hist_cols:
            if "currency" not in existing_hist_cols:
                cursor.execute("ALTER TABLE price_history ADD COLUMN currency TEXT DEFAULT 'USD'")
            if "data_source" not in existing_hist_cols:
                cursor.execute("ALTER TABLE price_history ADD COLUMN data_source TEXT DEFAULT 'demo_seed'")
            if "data_status" not in existing_hist_cols:
                cursor.execute("ALTER TABLE price_history ADD COLUMN data_status TEXT DEFAULT 'demo'")

        # 2b. Check products table columns (Phase 14 Stage 2: soft-archive support column)
        # Schema only. The archival state of individual products is business
        # data: it is applied explicitly through src.database.product_archival
        # and must never be rewritten by a schema migration. Re-running a
        # migration therefore cannot reactivate an archived product.
        cursor.execute("PRAGMA table_info(products)")
        existing_product_cols = {row["name"] for row in cursor.fetchall()}
        if existing_product_cols:
            if "is_active" not in existing_product_cols:
                cursor.execute("ALTER TABLE products ADD COLUMN is_active BOOLEAN DEFAULT 1")

        # 2c. Image Provenance & Verification Columns (Phase 14 Stage 3)
        cursor.execute("PRAGMA table_info(products)")
        existing_product_cols = {row["name"] for row in cursor.fetchall()}
        if existing_product_cols:
            if "image_source_url" not in existing_product_cols:
                cursor.execute("ALTER TABLE products ADD COLUMN image_source_url TEXT")
            if "image_source_name" not in existing_product_cols:
                cursor.execute("ALTER TABLE products ADD COLUMN image_source_name TEXT")
            if "image_status" not in existing_product_cols:
                cursor.execute("ALTER TABLE products ADD COLUMN image_status TEXT DEFAULT 'placeholder'")
            if "image_last_checked" not in existing_product_cols:
                cursor.execute("ALTER TABLE products ADD COLUMN image_last_checked TIMESTAMP")

        # 3. Ensure indexes exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        if cursor.fetchone():
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active)")

        # 3b. Phase 14 Stage D: purchase-link provenance on offers.
        # Additive and idempotent. The default marks a link as unverified, so
        # the seeded demo catalogue can never be presented as a set of real
        # retailer purchase links.
        cursor.execute("PRAGMA table_info(offers)")
        existing_offer_cols = {row["name"] for row in cursor.fetchall()}
        if existing_offer_cols:
            if "link_status" not in existing_offer_cols:
                cursor.execute(
                    "ALTER TABLE offers ADD COLUMN link_status TEXT DEFAULT 'demo_not_verified'"
                )
            if "link_checked_at" not in existing_offer_cols:
                cursor.execute("ALTER TABLE offers ADD COLUMN link_checked_at TIMESTAMP")
        if _table_exists(cursor, "offers"):
            cursor.execute(
                "UPDATE offers SET link_status = 'demo_not_verified' "
                "WHERE link_status IS NULL OR link_status = ''"
            )

        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_history'")
        if cursor.fetchone():
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_history_offer_date ON price_history(offer_id, recorded_at)")

        # 4. Phase 7: Ensure users table exists
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                display_name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'suspended', 'deactivated')),
                is_admin BOOLEAN DEFAULT 0,
                token_version INTEGER DEFAULT 0
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

        # 4b. Phase 14 Stage B: administrator flag and session token version
        # Schema-only, additive and idempotent. Administrator rights are never
        # granted by a migration: the column defaults to 0 and is set
        # explicitly by the seeder or by an audited database update.
        cursor.execute("PRAGMA table_info(users)")
        existing_user_cols = {row["name"] for row in cursor.fetchall()}
        if existing_user_cols:
            if "is_admin" not in existing_user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN is_admin BOOLEAN DEFAULT 0")
            if "token_version" not in existing_user_cols:
                cursor.execute("ALTER TABLE users ADD COLUMN token_version INTEGER DEFAULT 0")

        # 5. Phase 7: Ensure wishlist table exists
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS wishlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                note TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                UNIQUE(user_id, product_id)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wishlist_user ON wishlist(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wishlist_product ON wishlist(product_id)")

        # 6. Phase 7: Ensure user_preferences table exists
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                user_id INTEGER PRIMARY KEY,
                preferred_categories TEXT DEFAULT '[]',
                preferred_brands TEXT DEFAULT '[]',
                min_budget REAL,
                max_budget REAL,
                preferred_store_id INTEGER,
                sort_preference TEXT DEFAULT 'best_deal',
                priority TEXT DEFAULT 'balanced' CHECK(priority IN ('lowest_price', 'best_deal', 'balanced')),
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (preferred_store_id) REFERENCES stores(id) ON DELETE SET NULL,
                CHECK(min_budget IS NULL OR min_budget >= 0),
                CHECK(max_budget IS NULL OR max_budget >= 0),
                CHECK(min_budget IS NULL OR max_budget IS NULL OR max_budget >= min_budget)
            )
            """
        )

        # 7. Phase 6 & 7: Ensure price_tracking table exists with user_id and multi-user uniqueness
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_tracking'")
        tracking_table_exists = cursor.fetchone() is not None

        if not tracking_table_exists:
            cursor.execute(
                """
                CREATE TABLE price_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    product_id INTEGER NOT NULL,
                    target_price REAL NOT NULL CHECK(target_price > 0),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'paused')),
                    last_observed_price REAL,
                    last_checked_at TIMESTAMP,
                    last_alert_at TIMESTAMP,
                    last_alert_price REAL,
                    last_alert_type TEXT,
                    alert_trigger_type TEXT DEFAULT 'target_or_drop' CHECK(alert_trigger_type IN ('target_or_drop', 'target_only', 'drop_only')),
                    note TEXT,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                    UNIQUE(user_id, product_id)
                )
                """
            )
        else:
            cursor.execute("PRAGMA table_info(price_tracking)")
            tracking_cols = {row["name"] for row in cursor.fetchall()}
            if "user_id" not in tracking_cols:
                # Migrate price_tracking safely to support user_id and composite unique constraint
                conn.execute("PRAGMA foreign_keys = OFF;")
                cursor.execute(
                    """
                    CREATE TABLE price_tracking_migrated (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        user_id INTEGER,
                        product_id INTEGER NOT NULL,
                        target_price REAL NOT NULL CHECK(target_price > 0),
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        status TEXT DEFAULT 'active' CHECK(status IN ('active', 'paused')),
                        last_observed_price REAL,
                        last_checked_at TIMESTAMP,
                        last_alert_at TIMESTAMP,
                        last_alert_price REAL,
                        last_alert_type TEXT,
                        alert_trigger_type TEXT DEFAULT 'target_or_drop' CHECK(alert_trigger_type IN ('target_or_drop', 'target_only', 'drop_only')),
                        note TEXT,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                        UNIQUE(user_id, product_id)
                    )
                    """
                )
                cursor.execute(
                    """
                    INSERT INTO price_tracking_migrated (
                        id, user_id, product_id, target_price, created_at, status,
                        last_observed_price, last_checked_at, last_alert_at,
                        last_alert_price, last_alert_type, alert_trigger_type, note
                    )
                    SELECT 
                        id, NULL, product_id, target_price, created_at, status,
                        last_observed_price, last_checked_at, last_alert_at,
                        last_alert_price, last_alert_type, alert_trigger_type, note
                    FROM price_tracking
                    """
                )
                cursor.execute("DROP TABLE price_tracking")
                cursor.execute("ALTER TABLE price_tracking_migrated RENAME TO price_tracking")
                conn.execute("PRAGMA foreign_keys = ON;")

        # 8. Phase 6 & 7: Ensure price_alerts table exists and has user_id
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='price_alerts'")
        alerts_table_exists = cursor.fetchone() is not None

        if not alerts_table_exists:
            cursor.execute(
                """
                CREATE TABLE price_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    tracking_id INTEGER NOT NULL,
                    product_id INTEGER NOT NULL,
                    alert_type TEXT NOT NULL CHECK(alert_type IN ('target_reached', 'price_drop')),
                    observed_price REAL NOT NULL,
                    previous_price REAL,
                    target_price REAL,
                    message TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_read INTEGER DEFAULT 0 CHECK(is_read IN (0, 1)),
                    trigger_key TEXT UNIQUE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                    FOREIGN KEY (tracking_id) REFERENCES price_tracking(id) ON DELETE CASCADE,
                    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
                )
                """
            )
        else:
            cursor.execute("PRAGMA table_info(price_alerts)")
            alerts_cols = {row["name"] for row in cursor.fetchall()}
            if "user_id" not in alerts_cols:
                cursor.execute("ALTER TABLE price_alerts ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")
                cursor.execute(
                    """
                    UPDATE price_alerts
                    SET user_id = (SELECT user_id FROM price_tracking WHERE price_tracking.id = price_alerts.tracking_id)
                    """
                )
            if "delivery_status" not in alerts_cols:
                cursor.execute("ALTER TABLE price_alerts ADD COLUMN delivery_status TEXT DEFAULT 'in_app_delivered'")
            if "channel" not in alerts_cols:
                cursor.execute("ALTER TABLE price_alerts ADD COLUMN channel TEXT DEFAULT 'in_app'")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracking_user ON price_tracking(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracking_product ON price_tracking(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tracking_status ON price_tracking(status)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_user ON price_alerts(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_tracking ON price_alerts(tracking_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_product ON price_alerts(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_alerts_is_read ON price_alerts(is_read)")

        # 8. Phase 4: Product Reviews and Platform Rating Aggregations
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS product_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                reviewer_name TEXT NOT NULL,
                rating REAL NOT NULL CHECK(rating >= 0 AND rating <= rating_scale),
                rating_scale REAL DEFAULT 5.0,
                title TEXT,
                comment TEXT NOT NULL,
                review_date TEXT,
                verified_buyer INTEGER DEFAULT 0 CHECK(verified_buyer IN (0, 1)),
                skin_type TEXT,
                source_url TEXT,
                data_status TEXT DEFAULT 'demo' CHECK(data_status IN ('demo', 'verified_retailer', 'manually_curated')),
                external_review_id TEXT UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_product ON product_reviews(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_platform ON product_reviews(platform)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reviews_rating ON product_reviews(rating)")

        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS product_platform_ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                platform TEXT NOT NULL,
                average_rating REAL,
                review_count INTEGER,
                rating_scale REAL DEFAULT 5.0,
                data_source TEXT DEFAULT 'Retailer Feed (Demo)',
                product_url TEXT,
                last_verified TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                UNIQUE(product_id, platform)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_plat_ratings_product ON product_platform_ratings(product_id)")

        # 9. Phase 6: Automatic Live Price Check Audit Logs
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS price_check_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER,
                retailer_id TEXT NOT NULL,
                retailer_name TEXT NOT NULL,
                product_url TEXT,
                canonical_url TEXT,
                status TEXT NOT NULL CHECK(status IN ('retrieved', 'unavailable', 'unsupported', 'restricted', 'mismatch', 'error')),
                listed_price REAL,
                mrp REAL,
                shipping_fee REAL,
                coupon_code TEXT,
                coupon_discount REAL,
                total_cost REAL,
                variant_detected TEXT,
                match_classification TEXT,
                checked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_check_logs_product ON price_check_logs(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_check_logs_retailer ON price_check_logs(retailer_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_check_logs_checked ON price_check_logs(checked_at)")

        # 10. Phase 7: Personalized Beauty User Profiles
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT,
                preferred_name TEXT,
                skin_type TEXT DEFAULT 'unsure',
                skin_concerns TEXT DEFAULT '[]',
                preferred_categories TEXT DEFAULT '[]',
                preferred_brands TEXT DEFAULT '[]',
                min_budget REAL,
                max_budget REAL,
                makeup_preferences TEXT DEFAULT '[]',
                ingredient_preferences TEXT DEFAULT '[]',
                ingredient_avoidance TEXT DEFAULT '[]',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )

        # 11. Phase 7: User Skincare Routines (Morning & Evening)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_routines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                routine_type TEXT NOT NULL CHECK(routine_type IN ('morning', 'evening', 'weekly', 'custom')),
                title TEXT NOT NULL,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_routines_user ON user_routines(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_routines_type ON user_routines(user_id, routine_type)")

        # 12. Phase 7: Routine Steps / Items
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS user_routine_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                routine_id INTEGER NOT NULL,
                product_id INTEGER,
                step_number INTEGER NOT NULL,
                step_name TEXT NOT NULL,
                custom_product_name TEXT,
                usage_instructions TEXT,
                precautions TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (routine_id) REFERENCES user_routines(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_routine_items_routine ON user_routine_items(routine_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_routine_items_step ON user_routine_items(routine_id, step_number)")

        # 13. Phase 8D: Manual Verification Requests
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_verification_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                retailer TEXT NOT NULL,
                product_url TEXT NOT NULL,
                user_submitted_price REAL,
                size_volume TEXT,
                shade TEXT,
                formulation TEXT,
                notes TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'verified', 'rejected', 'restricted', 'unavailable')),
                verification_status TEXT CHECK(verification_status IN ('LIVE_VERIFIED', 'MANUAL_VERIFIED', 'CACHED', 'HISTORICAL', 'POSSIBLE_MATCH', 'RESTRICTED', 'UNAVAILABLE', 'DEMO')),
                verified_price REAL,
                verified_mrp REAL,
                verified_discount_pct REAL,
                verified_shipping_fee REAL,
                verified_size_volume TEXT,
                verified_shade TEXT,
                verified_formulation TEXT,
                verified_product_name TEXT,
                verified_brand TEXT,
                verification_notes TEXT,
                source_url TEXT,
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                verified_at TIMESTAMP,
                reviewed_at TIMESTAMP,
                reviewed_by INTEGER,
                rejection_reason TEXT,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_manual_verification_user ON manual_verification_requests(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_manual_verification_product ON manual_verification_requests(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_manual_verification_status ON manual_verification_requests(status)")

        # 14. Phase 8D: Price Correction Submissions (Report Price)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS price_correction_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                product_id INTEGER NOT NULL,
                retailer TEXT NOT NULL,
                product_url TEXT NOT NULL,
                submitted_price REAL NOT NULL,
                submitted_mrp REAL,
                size_volume TEXT,
                shade TEXT,
                formulation TEXT,
                notes TEXT,
                evidence_url TEXT,
                status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected', 'merged')),
                reviewed_at TIMESTAMP,
                reviewed_by INTEGER,
                rejection_reason TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY (reviewed_by) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_correction_user ON price_correction_submissions(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_correction_product ON price_correction_submissions(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_price_correction_status ON price_correction_submissions(status)")

        # 15. Phase 8D: Evidence References
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference_type TEXT NOT NULL CHECK(reference_type IN ('manual_verification', 'price_correction')),
                reference_id INTEGER NOT NULL,
                evidence_url TEXT NOT NULL,
                evidence_type TEXT CHECK(evidence_type IN ('screenshot', 'receipt', 'product_page', 'other')),
                description TEXT,
                uploaded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                uploaded_by INTEGER NOT NULL,
                FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_reference ON evidence_references(reference_type, reference_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_evidence_uploaded_by ON evidence_references(uploaded_by)")



        # 13. Phase 8E: Gemini Response Cache
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gemini_cache (
                cache_key TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                model TEXT NOT NULL,
                response TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_gemini_cache_expires ON gemini_cache(expires_at)")

        # 14. Phase 8E: Gemini Rate Limits
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gemini_rate_limits (
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                count INTEGER DEFAULT 0,
                PRIMARY KEY (user_id, date)
            )
            """
        )

        # 15. Phase 8E: Gemini Token Usage Tracking
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS gemini_token_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                model TEXT NOT NULL,
                prompt_tokens INTEGER NOT NULL,
                completion_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                success INTEGER NOT NULL,
                error_code TEXT,
                requested_at TEXT NOT NULL
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_user ON gemini_token_usage(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_token_usage_date ON gemini_token_usage(requested_at)")

        # 16. Phase 8E: Ingredient Analysis Cache
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS ingredient_analysis_cache (
                product_id INTEGER PRIMARY KEY,
                product_name TEXT NOT NULL,
                analysis_json TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence_score REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE
            )
            """
        )

        # 17. Phase 8E: Alternative Finder Cache
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS alternative_finder_cache (
                original_product_id INTEGER NOT NULL,
                criteria_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (original_product_id, criteria_hash),
                FOREIGN KEY (original_product_id) REFERENCES products(id) ON DELETE CASCADE
            )
            """
        )

        # 18. Phase 8E: Routine Recommendation Cache
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS routine_recommendation_cache (
                user_id INTEGER NOT NULL,
                routine_type TEXT NOT NULL,
                criteria_hash TEXT NOT NULL,
                result_json TEXT NOT NULL,
                source TEXT NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, routine_type, criteria_hash),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )


# ==============================================================================
# Phase 14 Stage 2.5 (FIX 2): Schema migration runner
# ==============================================================================
# Contract of migrate_db():
#   * SCHEMA ONLY. It performs additive DDL (columns, indexes, tables) and
#     never creates, archives, restores or rewrites business records.
#   * IDEMPOTENT. Every statement is safe to execute repeatedly, and the
#     runner itself executes at most once per database per process, so an
#     ordinary authenticated request never triggers DDL.
#   * ENGINE AWARE. PostgreSQL is used when DATABASE_URL is configured;
#     SQLite is used otherwise.
#
# Product archival state is business data and lives in
# src.database.product_archival, which operates on explicit product IDs and
# never on numeric ranges.

# Records the signature of each database that has already been migrated in
# this process, keyed by migration target.
_MIGRATION_SIGNATURES: dict[str, str] = {}


def _migration_target_key(custom_path: str | None) -> str:
    """Return a stable identifier for a migration target.

    PostgreSQL targets are keyed by a short digest of the connection URL so
    that switching databases (for example between staging branches) never
    reuses a previous migration state. The URL itself is never logged.
    """
    if custom_path:
        return f"sqlite:{Path(custom_path).resolve()}"
    if get_database_engine_type() == "postgresql":
        url = (os.environ.get("DATABASE_URL") or DATABASE_URL or "").strip()
        digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] if url else "unknown"
        return f"postgresql:{digest}"
    return f"sqlite:{Path(DATABASE_PATH).resolve()}"


def _migration_signature(custom_path: str | None) -> str:
    """Return a fingerprint that changes when the target database is replaced.

    SQLite files are identified by inode, which survives ordinary writes but
    changes when a database file is deleted and recreated. This lets the
    runner detect a replaced database without re-running DDL on every write.
    """
    if custom_path:
        path = Path(custom_path)
    elif get_database_engine_type() == "postgresql":
        return "postgresql"
    else:
        path = Path(DATABASE_PATH)
    try:
        return f"inode:{path.stat().st_ino}"
    except OSError:
        return "missing"


def _migrate_postgres_schema() -> None:
    """Apply idempotent, PostgreSQL-safe schema migrations.

    Only additive, engine-safe DDL is executed here. The portable SQLite DDL
    used by _migrate_sqlite_schema() is not valid PostgreSQL (AUTOINCREMENT,
    PRAGMA), so it is never replayed against a PostgreSQL server.

    The relational schema of a PostgreSQL deployment is provisioned by
    scripts/migrate_sqlite_to_postgres.py; this function only brings the
    Phase 14 catalogue columns and indexes up to date.
    """
    with get_connection() as conn:
        cursor = conn.cursor()

        # 1. Phase 14 Stage 2: soft-archive support column (schema only)
        cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")

        # 2. Phase 14 Stage 3: image provenance metadata columns (schema only)
        cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_source_url TEXT")
        cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_source_name TEXT")
        cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_status TEXT DEFAULT 'placeholder'")
        cursor.execute("ALTER TABLE products ADD COLUMN IF NOT EXISTS image_last_checked TIMESTAMP")

        # 3. Indexes supporting the soft-archive filters
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_is_active ON products(is_active)")

        # 4. Phase 14 Stage B: explicit administrator flag and session token
        #    version. Both are additive, idempotent and default to the
        #    non-privileged value, so a migration can never grant rights.
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE")
        cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS token_version INTEGER DEFAULT 0")

        # 5. Phase 14 Stage D: purchase-link provenance on offers. The
        #    default marks a link as unverified; it is only set to 'verified'
        #    by an explicit, evidence-backed verification step.
        cursor.execute(
            "ALTER TABLE offers ADD COLUMN IF NOT EXISTS link_status TEXT DEFAULT 'demo_not_verified'"
        )
        cursor.execute("ALTER TABLE offers ADD COLUMN IF NOT EXISTS link_checked_at TIMESTAMP")

        # 4. Report (never create) a missing relational schema. The portable
        #    DDL is SQLite-specific, so provisioning stays an explicit,
        #    operator-driven step via scripts/migrate_sqlite_to_postgres.py.
        cursor.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
        existing_tables = {str(row[0]) for row in cursor.fetchall()}
        required_tables = {"products", "offers", "price_history", "stores", "users"}
        missing_tables = sorted(required_tables - existing_tables)
        if missing_tables:
            logger.warning(
                "PostgreSQL database is missing expected tables: %s. Provision them with "
                "scripts/migrate_sqlite_to_postgres.py.",
                ", ".join(missing_tables),
            )


def migrate_db(custom_path: str | None = None, force: bool = False) -> None:
    """Apply idempotent schema migrations to the configured database.

    Phase 14 Stage 2.5 (FIX 2) guarantees:
      * schema migration is strictly separated from business-data updates, so
        archival state is never rewritten by a migration;
      * migrations are idempotent and run at most once per database per
        process, so authenticated requests do not repeatedly execute DDL;
      * the migration runs against the correct engine (PostgreSQL when
        DATABASE_URL is configured, SQLite otherwise).

    Args:
        custom_path: optional SQLite database path (tests and tooling).
        force: re-run the migration even if it already ran for this target in
            the current process.
    """
    key = _migration_target_key(custom_path)
    signature = _migration_signature(custom_path)

    if not force and _MIGRATION_SIGNATURES.get(key) == signature:
        return

    engine = get_database_engine_type() if not custom_path else "sqlite"
    if engine == "postgresql":
        _migrate_postgres_schema()
    else:
        _migrate_sqlite_schema(custom_path)

    _MIGRATION_SIGNATURES[key] = signature


def init_db(custom_path: str | None = None) -> None:
    """Initialize database tables using schema.sql and apply migrations.

    The bundled schema script is SQLite-specific. PostgreSQL deployments are
    provisioned with scripts/migrate_sqlite_to_postgres.py instead.
    """
    if not custom_path and get_database_engine_type() == "postgresql":
        raise RuntimeError(
            "init_db() replays the SQLite schema script and cannot be used with "
            "PostgreSQL. Provision a PostgreSQL database with "
            "scripts/migrate_sqlite_to_postgres.py instead."
        )

    db_path = get_db_path(custom_path)
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found at {SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_connection(str(db_path)) as conn:
        conn.executescript(schema_sql)

    migrate_db(custom_path)
