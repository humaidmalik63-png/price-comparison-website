"""Data models for PriceWise AI entities."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class Store:
    id: int
    name: str
    domain: str
    rating: float = 4.5
    shipping_policy: str = ""
    created_at: Optional[datetime] = None


@dataclass
class PricePoint:
    price: float
    recorded_at: str  # ISO string or YYYY-MM-DD HH:MM:SS
    currency: str = "USD"
    data_source: str = "demo_seed"
    data_status: str = "demo"
    id: Optional[int] = None
    offer_id: Optional[int] = None


@dataclass
class Offer:
    id: int
    product_id: int
    store_id: int
    store_name: str
    store_rating: float
    current_price: float
    original_price: Optional[float] = None
    shipping_cost: float = 0.0
    currency: str = "USD"
    availability: str = "In Stock"
    variant_name: str = "Standard"
    condition: str = "Brand New"
    offer_url: str = ""
    last_checked: Optional[str] = None
    price_history: list[PricePoint] = field(default_factory=list)
    is_shipping_disclosed: bool = True
    coupon_discount: float = 0.0
    coupon_code: Optional[str] = None
    source_type: str = "demo"  # 'verified_live', 'partner_feed', 'cached', 'manually_curated', 'demo', 'unavailable'
    # Phase 14 Stage D: whether the purchase link points at a real, checked
    # product page. Demo catalogue rows carry synthetic SKU-shaped URLs that
    # do not resolve on the retailer site, so they are never presented as a
    # purchase link.
    link_status: str = "demo_not_verified"  # 'verified', 'demo_not_verified', 'unavailable'
    link_checked_at: Optional[str] = None

    @property
    def currency_symbol(self) -> str:
        """Return ₹ for Indian Rupee or $ for USD."""
        return "₹" if (self.currency or "").upper() == "INR" else "$"

    @property
    def is_available(self) -> bool:
        """True if the offer is in stock or available to purchase."""
        if not self.availability:
            return False
        status = self.availability.strip().lower()
        return status not in ("out of stock", "unavailable", "discontinued", "sold out")

    @property
    def has_valid_price(self) -> bool:
        """True if current price is a positive, non-zero number."""
        return self.current_price is not None and self.current_price > 0

    @property
    def landed_cost(self) -> Optional[float]:
        """
        Total landed cost (base + shipping - coupon).
        Returns None if shipping is undisclosed / unknown.
        """
        if not self.has_valid_price:
            return None
        if not self.is_shipping_disclosed:
            return None
        shipping = self.shipping_cost if self.shipping_cost is not None else 0.0
        coupon = self.coupon_discount or 0.0
        return round(max(0.0, self.current_price + shipping - coupon), 2)

    @property
    def total_cost(self) -> float:
        """Effective total cost including shipping and coupon."""
        if not self.has_valid_price:
            return 0.0
        shipping = self.shipping_cost if (self.is_shipping_disclosed and self.shipping_cost is not None) else 0.0
        coupon = self.coupon_discount or 0.0
        return round(max(0.0, self.current_price + shipping - coupon), 2)

    @property
    def direct_discount_pct(self) -> float:
        """Discount percentage against store's listed original price."""
        if (
            self.has_valid_price
            and self.original_price
            and self.original_price > self.current_price
            and self.original_price > 0
        ):
            return round(((self.original_price - self.current_price) / self.original_price) * 100, 1)
        return 0.0


@dataclass
class Product:
    id: int
    sku: str
    title: str
    brand: str
    category: str
    description: str
    specs: dict[str, Any] = field(default_factory=dict)
    image_url: str = ""
    created_at: Optional[str] = None
    is_active: bool = True
    image_source_url: Optional[str] = None
    image_source_name: Optional[str] = None
    image_status: str = "placeholder"
    image_last_checked: Optional[str] = None
    # Phase 15: the manufacturer's own product page, recorded in the curated
    # catalogue specifications together with its source and evidence. It is a
    # brand page, not a retailer offer, and it is presented as such.
    official_url: Optional[str] = None
    official_source: Optional[str] = None
    official_evidence: Optional[str] = None
    offers: list[Offer] = field(default_factory=list)

    @property
    def currency_symbol(self) -> str:
        """Return ₹ if any offer is in INR, else $."""
        for o in self.offers:
            if (o.currency or "").upper() == "INR":
                return "₹"
        return "$"

    @property
    def available_offers(self) -> list[Offer]:
        """List of offers that are both in stock and have valid positive pricing."""
        return [o for o in self.offers if o.is_available and o.has_valid_price]

    @property
    def lowest_price(self) -> Optional[float]:
        """Lowest listed product price among available offers, or fallback to any valid offer."""
        avail = [o.current_price for o in self.available_offers]
        if avail:
            return min(avail)
        all_valid = [o.current_price for o in self.offers if o.has_valid_price]
        return min(all_valid) if all_valid else None

    @property
    def lowest_total_cost(self) -> Optional[float]:
        """Lowest effective total cost among available offers."""
        avail = [o.total_cost for o in self.available_offers]
        if avail:
            return min(avail)
        all_valid = [o.total_cost for o in self.offers if o.has_valid_price]
        return min(all_valid) if all_valid else None

    @property
    def highest_price(self) -> Optional[float]:
        """Highest listed price among valid offers."""
        valid = [o.current_price for o in self.offers if o.has_valid_price]
        return max(valid) if valid else None

    @property
    def slug(self) -> str:
        """Generate a clean, deterministic URL-friendly slug from brand and title or SKU."""
        import re
        raw = f"{self.brand}-{self.title}".lower()
        cleaned = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
        return cleaned or f"product-{self.id}"

    @property
    def offer_count(self) -> int:
        return len(self.offers)

    @property
    def available_offer_count(self) -> int:
        return len(self.available_offers)

    @property
    def unique_store_count(self) -> int:
        return len({o.store_name for o in self.offers})


@dataclass
class PriceTrackingRecord:
    id: int
    product_id: int
    target_price: float
    created_at: str
    status: str = "active"  # 'active' or 'paused'
    user_id: Optional[int] = None
    last_observed_price: Optional[float] = None
    last_checked_at: Optional[str] = None
    last_alert_at: Optional[str] = None
    last_alert_price: Optional[float] = None
    last_alert_type: Optional[str] = None
    alert_trigger_type: str = "target_or_drop"  # 'target_or_drop', 'target_only', 'drop_only'
    note: Optional[str] = None

    # Joined fields for UI convenience
    product_title: Optional[str] = None
    product_brand: Optional[str] = None
    product_category: Optional[str] = None
    product_image_url: Optional[str] = None
    product_sku: Optional[str] = None
    current_lowest_price: Optional[float] = None
    current_lowest_store: Optional[str] = None
    is_available: bool = True

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def full_name(self) -> str:
        return self.display_name

    @property
    def is_paused(self) -> bool:
        return self.status == "paused"

    @property
    def is_target_reached(self) -> bool:
        """True if currently observed price is at or below target price."""
        ref_price = self.current_lowest_price if self.current_lowest_price is not None else self.last_observed_price
        if ref_price is not None:
            return ref_price <= self.target_price
        return False

    @property
    def price_to_target(self) -> Optional[float]:
        """Price difference (current - target). Positive means still above target."""
        ref_price = self.current_lowest_price if self.current_lowest_price is not None else self.last_observed_price
        if ref_price is not None:
            return round(ref_price - self.target_price, 2)
        return None

    @property
    def price_to_target_pct(self) -> Optional[float]:
        """Percentage above/below target."""
        diff = self.price_to_target
        if diff is not None and self.target_price > 0:
            return round((diff / self.target_price) * 100, 1)
        return None


@dataclass
class PriceAlert:
    id: int
    tracking_id: int
    product_id: int
    alert_type: str  # 'target_reached', 'price_drop'
    observed_price: float
    message: str
    created_at: str
    user_id: Optional[int] = None
    previous_price: Optional[float] = None
    target_price: Optional[float] = None
    is_read: bool = False
    trigger_key: Optional[str] = None
    delivery_status: str = "in_app_delivered"  # 'in_app_delivered', 'email_unconfigured', 'pending'
    channel: str = "in_app"  # 'in_app', 'email' (labeled unconfigured when email)

    # Joined fields
    product_title: Optional[str] = None
    product_brand: Optional[str] = None
    product_image_url: Optional[str] = None


@dataclass
class User:
    """User account entity for PriceWise AI (Phase 7)."""
    id: int
    display_name: str
    email: str
    password_hash: str
    created_at: str
    status: str = "active"  # 'active', 'suspended', 'deactivated'
    # Phase 14 Stage B: explicit administrator authorization. Administrator
    # rights are granted by the seeder or by an audited database update and
    # can never be obtained by self-registration.
    is_admin: bool = False
    # Incremented whenever the credentials change, so previously issued
    # session tokens stop validating.
    token_version: int = 0

    @property
    def is_active(self) -> bool:
        return self.status == "active"

    @property
    def full_name(self) -> str:
        return self.display_name


# =====================================================================
# Phase 4: Reviews, Platform Comparison & Usage Intelligence Models
# =====================================================================

@dataclass
class ProductReview:
    id: int
    product_id: int
    platform: str  # 'Nykaa', 'Tira', 'Purplle', 'Amazon India', 'Myntra'
    reviewer_name: str
    rating: float  # out of rating_scale
    comment: str
    rating_scale: float = 5.0
    title: Optional[str] = None
    review_date: Optional[str] = None
    verified_buyer: bool = False
    skin_type: Optional[str] = None
    source_url: Optional[str] = None
    data_status: str = "demo"  # 'demo', 'verified_retailer', 'manually_curated'
    external_review_id: Optional[str] = None
    created_at: Optional[str] = None

    @property
    def normalized_rating(self) -> float:
        """Normalize rating to standard 5.0 scale."""
        if self.rating_scale and self.rating_scale > 0:
            return round((self.rating / self.rating_scale) * 5.0, 1)
        return self.rating


@dataclass
class PlatformRatingSummary:
    platform: str
    average_rating: Optional[float]
    review_count: Optional[int]
    rating_scale: float = 5.0
    data_source: str = "Retailer Feed (Demo)"
    product_url: Optional[str] = None
    last_verified: Optional[str] = None
    is_available: bool = True

    @property
    def normalized_rating(self) -> Optional[float]:
        """Normalized 5-star rating."""
        if self.average_rating is not None and self.rating_scale > 0:
            return round((self.average_rating / self.rating_scale) * 5.0, 2)
        return None


@dataclass
class WeightedReviewScore:
    product_id: int
    weighted_rating: Optional[float]
    total_reviews: int
    platforms_included: int
    platform_breakdown: list[PlatformRatingSummary] = field(default_factory=list)
    calculation_method: str = "Sum(Rating_i * Count_i) / Sum(Count_i)"
    explanation: str = ""
    data_status: str = "demo"


@dataclass
class ProductUsageGuide:
    product_id: int
    routine: str  # 'AM', 'PM', 'AM & PM'
    step_number: int  # 1 to 5
    step_name: str  # e.g. 'Cleanse', 'Tone', 'Treat', 'Moisturize', 'Sunscreen'
    frequency: str  # e.g. 'Daily every morning', 'Twice daily', '2-3 nights per week'
    application_instructions: str
    precautions: str
    patch_test_guideline: str
    sun_safety_guideline: Optional[str] = None
    key_actives_breakdown: list[dict[str, str]] = field(default_factory=list)
    source_reference: str = "Manufacturer Label & Indian Dermatological Society Guidelines"


@dataclass
class WishlistItem:
    """Product saved in a user's personal wishlist."""
    id: int
    user_id: int
    product_id: int
    created_at: str
    note: Optional[str] = None

    # Joined fields
    product_title: Optional[str] = None
    product_brand: Optional[str] = None
    product_category: Optional[str] = None
    product_image_url: Optional[str] = None
    product_sku: Optional[str] = None
    current_lowest_price: Optional[float] = None
    current_lowest_store: Optional[str] = None
    is_available: bool = True
    is_tracked: bool = False
    tracked_target_price: Optional[float] = None

    @property
    def lowest_price(self) -> Optional[float]:
        return self.current_lowest_price

    @property
    def lowest_store_name(self) -> Optional[str]:
        return self.current_lowest_store

    @property
    def title(self) -> Optional[str]:
        return self.product_title

    @property
    def brand(self) -> Optional[str]:
        return self.product_brand

    @property
    def category(self) -> Optional[str]:
        return self.product_category

    @property
    def image_url(self) -> Optional[str]:
        return self.product_image_url

    @property
    def sku(self) -> Optional[str]:
        return self.product_sku

    @property
    def tracking_target_price(self) -> Optional[float]:
        return self.tracked_target_price


@dataclass
class UserPreferences:
    """Saved personal shopping preferences for a user."""
    user_id: int
    preferred_categories: list[str] = field(default_factory=list)
    preferred_brands: list[str] = field(default_factory=list)
    min_budget: Optional[float] = None
    max_budget: Optional[float] = None
    preferred_store_id: Optional[int] = None
    preferred_store_name: Optional[str] = None
    sort_preference: str = "best_deal"  # 'lowest_price', 'best_deal', 'highest_price', 'name'
    priority: str = "balanced"  # 'lowest_price', 'best_deal', 'balanced'
    updated_at: Optional[str] = None



