"""API Response and Request Schemas for PriceWise AI Beauty (Phase 6A)."""

from typing import Any, Optional, List, Dict
from pydantic import BaseModel, Field, ConfigDict


class HealthResponse(BaseModel):
    status: str = "ok"
    app_name: str
    version: str
    database: str
    record_count: int


class OfferSchema(BaseModel):
    id: int
    product_id: int
    store_id: int
    store_name: str
    store_rating: float
    current_price: float
    original_price: Optional[float] = None
    shipping_cost: Optional[float] = None
    is_shipping_disclosed: bool = True
    currency: str = "INR"
    availability: str = "In Stock"
    variant_name: str = "Standard"
    condition: str = "Brand New"
    offer_url: str = ""
    coupon_code: Optional[str] = None
    coupon_discount: float = 0.0
    total_cost: Optional[float] = None
    source_type: str = "demo"
    last_checked: Optional[str] = None
    # Phase 14 Stage D: link provenance. `purchase_url` is only populated when
    # the link has been verified to resolve to this exact product.
    link_status: str = "demo_not_verified"
    purchase_url: Optional[str] = None
    link_checked_at: Optional[str] = None


class ProductListItemSchema(BaseModel):
    id: int
    sku: str
    slug: str
    title: str
    brand: str
    category: str
    description: str
    image_url: str
    lowest_price: Optional[float] = None
    highest_price: Optional[float] = None
    lowest_total_cost: Optional[float] = None
    currency_symbol: str = "₹"
    available_offer_count: int = 0
    specs: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True
    image_source_url: Optional[str] = None
    image_source_name: Optional[str] = None
    image_status: str = "placeholder"
    image_last_checked: Optional[str] = None


class ProductDetailSchema(ProductListItemSchema):
    offers: list[OfferSchema] = Field(default_factory=list)
    created_at: Optional[str] = None


class LiveRetailerOfferSchema(BaseModel):
    retailer_name: str
    store_id: str
    status: str
    listed_price: Optional[float] = None
    mrp: Optional[float] = None
    discount_pct: float = 0.0
    shipping_fee: Optional[float] = None
    is_shipping_disclosed: bool = True
    coupon_code: Optional[str] = None
    coupon_discount: float = 0.0
    total_cost: Optional[float] = None
    stock_status: str = "In Stock"
    in_stock: bool = True
    purchase_url: str = ""
    variant_detected: Optional[str] = None
    match_classification: str = "verified_match"
    is_lowest_listed: bool = False
    is_lowest_total: bool = False
    source_type: str = "verified_live"
    retrieved_at: str
    validation_notes: Optional[str] = None


class LiveComparisonSummarySchema(BaseModel):
    lowest_listed_price: Optional[float] = None
    lowest_listed_retailer: Optional[str] = None
    lowest_total_cost: Optional[float] = None
    lowest_total_retailer: Optional[str] = None
    retailers_checked: int = 0
    retailers_retrieved: int = 0
    retailers_unavailable: int = 0
    retailers_unsupported: int = 0
    retailers_restricted: int = 0
    cheapest_savings_amount: float = 0.0
    cheapest_savings_percent: float = 0.0


class LiveComparisonResponse(BaseModel):
    product_id: Optional[int] = None
    product_title: str
    brand: str
    target_variant: str
    is_cached: bool = False
    freshness_seconds: int = 0
    retrieval_timestamp: str
    offers: list[LiveRetailerOfferSchema] = Field(default_factory=list)
    summary: LiveComparisonSummarySchema


class ManualUrlCheckRequest(BaseModel):
    url: str


class ManualUrlCheckResponse(BaseModel):
    retailer_name: str
    store_id: str
    product_url: str
    verification_status: str
    listed_price: Optional[float] = None
    mrp: Optional[float] = None
    shipping_fee: Optional[float] = None
    is_shipping_disclosed: bool = True
    total_cost: Optional[float] = None
    in_stock: bool = True
    stock_status: str = "In Stock"
    product_name: Optional[str] = None
    retrieved_at: str
    validation_notes: Optional[str] = None


# =====================================================================
# Phase 7: Authentication, User Profiles, Routines & Watchlist Schemas
# =====================================================================

class UserSchema(BaseModel):
    id: int
    display_name: str
    name: Optional[str] = None
    email: str
    created_at: str
    status: str = "active"


class RegisterRequest(BaseModel):
    email: str
    password: str
    display_name: Optional[str] = None
    name: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None
    user: Optional[UserSchema] = None


class UserProfileSchema(BaseModel):
    user_id: int
    display_name: str
    preferred_name: Optional[str] = None
    skin_type: str = "unsure"
    skin_concerns: list[str] = Field(default_factory=list)
    preferred_categories: list[str] = Field(default_factory=list)
    preferred_brands: list[str] = Field(default_factory=list)
    min_budget: Optional[float] = None
    max_budget: Optional[float] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    makeup_preferences: Any = Field(default_factory=list)
    ingredient_preferences: list[str] = Field(default_factory=list)
    ingredient_avoidance: list[str] = Field(default_factory=list)
    ingredient_avoidances: list[str] = Field(default_factory=list)
    updated_at: str
    medical_disclaimer: str


class UpdateProfileRequest(BaseModel):
    display_name: Optional[str] = None
    preferred_name: Optional[str] = None
    skin_type: Optional[str] = None
    skin_concerns: Optional[list[str]] = None
    preferred_categories: Optional[list[str]] = None
    preferred_brands: Optional[list[str]] = None
    min_budget: Optional[float] = None
    max_budget: Optional[float] = None
    budget_min: Optional[float] = None
    budget_max: Optional[float] = None
    makeup_preferences: Optional[Any] = None
    ingredient_preferences: Optional[list[str]] = None
    ingredient_avoidance: Optional[list[str]] = None
    ingredient_avoidances: Optional[list[str]] = None


class RoutineItemSchema(BaseModel):
    id: int
    routine_id: int
    step_number: int
    step_name: str
    product_id: Optional[int] = None
    custom_product_name: Optional[str] = None
    usage_instructions: Optional[str] = None
    precautions: Optional[str] = None
    category: Optional[str] = None
    product_title: Optional[str] = None
    product_brand: Optional[str] = None
    product_image_url: Optional[str] = None
    product_price: Optional[float] = None
    product_slug: Optional[str] = None


class RoutineSchema(BaseModel):
    id: int
    user_id: int
    routine_type: str
    title: str
    name: Optional[str] = None
    description: Optional[str] = None
    created_at: str
    updated_at: str
    items: list[RoutineItemSchema] = Field(default_factory=list)
    conflict_warnings: list[str] = Field(default_factory=list)
    conflicts: list[Any] = Field(default_factory=list)
    medical_disclaimer: str
    disclaimer: Optional[str] = None


class CreateRoutineRequest(BaseModel):
    routine_type: str
    title: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None


class UpdateRoutineRequest(BaseModel):
    title: Optional[str] = None
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class AddRoutineItemRequest(BaseModel):
    step_name: str
    category: Optional[str] = None
    product_id: Optional[int] = None
    custom_product_name: Optional[str] = None
    usage_instructions: Optional[str] = None
    precautions: Optional[str] = None
    step_number: Optional[int] = None


class ReorderRoutineRequest(BaseModel):
    item_ids_in_order: list[int] = Field(default_factory=list)
    item_order: list[int] = Field(default_factory=list)


class WatchlistItemSchema(BaseModel):
    id: int
    user_id: int
    product_id: int
    title: str
    brand: str
    category: str
    image_url: Optional[str] = None
    slug: str
    current_lowest_price: Optional[float] = None
    original_price: Optional[float] = None
    created_at: str
    note: Optional[str] = None


class AddWatchlistRequest(BaseModel):
    product_id: int
    note: Optional[str] = None
    notes: Optional[str] = None
    target_price: Optional[float] = None


class SyncWatchlistRequest(BaseModel):
    product_ids: list[Any] = Field(default_factory=list)
    items: list[Any] = Field(default_factory=list)


class RecommendedProductSchema(BaseModel):
    product_id: int
    title: str
    name: Optional[str] = None
    brand: str
    category: str
    price: Optional[float] = None
    image_url: Optional[str] = None
    image: Optional[str] = None
    slug: str
    match_score: int
    recommendation_score: Optional[int] = None
    match_reasons: list[str] = Field(default_factory=list)
    matched_reasons: list[str] = Field(default_factory=list)
    key_ingredients: Optional[str] = None
    skin_type_suitability: Optional[str] = None


class PersonalizedRecommendationsResponse(BaseModel):
    user_id: int
    skin_type: str
    skin_concerns: list[str] = Field(default_factory=list)
    max_budget: Optional[float] = None
    products: list[RecommendedProductSchema] = Field(default_factory=list)
    recommendations: list[RecommendedProductSchema] = Field(default_factory=list)
    has_profile: bool
    medical_disclaimer: str
    disclaimer: Optional[str] = None


# =====================================================================
# Phase 8D: Manual Verification & Price Correction Schemas
# =====================================================================

class ManualVerificationRequest(BaseModel):
    product_id: int
    retailer: str
    product_url: str
    user_submitted_price: Optional[float] = None
    size_volume: Optional[str] = None
    shade: Optional[str] = None
    formulation: Optional[str] = None
    notes: Optional[str] = None
    evidence_url: Optional[str] = None


class ManualVerificationResponse(BaseModel):
    id: int
    user_id: int
    product_id: int
    retailer: str
    product_url: str
    user_submitted_price: Optional[float] = None
    size_volume: Optional[str] = None
    shade: Optional[str] = None
    formulation: Optional[str] = None
    notes: Optional[str] = None
    status: str
    verification_status: Optional[str] = None
    verified_price: Optional[float] = None
    verified_mrp: Optional[float] = None
    verified_discount_pct: Optional[float] = None
    verified_shipping_fee: Optional[float] = None
    verified_size_volume: Optional[str] = None
    verified_shade: Optional[str] = None
    verified_formulation: Optional[str] = None
    verified_product_name: Optional[str] = None
    verified_brand: Optional[str] = None
    verification_notes: Optional[str] = None
    source_url: Optional[str] = None
    submitted_at: str
    verified_at: Optional[str] = None
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[int] = None
    rejection_reason: Optional[str] = None


class ManualVerificationListResponse(BaseModel):
    status: str = "ok"
    items: list[ManualVerificationResponse]
    count: int


class PriceCorrectionSubmission(BaseModel):
    product_id: int
    retailer: str
    product_url: str
    submitted_price: float
    submitted_mrp: Optional[float] = None
    size_volume: Optional[str] = None
    shade: Optional[str] = None
    formulation: Optional[str] = None
    notes: Optional[str] = None
    evidence_url: Optional[str] = None


class PriceCorrectionResponse(BaseModel):
    id: int
    user_id: int
    product_id: int
    retailer: str
    product_url: str
    submitted_price: float
    submitted_mrp: Optional[float] = None
    size_volume: Optional[str] = None
    shade: Optional[str] = None
    formulation: Optional[str] = None
    notes: Optional[str] = None
    evidence_url: Optional[str] = None
    status: str
    reviewed_at: Optional[str] = None
    reviewed_by: Optional[int] = None
    rejection_reason: Optional[str] = None
    created_at: str


class PriceCorrectionListResponse(BaseModel):
    status: str = "ok"
    items: list[PriceCorrectionResponse]
    count: int


class EvidenceReference(BaseModel):
    id: int
    reference_type: str
    reference_id: int
    evidence_url: str
    evidence_type: Optional[str] = None
    description: Optional[str] = None
    uploaded_at: str
    uploaded_by: int


class EvidenceReferenceListResponse(BaseModel):
    status: str = "ok"
    items: list[EvidenceReference]
    count: int


# =============================================================================
# Phase 11B: Hybrid Price Collection and Admin Verification Schemas
# =============================================================================

class PriceCollectionResponseSchema(BaseModel):
    status: str
    product_id: int
    product_title: Optional[str] = None
    collected_count: int
    results: list[dict[str, Any]]
    timestamp: str


class RetailerPolicyStatusSchema(BaseModel):
    retailer_key: str
    retailer_name: str
    domain: str
    store_id: int
    policy_status: str
    circuit_breaker_active: bool
    explanation: str
    permitted_methods: list[str]


class RetailerPolicyListResponse(BaseModel):
    status: str = "ok"
    retailers: list[RetailerPolicyStatusSchema]
    count: int


class ProductRetailerSourceItemSchema(BaseModel):
    offer_id: int
    retailer_name: str
    store_id: int
    product_url: str
    current_price: float
    original_price: Optional[float] = None
    discount_pct: float = 0.0
    currency: str = "INR"
    variant_name: str = "Standard"
    availability: str = "In Stock"
    verification_status: str
    last_verified_at: Optional[str] = None
    last_checked_at: Optional[str] = None
    policy_status: str
    requires_manual_verification: bool = False


class ProductRetailerSourcesResponse(BaseModel):
    status: str = "ok"
    product_id: int
    sources: list[ProductRetailerSourceItemSchema]
    count: int


class AdminVerificationApprovalRequest(BaseModel):
    verified_price: Optional[float] = None
    verified_mrp: Optional[float] = None
    notes: Optional[str] = None


class AdminVerificationRejectionRequest(BaseModel):
    rejection_reason: str


class AdminVerificationQueueResponse(BaseModel):
    status: str = "ok"
    pending_manual_verifications: list[dict[str, Any]]
    pending_price_corrections: list[dict[str, Any]]
    total_pending: int


class EvidenceUploadResponse(BaseModel):
    status: str = "ok"
    evidence_url: str
    filename: str
    file_size: int


# Verification Status Constants for frontend

# =============================================================================
# Phase 8E: Beauty Intelligence Schemas
# =============================================================================

class IngredientInfoSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    function: str
    benefits: list[str] = []
    concerns: list[str] = []
    compatible_with: list[str] = []
    avoid_with: list[str] = []
    concentration_range: Optional[str] = None
    safety_rating: Optional[str] = None
    source: str = "gemini_model"


class IngredientAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    product_name: str
    ingredients: list[IngredientInfoSchema]
    key_actives: list[str] = []
    potential_conflicts: list[str] = []
    routine_compatibility: dict[str, list[str]] = {}
    extraction_source: str = "gemini_model"
    confidence_score: float = 0.0
    error_message: Optional[str] = None


class SkinConcernMatchSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    concern: str
    product_id: int
    product_name: str
    brand: str
    category: str
    matched_ingredients: list[str]
    suitability_score: float
    explanation: str
    price: Optional[float] = None
    verification_status: str = "DEMO"


class SkinConcernAnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    concern: str
    matches: list[SkinConcernMatchSchema]
    total_products_analyzed: int
    has_live_data: bool = False
    source: str = "deterministic_ingredient_rules"


class AlternativeProductSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    original_product_id: int
    original_product_name: str
    original_brand: str
    original_price: Optional[float]
    alternative_product_id: int
    alternative_product_name: str
    alternative_brand: str
    alternative_price: Optional[float]
    price_difference: Optional[float]
    price_difference_pct: Optional[float]
    similarity_score: float
    matched_attributes: list[str]
    differences: list[str]
    suitability_score: float
    explanation: str
    price_verified: bool = False
    # Phase 14 Stage F: an approximate alternative is never presented as an
    # identical dupe. The classification is computed deterministically from
    # formulation, pack size and shared active ingredients.
    match_type: str = "close_alternative"
    size_comparison: str = ""
    caveats: list[str] = []


class AlternativeFinderResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    original_product_id: int
    alternatives: list[AlternativeProductSchema]
    search_criteria: dict
    extraction_source: str = "gemini_model"


class RoutineStepRecommendationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    step_number: int
    step_name: str
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    key_ingredients: list[str] = []
    frequency: str = "Daily"
    usage_instructions: str = ""
    precautions: str = ""
    patch_test_recommended: bool = False
    conflicts_with: list[int] = []


class RoutineRecommendationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    routine_type: str
    skin_type: str
    skin_concerns: list[str]
    budget_range: Optional[list[float]] = None
    steps: list[RoutineStepRecommendationSchema]
    total_estimated_cost: Optional[float] = None
    warnings: list[str] = []
    patch_test_items: list[int] = []
    sunscreen_required: bool = False
    generation_source: str = "gemini_model"


class BeautyIntelligenceUsageResponse(BaseModel):
    rate_limit: dict
    token_usage: dict
    daily_limit: int


class BeautyIntelligenceAdminStatsResponse(BaseModel):
    period_days: int
    total_tokens: int
    total_requests: int
    by_model: dict



LIVE_VERIFIED = "LIVE_VERIFIED"
MANUAL_VERIFIED = "MANUAL_VERIFIED"
CACHED = "CACHED"
HISTORICAL = "HISTORICAL"
POSSIBLE_MATCH = "POSSIBLE_MATCH"
RESTRICTED = "RESTRICTED"
UNAVAILABLE = "UNAVAILABLE"
DEMO = "DEMO"


# =============================================================================
# Phase 9: Advanced Price Intelligence & Deal Analytics Schemas
# =============================================================================

class PricePointDtoSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    offer_id: int
    price: float
    currency: str = "INR"
    recorded_at: str
    data_source: str = "demo_seed"
    data_status: str = "demo"


class ProductPriceAnalyticsResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    product_slug: str
    product_title: str
    window_days: int
    points: list[PricePointDtoSchema] = []
    lowest_recorded_price: Optional[float] = None
    highest_recorded_price: Optional[float] = None
    average_recorded_price: Optional[float] = None
    current_lowest_price: Optional[float] = None
    price_movement_pct: Optional[float] = None
    price_trend: str = "insufficient_data"
    observation_count: int = 0
    is_sufficient_history: bool = False
    currency: str = "INR"
    history_data_status: str = "DEMO"
    is_simulated: bool = True
    disclaimer: str = ""


class CouponValidationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    code: str
    is_valid: bool
    discount_amount: float = 0.0
    discount_pct: Optional[float] = None
    min_spend: float = 0.0
    description: str = ""
    rejection_reason: Optional[str] = None
    expires_at: Optional[str] = None
    is_expired: bool = False
    source: str = "simulated"
    is_simulated: bool = True
    disclaimer: str = ""


class TotalPurchaseCostBreakdownSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    retailer_name: str
    base_price: float
    shipping_fee: Optional[float] = None
    is_shipping_known: bool = True
    shipping_label: str = "Free Shipping"
    coupon_applied: Optional[CouponValidationSchema] = None
    final_payable_price: float
    is_final_exact: bool = True
    payable_state_note: str = ""
    reference_mrp: Optional[float] = None
    mrp_discount: float = 0.0
    confirmed_savings: float = 0.0
    simulated_coupon_savings: float = 0.0
    coupon_savings: float = 0.0
    total_potential_savings: float = 0.0
    genuine_verified_market_savings: float = 0.0
    currency: str = "INR"
    data_status: str = "demo"
    calculated_at: str


class DealFactorExplanationSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    factor_name: str
    points_awarded: float
    max_points: float
    explanation: str


class DealIntelligenceResponseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: int
    product_title: str
    retailer_name: str
    current_price: float
    deal_score: int
    deal_grade: str
    deal_classification: str
    is_simulated_deal: bool = True
    source_status: str = "DEMO"
    verified_deal_eligible: bool = False
    confidence_score: float = 0.5
    factors: list[DealFactorExplanationSchema] = []
    landed_cost_breakdown: TotalPurchaseCostBreakdownSchema
    summary_verdict: str


class TotalCostRequestSchema(BaseModel):
    product_id: Optional[int] = None
    retailer_name: Optional[str] = "Retailer"
    coupon_code: Optional[str] = None
    custom_price: Optional[float] = None
    custom_shipping: Optional[float] = None


class TrackProductRequestSchema(BaseModel):
    product_id: int
    target_price: float
    alert_trigger_type: str = "target_or_drop"
    note: Optional[str] = None


class PriceTrackingItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    product_id: int
    product_title: str
    target_price: float
    current_price: float
    status: str
    alert_trigger_type: str
    note: Optional[str] = None
    created_at: str
    last_observed_price: Optional[float] = None
    last_alert_at: Optional[str] = None


class PriceAlertItemSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    user_id: int
    product_id: int
    product_title: str
    alert_type: str
    observed_price: float
    previous_price: Optional[float] = None
    target_price: float
    message: str
    created_at: str
    is_read: bool
    is_demo: bool = True


# =============================================================================
# Phase 10: Advanced Beauty Intelligence Schemas
# =============================================================================

class IngredientCompatibilityRequest(BaseModel):
    ingredients: List[str]


class IngredientCompatibilityResponse(BaseModel):
    analyzed_ingredients: List[Dict[str, Any]]
    overall_status: str
    safety_score: int
    summary: str
    warnings: List[Dict[str, Any]]
    synergies: List[Dict[str, Any]]
    total_conflicts: int
    total_synergies: int
    medical_disclaimer: str


class RoutineStepInputSchema(BaseModel):
    step_name: str
    product_name: Optional[str] = None
    custom_product_name: Optional[str] = None
    key_ingredients: Optional[List[str]] = Field(default_factory=list)


class RoutineCheckerRequest(BaseModel):
    am_steps: List[RoutineStepInputSchema] = Field(default_factory=list)
    pm_steps: List[RoutineStepInputSchema] = Field(default_factory=list)
    user_skin_type: Optional[str] = "Combination"


class RoutineCheckerResponse(BaseModel):
    overall_score: int
    irritation_risk: str
    safety_rating: str
    total_conflicts: int
    conflicts: List[Dict[str, Any]]
    active_overloads: List[Dict[str, Any]]
    optimization_steps: List[str]
    am_active_count: int
    pm_active_count: int
    sunscreen_compliant: bool
    medical_disclaimer: str


class ClimateSkincareRequest(BaseModel):
    climate_code: str
    skin_type: Optional[str] = "Combination"
    concerns: Optional[List[str]] = Field(default_factory=list)


class ClimateSkincareResponse(BaseModel):
    climate_profile: Dict[str, Any]
    user_context: Dict[str, Any]
    matched_catalog_products: List[Dict[str, Any]]
    medical_disclaimer: str


class FoundationMatchRequest(BaseModel):
    skin_depth: str
    undertone: str
    coverage: Optional[str] = "Medium"
    finish: Optional[str] = "Matte"
    reference_brand: Optional[str] = None
    reference_shade: Optional[str] = None


class FoundationMatchResponse(BaseModel):
    user_profile: Dict[str, Any]
    shade_benchmark: Dict[str, Any]
    matches: List[Dict[str, Any]]
    undertone_guidance: str
    disclaimer: str


class AdvancedDiscoveryProductSchema(BaseModel):
    id: int
    title: str
    brand: str
    category: str
    brand_tier: str
    price: float
    reference_mrp: float
    image_url: str
    key_ingredients: List[str] = Field(default_factory=list)
    skin_type: str
    finish: Optional[str] = None
    match_score: int
    matching_tags: List[str] = Field(default_factory=list)
    is_dupe_candidate: bool


class AdvancedDiscoveryResponse(BaseModel):
    total_results: int
    products: List[AdvancedDiscoveryProductSchema]
    active_filters: Dict[str, Any]





