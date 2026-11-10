"""Lightweight FastAPI Backend Bridge for PriceWise AI Beauty (Phase 6A).

Exposes REST endpoints for the React frontend while reusing existing
database models and service layers. Keeps Streamlit fully operational.
"""

import logging
import os
from typing import Any, Optional
from fastapi import FastAPI, HTTPException, Query, Depends, Response, status, Body
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from src.config import APP_NAME, APP_VERSION
from src.database.connection import get_connection
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
)
from src.services.live_comparison_engine import get_live_comparison_engine
from src.api.auth_deps import get_current_user, get_optional_current_user
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

app = FastAPI(
    title=f"{APP_NAME} API",
    description="Bridge API connecting React frontend to Python service layer.",
    version=APP_VERSION,
)

# CORS Configuration for local development and production
default_origins = [
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
    origins = [o.strip() for o in cors_env.split(",") if o.strip()]
    for d in default_origins:
        if d not in origins:
            origins.append(d)
else:
    origins = default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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


@app.get("/api/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Health check endpoint reporting database connectivity and record volume."""
    record_count = 0
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT count(*) FROM products")
            record_count = cur.fetchone()[0]
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        raise HTTPException(status_code=500, detail="Database connectivity failure")

    return HealthResponse(
        status="ok",
        app_name=APP_NAME,
        version=APP_VERSION,
        database="sqlite",
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

    if not prod:
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

    token = generate_session_token(user.id, user.email)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
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

    token = generate_session_token(user.id, user.email)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,
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


# =====================================================================
# Phase 16.2 Stage 3.1: Admin Manual Price Entry Endpoint
# =====================================================================

from src.services.price_collection_engine import record_manual_price_observation


class ManualPriceEntryRequest(BaseModel):
    """Request schema for manual price entry."""
    product_id: int
    retailer: str
    product_url: str
    observed_price: float
    observed_mrp: Optional[float] = None
    size_volume: Optional[str] = None
    shade: Optional[str] = None
    formulation: Optional[str] = None
    evidence_notes: Optional[str] = None
    evidence_reference: Optional[str] = None


class ManualPriceEntryResponse(BaseModel):
    """Response schema for manual price entry."""
    id: int
    product_id: int
    retailer: str
    product_url: str
    observed_price: float
    observed_mrp: Optional[float] = None
    size_volume: Optional[str] = None
    shade: Optional[str] = None
    formulation: Optional[str] = None
    observation_type: str
    observation_status: str
    verified_by_admin: bool
    verified_price: Optional[float] = None
    verification_status: str
    admin_user_id: Optional[int] = None
    created_at: str
    evidence_notes: Optional[str] = None
    evidence_reference: Optional[str] = None
    admin_user: Optional[UserSchema] = None


@app.post("/api/admin/price-observations/manual", response_model=ManualPriceEntryResponse)
def manual_price_entry(
    req: ManualPriceEntryRequest = Body(...),
    current_user: User = Depends(get_current_user),
):
    """
    Manual Retailer Price Entry endpoint (Stage 3.1).

    Allows authenticated admins to enter actual retailer prices when
    automated collection is restricted.

    Requirements:
    - Product ID must exist
    - Retailer must be supported (nykaa, tira, purplle, amazon, myntra)
    - Price must be positive
    - URL must be a product page (not homepage)
    - Evidence notes are recorded for audit

    Validation rejects:
    - Homepage URLs (only product pages allowed)
    - Negative or zero prices
    - Unknown retailers
    """
    # Create a user-like object for the service
    class AdminUser:
        id = current_user.id
        email = current_user.email

    try:
        obs = record_manual_price_observation(
            product_id=req.product_id,
            retailer=req.retailer,
            product_url=req.product_url,
            observed_price=req.observed_price,
            observed_mrp=req.observed_mrp,
            size_volume=req.size_volume,
            shade=req.shade,
            formulation=req.formulation,
            evidence_notes=req.evidence_notes,
            evidence_reference=req.evidence_reference,
            admin_user=AdminUser(),
        )

        return ManualPriceEntryResponse(
            id=obs["id"],
            product_id=obs["product_id"],
            retailer=obs["retailer"],
            product_url=obs["product_url"],
            observed_price=obs["observed_price"],
            observed_mrp=obs.get("observed_mrp"),
            size_volume=obs.get("size_volume"),
            shade=obs.get("shade"),
            formulation=obs.get("formulation"),
            observation_type=obs["observation_type"],
            observation_status=obs["observation_status"],
            verified_by_admin=obs["verified_by_admin"],
            verified_price=obs.get("verified_price"),
            verification_status=obs["verification_status"],
            admin_user_id=obs.get("admin_user_id"),
            created_at=obs["created_at"],
            evidence_notes=obs.get("evidence_notes"),
            evidence_reference=obs.get("evidence_reference"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Manual price entry failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to record manual price observation")

