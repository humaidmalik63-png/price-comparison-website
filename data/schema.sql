-- PriceWise AI Database Schema
-- Academic Prototype: Database structure for product price comparison and real deal detection

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sku TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    brand TEXT NOT NULL,
    category TEXT NOT NULL,
    description TEXT,
    specs_json TEXT,
    image_url TEXT,
    source_type TEXT DEFAULT 'demo' CHECK(source_type IN ('demo', 'catalog_verified', 'manufacturer_verified')),
    data_status TEXT DEFAULT 'pending_review' CHECK(data_status IN ('pending_review', 'catalog_verified', 'manufacturer_verified')),
    is_active INTEGER DEFAULT 1 CHECK(is_active IN (0, 1)),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    domain TEXT NOT NULL,
    rating REAL DEFAULT 4.5,
    shipping_policy TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    store_id INTEGER NOT NULL,
    current_price REAL NOT NULL,
    original_price REAL,
    shipping_cost REAL DEFAULT 0.0,
    currency TEXT DEFAULT 'USD',
    availability TEXT DEFAULT 'In Stock',
    variant_name TEXT DEFAULT 'Standard',
    condition TEXT DEFAULT 'Brand New',
    offer_url TEXT,
    last_checked TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (store_id) REFERENCES stores(id) ON DELETE CASCADE,
    UNIQUE(product_id, store_id)
);

CREATE TABLE IF NOT EXISTS price_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    offer_id INTEGER NOT NULL,
    price REAL NOT NULL,
    currency TEXT DEFAULT 'USD',
    data_source TEXT DEFAULT 'demo_seed',
    data_status TEXT DEFAULT 'demo',
    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (offer_id) REFERENCES offers(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_products_category ON products(category);
CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand);
CREATE INDEX IF NOT EXISTS idx_offers_product ON offers(product_id);
CREATE INDEX IF NOT EXISTS idx_offers_store ON offers(store_id);
CREATE INDEX IF NOT EXISTS idx_price_history_offer_date ON price_history(offer_id, recorded_at);

-- Phase 6 & 7: User Accounts, Watchlists & Alerts
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT DEFAULT 'active' CHECK(status IN ('active', 'suspended', 'deactivated'))
);

-- Phase 16: Retail Price Observations Table
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
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL
);

-- Indexes for price observations performance
CREATE INDEX IF NOT EXISTS idx_observations_product ON retail_price_observation(product_id);
CREATE INDEX IF NOT EXISTS idx_observations_retailer ON retail_price_observation(retailer);
CREATE INDEX IF NOT EXISTS idx_observations_status ON retail_price_observation(observation_status);
CREATE INDEX IF NOT EXISTS idx_observations_type ON retail_price_observation(observation_type);
CREATE INDEX IF NOT EXISTS idx_observations_verification ON retail_price_observation(verification_status);

-- Phase 16: OBF Product Verification Table
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
);

CREATE INDEX IF NOT EXISTS idx_obf_product ON obf_product_verification(product_id);
CREATE INDEX IF NOT EXISTS idx_obf_admin ON obf_product_verification(admin_user_id);

CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    note TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE CASCADE,
    UNIQUE(user_id, product_id)
);

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
);

CREATE TABLE IF NOT EXISTS price_tracking (
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
);

CREATE TABLE IF NOT EXISTS price_alerts (
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
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
CREATE INDEX IF NOT EXISTS idx_wishlist_user ON wishlist(user_id);
CREATE INDEX IF NOT EXISTS idx_wishlist_product ON wishlist(product_id);
CREATE INDEX IF NOT EXISTS idx_tracking_user ON price_tracking(user_id);
CREATE INDEX IF NOT EXISTS idx_tracking_product ON price_tracking(product_id);
CREATE INDEX IF NOT EXISTS idx_tracking_status ON price_tracking(status);
CREATE INDEX IF NOT EXISTS idx_alerts_user ON price_alerts(user_id);
CREATE INDEX IF NOT EXISTS idx_alerts_tracking ON price_alerts(tracking_id);
CREATE INDEX IF NOT EXISTS idx_alerts_product ON price_alerts(product_id);
CREATE INDEX IF NOT EXISTS idx_alerts_is_read ON price_alerts(is_read);

