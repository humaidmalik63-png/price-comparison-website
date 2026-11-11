# PriceWise AI — Comprehensive Academic Demo & Viva Presentation Guide 🎓

> **Course Project:** Price Comparison Website with Real Deal Detector™  
> **Brand:** PriceWise AI (*Shop smarter. Save strategically.*)  
> **Version:** 1.0.0 (Phase 8 Final Academic Release)  
> **Stack:** Python 3.12 | Streamlit | SQLite3 | Pandas | Altair | Pytest  

---

## 📋 Executive Viva Overview

**PriceWise AI** is an academic prototype designed to address misleading retail practices in modern e-commerce—specifically artificial reference pricing ("phantom markdowns"), price volatility, and shipping cost opacity.

Rather than acting as a simple shopping catalog, PriceWise AI serves as a **transparent shopping intelligence engine** that:
1. Compares multi-store total checkout prices (base price + shipping).
2. Evaluates offers against empirical price history using a deterministic mathematical model (**Real Deal Detector™**).
3. Flags suspicious advertised discounts without subjective accusations.
4. Provides multi-objective recommendations tailored to shopper constraints (**Smart Purchase Advisor**).
5. Monitors target prices and price drops with deduplicated notifications.
6. Delivers secure, multi-tenant personalization with strict tenant isolation.

---

## 🔑 Quick-Start Credentials & Environment Setup

### 1. Terminal Startup
```bash
# Activate virtual environment
.\.venv\Scripts\Activate.ps1    # On Windows PowerShell
# or: source .venv/bin/activate # On macOS/Linux

# (Optional) Re-seed clean demo database
python -m src.database.seed

# Launch Streamlit dashboard
streamlit run app.py
```
Open **`http://localhost:8501`** in your browser.

### 2. Pre-Configured Demo Account
| Parameter | Value |
|:---|:---|
| **Email** | `demo@pricewise.ai` |
| **Password** | Set via `PRICEWISE_DEMO_USER_PASSWORD` env var |
| **Name** | Demo Researcher |
| **Quick Action** | Click **⚡ Quick Fill Demo Login** in the sidebar |

---

## 🎬 15-Step Live Demonstration Script

Follow these 15 steps sequentially during a project demonstration or viva examination.

---

### Step 1: Launch Application & Overview Initial View
- **Action**: Open the home page (`http://localhost:8501`).
- **Talking Points**:
  - Point out the branding, tagline *"Shop smarter. Save strategically."*, and the prominent **DEMO DATA** badge confirming ethical academic prototyping.
  - Review the **Intelligence Stats Bar** at the top showing total tracked products, active offers across stores, recorded price points, and active monitored alerts.
  - Highlight the clean visual hierarchy, organized category tabs, and search bar.

---

### Step 2: Demonstrate Search, Dynamic Filters & Sorting
- **Action**:
  1. In the search box, type `Apple` or `Sony` (case-insensitive test).
  2. Select the **Laptops** category. Observe that the brand dropdown dynamically adjusts to show only brands available in that category.
  3. Change the sort selector to **Lowest Base Price** and **Highest Base Price**.
  4. Type an unmatched term like `xyznotfound` to show the friendly empty-search state.
- **Talking Points**:
  - Search matches across titles, brands, SKUs, and specification metadata.
  - Dynamic dropdown filtering prevents invalid filter combinations.

---

### Step 3: Open Product Comparison & Explain Deal Scoring
- **Action**: Click on **MacBook Pro 14" (M3)** or **Sony WH-1000XM5** to open the **Multi-Store Price Comparison** view.
- **Talking Points**:
  - Show the multi-store offer table comparing 5 distinct retailers (*TechMart Demo*, *ElectroHub Demo*, etc.).
  - Emphasize that **Lowest Total Cost** accounts for base price **plus** shipping fees.
  - Point out the **Real Deal Detector™** widget displaying the Deal Score (e.g., 78/100 `GOOD DEAL` or `EXCELLENT DEAL`).
  - Explain the dual-factor mathematical formula:
    $$\text{Deal Score} = \text{clamp}\left(0.60 \times S_{range} + 0.40 \times S_{avg}, 0, 100\right)$$
    where $S_{range}$ evaluates position between all-time minimum and maximum, and $S_{avg}$ evaluates discount relative to historical mean.

---

### Step 4: Show Historical Price Chart & Interpret Time-Series
- **Action**: Scroll down to the **Historical Price Trend** chart in the comparison view. Toggle between **30d**, **90d**, and **All-Time** views.
- **Talking Points**:
  - Chart is generated interactively using **Altair** and bounded strictly by variant (e.g. 512GB SSD) and currency (USD).
  - Green dotted reference line indicates the **Historical Minimum** ($P_{min}$).
  - Gray dashed reference line indicates the **Historical Mean** ($\mu_{hist}$).
  - Hover over data points to demonstrate immutable, timestamped observation tracking.

---

### Step 5: Demonstrate Suspicious Discount Detection
- **Action**: Open the **Samsung Galaxy Watch 6** or **Logitech MX Master 3S** comparison view.
- **Talking Points**:
  - Highlight the **Suspicious Advertised Discount Warning** banner.
  - Explain the two analytical triggers:
    1. *Sale Price Exceeds Average*: Retailer advertises a "Sale" tag, but the current price is actually higher than the product's historical average.
    2. *Unverified Reference MSRP*: Retailer crosses out a fabricated "original" price that is >15% higher than any recorded price in the history table.
  - Emphasize academic integrity: the system labels these as *analytical anomalies*, not fraud accusations.

---

### Step 6: Use Smart Purchase Advisor with Specific Constraints
- **Action**: Navigate to **Smart Purchase Advisor** from the sidebar.
  1. Select Category: **Laptops**.
  2. Select Primary Use Case: **Programming**.
  3. Set Maximum Budget: **$2,000**.
  4. Specify Minimum RAM: **16 GB**.
  5. Click **🔍 Generate Recommendations**.
- **Talking Points**:
  - Explain the 3 distinct recommendation categories:
    - **🌟 BEST OVERALL**: Highest composite score ($R_{score} = 0.40 S_{use} + 0.30 S_{spec} + 0.20 S_{budget} + 0.10 S_{brand}$).
    - **💰 BEST BUDGET**: Lowest total cost that fully satisfies all hard constraints.
    - **🏷️ BEST CURRENT DEAL**: Highest verified Real Deal Score ($\ge 65$).
  - Demonstrate **Missing Specification Safeguards**: Unknown specs are never assumed compliant.
  - Demonstrate **Closest Alternatives**: If budget is set unrealistically low (e.g., $500 for a 32GB laptop), the system gracefully displays near-matches with overrun amounts highlighted.

---

### Step 7: Demonstrate Price Tracking Setup
- **Action**:
  1. From the comparison view or advisor, click **🔔 Track this Product**.
  2. Input a target price (e.g., $1,400.00) and select alert trigger mode: **Target Reached or Meaningful Drop**.
  3. Add a personal note: *"Alert for semester project workstation"*.
  4. Click **Set Price Alert**.
- **Talking Points**:
  - The tracking record is persistently saved to the SQLite `price_tracking` table.
  - Target price must be positive, and duplicate monitoring for the same product is prevented.

---

### Step 8: Show Price Tracker Dashboard & Alerts Inbox
- **Action**: Navigate to **Price Tracker & Alerts** in the sidebar.
- **Talking Points**:
  - Point out active vs. paused monitors.
  - Show status badge (**Active**, **Target Reached**).
  - Open the **Alerts Inbox** tab:
    - Review trigger types: `target_reached` ($P_{curr} \le P_{target}$) and `price_drop` ($\Delta P \ge \$1.00 \land \Delta P / P_{prev} \ge 1\%$).
    - Point out **Deduplication Engine**: Uses deterministic trigger keys (`<track_id>:<type>:<price>`) to prevent duplicate spam on re-runs.
    - Click **Mark as Read** to update alert state.

---

### Step 9: User Registration, Login & Session State
- **Action**:
  1. Log out if currently signed in.
  2. Click **⚡ Quick Fill Demo Login** in the sidebar, or enter `demo@pricewise.ai` / the value of `PRICEWISE_DEMO_USER_PASSWORD`.
  3. Click **Sign In**.
- **Talking Points**:
  - Security architecture:
    - Passwords hashed using standard library `hashlib.pbkdf2_hmac` (`sha256`, 260,000 iterations, 16-byte random salt).
    - Constant-time verification using `secrets.compare_digest` to prevent timing side-channel attacks.
    - No plaintext passwords ever written to disk or logs.
  - Streamlit `st.session_state` preserves authentication state across page navigations without external cookies or token vulnerabilities.

---

### Step 10: Demonstrate Wishlist Functionality
- **Action**: Navigate to **My Wishlist** in the sidebar.
- **Talking Points**:
  - Wishlist items display product image with automatic SVG fallback, brand, category, lowest offer across stores, and personal shopping notes.
  - Live link to price tracking: cards indicate if the wishlisted product is also being tracked in the Price Tracker.
  - Edit a note inline (e.g., *"Wait until Black Friday demo sale"*), click **Save Note**, and observe instant persistence in the `wishlist` table.
  - Click **Remove** to delete an item, showing real-time count decrement.

---

### Step 11: Set User Preferences & Personalized Recommendations
- **Action**:
  1. Navigate to **Shopping Preferences** in the sidebar.
  2. Select Preferred Brands: **Apple** and **Sony**.
  3. Set Preferred Retailer: **Best Buy Demo**.
  4. Set Budget Envelope: Min **$500**, Max **$2,200**.
  5. Select Default Sort: **Best Deal Score**.
  6. Click **Save Preferences**.
  7. Return to **Smart Purchase Advisor** and run a search.
- **Talking Points**:
  - Explain **Explainable Personalization**:
    - Recommendations gain tailored badges: *"Matches your saved preferred brand 'Apple'"* and *"Available at your preferred store 'Best Buy Demo'"*.
    - Brand match score receives full 10% weighting boost.
  - Emphasize constraint integrity: Preferences *never* override hard technical specs or budget limits.

---

### Step 12: Demonstrate Multi-Tenant Data Isolation
- **Action**:
  1. In the sidebar, click **Sign Out**.
  2. Register a new user: `guest.student@univ.edu` / `Pass123456!`.
  3. Open **My Wishlist** and **Price Tracker**.
- **Talking Points**:
  - The new user's wishlist is empty (0 items) and price tracker has 0 items.
  - None of `demo@pricewise.ai`'s private wishlist notes or target prices are visible.
  - Composite SQLite constraint `UNIQUE(user_id, product_id)` allows both users to track the same product with distinct target thresholds without collision.
  - Service methods enforce caller authorization checks (`WHERE id = ? AND user_id = ?`).

---

### Step 13: Data Safety & Resilience Demonstration
- **Action**:
  1. Open Catalog Search on the Home page.
  2. Enter a SQL injection payload: `'; DROP TABLE products; --`.
  3. Press Enter.
- **Talking Points**:
  - Show that the catalog safely returns empty results without crashing.
  - Re-type a normal query (e.g. `MacBook`) to show that all database tables remain intact.
  - Explain that all SQLite queries utilize parameterized bindings (`?`), completely preventing SQL injection vulnerabilities.
  - Mention image resilience: If any remote product image link returns 404 or fails, the client triggers `onerror="this.src=..."` substituting a clean inline SVG badge.

---

### Step 14: Explain Architecture & Technology Decisions
- **Action**: Navigate to **About & Architecture** in the sidebar.
- **Talking Points**:
  - Explain the 4-tier modular architecture:
    1. **Presentation Tier (`src/ui/`)**: Pure Streamlit UI components and views; zero direct SQL execution.
    2. **Service Tier (`src/services/`)**: Business orchestration (Search, Comparison, Advisor, Tracking, Wishlist, Auth).
    3. **Intelligence & Analysis Tier (`src/analysis/`)**: Mathematical scoring models (`DealDetector`, `PricePoint`, `PriceStatistics`).
    4. **Data Persistence Tier (`src/database/`)**: Models, parameterized queries, and idempotent migrations (`migrate_db`).
  - Explain why **Streamlit + SQLite** was chosen:
    - Zero heavy external daemon dependencies (no Redis, Docker, or Node required for viva examiners).
    - Single-file database portability (`data/pricewise.db`).
    - High execution speed: full 134-test suite completes in ~50 seconds on standard laptop hardware.

---

### Step 15: Conclude with Academic Takeaways & Future Work
- **Action**: Conclude the demonstration.
- **Summary Points**:
  - **Core Achievement**: Proved that mathematical time-series analysis can effectively expose misleading advertised retail discounts and provide actionable shopping advice.
  - **Key Differentiator**: Separation of nominal lowest price from genuine historical value; a cheap product is not automatically a "good deal".
  - **Limitations & Future Work**:
    1. Integration of real-world web scrapers or retailer affiliate APIs (subject to rate limiting and Terms of Service).
    2. Machine learning time-series forecasting (e.g., ARIMA or Prophet) to predict future price drops.
    3. Multi-currency live conversion via exchange rate APIs.

---

## 💡 Examiner Q&A Cheat Sheet

| Question | Recommended Answer |
|:---|:---|
| **Q1: Why did you not use a live web scraper or Amazon/eBay API?** | *Live retail APIs require paid corporate partner tiers, and live scraping is brittle and subject to frequent DOM breakage, IP bans, and legal terms of service restrictions. For academic validation, curated time-series data allows deterministic, reproducible evaluation of our Deal Scoring algorithms across known edge cases.* |
| **Q2: How does the Real Deal Detector prevent bias toward cheap products?** | *Nominal price is not deal score. A $30 cheap accessory can be a terrible deal if its usual price is $20. Our score measures $S_{range}$ (distance between all-time min and max) and $S_{avg}$ (deviation from historical mean $\mu_{hist}$). High score requires being significantly below its own typical pricing.* |
| **Q3: What happens when a product is brand new with no price history?** | *We enforce an honest Insufficient Data policy. Unless a product has at least 3 timestamped observations spanning 7+ days (or 5+ total points), the score is strictly withheld (`None`) and displays 'INSUFFICIENT DATA'. We never guess or fabricate arbitrary numbers.* |
| **Q4: How do you handle shipping costs in store comparison?** | *Effective total cost is calculated as $\text{Total} = \text{Base Price} + \text{Shipping Cost}$. A store offering $95 with $15 shipping loses to a store offering $100 with free shipping. In-stock availability is also strictly validated.* |
| **Q5: How do you protect user passwords without external auth libraries?** | *We implement standard library PBKDF2-HMAC-SHA256 with 260,000 iterations and 16 bytes of cryptographically secure random salt (`secrets.token_bytes(16)`). Passwords are verified in constant time via `secrets.compare_digest` to prevent timing attacks. Plaintext is never stored.* |
| **Q6: How do you ensure multi-tenant data isolation in SQLite?** | *Every query in `wishlist_service.py` and `price_tracking_service.py` filters by `user_id`. Mutating operations check `WHERE id = ? AND user_id = ?` and reject cross-tenant manipulation with an 'Access Denied' response, verified by automated unit tests.* |
| **Q7: What is the automated test coverage?** | *134 comprehensive automated unit and integration tests across 13 test files covering all phases (100% passing in ~50s via pytest). Includes tests for SQL injection, edge-case math, duplicate alert prevention, and migration backwards compatibility.* |

---
*PriceWise AI — Academic Prototype 2026*

