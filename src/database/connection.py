import sqlite3
from contextlib import contextmanager
from typing import Generator
from pathlib import Path
from src.config import DATABASE_PATH, SCHEMA_PATH


def get_db_path(custom_path: str | None = None) -> Path:
    """Return the resolved database path."""
    target = Path(custom_path) if custom_path else Path(DATABASE_PATH)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


@contextmanager
def get_connection(custom_path: str | None = None) -> Generator[sqlite3.Connection, None, None]:
    """Provide a transactional database connection with row factory enabled."""
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


def migrate_db(custom_path: str | None = None) -> None:
    """Ensure newer columns and indexes exist in the SQLite database."""
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

        # 3. Ensure indexes exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='products'")
        if cursor.fetchone():
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand)")

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
                status TEXT DEFAULT 'active' CHECK(status IN ('active', 'suspended', 'deactivated'))
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")

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

        # 13. Phase 16: Retail Price Observation table migration
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS retail_price_observation (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                retailer TEXT NOT NULL,
                product_url TEXT NOT NULL,
                observed_price REAL NOT NULL CHECK(observed_price > 0),
                observed_mrp REAL,
                size_volume TEXT,
                shade TEXT,
                formulation TEXT,
                observation_type TEXT NOT NULL DEFAULT 'live' CHECK(observation_type IN ('scheduled', 'manual', 'user_report', 'live', 'historical')),
                observation_status TEXT NOT NULL DEFAULT 'live' CHECK(observation_status IN ('live', 'expired', 'superseded', 'flagged')),
                verified_by_admin INTEGER DEFAULT 0 CHECK(verified_by_admin IN (0, 1)),
                verified_price REAL,
                verification_notes TEXT,
                verification_status TEXT DEFAULT 'pending' CHECK(verification_status IN ('pending', 'review_required', 'verified', 'provider_observed')),
                admin_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                evidence_notes TEXT,
                evidence_reference TEXT,
                match_result TEXT,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL
            )
            """
        )

        # Create indexes for observations table with idempotency check
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_observations_product'")
        if not cursor.fetchone():
            cursor.execute("CREATE INDEX idx_observations_product ON retail_price_observation(product_id)")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_observations_retailer'")
        if not cursor.fetchone():
            cursor.execute("CREATE INDEX idx_observations_retailer ON retail_price_observation(retailer)")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_observations_status'")
        if not cursor.fetchone():
            cursor.execute("CREATE INDEX idx_observations_status ON retail_price_observation(observation_status)")
        cursor.execute("SELECT name FROM sqlite_master WHERE type='index' AND name='idx_observations_verification'")
        if not cursor.fetchone():
            cursor.execute("CREATE INDEX idx_observations_verification ON retail_price_observation(verification_status)")

        # 14. Phase 16: OBF Product Verification table migration
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS obf_product_verification (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('approved', 'rejected', 'needs_review')),
                admin_user_id INTEGER NOT NULL,
                evidence_notes TEXT NOT NULL,
                previous_data_status TEXT NOT NULL,
                new_data_status TEXT NOT NULL,
                reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
                FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_obf_product ON obf_product_verification(product_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_obf_admin ON obf_product_verification(admin_user_id)")

        # 15. Phase 16: Add columns to products table if missing.
        #     migrate_db() may be called on a brand-new/empty database before
        #     init_db() (e.g. by read-only helpers), so guard every products
        #     operation on the table actually existing.
        cursor.execute("PRAGMA table_info(products)")
        product_cols = {row["name"] for row in cursor.fetchall()}
        products_table_exists = bool(product_cols)
        if products_table_exists and "data_status" not in product_cols:
            cursor.execute("ALTER TABLE products ADD COLUMN data_status TEXT DEFAULT 'pending_review'")
        if products_table_exists and "source_type" not in product_cols:
            cursor.execute("ALTER TABLE products ADD COLUMN source_type TEXT DEFAULT 'demo'")
        if products_table_exists and "is_active" not in product_cols:
            cursor.execute("ALTER TABLE products ADD COLUMN is_active INTEGER DEFAULT 1")
        if products_table_exists and "updated_at" not in product_cols:
            # SQLite rejects ALTER TABLE ADD COLUMN with a non-constant default
            # (CURRENT_TIMESTAMP). Add the column first, then backfill only the
            # rows that are missing a value. Existing timestamps are untouched.
            cursor.execute("ALTER TABLE products ADD COLUMN updated_at TIMESTAMP")
            cursor.execute(
                "UPDATE products SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL"
            )
        # Ensure timestamp triggers exist for both legacy (column just added) and
        # fresh databases. CREATE TRIGGER IF NOT EXISTS keeps this idempotent.
        # The insert trigger only fills genuinely NULL values; the update trigger
        # only fires when an UPDATE did not itself change updated_at.
        if products_table_exists:
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_products_updated_at_insert
                AFTER INSERT ON products
                FOR EACH ROW WHEN NEW.updated_at IS NULL
                BEGIN
                    UPDATE products SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
                END
                """
            )
            cursor.execute(
                """
                CREATE TRIGGER IF NOT EXISTS trg_products_updated_at_update
                AFTER UPDATE ON products
                FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at
                BEGIN
                    UPDATE products SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
                END
                """
            )

        # 16. Phase 16: Evidence columns for retail_price_observation (idempotent migration)
        cursor.execute("PRAGMA table_info(retail_price_observation)")
        observation_cols = {row["name"] for row in cursor.fetchall()}
        if "evidence_notes" not in observation_cols:
            cursor.execute("ALTER TABLE retail_price_observation ADD COLUMN evidence_notes TEXT")
        if "evidence_reference" not in observation_cols:
            cursor.execute("ALTER TABLE retail_price_observation ADD COLUMN evidence_reference TEXT")
        if "match_result" not in observation_cols:
            cursor.execute("ALTER TABLE retail_price_observation ADD COLUMN match_result TEXT")

        # 17. Phase 16.2: Remove UNIQUE(product_id, retailer) constraint on retail_price_observation
        # 18. Phase 16.5: Add 'live' and 'historical' to observation_type, add match_result
        #     SQLite cannot DROP a column-level UNIQUE constraint without recreating the table.
        #     Check whether the auto-index still exists; if so, rebuild without the constraint.
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='retail_price_observation'"
        )
        existing_indexes = {row["name"] for row in cursor.fetchall()}
        table_row = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='retail_price_observation'"
        ).fetchone()
        table_sql = (table_row["sql"] or "") if table_row else ""
        # Rebuild when either the legacy UNIQUE(product_id, retailer) autoindex is
        # present, or the verification_status CHECK predates 'provider_observed'
        # (Phase 16.5 live observations would otherwise be rejected on a fresh
        # checkout, where schema.sql created the restrictive constraint first).
        needs_rebuild = (
            any(idx.startswith("sqlite_autoindex_") for idx in existing_indexes)
            or ("provider_observed" not in table_sql and "verification_status" in table_sql)
        )
        if needs_rebuild:
            rows_data = cursor.execute("SELECT * FROM retail_price_observation").fetchall()
            col_desc = cursor.description
            col_names = [row["name"] for row in col_desc]
            cursor.execute("DROP TABLE IF EXISTS retail_price_observation_temp")
            cols_sql = ", ".join(
                [
                    "id INTEGER PRIMARY KEY AUTOINCREMENT",
                    "product_id INTEGER NOT NULL",
                    "retailer TEXT NOT NULL",
                    "product_url TEXT NOT NULL",
                    "observed_price REAL NOT NULL CHECK(observed_price > 0)",
                    "observed_mrp REAL",
                    "size_volume TEXT",
                    "shade TEXT",
                    "formulation TEXT",
                    "observation_type TEXT NOT NULL CHECK(observation_type IN ('scheduled', 'manual', 'user_report', 'live', 'historical'))",
                    "observation_status TEXT NOT NULL DEFAULT 'live' CHECK(observation_status IN ('live', 'expired', 'superseded', 'flagged'))",
                    "verified_by_admin INTEGER DEFAULT 0 CHECK(verified_by_admin IN (0, 1))",
                    "verified_price REAL",
                    "verification_notes TEXT",
                    "verification_status TEXT DEFAULT 'pending' CHECK(verification_status IN ('pending', 'review_required', 'verified', 'provider_observed'))",
                    "admin_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL",
                    "created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
                    "evidence_notes TEXT",
                    "evidence_reference TEXT",
                    "match_result TEXT",
                    "FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE",
                    "FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL",
                ]
            )
            cursor.execute(f"CREATE TABLE retail_price_observation_temp ({cols_sql})")
            if rows_data:
                placeholders = ", ".join(["?"] * len(col_names))
                col_list = ", ".join(col_names)
                cursor.executemany(
                    f"INSERT INTO retail_price_observation_temp ({col_list}) VALUES ({placeholders})",
                    rows_data,
                )
            cursor.execute("DROP TABLE retail_price_observation")
            cursor.execute("ALTER TABLE retail_price_observation_temp RENAME TO retail_price_observation")
            # Recreate named indexes (auto-indexes no longer needed without UNIQUE constraint)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_product ON retail_price_observation(product_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_retailer ON retail_price_observation(retailer)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_status ON retail_price_observation(observation_status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_type ON retail_price_observation(observation_type)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_observations_verification ON retail_price_observation(verification_status)")


def init_db(custom_path: str | None = None) -> None:
    """Initialize database tables using schema.sql and apply migrations."""
    db_path = get_db_path(custom_path)
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found at {SCHEMA_PATH}")

    with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_connection(str(db_path)) as conn:
        conn.executescript(schema_sql)

    migrate_db(custom_path)


