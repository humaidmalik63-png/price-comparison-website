from src.database.connection import get_connection, init_db, get_db_path, migrate_db

# NOTE: src.database.product_archival is intentionally NOT imported here.
# Importing it eagerly would make `python -m src.database.product_archival`
# emit a double-import RuntimeWarning. Import it explicitly where needed:
#     from src.database.product_archival import archive_products, restore_products

__all__ = ["get_connection", "init_db", "get_db_path", "migrate_db"]
