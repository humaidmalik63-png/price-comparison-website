"""Lightweight FastAPI Backend Bridge for PriceWise AI Beauty (Phase 6A).



Exposes REST endpoints for the React frontend while reusing existing

database models and service layers. Keeps Streamlit fully operational.

"""



from dotenv import load_dotenv

load_dotenv()  # Load .env from project root before any service imports



import logging

import os

from typing import Any, Optional

from urllib.parse import urlparse

import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Query, Depends, Response, status, UploadFile, File, Request
from fastapi.responses import JSONResponse

from fastapi.responses import FileResponse

from fastapi.middleware.cors import CORSMiddleware

from src.config import (
    APP_NAME,
    APP_VERSION,
    DEMO_USER_EMAIL,
    ENVIRONMENT,
    IS_PRODUCTION,
    MAX_UPLOAD_SIZE_BYTES,
    RATE_LIMIT_PER_MINUTE,
    SESSION_COOKIE_SECURE,
    CORS_ORIGINS as CONFIG_CORS_ORIGINS,
    validate_session_secret_configuration,
)

from src.database.connection import get_connection, get_database_engine_type, migrate_db

from src.database.models import Offer, Product, User

from src.services.product_service import (

    get_products,

    get_product_by_slug,

    get_product_by_id,

    get_all_categories,

)

from src.api.schemas import (

    HealthResponse,

    OfferSchema,

    ProductListItemSchema,

    ProductDetailSchema,

    LiveComparisonResponse,

    LiveRetailerOfferSchema,

    LiveComparisonSummarySchema,

    ManualUrlCheckRequest,

    ManualUrlCheckResponse,

    UserSchema,

    RegisterRequest,

    LoginRequest,

    AuthResponse,

    UserProfileSchema,

    UpdateProfileRequest,

    RoutineSchema,

    RoutineItemSchema,

    CreateRoutineRequest,

    UpdateRoutineRequest,

    AddRoutineItemRequest,

    ReorderRoutineRequest,

    WatchlistItemSchema,

    AddWatchlistRequest,

    SyncWatchlistRequest,

    RecommendedProductSchema,

    PersonalizedRecommendationsResponse,

    ManualVerificationRequest,

    ManualVerificationResponse,

    ManualVerificationListResponse,

    PriceCorrectionSubmission,

    PriceCorrectionResponse,

    PriceCorrectionListResponse,

    EvidenceReference,

    EvidenceReferenceListResponse,

    PriceCollectionResponseSchema,

    RetailerPolicyStatusSchema,

    RetailerPolicyListResponse,

    ProductRetailerSourceItemSchema,

    ProductRetailerSourcesResponse,

    AdminVerificationApprovalRequest,

    AdminVerificationRejectionRequest,

    AdminVerificationQueueResponse,

    EvidenceUploadResponse,

    IngredientInfoSchema,

    IngredientAnalysisResponse,

    SkinConcernMatchSchema,

    SkinConcernAnalysisResponse,

    AlternativeProductSchema,

    AlternativeFinderResponse,

    RoutineStepRecommendationSchema,

    RoutineRecommendationResponse,

    BeautyIntelligenceUsageResponse,

    BeautyIntelligenceAdminStatsResponse,

    ProductPriceAnalyticsResponseSchema,

    DealIntelligenceResponseSchema,

    TotalCostRequestSchema,

    TotalPurchaseCostBreakdownSchema,

    TrackProductRequestSchema,

    PriceTrackingItemSchema,

    PriceAlertItemSchema,

    IngredientCompatibilityRequest,

    IngredientCompatibilityResponse,

    RoutineCheckerRequest,

    RoutineCheckerResponse,

    ClimateSkincareRequest,

    ClimateSkincareResponse,

    FoundationMatchRequest,

    FoundationMatchResponse,

    AdvancedDiscoveryResponse,

)



from src.services.price_intelligence_service import (

    get_product_price_analytics,

    calculate_total_purchase_cost,

    calculate_deal_score,

    get_user_tracking_records,

    get_user_price_alerts_list,

    validate_retailer_coupon,

)

from src.services.price_tracking_service import (

    add_tracked_product,

    remove_tracking,

    mark_alert_read,

    evaluate_tracking_rules,

)



from src.services.beauty_intelligence_service import get_beauty_intelligence_service, BeautyIntelligenceService

from src.services.price_verification_service import (

    record_evidence_reference,

    get_evidence_for_reference,

    get_pending_verification_queue,

    approve_manual_verification,

    reject_manual_verification,

    approve_price_correction,

    reject_price_correction,

    VerificationStatus,

)

from src.services.price_collection_engine import (

    get_retailer_status_list,

    get_product_retailer_sources,

    collect_product_prices,

    RetailerAccessStatus,

)

from src.services.beauty_intelligence_advanced import (

    check_ingredient_compatibility,

    check_routine_safety,

    get_climate_recommendations,

    match_foundation_shade,

    search_advanced_discovery,

    MASTER_INGREDIENTS,

    CLIMATE_PROFILES,

    SHADE_BENCHMARKS,

)

from src.services.live_comparison_engine import get_live_comparison_engine

from src.api.auth_deps import get_current_user, get_optional_current_user
from src.api import rate_limit

from src.services.auth_service import register_user, authenticate_user, generate_session_token

from src.services.profile_service import get_user_profile, save_user_profile, reset_user_profile

from src.services.routine_service import (

    get_user_routines,

    get_user_routine_by_id,

    create_user_routine,

    update_user_routine,

    delete_user_routine,

    add_routine_item,

    reorder_routine_items,

    delete_routine_item,

    ROUTINE_MEDICAL_DISCLAIMER,

)

from src.services.wishlist_service import (

    get_user_wishlist,

    add_to_wishlist,

    remove_from_wishlist,

    remove_product_from_wishlist,

)

from src.services.personalized_recommendation_service import get_personalized_recommendations



# Setup logging

logging.basicConfig(level=logging.INFO)

logger = logging.getLogger("pricewise.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Application start-up lifecycle.

    Phase 14 Stage 2.5 (FIX 1): the service refuses to start when the
    session signing secret is missing in a secured environment (production /
    staging) instead of signing tokens with an unconfigured secret.

    Phase 14 Stage 2.5 (FIX 2): schema migrations are applied once here, so
    ordinary authenticated requests never execute DDL. A migration failure is
    logged rather than fatal, because database availability is reported by the
    readiness probe (/api/health/ready).
    """
    validate_session_secret_configuration()

    try:
        migrate_db()
    except Exception as exc:  # pragma: no cover - depends on live database
        logger.error("Start-up schema migration failed: %s", exc)

    yield


app = FastAPI(

    title=f"{APP_NAME} API",

    description="Bridge API connecting React frontend to Python service layer.",

    version=APP_VERSION,

    lifespan=lifespan,

)



# CORS Configuration for local development and production (Phase 12 Hardened)
default_dev_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:5175",
    "http://127.0.0.1:5175",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:8501",
    "http://127.0.0.1:8501",
]

cors_env = os.getenv("CORS_ORIGINS", "")
if cors_env:
    env_origins = [o.strip() for o in cors_env.split(",") if o.strip()]
else:
    env_origins = CONFIG_CORS_ORIGINS

if IS_PRODUCTION:
    origins = env_origins if env_origins else ["https://pricewise-ai.vercel.app"]
    origin_regex = None
else:
    origins = list(set(default_dev_origins + env_origins))
    origin_regex = r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"],
)


@app.middleware("http")
async def add_security_headers_and_timing(request: Request, call_next):
    start_time = time.perf_counter()
    response = await call_next(request)
    duration_ms = (time.perf_counter() - start_time) * 1000
    response.headers["X-Process-Time"] = f"{duration_ms:.2f}ms"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if IS_PRODUCTION or request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


@app.middleware("http")
async def enforce_rate_limit(request: Request, call_next):
    """Enforce the configured per-client request budget (Phase 14 Stage B).

    ``RATE_LIMIT_PER_MINUTE`` was previously declared in configuration and in
    ``render.yaml`` but never enforced. Health probes and API documentation
    are exempt so an orchestrator can always poll the service.
    """
    if rate_limit.is_exempt(request.url.path):
        return await call_next(request)

    key = rate_limit.client_key_for(request)
    allowed, remaining, retry_after = rate_limit.rate_limiter.check(key)

    if not allowed:
        logger.warning(
            "Rate limit exceeded for client bucket (path=%s)", request.url.path
        )
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={
                "detail": (
                    "Too many requests. Please retry in "
                    f"{retry_after} second(s)."
                ),
                "retry_after_seconds": retry_after,
            },
            headers={
                "Retry-After": str(retry_after),
                "X-RateLimit-Limit": str(rate_limit.rate_limiter.requests_per_minute),
                "X-RateLimit-Remaining": "0",
            },
        )

    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(rate_limit.rate_limiter.requests_per_minute)
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response





def _serialize_offer(offer: Offer) -> OfferSchema:

    """Map Offer dataclass to schema."""

    return OfferSchema(

        id=offer.id,

        product_id=offer.product_id,

        store_id=offer.store_id,

        store_name=offer.store_name,

        store_rating=offer.store_rating,

        current_price=offer.current_price,

        original_price=offer.original_price,

        shipping_cost=offer.shipping_cost,

        is_shipping_disclosed=getattr(offer, "is_shipping_disclosed", True),

        currency=offer.currency or "INR",

        availability=offer.availability,

        variant_name=offer.variant_name,

        condition=offer.condition,

        offer_url=offer.offer_url,

        coupon_code=getattr(offer, "coupon_code", None),

        coupon_discount=getattr(offer, "coupon_discount", 0.0),

        total_cost=offer.total_cost if getattr(offer, "is_shipping_disclosed", True) else None,

        source_type=getattr(offer, "source_type", "demo"),

        last_checked=offer.last_checked,

    )





def _serialize_product_item(product: Product) -> ProductListItemSchema:

    """Map Product dataclass to list item schema."""

    return ProductListItemSchema(

        id=product.id,

        sku=product.sku,

        slug=product.slug,

        title=product.title,

        brand=product.brand,

        category=product.category,

        description=product.description,

        image_url=product.image_url,

        lowest_price=product.lowest_price,

        highest_price=product.highest_price,

        lowest_total_cost=product.lowest_total_cost,

        currency_symbol=product.currency_symbol,

        available_offer_count=product.available_offer_count,

        specs=product.specs or {},

        is_active=getattr(product, "is_active", True),

    )





def _serialize_product_detail(product: Product) -> ProductDetailSchema:

    """Map Product dataclass to full detail schema."""

    item = _serialize_product_item(product)

    offers = [_serialize_offer(o) for o in product.offers]

    return ProductDetailSchema(

        **item.model_dump(),

        offers=offers,

        created_at=product.created_at,

    )





@app.get("/api/health/live")
def get_health_live() -> dict:
    """Lightweight liveness probe."""
    return {"status": "alive", "timestamp": datetime.now(timezone.utc).isoformat()}


@app.get("/api/health/ready")
def get_health_ready() -> dict:
    """Readiness probe verifying database connectivity and latency."""
    engine = get_database_engine_type()
    start = time.perf_counter()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as cnt FROM products")
            row = cur.fetchone()
            count = int(row["cnt"]) if hasattr(row, "__getitem__") and "cnt" in row.keys() else int(row[0])
        latency_ms = (time.perf_counter() - start) * 1000
        return {
            "status": "ready",
            "database_engine": engine,
            "database_healthy": True,
            "product_count": count,
            "latency_ms": round(latency_ms, 2),
            "environment": ENVIRONMENT,
        }
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Database connectivity failure: {str(e)}")


@app.get("/api/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Health check endpoint reporting database connectivity and record volume."""
    record_count = 0
    engine = get_database_engine_type()
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) as cnt FROM products")
            row = cur.fetchone()
            record_count = int(row["cnt"]) if hasattr(row, "__getitem__") and "cnt" in row.keys() else int(row[0])
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=500, detail="Database connectivity failure")

    return HealthResponse(
        status="ok",
        app_name=APP_NAME,
        version=APP_VERSION,
        database=engine,
        record_count=record_count,
    )





@app.get("/api/products", response_model=list[ProductListItemSchema])

def list_products(

    category: Optional[str] = Query(None, description="Category filter"),

    brand: Optional[str] = Query(None, description="Brand filter"),

    search: Optional[str] = Query(None, description="Search keyword"),

    skin_type: Optional[str] = Query(None, description="Skin suitability filter"),

    in_stock_only: bool = Query(False, description="Filter for in-stock items only"),

    min_price: Optional[float] = Query(None, description="Minimum price in INR"),

    max_price: Optional[float] = Query(None, description="Maximum price in INR"),

    sort_by: str = Query("featured", description="Sort criteria"),

) -> list[ProductListItemSchema]:

    """Retrieve catalog products with multi-criteria filtering and sorting."""

    resolved_category = category

    if category and category != "All":

        cat_lower = category.strip().lower()

        for c in get_all_categories():

            if c.lower() == cat_lower or c.lower().startswith(cat_lower) or cat_lower.startswith(c.lower()):

                resolved_category = c

                break



    products = get_products(

        category=resolved_category,

        brand=brand,

        search_query=search,

        skin_type=skin_type,

        in_stock_only=in_stock_only,

        min_price=min_price,

        max_price=max_price,

        sort_by=sort_by,

    )

    return [_serialize_product_item(p) for p in products]





@app.get("/api/products/{slug_or_id}", response_model=ProductDetailSchema)

def get_product(slug_or_id: str) -> ProductDetailSchema:

    """Retrieve single product detail by slug, SKU, or numeric ID."""

    prod = None

    if slug_or_id.isdigit():

        prod = get_product_by_id(int(slug_or_id))



    if not prod:

        prod = get_product_by_slug(slug_or_id)



    if not prod or not getattr(prod, "is_active", True):

        raise HTTPException(

            status_code=404,

            detail=f"Product '{slug_or_id}' not found in catalog.",

        )



    return _serialize_product_detail(prod)





@app.get("/api/compare/auto", response_model=LiveComparisonResponse)

def get_auto_live_comparison(

    product_id: Optional[int] = Query(None, description="Catalog product numeric ID"),

    slug: Optional[str] = Query(None, description="Product canonical slug or SKU"),

    force_refresh: bool = Query(False, description="Bypass cache and force fresh retailer check"),

) -> LiveComparisonResponse:

    """

    Automatic live retailer price comparison engine endpoint.

    Initiated automatically on ProductDetailPage mount (no manual button required).

    """

    if not product_id and not slug:

        raise HTTPException(status_code=400, detail="Either product_id or slug must be provided.")



    engine = get_live_comparison_engine()

    res = engine.execute_live_comparison(

        product_id=product_id,

        slug_or_id=slug,

        force_refresh=force_refresh,

    )



    offers_schema = [

        LiveRetailerOfferSchema(

            retailer_name=o.retailer_name,

            store_id=o.store_id,

            status=o.status,

            listed_price=o.listed_price,

            mrp=o.mrp,

            discount_pct=o.discount_pct,

            shipping_fee=o.shipping_fee,

            is_shipping_disclosed=o.is_shipping_disclosed,

            coupon_code=o.coupon_code,

            coupon_discount=o.coupon_discount,

            total_cost=o.total_cost,

            stock_status=o.stock_status,

            in_stock=o.in_stock,

            purchase_url=o.purchase_url,

            variant_detected=o.variant_detected,

            match_classification=o.match_classification,

            is_lowest_listed=o.is_lowest_listed,

            is_lowest_total=o.is_lowest_total,

            source_type=o.source_type,

            retrieved_at=o.retrieved_at,

            validation_notes=o.validation_notes,

        )

        for o in res.offers

    ]



    summary_schema = LiveComparisonSummarySchema(

        lowest_listed_price=res.summary.lowest_listed_price,

        lowest_listed_retailer=res.summary.lowest_listed_retailer,

        lowest_total_cost=res.summary.lowest_total_cost,

        lowest_total_retailer=res.summary.lowest_total_retailer,

        retailers_checked=res.summary.retailers_checked,

        retailers_retrieved=res.summary.retailers_retrieved,

        retailers_unavailable=res.summary.retailers_unavailable,

        retailers_unsupported=res.summary.retailers_unsupported,

        retailers_restricted=res.summary.retailers_restricted,

        cheapest_savings_amount=res.summary.cheapest_savings_amount,

        cheapest_savings_percent=res.summary.cheapest_savings_percent,

    )



    return LiveComparisonResponse(

        product_id=res.product_id,

        product_title=res.product_title,

        brand=res.brand,

        target_variant=res.target_variant,

        is_cached=res.is_cached,

        freshness_seconds=res.freshness_seconds,

        retrieval_timestamp=res.retrieval_timestamp,

        offers=offers_schema,

        summary=summary_schema,

    )





@app.post("/api/compare/url", response_model=ManualUrlCheckResponse)

def check_manual_url(req: ManualUrlCheckRequest) -> ManualUrlCheckResponse:

    """

    Manual single product URL price check.

    Enforces strict URL validation against the retailer domain allowlist.

    """

    engine = get_live_comparison_engine()

    res = engine.check_manual_url_price(req.url)



    return ManualUrlCheckResponse(

        retailer_name=res.retailer_name,

        store_id=res.store_id,

        product_url=res.product_url,

        verification_status=res.verification_status,

        listed_price=res.listed_price,

        mrp=res.mrp,

        shipping_fee=res.shipping_fee,

        is_shipping_disclosed=res.is_shipping_disclosed,

        total_cost=res.total_cost,

        in_stock=res.in_stock,

        stock_status=res.stock_status,

        product_name=res.product_name,

        retrieved_at=res.retrieved_at,

        validation_notes=res.validation_notes,

    )





# =====================================================================

# Phase 7: Authentication Endpoints

# =====================================================================



@app.post("/api/auth/register", response_model=AuthResponse)

def api_register(req: RegisterRequest, response: Response) -> AuthResponse:

    """Register a new user account and set secure session cookie."""

    display_name = req.display_name or req.name or "Beauty Enthusiast"

    success, msg, user = register_user(

        email=req.email,

        password=req.password,

        display_name=display_name,

    )

    if not success or not user:

        if "already registered" in msg.lower() or "already exists" in msg.lower():

            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg)

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)



    token = generate_session_token(user.id, user.email, token_version=user.token_version)

    response.set_cookie(

        key="session_token",

        value=token,

        httponly=True,

        samesite="lax",

        # Phase 14 Stage B: the cookie is marked Secure in every environment
        # that is served over TLS (production, staging). Plain-HTTP local
        # development keeps it usable.
        secure=SESSION_COOKIE_SECURE,

        max_age=7 * 24 * 3600,

        path="/",

    )



    return AuthResponse(

        success=True,

        message=msg,

        token=token,

        user=UserSchema(

            id=user.id,

            display_name=user.display_name,

            name=user.display_name,

            email=user.email,

            created_at=user.created_at,

            status=user.status,

        ),

    )





@app.post("/api/auth/login", response_model=AuthResponse)

def api_login(req: LoginRequest, response: Response) -> AuthResponse:

    """Authenticate existing user credentials and return signed session token."""

    success, msg, user = authenticate_user(

        email=req.email,

        password=req.password,

    )

    if not success or not user:

        raise HTTPException(

            status_code=status.HTTP_401_UNAUTHORIZED,

            detail="Invalid email or password.",

        )



    token = generate_session_token(user.id, user.email, token_version=user.token_version)

    response.set_cookie(

        key="session_token",

        value=token,

        httponly=True,

        samesite="lax",

        # Phase 14 Stage B: the cookie is marked Secure in every environment
        # that is served over TLS (production, staging). Plain-HTTP local
        # development keeps it usable.
        secure=SESSION_COOKIE_SECURE,

        max_age=7 * 24 * 3600,

        path="/",

    )



    return AuthResponse(

        success=True,

        message="Login successful.",

        token=token,

        user=UserSchema(

            id=user.id,

            display_name=user.display_name,

            name=user.display_name,

            email=user.email,

            created_at=user.created_at,

            status=user.status,

        ),

    )





@app.post("/api/auth/logout")

def api_logout(response: Response) -> dict[str, str]:

    """Clear session cookie and log user out."""

    response.delete_cookie(key="session_token", path="/")

    return {"status": "ok", "message": "Logged out successfully."}





@app.get("/api/auth/me")

def api_me(current_user: User = Depends(get_current_user)) -> dict[str, Any]:

    """Return currently authenticated user profile."""

    user_schema = UserSchema(

        id=current_user.id,

        display_name=current_user.display_name,

        name=current_user.display_name,

        email=current_user.email,

        created_at=current_user.created_at,

        status=current_user.status,

    )

    return {

        "status": "ok",

        "user": user_schema.model_dump(),

        "id": current_user.id,

        "display_name": current_user.display_name,

        "name": current_user.display_name,

        "email": current_user.email,

        "created_at": current_user.created_at,

        "status": current_user.status,

    }





# =====================================================================

# Phase 7: User Profile Endpoints

# =====================================================================



@app.get("/api/profile")

def api_get_profile(current_user: User = Depends(get_current_user)) -> dict[str, Any]:

    """Get beauty profile for current user."""

    profile = get_user_profile(current_user.id)

    schema = UserProfileSchema(

        user_id=profile.user_id,

        display_name=profile.display_name,

        preferred_name=profile.preferred_name,

        skin_type=profile.skin_type,

        skin_concerns=profile.skin_concerns,

        preferred_categories=profile.preferred_categories,

        preferred_brands=profile.preferred_brands,

        min_budget=profile.min_budget,

        max_budget=profile.max_budget,

        budget_min=profile.min_budget,

        budget_max=profile.max_budget,

        makeup_preferences=profile.makeup_preferences,

        ingredient_preferences=profile.ingredient_preferences,

        ingredient_avoidance=profile.ingredient_avoidance,

        ingredient_avoidances=profile.ingredient_avoidance,

        updated_at=profile.updated_at,

        medical_disclaimer=profile.medical_disclaimer,

    )

    dumped = schema.model_dump()

    dumped["profile"] = schema.model_dump()

    dumped["disclaimer"] = profile.medical_disclaimer

    return dumped





@app.put("/api/profile")

def api_update_profile(

    req: UpdateProfileRequest,

    current_user: User = Depends(get_current_user),

) -> dict[str, Any]:

    """Update beauty profile for current user."""

    min_b = req.min_budget if req.min_budget is not None else req.budget_min

    max_b = req.max_budget if req.max_budget is not None else req.budget_max

    ing_avoid = req.ingredient_avoidances if req.ingredient_avoidances is not None else req.ingredient_avoidance



    makeup_pref = req.makeup_preferences

    if isinstance(makeup_pref, dict):

        makeup_pref = [f"{k}:{v}" for k, v in makeup_pref.items() if v]



    success, msg, updated = save_user_profile(

        user_id=current_user.id,

        display_name=req.display_name,

        preferred_name=req.preferred_name,

        skin_type=req.skin_type,

        skin_concerns=req.skin_concerns,

        preferred_categories=req.preferred_categories,

        preferred_brands=req.preferred_brands,

        min_budget=min_b,

        max_budget=max_b,

        makeup_preferences=makeup_pref,

        ingredient_preferences=req.ingredient_preferences,

        ingredient_avoidance=ing_avoid,

    )

    if not success or not updated:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)



    schema = UserProfileSchema(

        user_id=updated.user_id,

        display_name=updated.display_name,

        preferred_name=updated.preferred_name,

        skin_type=updated.skin_type,

        skin_concerns=updated.skin_concerns,

        preferred_categories=updated.preferred_categories,

        preferred_brands=updated.preferred_brands,

        min_budget=updated.min_budget,

        max_budget=updated.max_budget,

        budget_min=updated.min_budget,

        budget_max=updated.max_budget,

        makeup_preferences=updated.makeup_preferences,

        ingredient_preferences=updated.ingredient_preferences,

        ingredient_avoidance=updated.ingredient_avoidance,

        ingredient_avoidances=updated.ingredient_avoidance,

        updated_at=updated.updated_at,

        medical_disclaimer=updated.medical_disclaimer,

    )

    dumped = schema.model_dump()

    dumped["profile"] = schema.model_dump()

    dumped["disclaimer"] = updated.medical_disclaimer

    return dumped





@app.delete("/api/profile")

def api_reset_profile(current_user: User = Depends(get_current_user)) -> dict[str, str]:

    """Reset optional preferences to defaults."""

    success, msg = reset_user_profile(current_user.id)

    if not success:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return {"status": "ok", "message": msg}





# =====================================================================

# Phase 7: Skincare Routine Endpoints

# =====================================================================



def _serialize_routine(r: Any) -> RoutineSchema:

    items_schema = [

        RoutineItemSchema(

            id=itm.id,

            routine_id=itm.routine_id,

            step_number=itm.step_number,

            step_name=itm.step_name,

            product_id=itm.product_id,

            custom_product_name=itm.custom_product_name,

            usage_instructions=itm.usage_instructions,

            precautions=itm.precautions,

            product_title=itm.product_title,

            product_brand=itm.product_brand,

            product_image_url=itm.product_image_url,

            product_price=itm.product_price,

            product_slug=itm.product_slug,

        )

        for itm in r.items

    ]

    # Check if conflict_warnings is a list of strings or dicts

    warnings_strs = []

    conflicts_list = []

    if isinstance(r.conflict_warnings, list):

        for w in r.conflict_warnings:

            if isinstance(w, dict):

                conflicts_list.append(w)

                warnings_strs.append(f"{w.get('description', '')} {w.get('recommendation', '')}")

            else:

                warnings_strs.append(str(w))

                conflicts_list.append({"conflict_type": "precaution", "description": str(w), "severity": "info", "recommendation": ""})



    rt = r.routine_type.lower()

    canonical_type = "AM" if rt in ["am", "morning"] else "PM" if rt in ["pm", "evening"] else r.routine_type



    return RoutineSchema(

        id=r.id,

        user_id=r.user_id,

        routine_type=canonical_type,

        title=r.title,

        name=r.title,

        description=r.description,

        created_at=r.created_at,

        updated_at=r.updated_at,

        items=items_schema,

        conflict_warnings=warnings_strs,

        conflicts=conflicts_list,

        medical_disclaimer=r.medical_disclaimer,

        disclaimer=r.medical_disclaimer,

    )





@app.get("/api/routines")

def api_list_routines(current_user: User = Depends(get_current_user)) -> dict[str, Any]:

    """List all skincare routines (morning and evening) for authenticated user."""

    routines = get_user_routines(current_user.id)

    serialized = [_serialize_routine(r).model_dump() for r in routines]

    return {

        "status": "ok",

        "routines": serialized,

        "disclaimer": ROUTINE_MEDICAL_DISCLAIMER,

        "medical_disclaimer": ROUTINE_MEDICAL_DISCLAIMER,

    }





@app.post("/api/routines")

def api_create_routine(

    req: CreateRoutineRequest,

    current_user: User = Depends(get_current_user),

) -> dict[str, Any]:

    """Create a new custom skincare routine."""

    title = req.title or req.name or "My Custom Routine"

    success, msg, routine = create_user_routine(

        user_id=current_user.id,

        routine_type=req.routine_type,

        title=title,

        description=req.description,

    )

    if not success or not routine:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    serialized = _serialize_routine(routine).model_dump()

    return {"status": "ok", "routine": serialized, **serialized}





@app.put("/api/routines/{routine_id}")

def api_update_routine(

    routine_id: int,

    req: UpdateRoutineRequest,

    current_user: User = Depends(get_current_user),

) -> dict[str, Any]:

    """Update title/description of an existing routine."""

    title = req.title or req.name

    success, msg, routine = update_user_routine(

        user_id=current_user.id,

        routine_id=routine_id,

        title=title,

        description=req.description,

    )

    if not success or not routine:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)

    serialized = _serialize_routine(routine).model_dump()

    return {"status": "ok", "routine": serialized, **serialized}





@app.delete("/api/routines/{routine_id}")

def api_delete_routine(

    routine_id: int,

    current_user: User = Depends(get_current_user),

) -> dict[str, str]:

    """Delete a routine and all its steps."""

    success, msg = delete_user_routine(current_user.id, routine_id)

    if not success:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)

    return {"status": "ok", "message": msg}





@app.post("/api/routines/{routine_id}/items")

def api_add_routine_item(

    routine_id: int,

    req: AddRoutineItemRequest,

    current_user: User = Depends(get_current_user),

) -> dict[str, Any]:

    """Add a new product/step to an existing routine."""

    success, msg, item = add_routine_item(

        user_id=current_user.id,

        routine_id=routine_id,

        step_name=req.step_name,

        product_id=req.product_id,

        custom_product_name=req.custom_product_name,

        usage_instructions=req.usage_instructions,

        precautions=req.precautions,

        step_number=req.step_number,

    )

    if not success or not item:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)



    item_schema = RoutineItemSchema(

        id=item.id,

        routine_id=item.routine_id,

        step_number=item.step_number,

        step_name=item.step_name,

        product_id=item.product_id,

        custom_product_name=item.custom_product_name,

        usage_instructions=item.usage_instructions,

        precautions=item.precautions,

        category=req.category,

        product_title=item.product_title,

        product_brand=item.product_brand,

        product_image_url=item.product_image_url,

        product_price=item.product_price,

        product_slug=item.product_slug,

    )

    return {"status": "ok", "item": item_schema.model_dump(), **item_schema.model_dump()}





@app.put("/api/routines/{routine_id}/reorder")

def api_reorder_routine(

    routine_id: int,

    req: ReorderRoutineRequest,

    current_user: User = Depends(get_current_user),

) -> dict[str, str]:

    """Reorder steps in a routine."""

    item_ids = req.item_order or req.item_ids_in_order

    success, msg = reorder_routine_items(

        user_id=current_user.id,

        routine_id=routine_id,

        item_ids_in_order=item_ids,

    )

    if not success:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return {"status": "ok", "message": msg}





@app.delete("/api/routines/{routine_id}/items/{item_id}")

def api_delete_routine_item(

    routine_id: int,

    item_id: int,

    current_user: User = Depends(get_current_user),

) -> dict[str, str]:

    """Delete a step from a routine."""

    success, msg = delete_routine_item(

        user_id=current_user.id,

        routine_id=routine_id,

        item_id=item_id,

    )

    if not success:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)

    return {"status": "ok", "message": msg}





# =====================================================================

# Phase 7: Persistent Watchlist Endpoints

# =====================================================================



@app.get("/api/watchlist")

def api_get_watchlist(current_user: User = Depends(get_current_user)) -> dict[str, Any]:

    """Retrieve saved wishlist for authenticated user with current prices."""

    items = get_user_wishlist(current_user.id)

    serialized = [

        WatchlistItemSchema(

            id=item.id,

            user_id=item.user_id,

            product_id=item.product_id,

            title=getattr(item, "product_title", None) or getattr(item, "title", "Product"),

            brand=getattr(item, "product_brand", None) or getattr(item, "brand", ""),

            category=getattr(item, "product_category", None) or getattr(item, "category", ""),

            image_url=getattr(item, "product_image_url", None) or getattr(item, "image_url", None),

            slug=getattr(item, "slug", f"product-{item.product_id}"),

            current_lowest_price=getattr(item, "current_lowest_price", None),

            original_price=getattr(item, "original_price", None),

            created_at=str(getattr(item, "created_at", "")),

            note=getattr(item, "note", None),

        ).model_dump()

        for item in items

    ]

    return {

        "status": "ok",

        "items": serialized,

        "count": len(serialized),

    }





@app.post("/api/watchlist")

def api_add_watchlist(

    req: AddWatchlistRequest,

    current_user: User = Depends(get_current_user),

) -> dict[str, Any]:

    """Add a product to user's persistent wishlist."""

    note = req.note or req.notes

    success, msg, wish_id = add_to_wishlist(

        user_id=current_user.id,

        product_id=req.product_id,

        note=note,

    )

    if not success:

        # Check if already in wishlist

        items = get_user_wishlist(current_user.id)

        existing = next((i for i in items if i.product_id == req.product_id), None)

        if existing:

            schema = WatchlistItemSchema(

                id=existing.id,

                user_id=existing.user_id,

                product_id=existing.product_id,

                title=getattr(existing, "product_title", None) or getattr(existing, "title", "Product"),

                brand=getattr(existing, "product_brand", None) or getattr(existing, "brand", ""),

                category=getattr(existing, "product_category", None) or getattr(existing, "category", ""),

                image_url=getattr(existing, "product_image_url", None) or getattr(existing, "image_url", None),

                slug=getattr(existing, "slug", f"product-{existing.product_id}"),

                current_lowest_price=getattr(existing, "current_lowest_price", None),

                original_price=getattr(existing, "original_price", None),

                created_at=str(getattr(existing, "created_at", "")),

                note=getattr(existing, "note", None),

            )

            return {"status": "ok", "message": "Already in wishlist", "item": schema.model_dump(), **schema.model_dump()}

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)



    items = get_user_wishlist(current_user.id)

    added = next((i for i in items if i.id == wish_id), None)

    if not added:

        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Could not load created item.")



    schema = WatchlistItemSchema(

        id=added.id,

        user_id=added.user_id,

        product_id=added.product_id,

        title=getattr(added, "product_title", None) or getattr(added, "title", "Product"),

        brand=getattr(added, "product_brand", None) or getattr(added, "brand", ""),

        category=getattr(added, "product_category", None) or getattr(added, "category", ""),

        image_url=getattr(added, "product_image_url", None) or getattr(added, "image_url", None),

        slug=getattr(added, "slug", f"product-{added.product_id}"),

        current_lowest_price=getattr(added, "current_lowest_price", None),

        original_price=getattr(added, "original_price", None),

        created_at=str(getattr(added, "created_at", "")),

        note=getattr(added, "note", None),

    )

    return {"status": "ok", "message": "Item added to watchlist", "item": schema.model_dump(), **schema.model_dump()}





@app.delete("/api/watchlist/{product_id}")

def api_remove_watchlist(

    product_id: int,

    current_user: User = Depends(get_current_user),

) -> dict[str, str]:

    """Remove product from user's persistent wishlist."""

    success, msg = remove_product_from_wishlist(current_user.id, product_id)

    if not success:

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg)

    return {"status": "ok", "message": msg}





@app.post("/api/watchlist/sync")

def api_sync_watchlist(

    req: SyncWatchlistRequest,

    current_user: User = Depends(get_current_user),

) -> dict[str, Any]:

    """

    Synchronize anonymous localStorage items into the authenticated user account upon login.

    """

    synced_count = 0

    raw_list = req.items or req.product_ids

    for item in raw_list:

        pid = None

        note = None

        if isinstance(item, int):

            pid = item

        elif isinstance(item, str):

            if item.isdigit():

                pid = int(item)

            elif item.startswith("prod-"):

                prod = get_product_by_slug(item)

                if prod:

                    pid = prod.id

        elif isinstance(item, dict):

            raw_pid = item.get("product_id") or item.get("id")

            if isinstance(raw_pid, int):

                pid = raw_pid

            elif isinstance(raw_pid, str) and raw_pid.isdigit():

                pid = int(raw_pid)

            note = item.get("notes") or item.get("note")



        if pid:

            success, _, _ = add_to_wishlist(user_id=current_user.id, product_id=pid, note=note)

            if success:

                synced_count += 1



    watchlist_res = api_get_watchlist(current_user)

    return {

        "status": "ok",

        "synced_count": synced_count,

        "items": watchlist_res["items"],

        "count": watchlist_res["count"],

    }







# =====================================================================

# Phase 8D: Manual Verification & Price Correction Endpoints

# =====================================================================



@app.post("/api/verification/manual", response_model=ManualVerificationResponse)

def api_submit_manual_verification(

    req: ManualVerificationRequest,

    current_user: User = Depends(get_current_user),

) -> ManualVerificationResponse:

    """Submit a manual product URL for price verification."""

    # Validate retailer domain

    allowed_retailers = ["nykaa", "myntra", "purplle", "tira", "amazon india", "amazon"]

    retailer_lower = req.retailer.lower().strip()

    if retailer_lower not in allowed_retailers:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=f"Retailer '{req.retailer}' is not supported. Supported retailers: {', '.join(allowed_retailers)}",

        )



    # Validate URL

    try:

        parsed = urlparse(req.product_url)

        if parsed.scheme not in ("http", "https"):

            raise ValueError("Invalid scheme")

        if not parsed.netloc:

            raise ValueError("Missing hostname")

    except Exception:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="Invalid product URL format",

        )



    # Check if retailer domain matches URL

    retailer_domain = retailer_lower.replace(" ", "")

    if retailer_domain not in parsed.netloc.lower():

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=f"URL domain does not match retailer '{req.retailer}'",

        )



    # Create verification request

    with get_connection() as conn:

        cursor = conn.cursor()



        # Duplicate submission prevention: check for existing pending request

        cursor.execute(

            """

            SELECT id FROM manual_verification_requests

            WHERE user_id = ? AND product_id = ? AND LOWER(retailer) = LOWER(?) AND status = 'pending'

            """,

            (current_user.id, req.product_id, req.retailer),

        )

        existing = cursor.fetchone()

        if existing:

            raise HTTPException(

                status_code=status.HTTP_409_CONFLICT,

                detail=f"You already have a pending verification request (ID #{existing['id']}) for this product and retailer.",

            )



        cursor.execute(

            """

            INSERT INTO manual_verification_requests (

                user_id, product_id, retailer, product_url, user_submitted_price,

                size_volume, shade, formulation, notes, status, submitted_at

            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)

            """,

            (

                current_user.id,

                req.product_id,

                req.retailer,

                req.product_url,

                req.user_submitted_price,

                req.size_volume,

                req.shade,

                req.formulation,

                req.notes,

            ),

        )

        request_id = cursor.lastrowid



        if req.evidence_url:

            cursor.execute(

                """

                INSERT INTO evidence_references (

                    reference_type, reference_id, evidence_url, evidence_type, description, uploaded_by

                ) VALUES ('manual_verification', ?, ?, 'screenshot', ?, ?)

                """,

                (request_id, req.evidence_url, req.notes or "Price verification screenshot proof", current_user.id),

            )



        # Return the created request

        cursor.execute(

            "SELECT * FROM manual_verification_requests WHERE id = ?",

            (request_id,),

        )

        row = cursor.fetchone()



    return ManualVerificationResponse(

        id=row["id"],

        user_id=row["user_id"],

        product_id=row["product_id"],

        retailer=row["retailer"],

        product_url=row["product_url"],

        user_submitted_price=row["user_submitted_price"],

        size_volume=row["size_volume"],

        shade=row["shade"],

        formulation=row["formulation"],

        notes=row["notes"],

        status=row["status"],

        verification_status=row["verification_status"],

        verified_price=row["verified_price"],

        verified_mrp=row["verified_mrp"],

        verified_discount_pct=row["verified_discount_pct"],

        verified_shipping_fee=row["verified_shipping_fee"],

        verified_size_volume=row["verified_size_volume"],

        verified_shade=row["verified_shade"],

        verified_formulation=row["verified_formulation"],

        verified_product_name=row["verified_product_name"],

        verified_brand=row["verified_brand"],

        verification_notes=row["verification_notes"],

        source_url=row["source_url"],

        submitted_at=row["submitted_at"],

        verified_at=row["verified_at"],

        reviewed_at=row["reviewed_at"],

        reviewed_by=row["reviewed_by"],

        rejection_reason=row["rejection_reason"],

    )





@app.get("/api/verification/manual", response_model=ManualVerificationListResponse)

def api_list_manual_verifications(

    status: Optional[str] = Query(None, description="Filter by status"),

    current_user: User = Depends(get_current_user),

) -> ManualVerificationListResponse:

    """List manual verification requests for the current user."""

    with get_connection() as conn:

        cursor = conn.cursor()

        if status:

            cursor.execute(

                "SELECT * FROM manual_verification_requests WHERE user_id = ? AND status = ? ORDER BY submitted_at DESC",

                (current_user.id, status),

            )

        else:

            cursor.execute(

                "SELECT * FROM manual_verification_requests WHERE user_id = ? ORDER BY submitted_at DESC",

                (current_user.id,),

            )

        rows = cursor.fetchall()



    items = []

    for row in rows:

        items.append(

            ManualVerificationResponse(

                id=row["id"],

                user_id=row["user_id"],

                product_id=row["product_id"],

                retailer=row["retailer"],

                product_url=row["product_url"],

                user_submitted_price=row["user_submitted_price"],

                size_volume=row["size_volume"],

                shade=row["shade"],

                formulation=row["formulation"],

                notes=row["notes"],

                status=row["status"],

                verification_status=row["verification_status"],

                verified_price=row["verified_price"],

                verified_mrp=row["verified_mrp"],

                verified_discount_pct=row["verified_discount_pct"],

                verified_shipping_fee=row["verified_shipping_fee"],

                verified_size_volume=row["verified_size_volume"],

                verified_shade=row["verified_shade"],

                verified_formulation=row["verified_formulation"],

                verified_product_name=row["verified_product_name"],

                verified_brand=row["verified_brand"],

                verification_notes=row["verification_notes"],

                source_url=row["source_url"],

                submitted_at=row["submitted_at"],

                verified_at=row["verified_at"],

                reviewed_at=row["reviewed_at"],

                reviewed_by=row["reviewed_by"],

                rejection_reason=row["rejection_reason"],

            )

        )



    return ManualVerificationListResponse(status="ok", items=items, count=len(items))





@app.post("/api/price-correction", response_model=PriceCorrectionResponse)

def api_submit_price_correction(

    req: PriceCorrectionSubmission,

    current_user: User = Depends(get_current_user),

) -> PriceCorrectionResponse:

    """Submit a price correction (report incorrect price)."""

    # Validate retailer

    allowed_retailers = ["nykaa", "myntra", "purplle", "tira", "amazon india", "amazon"]

    retailer_lower = req.retailer.lower().strip()

    if retailer_lower not in allowed_retailers:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=f"Retailer '{req.retailer}' is not supported",

        )



    # Validate URL

    try:

        parsed = urlparse(req.product_url)

        if parsed.scheme not in ("http", "https"):

            raise ValueError("Invalid scheme")

        if not parsed.netloc:

            raise ValueError("Missing hostname")

    except Exception:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="Invalid product URL format",

        )



    # Check retailer matches URL

    if retailer_lower not in parsed.netloc.lower():

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=f"URL domain does not match retailer '{req.retailer}'",

        )



    # Validate price

    if req.submitted_price <= 0:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail="Submitted price must be positive",

        )



    with get_connection() as conn:

        cursor = conn.cursor()



        # Duplicate submission prevention: check for existing pending request

        cursor.execute(

            """

            SELECT id FROM price_correction_submissions

            WHERE user_id = ? AND product_id = ? AND LOWER(retailer) = LOWER(?) AND status = 'pending'

            """,

            (current_user.id, req.product_id, req.retailer),

        )

        existing = cursor.fetchone()

        if existing:

            raise HTTPException(

                status_code=status.HTTP_409_CONFLICT,

                detail=f"You already have a pending price correction (ID #{existing['id']}) for this product and retailer.",

            )



        cursor.execute(

            """

            INSERT INTO price_correction_submissions (

                user_id, product_id, retailer, product_url, submitted_price,

                submitted_mrp, size_volume, shade, formulation, notes, evidence_url,

                status, created_at

            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', CURRENT_TIMESTAMP)

            """,

            (

                current_user.id,

                req.product_id,

                req.retailer,

                req.product_url,

                req.submitted_price,

                req.submitted_mrp,

                req.size_volume,

                req.shade,

                req.formulation,

                req.notes,

                req.evidence_url,

            ),

        )

        submission_id = cursor.lastrowid



        if req.evidence_url:

            cursor.execute(

                """

                INSERT INTO evidence_references (

                    reference_type, reference_id, evidence_url, evidence_type, description, uploaded_by

                ) VALUES ('price_correction', ?, ?, 'screenshot', ?, ?)

                """,

                (submission_id, req.evidence_url, req.notes or "Price correction screenshot proof", current_user.id),

            )



        cursor.execute(

            "SELECT * FROM price_correction_submissions WHERE id = ?",

            (submission_id,),

        )

        row = cursor.fetchone()



    return PriceCorrectionResponse(

        id=row["id"],

        user_id=row["user_id"],

        product_id=row["product_id"],

        retailer=row["retailer"],

        product_url=row["product_url"],

        submitted_price=row["submitted_price"],

        submitted_mrp=row["submitted_mrp"],

        size_volume=row["size_volume"],

        shade=row["shade"],

        formulation=row["formulation"],

        notes=row["notes"],

        evidence_url=row["evidence_url"],

        status=row["status"],

        reviewed_at=row["reviewed_at"],

        reviewed_by=row["reviewed_by"],

        rejection_reason=row["rejection_reason"],

        created_at=row["created_at"],

    )





@app.get("/api/price-corrections", response_model=PriceCorrectionListResponse)

def api_list_price_corrections(

    status: Optional[str] = Query(None, description="Filter by status"),

    current_user: User = Depends(get_current_user),

) -> PriceCorrectionListResponse:

    """List price correction submissions for the current user."""

    with get_connection() as conn:

        cursor = conn.cursor()

        if status:

            cursor.execute(

                "SELECT * FROM price_correction_submissions WHERE user_id = ? AND status = ? ORDER BY created_at DESC",

                (current_user.id, status),

            )

        else:

            cursor.execute(

                "SELECT * FROM price_correction_submissions WHERE user_id = ? ORDER BY created_at DESC",

                (current_user.id,),

            )

        rows = cursor.fetchall()



    items = []

    for row in rows:

        items.append(

            PriceCorrectionResponse(

                id=row["id"],

                user_id=row["user_id"],

                product_id=row["product_id"],

                retailer=row["retailer"],

                product_url=row["product_url"],

                submitted_price=row["submitted_price"],

                submitted_mrp=row["submitted_mrp"],

                size_volume=row["size_volume"],

                shade=row["shade"],

                formulation=row["formulation"],

                notes=row["notes"],

                evidence_url=row["evidence_url"],

                status=row["status"],

                reviewed_at=row["reviewed_at"],

                reviewed_by=row["reviewed_by"],

                rejection_reason=row["rejection_reason"],

                created_at=row["created_at"],

            )

        )



    return PriceCorrectionListResponse(status="ok", items=items, count=len(items))





# =====================================================================

# Phase 11B: Evidence File Upload & Serving

# =====================================================================



EVIDENCE_UPLOAD_DIR = os.path.join("data", "evidence_uploads")

os.makedirs(EVIDENCE_UPLOAD_DIR, exist_ok=True)

ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp"}

# Phase 14 Stage B: the upload ceiling comes from configuration instead of a
# hard-coded literal, so operators can tighten it without a code change.
MAX_EVIDENCE_BYTES = MAX_UPLOAD_SIZE_BYTES

# Phase 14 Stage B: the client supplied Content-Type is not trusted. The
# actual file signature (magic bytes) is verified instead, so a renamed
# executable or HTML document cannot be stored as an "image".
def _detect_evidence_extension(contents: bytes):
    """Return the extension implied by the file signature, or None when unknown."""
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if contents[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if contents[:4] == b"RIFF" and contents[8:12] == b"WEBP":
        return ".webp"
    return None





@app.post("/api/verification/upload-evidence", response_model=EvidenceUploadResponse)

async def api_upload_evidence(

    file: UploadFile = File(...),

    current_user: User = Depends(get_current_user),

) -> EvidenceUploadResponse:

    """Upload a screenshot or photo proof of retailer price (<5MB, PNG/JPEG/WEBP)."""

    if file.content_type not in ALLOWED_MIME_TYPES:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=f"Unsupported file format '{file.content_type}'. Allowed: PNG, JPEG, WEBP.",

        )



    contents = await file.read()

    if len(contents) > MAX_EVIDENCE_BYTES:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=f"File exceeds 5MB size limit (got {len(contents)} bytes).",

        )



    import uuid

    # Phase 14 Stage B: verify the real file type and use a high-entropy
    # filename. The client supplied name and extension are ignored entirely.
    detected_ext = _detect_evidence_extension(contents)

    if detected_ext is None:

        raise HTTPException(

            status_code=status.HTTP_400_BAD_REQUEST,

            detail=(
                "Unsupported file content. Allowed: PNG, JPEG, WEBP "
                "(verified by file signature)."
            ),

        )

    ext = detected_ext

    safe_filename = f"evidence_{uuid.uuid4().hex}{ext}"

    dest_path = os.path.join(EVIDENCE_UPLOAD_DIR, safe_filename)



    with open(dest_path, "wb") as f:

        f.write(contents)



    evidence_url = f"/api/verification/evidence/{safe_filename}"

    return EvidenceUploadResponse(

        status="ok",

        evidence_url=evidence_url,

        filename=safe_filename,

        file_size=len(contents),

    )





@app.get("/api/verification/evidence/{filename}")

def api_get_evidence_file(filename: str):

    """Safely serve an uploaded evidence screenshot with path traversal protection."""

    clean_name = os.path.basename(filename)

    target_path = os.path.join(EVIDENCE_UPLOAD_DIR, clean_name)

    if not os.path.exists(target_path):

        raise HTTPException(

            status_code=status.HTTP_404_NOT_FOUND,

            detail="Evidence file not found.",

        )

    return FileResponse(

        target_path,

        headers={

            # Never let the browser sniff the type of a stored upload.
            "X-Content-Type-Options": "nosniff",

            # Uploads are images only; block active content and framing.
            "Content-Security-Policy": (
                "default-src 'none'; img-src 'self'; sandbox"
            ),

            "Content-Disposition": "inline",

        },

    )





# =====================================================================

# Phase 11B: Admin Verification Queue & Review Endpoints

# =====================================================================



def is_admin_user(user: User) -> bool:
    """Determine whether user has admin privileges for verification review.

    Phase 14 Stage B (explicit administrator authorization):

    * The previous rule granted administrator rights to ``user.id == 1`` and to
      **any** account whose e-mail address ended in ``@pricewise.ai``. Because
      registration accepted arbitrary addresses, any visitor able to register
      an ``@pricewise.ai`` address inherited full review rights.
    * Administrator status is now an explicit, persisted ``users.is_admin``
      flag. It is granted explicitly (seed administrator, or a direct audited
      database update) and can never be obtained by self-registration.
    """
    if getattr(user, "is_admin", False):

        return True

    # Legacy compatibility: the very first account created by the local
    # seeder is the demo administrator. It is honoured only when that account
    # actually exists and is the seeded demo account, never for a
    # self-registered address.
    if user.id == 1:

        try:

            with get_connection() as conn:

                cursor = conn.cursor()

                cursor.execute(
                    "SELECT is_admin, email FROM users WHERE id = ?", (user.id,)
                )

                row = cursor.fetchone()

        except Exception:  # pragma: no cover - defensive

            return False

        if not row:

            return False

        if bool(row["is_admin"]):

            return True

        return str(row["email"] or "").lower() == DEMO_USER_EMAIL

    return False





def require_admin_user(current_user: User = Depends(get_current_user)) -> User:

    """FastAPI dependency requiring administrator credentials."""

    if not is_admin_user(current_user):

        raise HTTPException(

            status_code=status.HTTP_403_FORBIDDEN,

            detail="Admin privileges required to access verification queue or review submissions.",

        )

    return current_user





@app.get("/api/admin/verifications", response_model=AdminVerificationQueueResponse)

def api_get_admin_verification_queue(

    admin_user: User = Depends(require_admin_user),

) -> AdminVerificationQueueResponse:

    """Retrieve all pending manual verification requests and price corrections for admin review."""

    queue = get_pending_verification_queue(limit=50)

    return AdminVerificationQueueResponse(

        status="ok",

        pending_manual_verifications=queue["pending_manual_verifications"],

        pending_price_corrections=queue["pending_price_corrections"],

        total_pending=queue["total_pending"],

    )





@app.post("/api/admin/verifications/{request_id}/approve")

def api_admin_approve_verification(

    request_id: int,

    req: AdminVerificationApprovalRequest,

    admin_user: User = Depends(require_admin_user),

):

    """Admin approves a manual price verification request."""

    try:

        result = approve_manual_verification(

            request_id=request_id,

            reviewer=admin_user,

            verified_price=req.verified_price,

            verified_mrp=req.verified_mrp,

            notes=req.notes,

        )

        return result

    except ValueError as e:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))





@app.post("/api/admin/verifications/{request_id}/reject")

def api_admin_reject_verification(

    request_id: int,

    req: AdminVerificationRejectionRequest,

    admin_user: User = Depends(require_admin_user),

):

    """Admin rejects a manual price verification request."""

    try:

        result = reject_manual_verification(

            request_id=request_id,

            reviewer=admin_user,

            rejection_reason=req.rejection_reason,

        )

        return result

    except ValueError as e:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))





@app.post("/api/admin/price-corrections/{submission_id}/approve")

def api_admin_approve_price_correction(

    submission_id: int,

    req: AdminVerificationApprovalRequest,

    admin_user: User = Depends(require_admin_user),

):

    """Admin approves a user price correction submission."""

    try:

        result = approve_price_correction(

            submission_id=submission_id,

            reviewer=admin_user,

            verified_price=req.verified_price,

            verified_mrp=req.verified_mrp,

            notes=req.notes,

        )

        return result

    except ValueError as e:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))





@app.post("/api/admin/price-corrections/{submission_id}/reject")

def api_admin_reject_price_correction(

    submission_id: int,

    req: AdminVerificationRejectionRequest,

    admin_user: User = Depends(require_admin_user),

):

    """Admin rejects a user price correction submission."""

    try:

        result = reject_price_correction(

            submission_id=submission_id,

            reviewer=admin_user,

            rejection_reason=req.rejection_reason,

        )

        return result

    except ValueError as e:

        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))





# =====================================================================

# Phase 11B: Hybrid Price Collection & Retailer Sources Endpoints

# =====================================================================



@app.get("/api/prices/retailer-status", response_model=RetailerPolicyListResponse)

def api_get_retailer_status() -> RetailerPolicyListResponse:

    """Get operational access and policy statuses for all 5 monitored beauty retailers."""

    statuses = get_retailer_status_list()

    return RetailerPolicyListResponse(

        status="ok",

        retailers=[RetailerPolicyStatusSchema(**s) for s in statuses],

        count=len(statuses),

    )





@app.get("/api/prices/sources/{product_id}", response_model=ProductRetailerSourcesResponse)

def api_get_product_sources(product_id: int) -> ProductRetailerSourcesResponse:

    """Retrieve all genuine retailer links, offers, and verification statuses for a product."""

    sources = get_product_retailer_sources(product_id)

    return ProductRetailerSourcesResponse(

        status="ok",

        product_id=product_id,

        sources=[ProductRetailerSourceItemSchema(**s) for s in sources],

        count=len(sources),

    )





@app.post("/api/prices/collect/{product_id}", response_model=PriceCollectionResponseSchema)

def api_collect_product_prices(

    product_id: int,

    force_refresh: bool = False,

) -> PriceCollectionResponseSchema:

    """

    Execute hybrid price collection pipeline for a product.

    Respects retailer access policies, rate limits, and circuit breakers.

    """

    result = collect_product_prices(product_id, force_refresh=force_refresh)

    if result.get("status") == "not_found":

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=result.get("error"))

    if result.get("status") == "busy":

        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=result.get("message"))



    return PriceCollectionResponseSchema(

        status=result["status"],

        product_id=result["product_id"],

        product_title=result.get("product_title"),

        collected_count=result.get("collected_count", 0),

        results=result.get("results", []),

        timestamp=result["timestamp"],

    )





@app.get("/api/prices/collection-status/{product_id}", response_model=ProductRetailerSourcesResponse)

def api_get_collection_status(product_id: int) -> ProductRetailerSourcesResponse:

    """Check the collection freshness and status for a product."""

    return api_get_product_sources(product_id)





@app.post("/api/prices/refresh/{product_id}", response_model=PriceCollectionResponseSchema)

def api_refresh_product_prices(product_id: int) -> PriceCollectionResponseSchema:

    """Trigger on-demand price refresh for a product adhering to rate limits."""

    return api_collect_product_prices(product_id, force_refresh=True)





# =====================================================================

# Phase 7: Personalized Recommendations Endpoint

# =====================================================================



@app.get("/api/recommendations/personalized", response_model=PersonalizedRecommendationsResponse)

def api_get_recommendations(

    limit: int = Query(8, ge=1, le=20),

    current_user: User = Depends(get_current_user),

) -> PersonalizedRecommendationsResponse:

    """Get personalized catalog product recommendations based on user beauty profile."""

    res = get_personalized_recommendations(current_user.id, limit=limit)

    items = [

        RecommendedProductSchema(

            product_id=p.product_id,

            title=p.title,

            name=p.title,

            brand=p.brand,

            category=p.category,

            price=p.price,

            image_url=p.image_url,

            image=p.image_url,

            slug=p.slug,

            match_score=p.match_score,

            recommendation_score=p.match_score,

            match_reasons=p.match_reasons,

            matched_reasons=p.match_reasons,

            key_ingredients=p.key_ingredients,

            skin_type_suitability=p.skin_type_suitability,

        )

        for p in res.products

    ]

    return PersonalizedRecommendationsResponse(

        user_id=res.user_id,

        skin_type=res.skin_type,

        skin_concerns=res.skin_concerns,

        max_budget=res.max_budget,

        products=items,

        recommendations=items,

        has_profile=res.has_profile,

        medical_disclaimer=res.medical_disclaimer,

        disclaimer=res.medical_disclaimer,

    )







# =============================================================================

# Phase 8E: Beauty Intelligence API Endpoints

# =============================================================================



beauty_service = get_beauty_intelligence_service()





@app.post("/api/beauty/analyze-ingredients/{product_id}", response_model=IngredientAnalysisResponse)

async def analyze_ingredients(

    product_id: int,

    current_user = Depends(get_current_user),

    force_refresh: bool = False,

):

    """Analyze product ingredients using Gemini with caching."""

    result = beauty_service.analyze_ingredients(

        product_id=product_id,

        user_id=current_user.id,

        force_refresh=force_refresh,

    )

    return IngredientAnalysisResponse.model_validate(result)





@app.post("/api/beauty/match-skin-concerns", response_model=SkinConcernAnalysisResponse)

async def match_skin_concerns(

    request: dict,  # {concerns: [], skin_type?: str, budget_range?: [min, max]}

    current_user = Depends(get_current_user),

):

    """Match products to skin concerns using ingredient analysis."""

    concerns = request.get("concerns", [])

    skin_type = request.get("skin_type")

    budget_range = request.get("budget_range")

    

    if not concerns:

        raise HTTPException(status_code=400, detail="At least one skin concern required")

    

    if budget_range and len(budget_range) == 2:

        budget_range = tuple(budget_range)

    

    result = beauty_service.match_skin_concerns(

        concerns=concerns,

        skin_type=skin_type,

        budget_range=budget_range,

        user_id=current_user.id,

    )

    return SkinConcernAnalysisResponse.model_validate(result)





@app.post("/api/beauty/find-alternatives/{product_id}", response_model=AlternativeFinderResponse)

async def find_alternatives(

    product_id: int,

    request: dict = None,  # {max_price_ratio?: 0.8, min_similarity?: 0.6}

    current_user = Depends(get_current_user),

):

    """Find cheaper alternatives/dupes for a product."""

    max_price_ratio = (request or {}).get("max_price_ratio", 0.8)

    min_similarity = (request or {}).get("min_similarity", 0.6)

    

    result = beauty_service.find_alternatives(

        product_id=product_id,

        max_price_ratio=max_price_ratio,

        min_similarity=min_similarity,

        user_id=current_user.id,

    )

    return AlternativeFinderResponse.model_validate(result)





@app.post("/api/beauty/generate-routine/{routine_type}", response_model=RoutineRecommendationResponse)

async def generate_routine(

    routine_type: str,

    request: dict,  # {skin_type, skin_concerns, existing_products?, budget_range?}

    current_user = Depends(get_current_user),

):

    """Generate AM or PM skincare routine."""

    if routine_type not in ["AM", "PM"]:

        raise HTTPException(status_code=400, detail="routine_type must be 'AM' or 'PM'")

    

    skin_type = request.get("skin_type")

    skin_concerns = request.get("skin_concerns", [])

    existing_products = request.get("existing_products", [])

    budget_range = request.get("budget_range")

    

    if not skin_type:

        raise HTTPException(status_code=400, detail="skin_type required")

    if not skin_concerns:

        raise HTTPException(status_code=400, detail="At least one skin concern required")

    

    if budget_range and len(budget_range) == 2:

        budget_range = tuple(budget_range)

    

    result = beauty_service.generate_routine(

        skin_type=skin_type,

        skin_concerns=skin_concerns,

        routine_type=routine_type,

        existing_products=existing_products,

        budget_range=budget_range,

        user_id=current_user.id,

    )

    return RoutineRecommendationResponse.model_validate(result)





@app.get("/api/beauty/usage", response_model=BeautyIntelligenceUsageResponse)

async def get_beauty_usage(

    current_user = Depends(get_current_user),

):

    """Get current user's Gemini usage statistics."""

    daily_limit = int(os.getenv("GEMINI_DAILY_LIMIT", "50"))

    usage = beauty_service.get_user_usage(current_user.id)

    usage["daily_limit"] = daily_limit

    return BeautyIntelligenceUsageResponse(**usage)





@app.get("/api/beauty/admin/stats", response_model=BeautyIntelligenceAdminStatsResponse)

async def get_beauty_admin_stats(

    days: int = 30,

    current_user = Depends(get_current_user),

):

    """Get admin statistics for Gemini usage (admin only)."""

    # Check if user is admin (simple check - could be enhanced)

    is_admin = current_user.email.endswith("@pricewise.ai") or current_user.id == 1

    if not is_admin:

        raise HTTPException(status_code=403, detail="Admin access required")

    

    stats = beauty_service.get_admin_stats(days)

    return BeautyIntelligenceAdminStatsResponse(**stats)





@app.post("/api/beauty/cache/clear", response_model=dict)

async def clear_beauty_cache(

    current_user = Depends(get_current_user),

):

    """Clear expired cache entries (admin only)."""

    is_admin = current_user.email.endswith("@pricewise.ai") or current_user.id == 1

    if not is_admin:

        raise HTTPException(status_code=403, detail="Admin access required")

    

    deleted = beauty_service.clear_expired_cache()

    return {"status": "ok", "deleted_entries": deleted}





# =====================================================================

# Phase 9: Advanced Price Intelligence, Deal Analytics & Alerts

# =====================================================================



@app.get("/api/products/{slug_or_id}/price-history", response_model=ProductPriceAnalyticsResponseSchema)

def get_product_price_history_endpoint(

    slug_or_id: str,

    window_days: int = Query(30, description="Window in days: 7, 30, 90, or 180"),

) -> ProductPriceAnalyticsResponseSchema:

    """Retrieve historical price points and analytics over 7, 30, 90, or 180 days."""

    analytics = get_product_price_analytics(slug_or_id, window_days=window_days)

    return ProductPriceAnalyticsResponseSchema.model_validate(analytics)





@app.get("/api/products/{slug_or_id}/deal-intelligence", response_model=DealIntelligenceResponseSchema)

def get_product_deal_intelligence_endpoint(

    slug_or_id: str,

    retailer: Optional[str] = Query(None, description="Retailer name filter (e.g., Nykaa, Tira)"),

    coupon_code: Optional[str] = Query(None, description="Optional coupon code to test"),

) -> DealIntelligenceResponseSchema:

    """

    Compute transparent, factor-based Deal Score (0-100) and landed purchase cost.

    Strictly enforces simulated deal flagging for demo catalog data.

    """

    prod = None

    if slug_or_id.isdigit():

        prod = get_product_by_id(int(slug_or_id))

    if not prod:

        prod = get_product_by_slug(slug_or_id)

    if not prod:

        raise HTTPException(status_code=404, detail=f"Product '{slug_or_id}' not found.")



    offers = prod.offers if hasattr(prod, "offers") and prod.offers else []

    target_offer = None

    if retailer and offers:

        for o in offers:

            if o.store_name and o.store_name.lower() == retailer.lower():

                target_offer = o

                break

    if not target_offer and offers:

        target_offer = min(offers, key=lambda x: x.current_price)



    cur_price = target_offer.current_price if target_offer else prod.lowest_price

    retailer_name = target_offer.store_name if target_offer else (retailer or "Catalog Baseline")

    ship_fee = target_offer.shipping_cost if target_offer else 0.0

    ship_disclosed = getattr(target_offer, "is_shipping_disclosed", True) if target_offer else True

    src_type = getattr(target_offer, "source_type", "demo") if target_offer else "demo"



    # Historical low calculation over 90 days

    analytics = get_product_price_analytics(prod.id, window_days=90)

    hist_low = analytics.lowest_recorded_price or cur_price



    coupon_discount = 0.0

    if coupon_code:

        c_res = validate_retailer_coupon(coupon_code, cur_price, retailer_name)

        if c_res.is_valid:

            coupon_discount = c_res.discount_amount



    deal_score_data = calculate_deal_score(

        product_id=prod.id,

        current_price=cur_price,

        reference_mrp=prod.highest_price or cur_price,

        historical_low=hist_low,

        shipping_fee=ship_fee,

        is_shipping_disclosed=ship_disclosed,

        coupon_discount=coupon_discount,

        source_type=src_type,

        retailer_name=retailer_name,

        product_title=prod.title,

        coupon_code=coupon_code,

    )

    return DealIntelligenceResponseSchema.model_validate(deal_score_data)





@app.post("/api/products/{slug_or_id}/total-cost", response_model=TotalPurchaseCostBreakdownSchema)

def calculate_landed_total_cost_endpoint(

    slug_or_id: str,

    req: TotalCostRequestSchema,

) -> TotalPurchaseCostBreakdownSchema:

    """

    Calculate full landed cost itemization: product price + shipping - valid coupon.

    Enforces that undisclosed shipping remains unknown (NOT auto-zero).

    """

    prod = None

    if slug_or_id.isdigit():

        prod = get_product_by_id(int(slug_or_id))

    if not prod:

        prod = get_product_by_slug(slug_or_id)

    if not prod:

        raise HTTPException(status_code=404, detail=f"Product '{slug_or_id}' not found.")



    price = req.custom_price if req.custom_price is not None else prod.lowest_price

    shipping_disclosed = True

    shipping_fee = req.custom_shipping

    if shipping_fee is None:

        shipping_fee = 0.0



    breakdown = calculate_total_purchase_cost(

        product_price=price,

        shipping_fee=shipping_fee,

        is_shipping_disclosed=shipping_disclosed,

        coupon_code=req.coupon_code,

        retailer_name=req.retailer_name or "Retailer",

        reference_mrp=prod.highest_price,

        data_status="demo",

    )

    return TotalPurchaseCostBreakdownSchema.model_validate(breakdown)





@app.get("/api/price-tracking", response_model=list[PriceTrackingItemSchema])

def get_user_price_tracking_endpoint(

    current_user: User = Depends(get_current_user),

) -> list[PriceTrackingItemSchema]:

    """Retrieve active price tracking records for the authenticated user."""

    records = get_user_tracking_records(current_user.id)

    return [PriceTrackingItemSchema.model_validate(r) for r in records]





@app.post("/api/price-tracking")

def add_price_tracking_endpoint(

    req: TrackProductRequestSchema,

    current_user: User = Depends(get_current_user),

):

    """Add or update a tracked product with target price for authenticated user."""

    success, msg, tracking_id = add_tracked_product(

        product_id=req.product_id,

        target_price=req.target_price,

        note=req.note,

        alert_trigger_type=req.alert_trigger_type,

        user_id=current_user.id,

    )

    if not success:

        # If already tracked, update target price

        if "already in your Price Tracker" in msg and tracking_id:

            from src.services.price_tracking_service import update_target_price

            upd_success, upd_msg = update_target_price(

                tracking_id=tracking_id,

                new_target_price=req.target_price,

                user_id=current_user.id,

            )

            return {"status": "ok", "message": f"Updated target price to ₹{req.target_price:.2f}", "tracking_id": tracking_id}

        raise HTTPException(status_code=400, detail=msg)



    # Evaluate tracking rules once immediately so if target price is already met, alert triggers

    try:

        evaluate_tracking_rules(tracking_id=tracking_id, user_id=current_user.id)

    except Exception as e:

        logger.warning(f"Initial alert evaluation error: {e}")



    return {"status": "ok", "message": msg, "tracking_id": tracking_id}





@app.delete("/api/price-tracking/{id_or_product_id}")

def delete_price_tracking_endpoint(

    id_or_product_id: int,

    current_user: User = Depends(get_current_user),

):

    """Remove product tracking record for the authenticated user."""

    success, msg = remove_tracking(tracking_id=id_or_product_id, user_id=current_user.id)

    if not success:

        from src.services.price_tracking_service import get_tracking_by_product_id

        record = get_tracking_by_product_id(product_id=id_or_product_id, user_id=current_user.id)

        if record:

            success, msg = remove_tracking(tracking_id=record.id, user_id=current_user.id)

        

    if not success:

        raise HTTPException(status_code=404, detail="Tracked product record not found.")



    return {"status": "ok", "message": msg}





@app.get("/api/price-alerts", response_model=list[PriceAlertItemSchema])

def get_user_price_alerts_endpoint(

    unread_only: bool = Query(False),

    current_user: User = Depends(get_current_user),

) -> list[PriceAlertItemSchema]:

    """Retrieve price alert notifications for authenticated user with strict isolation."""

    alerts = get_user_price_alerts_list(user_id=current_user.id, unread_only=unread_only)

    return [PriceAlertItemSchema.model_validate(a) for a in alerts]





@app.put("/api/price-alerts/{alert_id}/read")

def mark_price_alert_read_endpoint(

    alert_id: int,

    current_user: User = Depends(get_current_user),

):

    """Mark a price alert as read."""

    success = mark_alert_read(alert_id=alert_id, user_id=current_user.id)

    if not success:

        raise HTTPException(status_code=404, detail="Price alert not found or unauthorized.")

    return {"status": "ok", "message": "Alert marked as read"}





# =====================================================================

# Phase 10: Advanced Beauty Intelligence & Discovery Endpoints

# =====================================================================



@app.get("/api/beauty/ingredients")

def get_master_ingredients_endpoint():

    """Retrieve curated master list of cosmetic active ingredients with clinical profiles."""

    return {

        "total": len(MASTER_INGREDIENTS),

        "ingredients": [

            {

                "id": ing.id,

                "name": ing.name,

                "inci_name": ing.inci_name,

                "category": ing.category,

                "description": ing.description,

                "what_it_does": ing.what_it_does,

                "why_used": ing.why_used,

                "benefits": ing.benefits,

                "potential_irritations": ing.potential_irritations,

                "skin_suitability": ing.skin_suitability,

                "evidence_level": ing.evidence_level,

                "optimal_ph": ing.optimal_ph,

                "typical_concentration": ing.typical_concentration,

            }

            for ing in MASTER_INGREDIENTS.values()

        ],

    }





@app.post("/api/beauty/ingredient-compatibility", response_model=IngredientCompatibilityResponse)

def check_ingredient_compatibility_endpoint(

    req: IngredientCompatibilityRequest,

) -> IngredientCompatibilityResponse:

    """Evaluate pairwise compatibility, clashes, and synergies between active ingredients."""

    result = check_ingredient_compatibility(req.ingredients)

    return IngredientCompatibilityResponse(**result)





@app.post("/api/beauty/routine-checker", response_model=RoutineCheckerResponse)

def check_routine_safety_endpoint(

    req: RoutineCheckerRequest,

) -> RoutineCheckerResponse:

    """Analyze AM and PM skincare routines for conflicts, photosensitivity, duplicate actives, and sunscreen compliance."""

    am_data = [item.model_dump() for item in req.am_steps]

    pm_data = [item.model_dump() for item in req.pm_steps]

    result = check_routine_safety(am_items=am_data, pm_items=pm_data, user_skin_type=req.user_skin_type)

    return RoutineCheckerResponse(**result)





@app.post("/api/beauty/climate-recommendations", response_model=ClimateSkincareResponse)

def get_climate_recommendations_endpoint(

    req: ClimateSkincareRequest,

) -> ClimateSkincareResponse:

    """Generate Indian climate-adapted skincare guidance and matched catalog products."""

    result = get_climate_recommendations(

        climate_code=req.climate_code,

        skin_type=req.skin_type,

        concerns=req.concerns,

    )

    return ClimateSkincareResponse(**result)





@app.get("/api/beauty/climate-profiles")

def get_climate_profiles_endpoint():

    """List all available Indian climate profiles."""

    return {

        "profiles": [

            {

                "code": p.code,

                "name": p.name,

                "regions": p.regions,

                "temperature_range": p.temperature_range,

                "humidity_level": p.humidity_level,

            }

            for p in CLIMATE_PROFILES.values()

        ]

    }





@app.post("/api/beauty/foundation-matcher", response_model=FoundationMatchResponse)

def match_foundation_shade_endpoint(

    req: FoundationMatchRequest,

) -> FoundationMatchResponse:

    """Match skin depth and undertone to catalog foundations with confidence score and oxidation advisory."""

    result = match_foundation_shade(

        skin_depth=req.skin_depth,

        undertone=req.undertone,

        coverage=req.coverage,

        finish=req.finish,

        reference_brand=req.reference_brand,

        reference_shade=req.reference_shade,

    )

    return FoundationMatchResponse(**result)





@app.get("/api/beauty/advanced-discovery", response_model=AdvancedDiscoveryResponse)

def get_advanced_discovery_endpoint(

    category: Optional[str] = Query(None),

    brand: Optional[str] = Query(None),

    min_price: Optional[float] = Query(None),

    max_price: Optional[float] = Query(None),

    skin_type: Optional[str] = Query(None),

    concern: Optional[str] = Query(None),

    ingredient: Optional[str] = Query(None),

    finish: Optional[str] = Query(None),

    min_spf: Optional[int] = Query(None),

    undertone: Optional[str] = Query(None),

    query: Optional[str] = Query(None),

) -> AdvancedDiscoveryResponse:

    """Multi-criteria search and filtering across the 34 catalog products with explainable matching."""

    result = search_advanced_discovery(

        category=category,

        brand=brand,

        min_price=min_price,

        max_price=max_price,

        skin_type=skin_type,

        concern=concern,

        ingredient=ingredient,

        finish=finish,

        min_spf=min_spf,

        undertone=undertone,

        query=query,

    )

    return AdvancedDiscoveryResponse(**result)







