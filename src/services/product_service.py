"""Service layer for querying products and offers."""

import json
from typing import Optional
from src.database.connection import get_connection, get_database_engine_type
from src.database.models import Offer, PricePoint, Product


def parse_specs(specs_raw: Optional[str]) -> dict:
    if not specs_raw:
        return {}
    try:
        return json.loads(specs_raw)
    except Exception:
        return {}


def get_all_categories(custom_path: Optional[str] = None, active_only: bool = True) -> list[str]:
    """Retrieve distinct product categories."""
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        engine = get_database_engine_type() if not custom_path else "sqlite"
        active_cond = "WHERE (is_active IS NULL OR is_active = TRUE)" if engine == "postgresql" else "WHERE (is_active IS NULL OR is_active = 1)"
        where_clause = active_cond if active_only else ""
        cursor.execute(f"SELECT DISTINCT category FROM products {where_clause} ORDER BY category ASC")
        rows = cursor.fetchall()
        return [r["category"] for r in rows if r["category"]]


def get_all_brands(category: Optional[str] = None, custom_path: Optional[str] = None, active_only: bool = True) -> list[str]:
    """Retrieve distinct product brands, optionally filtered by category."""
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        engine = get_database_engine_type() if not custom_path else "sqlite"
        active_cond = "(is_active IS NULL OR is_active = TRUE)" if engine == "postgresql" else "(is_active IS NULL OR is_active = 1)"
        where_parts = [active_cond] if active_only else []
        params = []
        if category and category != "All":
            where_parts.append("category = ?")
            params.append(category)
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        cursor.execute(f"SELECT DISTINCT brand FROM products {where_clause} ORDER BY brand ASC", params)
        rows = cursor.fetchall()
        return [r["brand"] for r in rows if r["brand"]]


def get_all_stores(custom_path: Optional[str] = None) -> list[dict]:
    """Retrieve distinct registered stores."""
    from src.services.preference_service import get_available_stores
    return get_available_stores(custom_path)


# Backward-compatible alias
get_available_stores = get_all_stores


def get_all_skin_types(custom_path: Optional[str] = None) -> list[str]:
    """Retrieve verified skin types from product specifications."""
    skin_types = set()
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT specs_json FROM products WHERE specs_json IS NOT NULL")
        for row in cursor.fetchall():
            specs = parse_specs(row["specs_json"])
            st_raw = specs.get("Skin Type")
            if isinstance(st_raw, str):
                for st in st_raw.split(","):
                    cleaned = st.strip()
                    if cleaned:
                        skin_types.add(cleaned)
    return sorted(list(skin_types))


def get_all_product_types(custom_path: Optional[str] = None) -> list[str]:
    """Retrieve distinct product formulations/types from product specifications."""
    prod_types = set()
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT specs_json FROM products WHERE specs_json IS NOT NULL")
        for row in cursor.fetchall():
            specs = parse_specs(row["specs_json"])
            pt_raw = specs.get("Product Type")
            if isinstance(pt_raw, str) and pt_raw.strip():
                prod_types.add(pt_raw.strip())
    return sorted(list(prod_types))


def get_products(
    category: Optional[str] = None,
    brand: Optional[str] = None,
    search_query: Optional[str] = None,
    in_stock_only: bool = False,
    min_price: Optional[float] = None,
    max_price: Optional[float] = None,
    sort_by: str = "featured",
    include_history: bool = False,
    skin_type: Optional[str] = None,
    product_type: Optional[str] = None,
    custom_path: Optional[str] = None,
    active_only: bool = True,
) -> list[Product]:
    """
    Search and filter products with summary offer information.
    Supports case-insensitive multi-term search across title, brand, sku, description, and specs.
    sort_by options: 'featured', 'price_asc', 'price_desc', 'title_asc', 'name_asc', 'title_desc', 'savings_desc', 'best_deal'
    """
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        engine = get_database_engine_type() if not custom_path else "sqlite"
        active_cond = "(p.is_active IS NULL OR p.is_active = TRUE)" if engine == "postgresql" else "(p.is_active IS NULL OR p.is_active = 1)"

        sql = f"""
            SELECT 
                p.id, p.sku, p.title, p.brand, p.category, p.description, 
                p.specs_json, p.image_url, p.created_at, p.is_active
            FROM products p
            WHERE {'(' + active_cond + ')' if active_only else '1=1'}
        """
        params: list = []

        # 1. Category Filter
        if category and category != "All":
            sql += " AND p.category = ?"
            params.append(category)

        # 2. Brand Filter
        if brand and brand != "All":
            sql += " AND p.brand = ?"
            params.append(brand)

        # 3. Case-Insensitive Tokenized Search (matches title, brand, sku, description, specs including ingredients)
        if search_query and search_query.strip():
            terms = search_query.strip().split()
            for term in terms:
                wildcard = f"%{term.lower()}%"
                sql += """
                    AND (
                        LOWER(p.title) LIKE ?
                        OR LOWER(p.brand) LIKE ?
                        OR LOWER(p.sku) LIKE ?
                        OR LOWER(p.description) LIKE ?
                        OR LOWER(p.specs_json) LIKE ?
                    )
                """
                params.extend([wildcard, wildcard, wildcard, wildcard, wildcard])

        # 4. Skin Type Filter (via specs_json)
        if skin_type and skin_type != "All":
            sql += " AND LOWER(p.specs_json) LIKE ?"
            params.append(f"%{skin_type.lower()}%")

        # 5. Product Type Filter (via specs_json)
        if product_type and product_type != "All":
            sql += " AND LOWER(p.specs_json) LIKE ?"
            params.append(f"%{product_type.lower()}%")

        sql += " ORDER BY p.id ASC"
        cursor.execute(sql, params)
        product_rows = cursor.fetchall()

        products: list[Product] = []
        for prow in product_rows:
            # Fetch offers for this product
            cursor.execute(
                """
                SELECT 
                    o.id, o.product_id, o.store_id, o.current_price, o.original_price,
                    o.shipping_cost, o.currency, o.availability, o.variant_name, o.condition,
                    o.offer_url, o.last_checked, o.link_status, o.link_checked_at,
                    s.name as store_name, s.rating as store_rating
                FROM offers o
                JOIN stores s ON o.store_id = s.id
                WHERE o.product_id = ?
                ORDER BY (o.current_price + o.shipping_cost) ASC
                """,
                (prow["id"],),
            )
            offer_rows = cursor.fetchall()

            offers = []
            for orow in offer_rows:
                price_history = []
                if include_history:
                    cursor.execute(
                        """
                        SELECT id, offer_id, price, currency, data_source, data_status, recorded_at
                        FROM price_history
                        WHERE offer_id = ?
                        ORDER BY recorded_at ASC, id ASC
                        """,
                        (orow["id"],),
                    )
                    hist_rows = cursor.fetchall()
                    price_history = [
                        PricePoint(
                            id=h["id"] if "id" in h.keys() else None,
                            offer_id=h["offer_id"] if "offer_id" in h.keys() else orow["id"],
                            price=float(h["price"]),
                            recorded_at=str(h["recorded_at"]),
                            currency=h["currency"] if "currency" in h.keys() else "USD",
                            data_source=h["data_source"] if "data_source" in h.keys() else "demo_seed",
                            data_status=h["data_status"] if "data_status" in h.keys() else "demo",
                        )
                        for h in hist_rows
                    ]

                offers.append(
                    Offer(
                        id=orow["id"],
                        product_id=orow["product_id"],
                        store_id=orow["store_id"],
                        store_name=orow["store_name"],
                        store_rating=float(orow["store_rating"]),
                        current_price=float(orow["current_price"]),
                        original_price=float(orow["original_price"]) if orow["original_price"] is not None else None,
                        shipping_cost=float(orow["shipping_cost"]) if orow["shipping_cost"] is not None else 0.0,
                        currency=orow["currency"],
                        availability=orow["availability"] or "In Stock",
                        variant_name=orow["variant_name"] or "Standard",
                        condition=orow["condition"] or "Brand New",
                        offer_url=orow["offer_url"] or "",
                        last_checked=str(orow["last_checked"]),
                        link_status=(orow["link_status"] if "link_status" in orow.keys() and orow["link_status"] else "demo_not_verified"),
                        link_checked_at=(str(orow["link_checked_at"]) if "link_checked_at" in orow.keys() and orow["link_checked_at"] else None),
                        price_history=price_history,
                    )
                )

            parsed_specs = parse_specs(prow["specs_json"])
            prod = Product(
                id=prow["id"],
                sku=prow["sku"],
                title=prow["title"],
                brand=prow["brand"],
                category=prow["category"],
                description=prow["description"] or "",
                specs=parsed_specs,
                image_url=prow["image_url"] or "",
                created_at=str(prow["created_at"]),
                is_active=bool(prow["is_active"]) if "is_active" in prow.keys() and prow["is_active"] is not None else True,
                official_url=(parsed_specs.get("Product URL") or None),
                official_source=(parsed_specs.get("Source") or None),
                official_evidence=(parsed_specs.get("Evidence") or None),
                offers=offers,
            )
            products.append(prod)

        # 4. In-Stock Filter
        if in_stock_only:
            products = [p for p in products if p.available_offer_count > 0]

        # 5. Price Range Filter (based on lowest available price)
        if min_price is not None:
            products = [p for p in products if p.lowest_price is not None and p.lowest_price >= min_price]

        if max_price is not None:
            products = [p for p in products if p.lowest_price is not None and p.lowest_price <= max_price]

        # 6. Sorting Logic
        if sort_by == "price_asc":
            # Lowest available price first; items without valid prices go to end
            products.sort(key=lambda p: (p.lowest_price is None, p.lowest_price or float("inf")))
        elif sort_by == "price_desc":
            # Highest available price first; items without valid prices go to end
            products.sort(key=lambda p: (p.lowest_price is None, -(p.lowest_price or 0.0)))
        elif sort_by in ("title_asc", "name_asc"):
            products.sort(key=lambda p: p.title.lower())
        elif sort_by in ("title_desc", "name_desc"):
            products.sort(key=lambda p: p.title.lower(), reverse=True)
        elif sort_by in ("savings_desc", "best_deal"):
            # Sort by spread or savings percentage among available offers
            def available_savings(p: Product) -> float:
                avail_prices = [o.current_price for o in p.available_offers]
                if len(avail_prices) >= 2:
                    return max(avail_prices) - min(avail_prices)
                # Check direct discount
                discounts = [o.direct_discount_pct for o in p.available_offers]
                return max(discounts) if discounts else 0.0

            products.sort(key=available_savings, reverse=True)

        return products


def get_product_by_id(product_id: int, custom_path: Optional[str] = None) -> Optional[Product]:
    """Retrieve full product details including all store offers and complete price history."""
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, sku, title, brand, category, description, specs_json, image_url, created_at, is_active
            FROM products
            WHERE id = ?
            """,
            (product_id,),
        )
        prow = cursor.fetchone()
        if not prow:
            return None

        # Fetch offers
        cursor.execute(
            """
            SELECT 
                o.id, o.product_id, o.store_id, o.current_price, o.original_price,
                o.shipping_cost, o.currency, o.availability, o.variant_name, o.condition,
                o.offer_url, o.last_checked, o.link_status, o.link_checked_at,
                s.name as store_name, s.rating as store_rating
            FROM offers o
            JOIN stores s ON o.store_id = s.id
            WHERE o.product_id = ?
            ORDER BY (o.current_price + o.shipping_cost) ASC
            """,
            (product_id,),
        )
        offer_rows = cursor.fetchall()

        offers: list[Offer] = []
        for orow in offer_rows:
            # Fetch price history for this offer
            cursor.execute(
                """
                SELECT id, offer_id, price, currency, data_source, data_status, recorded_at
                FROM price_history
                WHERE offer_id = ?
                ORDER BY recorded_at ASC, id ASC
                """,
                (orow["id"],),
            )
            hist_rows = cursor.fetchall()
            price_history = [
                PricePoint(
                    id=h["id"] if "id" in h.keys() else None,
                    offer_id=h["offer_id"] if "offer_id" in h.keys() else orow["id"],
                    price=float(h["price"]),
                    recorded_at=str(h["recorded_at"]),
                    currency=h["currency"] if "currency" in h.keys() else "USD",
                    data_source=h["data_source"] if "data_source" in h.keys() else "demo_seed",
                    data_status=h["data_status"] if "data_status" in h.keys() else "demo",
                )
                for h in hist_rows
            ]

            offers.append(
                Offer(
                    id=orow["id"],
                    product_id=orow["product_id"],
                    store_id=orow["store_id"],
                    store_name=orow["store_name"],
                    store_rating=float(orow["store_rating"]),
                    current_price=float(orow["current_price"]),
                    original_price=float(orow["original_price"]) if orow["original_price"] is not None else None,
                    shipping_cost=float(orow["shipping_cost"]) if orow["shipping_cost"] is not None else 0.0,
                    currency=orow["currency"],
                    availability=orow["availability"] or "In Stock",
                    variant_name=orow["variant_name"] or "Standard",
                    condition=orow["condition"] or "Brand New",
                    offer_url=orow["offer_url"] or "",
                    last_checked=str(orow["last_checked"]),
                    link_status=(orow["link_status"] if "link_status" in orow.keys() and orow["link_status"] else "demo_not_verified"),
                    link_checked_at=(str(orow["link_checked_at"]) if "link_checked_at" in orow.keys() and orow["link_checked_at"] else None),
                    price_history=price_history,
                )
            )

        parsed_specs = parse_specs(prow["specs_json"])

        return Product(
            id=prow["id"],
            sku=prow["sku"],
            title=prow["title"],
            brand=prow["brand"],
            category=prow["category"],
            description=prow["description"] or "",
            specs=parsed_specs,
            image_url=prow["image_url"] or "",
            created_at=str(prow["created_at"]),
            is_active=bool(prow["is_active"]) if "is_active" in prow.keys() and prow["is_active"] is not None else True,
            official_url=(parsed_specs.get("Product URL") or None),
            official_source=(parsed_specs.get("Source") or None),
            official_evidence=(parsed_specs.get("Evidence") or None),
            offers=offers,
        )


def get_product_by_slug(slug: str, custom_path: Optional[str] = None, active_only: bool = True) -> Optional[Product]:
    """
    Retrieve product by URL-friendly slug, SKU, or numeric ID string.
    Returns None if no matching product is found (for clean 404 handling).
    """
    if not slug or not slug.strip():
        return None

    clean_slug = slug.strip().lower()

    # 1. If numeric string, check ID first
    if clean_slug.isdigit():
        prod = get_product_by_id(int(clean_slug), custom_path=custom_path)
        if prod:
            if active_only and not prod.is_active:
                return None
            return prod

    # 2. Check SKU match
    with get_connection(custom_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM products WHERE LOWER(sku) = ?", (clean_slug,))
        row = cursor.fetchone()
        if row:
            p = get_product_by_id(row["id"], custom_path=custom_path)
            if p and active_only and not p.is_active:
                return None
            return p

    # 3. Match against computed product slug or title slug
    import re
    all_products = get_products(custom_path=custom_path, active_only=active_only)
    for p in all_products:
        if p.slug == clean_slug or p.sku.lower() == clean_slug:
            return get_product_by_id(p.id, custom_path=custom_path)
        title_slug = re.sub(r"[^a-z0-9]+", "-", p.title.lower()).strip("-")
        if title_slug == clean_slug:
            return get_product_by_id(p.id, custom_path=custom_path)

    # 4. Flexible substring slug match (e.g. slug without duplicate brand prefix)
    for p in all_products:
        title_slug = re.sub(r"[^a-z0-9]+", "-", p.title.lower()).strip("-")
        if len(clean_slug) >= 5 and (clean_slug in p.slug or clean_slug in title_slug):
            return get_product_by_id(p.id, custom_path=custom_path)

    return None


get_product_by_id_or_slug = get_product_by_slug
