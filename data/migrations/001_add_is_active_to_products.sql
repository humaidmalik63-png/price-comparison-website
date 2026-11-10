-- ==============================================================================
-- PriceWise AI — Migration 001: Soft-Archive Non-Beauty Products
-- Phase 14 Stage 2: Database & Product Catalogue Recovery
--
-- PHASE 14 STAGE 2.5 AMENDMENT (FIX 2) — Product archival integrity
-- ------------------------------------------------------------------
-- Step 4 of the original version of this file reactivated every product whose
-- ID was greater than a threshold:
--
--     UPDATE products SET is_active = TRUE WHERE id >= 12 AND id NOT IN (998, 999);
--
-- Re-running the file therefore undid any archival applied after Phase 14
-- Stage 2 — the exact integrity defect fixed in Stage 2.5.
--
-- This file is now idempotent and safe to re-run:
--   * the archival set is an explicit list of product IDs;
--   * no statement reactivates a product based on its ID;
--   * applying it twice leaves the catalogue in exactly the same state.
--
-- Rolling this file back is NOT the way to undo an archival. Restore a
-- specific product explicitly instead:
--     python -m src.database.product_archival --restore <product_id> [...]
--
-- Schema migration and business-data updates are now separated: the migration
-- runner (src/database/connection.py) performs schema DDL only, and all
-- archival state changes live in src/database/product_archival.py.
-- ==============================================================================

-- 1. Add is_active column to products if not exists
-- Works on both PostgreSQL (IF NOT EXISTS) and SQLite (handled via migrate_db)
ALTER TABLE products ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

-- 2. Soft-archive legacy technology demo products (explicit ID list)
-- Preserves all foreign keys (offers, price history, watchlists, etc.) without deletion
UPDATE products SET is_active = FALSE WHERE id IN (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11);

-- 3. Soft-archive test fixtures if present in catalog (explicit ID list)
UPDATE products SET is_active = FALSE WHERE id IN (998, 999);

-- 4. NO blanket reactivation.
-- Products are never reactivated because their ID exceeds a threshold.
-- Restoring a product is an explicit operator action:
--     python -m src.database.product_archival --restore <product_id> [...]
