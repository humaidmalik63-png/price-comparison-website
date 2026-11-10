"""Seed script for PriceWise AI database.
Populates realistic demo products, stores, offers, and historical price trails.
ALL DATA IS DEMO DATA FOR ACADEMIC PROTOTYPE PURPOSES.
"""

from datetime import datetime, timedelta, timezone
import json
from src.database.connection import get_connection, init_db
from src.database.beauty_seed_data import DEMO_BEAUTY_STORES, DEMO_BEAUTY_PRODUCTS

# Demo stores
DEMO_STORES = [
    {
        "name": "TechMart (Demo)",
        "domain": "techmart-demo.example.com",
        "rating": 4.8,
        "shipping_policy": "Free shipping on orders over $50. Standard delivery 2-3 days.",
    },
    {
        "name": "ElectroHub (Demo)",
        "domain": "electrohub-demo.example.com",
        "rating": 4.6,
        "shipping_policy": "Flat $4.99 shipping. Next-day delivery available.",
    },
    {
        "name": "Apex Direct (Demo)",
        "domain": "apexdirect-demo.example.com",
        "rating": 4.7,
        "shipping_policy": "Free express shipping for members. 30-day returns.",
    },
    {
        "name": "DigitalBay (Demo)",
        "domain": "digitalbay-demo.example.com",
        "rating": 4.3,
        "shipping_policy": "Standard shipping $5.99. 14-day return window.",
    },
    {
        "name": "PrimeGear (Demo)",
        "domain": "primegear-demo.example.com",
        "rating": 4.5,
        "shipping_policy": "Free ground shipping. Free returns within 30 days.",
    },
]

# Demo products
DEMO_PRODUCTS = [
    {
        "sku": "LAP-MAC-M3-14",
        "title": "Apple MacBook Pro 14\" (M3 Pro, 18GB RAM, 512GB SSD)",
        "brand": "Apple",
        "category": "Laptops",
        "description": "Supercharged by M3 Pro chip featuring 11-core CPU and 14-core GPU, Liquid Retina XDR display, up to 18 hours battery life.",
        "specs": {"Screen": "14.2-inch XDR", "Processor": "M3 Pro", "RAM": "18GB", "Storage": "512GB SSD", "Weight": "1.61 kg"},
        "image_url": "https://images.unsplash.com/photo-1517336714731-489689fd1ca8?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "TechMart (Demo)",
                "current_price": 1799.00,
                "original_price": 1999.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "all_time_low",  # Price recently dropped below historical range
            },
            {
                "store_name": "ElectroHub (Demo)",
                "current_price": 1849.00,
                "original_price": 1999.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "moderate_deal",
            },
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 1899.00,
                "original_price": 1999.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
            {
                "store_name": "DigitalBay (Demo)",
                "current_price": 1949.00,
                "original_price": 1999.00,
                "shipping_cost": 9.99,
                "availability": "Limited Stock",
                "trend_type": "high",
            },
        ],
    },
    {
        "sku": "LAP-DELL-XPS15",
        "title": "Dell XPS 15 OLED (Intel Core i7-13700H, 32GB RAM, 1TB SSD, RTX 4060)",
        "brand": "Dell",
        "category": "Laptops",
        "description": "High-performance creator laptop with 3.5K OLED touchscreen, 13th Gen Intel Core processor, and NVIDIA GeForce RTX 4060 graphics.",
        "specs": {"Screen": "15.6-inch 3.5K OLED", "Processor": "i7-13700H", "RAM": "32GB", "Storage": "1TB SSD", "GPU": "RTX 4060"},
        "image_url": "https://images.unsplash.com/photo-1593642632823-8f785ba67e45?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 1899.99,
                "original_price": 2249.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "great_deal",
            },
            {
                "store_name": "TechMart (Demo)",
                "current_price": 1949.00,
                "original_price": 2249.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
            {
                "store_name": "PrimeGear (Demo)",
                "current_price": 2049.00,
                "original_price": 2249.99,
                "shipping_cost": 0.0,
                "availability": "Limited Stock",
                "trend_type": "high",
            },
        ],
    },
    {
        "sku": "PHN-SMP-S24U",
        "title": "Samsung Galaxy S24 Ultra 5G (256GB, Titanium Gray)",
        "brand": "Samsung",
        "category": "Smartphones",
        "description": "Flagship smartphone with Galaxy AI features, 200MP camera system, built-in S Pen, and Snapdragon 8 Gen 3 for Galaxy.",
        "specs": {"Screen": "6.8-inch QHD+ AMOLED 120Hz", "Chip": "Snapdragon 8 Gen 3", "Camera": "200MP Main", "Battery": "5000 mAh"},
        "image_url": "https://images.unsplash.com/photo-1610945415295-d9bbf067e59c?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "ElectroHub (Demo)",
                "current_price": 1049.99,
                "original_price": 1299.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "all_time_low",
            },
            {
                "store_name": "TechMart (Demo)",
                "current_price": 1149.99,
                "original_price": 1299.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 1199.00,
                "original_price": 1299.99,
                "shipping_cost": 4.99,
                "availability": "In Stock",
                "trend_type": "normal",
            },
            {
                "store_name": "DigitalBay (Demo)",
                "current_price": 1279.00,
                "original_price": 1299.99,
                "shipping_cost": 9.99,
                "availability": "In Stock",
                "trend_type": "inflated",  # Strikethrough fake discount demo
            },
        ],
    },
    {
        "sku": "PHN-APL-IP15P",
        "title": "Apple iPhone 15 Pro (128GB, Natural Titanium)",
        "brand": "Apple",
        "category": "Smartphones",
        "description": "Forged in titanium featuring industry-leading A17 Pro chip, customizable Action button, and 48MP Pro camera system.",
        "specs": {"Screen": "6.1-inch Super Retina XDR", "Chip": "A17 Pro", "Camera": "48MP Main + 12MP Ultra-wide + 3x Telephoto", "Weight": "187 g"},
        "image_url": "https://images.unsplash.com/photo-1695048133142-1a20484d2569?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "TechMart (Demo)",
                "current_price": 929.00,
                "original_price": 999.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "great_deal",
            },
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 949.00,
                "original_price": 999.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
            {
                "store_name": "PrimeGear (Demo)",
                "current_price": 989.00,
                "original_price": 999.00,
                "shipping_cost": 5.00,
                "availability": "Limited Stock",
                "trend_type": "high",
            },
        ],
    },
    {
        "sku": "AUD-SNY-WH1000XM5",
        "title": "Sony WH-1000XM5 Wireless Noise-Canceling Headphones",
        "brand": "Sony",
        "category": "Audio",
        "description": "Industry-leading noise cancellation with two processors and eight microphones, crystal clear hands-free calling, up to 30h battery.",
        "specs": {"Type": "Over-Ear", "Battery": "30 Hours", "ANC": "Auto NC Optimizer", "Fast Charge": "3 min for 3 hrs"},
        "image_url": "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "ElectroHub (Demo)",
                "current_price": 328.00,
                "original_price": 399.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "all_time_low",
            },
            {
                "store_name": "TechMart (Demo)",
                "current_price": 348.00,
                "original_price": 399.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "great_deal",
            },
            {
                "store_name": "DigitalBay (Demo)",
                "current_price": 389.00,
                "original_price": 399.99,
                "shipping_cost": 6.99,
                "availability": "In Stock",
                "trend_type": "inflated",
            },
            {
                "store_name": "PrimeGear (Demo)",
                "current_price": 359.00,
                "original_price": 399.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
        ],
    },
    {
        "sku": "AUD-BOS-QCULTRA",
        "title": "Bose QuietComfort Ultra Wireless Noise Cancelling Headphones",
        "brand": "Bose",
        "category": "Audio",
        "description": "Breakthrough spatialized audio for immersive listening, world-class quiet, and CustomTune technology for personalized sound.",
        "specs": {"Type": "Over-Ear", "Battery": "24 Hours", "Spatial Audio": "Yes", "Modes": "Quiet, Aware, Immersion"},
        "image_url": "https://images.unsplash.com/photo-1546435770-a3e426bf472b?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 379.00,
                "original_price": 429.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "great_deal",
            },
            {
                "store_name": "TechMart (Demo)",
                "current_price": 399.00,
                "original_price": 429.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
            {
                "store_name": "ElectroHub (Demo)",
                "current_price": 429.00,
                "original_price": 429.00,
                "shipping_cost": 4.99,
                "availability": "In Stock",
                "trend_type": "inflated",
            },
        ],
    },
    {
        "sku": "GAM-SON-PS5SLM",
        "title": "PlayStation 5 Slim Console (Disc Edition, 1TB SSD)",
        "brand": "Sony",
        "category": "Gaming",
        "description": "Slim design console packed with powerful gaming technology, 1TB of ultra-high speed SSD storage, 4K ray tracing support.",
        "specs": {"Storage": "1TB NVMe SSD", "Disc Drive": "Ultra HD Blu-ray", "Max Resolution": "4K 120Hz / 8K support", "Controller": "DualSense"},
        "image_url": "https://images.unsplash.com/photo-1606813907291-d86efa9b94db?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "TechMart (Demo)",
                "current_price": 449.99,
                "original_price": 499.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "great_deal",
            },
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 469.00,
                "original_price": 499.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
            {
                "store_name": "PrimeGear (Demo)",
                "current_price": 499.99,
                "original_price": 499.99,
                "shipping_cost": 12.99,
                "availability": "Limited Stock",
                "trend_type": "high",
            },
            {
                "store_name": "DigitalBay (Demo)",
                "current_price": 519.00,
                "original_price": 549.99,
                "shipping_cost": 9.99,
                "availability": "In Stock",
                "trend_type": "inflated",  # Artificial markup demo
            },
        ],
    },
    {
        "sku": "WCH-APL-S9-45",
        "title": "Apple Watch Series 9 GPS 45mm (Midnight Aluminum)",
        "brand": "Apple",
        "category": "Wearables",
        "description": "S9 SiP chip with Double Tap gesture, brighter display, on-device Siri, Precision Finding for iPhone, and comprehensive health monitoring.",
        "specs": {"Case Size": "45mm", "Display": "2000 nits OLED", "Battery": "18 hours", "Sensors": "ECG, Blood Oxygen, Temp"},
        "image_url": "https://images.unsplash.com/photo-1508685096489-7aacd43bd3b1?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "ElectroHub (Demo)",
                "current_price": 329.00,
                "original_price": 429.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "all_time_low",
            },
            {
                "store_name": "TechMart (Demo)",
                "current_price": 349.00,
                "original_price": 429.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "great_deal",
            },
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 379.00,
                "original_price": 429.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "trend_type": "normal",
            },
        ],
    },
    {
        "sku": "MON-DEL-U2723QE",
        "title": "Dell UltraSharp 27 4K USB-C Hub Monitor (U2723QE)",
        "brand": "Dell",
        "category": "Monitors",
        "description": "27-inch 4K IPS Black monitor with 2000:1 contrast ratio, 98% DCI-P3 color gamut, USB-C 90W power delivery, and built-in RJ45 Ethernet.",
        "specs": {"Size": "27 inch", "Panel": "IPS Black 4K (3840x2160)", "Contrast": "2000:1", "Ports": "USB-C 90W, HDMI, DP, Hub"},
        "image_url": "https://images.unsplash.com/photo-1527443224154-c4a3942d3acf?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 539.00,
                "original_price": 629.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "variant_name": "27\" 4K IPS Black",
                "condition": "Brand New",
                "trend_type": "great_deal",
            },
            {
                "store_name": "TechMart (Demo)",
                "current_price": 579.00,
                "original_price": 629.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "variant_name": "27\" 4K IPS Black",
                "condition": "Brand New",
                "trend_type": "normal",
            },
            {
                "store_name": "PrimeGear (Demo)",
                "current_price": 629.99,
                "original_price": 629.99,
                "shipping_cost": 15.00,
                "availability": "Limited Stock",
                "variant_name": "27\" 4K IPS Black",
                "condition": "Brand New",
                "trend_type": "inflated",
            },
        ],
    },
    {
        "sku": "CAM-SNY-A7IV",
        "title": "Sony Alpha 7 IV Full-Frame Mirrorless Camera (Body Only)",
        "brand": "Sony",
        "category": "Cameras",
        "description": "33MP Exmor R back-illuminated CMOS sensor, 4K 60p 10-bit 4:2:2 video recording, 8x more powerful BIONZ XR processing engine.",
        "specs": {"Sensor": "33MP Full-Frame Exmor R", "Mount": "Sony E-Mount", "Video": "4K 60p 10-bit", "Stabilization": "5-axis SteadyShot"},
        "image_url": "https://images.unsplash.com/photo-1516035069371-29a1b244cc32?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                "store_name": "DigitalBay (Demo)",
                "current_price": 2199.00,
                "original_price": 2499.00,
                "shipping_cost": 0.0,
                "availability": "Out of Stock",  # Cheapest price, but OUT OF STOCK!
                "variant_name": "Body Only / Black",
                "condition": "Brand New",
                "trend_type": "all_time_low",
            },
            {
                "store_name": "TechMart (Demo)",
                "current_price": 2298.00,
                "original_price": 2499.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",  # Lowest AVAILABLE offer
                "variant_name": "Body Only / Black",
                "condition": "Brand New",
                "trend_type": "great_deal",
            },
            {
                "store_name": "Apex Direct (Demo)",
                "current_price": 2398.00,
                "original_price": 2499.00,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "variant_name": "Body Only / Black",
                "condition": "Brand New",
                "trend_type": "normal",
            },
        ],
    },
    {
        "sku": "TV-LG-OLED65C3",
        "title": "LG C3 Series 65-Inch Class OLED evo 4K Smart TV",
        "brand": "LG",
        "category": "TVs",
        "description": "Self-lit OLED pixels with Brightness Booster, α9 AI Processor Gen6, 120Hz native refresh rate with Dolby Vision, Dolby Atmos, and G-SYNC.",
        "specs": {"Screen Size": "65 Inch", "Display": "4K OLED evo", "Refresh Rate": "120Hz", "Processor": "α9 AI Processor Gen6"},
        "image_url": "https://images.unsplash.com/photo-1593359677879-a4bb92f829d1?auto=format&fit=crop&w=600&q=80",
        "offers": [
            {
                # Single-store exclusive to evaluate single-store edge cases safely
                "store_name": "ElectroHub (Demo)",
                "current_price": 1596.99,
                "original_price": 1899.99,
                "shipping_cost": 0.0,
                "availability": "In Stock",
                "variant_name": "65\" evo OLED / Standard",
                "condition": "Brand New",
                "trend_type": "insufficient_history",  # Demonstrates insufficient history state!
            },
        ],
    },
]


def generate_history_points(current_price: float, trend_type: str, days: int = 90) -> list[tuple[str, float]]:
    """
    Generate realistic historical price records up to today.
    The points will model various pricing patterns for evaluating deals.
    """
    now = datetime.now(timezone.utc)
    if trend_type == "insufficient_history":
        # Only 1 observation recorded today
        return [(now.strftime("%Y-%m-%d %H:%M:%S"), current_price)]

    points = []
    # Generate points across a 90-day window
    intervals = [90, 75, 60, 45, 30, 21, 14, 7, 3, 0]

    for d in intervals:
        point_date = (now - timedelta(days=d)).strftime("%Y-%m-%d %H:%M:%S")

        if trend_type == "all_time_low":
            # In the past it was 10-25% higher, dropped recently
            if d > 14:
                price = round(current_price * 1.18, 2)
            elif d > 3:
                price = round(current_price * 1.08, 2)
            else:
                price = current_price
        elif trend_type == "great_deal":
            # Past price hovered around 12-15% higher
            if d > 7:
                price = round(current_price * 1.14, 2)
            else:
                price = current_price
        elif trend_type == "inflated":
            # In the past it was cheaper, recently raised!
            if d > 21:
                price = round(current_price * 0.88, 2)
            elif d > 7:
                price = round(current_price * 0.94, 2)
            else:
                price = current_price
        elif trend_type == "high":
            # Consistently near or at full price
            if d > 30:
                price = round(current_price * 0.98, 2)
            else:
                price = current_price
        else:  # normal / moderate
            # Slightly fluctuating around current price
            multiplier = 1.0 + (0.03 if (d % 2 == 0) else -0.01)
            price = round(current_price * multiplier, 2) if d > 0 else current_price

        points.append((point_date, price))

    return points


def seed_database(custom_path: str | None = None, force: bool = False, seed_demo_user: bool = False) -> None:
    """Seed the database with sample products, stores, offers, and price history."""
    init_db(custom_path)

    with get_connection(custom_path) as conn:
        cursor = conn.cursor()

        # Check if already seeded
        cursor.execute("SELECT COUNT(*) FROM products")
        count = cursor.fetchone()[0]
        if count > 0 and not force:
            return

        if force:
            cursor.execute("DELETE FROM price_alerts")
            cursor.execute("DELETE FROM price_tracking")
            cursor.execute("DELETE FROM user_preferences")
            cursor.execute("DELETE FROM wishlist")
            cursor.execute("DELETE FROM users")
            cursor.execute("DELETE FROM price_history")
            cursor.execute("DELETE FROM offers")
            cursor.execute("DELETE FROM stores")
            cursor.execute("DELETE FROM products")

        # 1. Insert Demo Stores (Tech & Indian Beauty Retailers)
        all_stores = DEMO_STORES + DEMO_BEAUTY_STORES
        store_ids = {}
        store_domains = {}
        for store in all_stores:
            cursor.execute(
                """
                INSERT INTO stores (name, domain, rating, shipping_policy)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                    domain=excluded.domain,
                    rating=excluded.rating,
                    shipping_policy=excluded.shipping_policy
                """,
                (store["name"], store["domain"], store["rating"], store["shipping_policy"]),
            )
            cursor.execute("SELECT id FROM stores WHERE name = ?", (store["name"],))
            store_ids[store["name"]] = cursor.fetchone()[0]
            store_domains[store["name"]] = store["domain"]

        # 2. Insert Products and Offers (Tech & Indian Beauty Catalog)
        all_products = DEMO_PRODUCTS + DEMO_BEAUTY_PRODUCTS
        for prod in all_products:
            cursor.execute(
                """
                INSERT INTO products (sku, title, brand, category, description, specs_json, image_url)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    prod["sku"],
                    prod["title"],
                    prod["brand"],
                    prod["category"],
                    prod["description"],
                    json.dumps(prod["specs"]),
                    prod["image_url"],
                ),
            )
            product_id = cursor.lastrowid

            currency = "INR" if "BEAUTY" in prod["sku"] else "USD"

            for offer in prod["offers"]:
                store_name = offer["store_name"]
                store_id = store_ids[store_name]
                store_domain = store_domains.get(store_name, "example.com")
                cursor.execute(
                    """
                    INSERT INTO offers (
                        product_id, store_id, current_price, original_price, 
                        shipping_cost, currency, availability, variant_name, condition, offer_url
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product_id,
                        store_id,
                        offer["current_price"],
                        offer.get("original_price"),
                        offer.get("shipping_cost", 0.0),
                        currency,
                        offer.get("availability", "In Stock"),
                        offer.get("variant_name", "Standard"),
                        offer.get("condition", "Brand New"),
                        f"https://{store_domain}/product/{prod['sku']}",
                    ),
                )
                offer_id = cursor.lastrowid

                # Generate historical data for this offer
                history_points = generate_history_points(offer["current_price"], offer.get("trend_type", "normal"))
                for recorded_at, hist_price in history_points:
                    cursor.execute(
                        """
                        INSERT INTO price_history (offer_id, price, currency, data_source, data_status, recorded_at)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (offer_id, hist_price, currency, "demo_seed", "demo", recorded_at),
                    )

    # 3. Seed Demo Member Account for Academic Viva / Evaluation
    if seed_demo_user:
        from src.services.auth_service import register_user, get_user_by_email
        from src.services.wishlist_service import add_to_wishlist
        from src.services.preference_service import save_user_preferences
        from src.services.price_tracking_service import add_tracked_product

        demo_user = get_user_by_email("demo@pricewise.ai", custom_path=custom_path)
        if not demo_user:
            ok, _, demo_user = register_user(
                email="demo@pricewise.ai",
                password="DemoPass123!",
                display_name="Alex Demo",
                custom_path=custom_path,
            )
        if demo_user:
            # Phase 14 Stage B: the seeded demo account is the only account
            # that is granted administrator rights automatically. Explicit
            # administrator authorisation replaced the previous rule that
            # treated every "@pricewise.ai" address as an administrator.
            with get_connection(custom_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE users SET is_admin = 1 WHERE id = ?", (demo_user.id,)
                )
            demo_user.is_admin = True
            from src.services.product_service import get_products
            prods = get_products(custom_path=custom_path)
            macbook = next((p for p in prods if "LAP-MAC" in p.sku), prods[0] if prods else None)
            sony = next((p for p in prods if "AUD-SNY" in p.sku), prods[1] if len(prods) > 1 else None)

            if macbook:
                add_to_wishlist(
                    user_id=demo_user.id,
                    product_id=macbook.id,
                    note="Wait for seasonal price drop or holiday bundle",
                    custom_path=custom_path,
                )
                add_tracked_product(
                    product_id=macbook.id,
                    target_price=round((macbook.lowest_price or 1800.0) * 0.90, 2),
                    note="Auto-alert target for MacBook Pro",
                    alert_trigger_type="target_or_drop",
                    user_id=demo_user.id,
                    custom_path=custom_path,
                )
            if sony:
                add_to_wishlist(
                    user_id=demo_user.id,
                    product_id=sony.id,
                    note="Top choice for noise-canceling study headphones",
                    custom_path=custom_path,
                )
            # Save demo preferences
            save_user_preferences(
                user_id=demo_user.id,
                preferred_categories=["Laptops", "Audio"],
                preferred_brands=["Apple", "Sony"],
                min_budget=200.0,
                max_budget=2000.0,
                sort_preference="best_deal",
                priority="balanced",
                custom_path=custom_path,
            )


if __name__ == "__main__":
    seed_database(force=True, seed_demo_user=True)
    print("Database successfully initialized and seeded with demo data.")

