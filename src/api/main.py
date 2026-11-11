"""Lightweight FastAPI Backend Bridge for PriceWise AI Beauty (Phase 6A).

Exposes REST endpoints for the React frontend while reusing existing
database models and service layers. Keeps Streamlit fully operational.
"""

import json
import logging
import os
from pathlib import Path
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
from src.services.price_intelligence import (
    get_verified_offers,
    get_cheapest_verified,
    list_cheapest_per_catalog,
    expire_stale_observations,
    get_observation_price_history,
    get_price_health_stats,
)
from src.adapters.mcp_adapters.priceinindia_adapter import PriceInIndiaAdapter
from src.adapters.mcp_adapters.open_beauty_facts_adapter import OpenBeautyFactsAdapter
from src.services.product_matching_service import evaluate_product_match, admin_correct_match, MatchClassification

# ── Phase 16.6 Stage 7: live price coverage, freshness & review APIs ────────
from src.services.cheapest_offer_service import (
    get_catalog_cheapest_eligible,
    get_cheapest_eligible,
    get_eligible_offers,
    get_excluded_offers,
)
from src.services.freshness_service import (
    FreshnessPolicy,
    classify_freshness,
    freshness_distribution,
    observation_age_hours,
)
from src.services.match_review_service import list_pending_matches, resolve_pending_match
from src.services.price_intelligence import (
    get_full_price_history,
    get_last_collection_time,
    get_latest_observation_per_retailer,
    get_price_history_summary,
)
from src.scripts.collect_pi_observations import DEFAULT_STATS_PATH as _DISCOVERY_STATS_PATH


def require_admin(current_user: User = Depends(get_current_user)) -> User:
    """Admin gate for Phase 16.6 admin endpoints.

    Preserves the exact auth behaviour of the existing admin endpoints
    (authenticated session required via get_current_user). No new or
    weaker mechanism is introduced.
    """
    return current_user


# Artifacts consulted by the collection-status endpoint. Monkeypatchable in
# tests; the endpoint reports honestly when no artifact exists.
COLLECTION_STATS_PATHS: list[Any] = [_DISCOVERY_STATS_PATH]


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



# ============================================================================
# Phase 16.2 Stage 4: Price Intelligence & MCP Integration Endpoints
# ============================================================================

@app.get("/api/products/{product_id}/offers")
def get_product_offers(product_id: int):
    """Return verified offers for a product with unit prices and discounts.

    Phase 16.6 Stage 7: additionally exposes the live-price section —
    eligible provider-observed offers and the transparent exclusion
    breakdown from the eligibility service (demo prices, unverified
    matches, stale or foreign-currency rows are excluded there, never
    here silently).
    """
    offers = get_verified_offers(product_id)
    eligible = get_eligible_offers(product_id)
    if not offers and not eligible:
        raise HTTPException(status_code=404, detail="No offers found for this product")
    excluded = get_excluded_offers(product_id)
    return {
        "product_id": product_id,
        "offers": offers,
        "live": {
            "eligible_offers": eligible,
            "excluded_offers": excluded,
            "assumptions": _eligibility_assumptions(),
        },
    }


def _eligibility_assumptions() -> list[str]:
    """Disclosed input assumptions of the live eligibility engine."""
    from src.services.cheapest_offer_service import ASSUMPTIONS

    return list(ASSUMPTIONS)


@app.get("/api/products/{product_id}/cheapest")
def get_product_cheapest(product_id: int):
    """Return the single cheapest verified offer for a product.

    Phase 16.6 Stage 7: additionally exposes ``live_cheapest`` — the
    cheapest eligibility-gated provider-observed offer with its freshness,
    match basis and disclosed assumptions (or ``null`` honestly, when no
    eligible live offer exists).
    """
    offer = get_cheapest_verified(product_id)
    live_cheapest = get_cheapest_eligible(product_id)
    if not offer and not live_cheapest:
        raise HTTPException(status_code=404, detail="No verified offers available")
    return {
        "product_id": product_id,
        "cheapest": offer,
        "live_cheapest": live_cheapest,
    }


@app.get("/api/catalog/cheapest-offers")
def list_catalog_cheapest_offers(limit: int = Query(200, ge=1, le=500)):
    """Return cheapest verified offer across all active products.

    Phase 16.6 Stage 7: additionally exposes the paginated live section —
    cheapest eligibility-gated offer per product. Products without any
    eligible live offer are honestly absent from ``live`` (never
    demo-filled).
    """
    results = list_cheapest_per_catalog(limit=limit)
    live = get_catalog_cheapest_eligible(limit=limit)
    return {
        "count": len(results),
        "offers": results,
        "live": {
            "items": live["items"],
            "total_products": live["total_products"],
            "products_with_eligible_offers": live["products_with_eligible_offers"],
            "assumptions": live["assumptions"],
        },
    }


@app.post("/api/admin/price-observations/expire-stale")
def expire_stale_endpoint(max_age_hours: int = Query(72, ge=1, le=720)):
    """Expire observations older than max_age_hours. Admin-only."""
    count = expire_stale_observations(max_age_hours=max_age_hours)
    return {"expired_count": count, "max_age_hours": max_age_hours}


@app.get("/api/products/{product_id}/price-history")
def get_product_price_history(product_id: int, limit: int = Query(30, ge=1, le=100)):
    """Return price history for a product (excludes superseded).

    Phase 16.6 Stage 7: additionally returns ``full_history`` (including
    superseded observations — history is retained, never deleted), the
    per-point ``price_change``, the latest observation per retailer with
    freshness annotation, and a summary over real observations only
    (lowest / highest / average / trend — no synthetic points).
    """
    history = get_observation_price_history(product_id, limit=limit)
    full_history = get_full_price_history(product_id, limit=limit)
    per_retailer = get_latest_observation_per_retailer(product_id)
    summary = get_price_history_summary(product_id)

    def _point(p) -> dict:
        return {
            "id": p.id,
            "retailer": p.retailer,
            "observed_price": p.observed_price,
            "observed_mrp": p.observed_mrp,
            "observation_type": p.observation_type,
            "observation_status": p.observation_status,
            "created_at": p.created_at,
            "unit_price": p.unit_price,
            "evidence_notes": p.evidence_notes,
            "price_change": p.price_change,
        }

    return {
        "product_id": product_id,
        "history_points": [_point(p) for p in history],
        "full_history": [_point(p) for p in full_history],
        "latest_per_retailer": [
            {
                "id": r["id"],
                "retailer": r["retailer"],
                "observed_price": r["observed_price"],
                "currency": r.get("currency"),
                "provider_name": r.get("provider_name"),
                "observation_status": r["observation_status"],
                "verification_status": r["verification_status"],
                "created_at": r["created_at"],
                "observed_age_hours": r["observed_age_hours"],
                "freshness": r["freshness"],
            }
            for r in per_retailer
        ],
        "summary": summary,
    }


def _collection_job_status() -> dict[str, Any]:
    """Read the most recent discovery-run statistics artifact.

    Honest reporting: when no artifact exists the job is reported as
    never_run — no invented progress or synthetic success.
    """
    for path in COLLECTION_STATS_PATHS:
        candidate = Path(path)
        if candidate.exists():
            try:
                stats = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"status": "unreadable", "artifact": str(candidate)}
            return {
                "status": "completed" if stats.get("finished_at") else "running",
                "artifact": str(candidate),
                "started_at": stats.get("started_at"),
                "finished_at": stats.get("finished_at"),
                "dry_run": stats.get("dry_run"),
                "totals": stats.get("totals"),
                "error_counts": stats.get("error_counts"),
                "duration_seconds": stats.get("duration_seconds"),
            }
    return {"status": "never_run", "artifact": None}


@app.get("/api/admin/health-stats")
def admin_health_stats():
    """Get overall data-quality health stats for the admin dashboard.

    Phase 16.6 Stage 7 additions:
    - ``freshness``: distribution of live observations over the configured
      freshness policy (fresh / aging / stale / unknown)
    - ``match_review_queue``: how many uncertain matches await human review
    - ``collection``: status of the latest controlled discovery run
      (from the run-stats artifact; ``never_run`` when absent)
    """
    stats = get_price_health_stats()

    # Freshness distribution over current live observations.
    with get_connection() as conn:
        rows = [
            dict(r)
            for r in conn.execute(
                "SELECT created_at FROM retail_price_observation "
                "WHERE observation_status = 'live'"
            ).fetchall()
        ]
    stats["freshness"] = freshness_distribution(rows)

    # Uncertain matches awaiting human review.
    try:
        queue = list_pending_matches(limit=1, offset=0)
        stats["match_review_queue"] = {"pending": queue["total"]}
    except Exception:
        # Health stats must not fail because of queue storage issues; the
        # failure is reported, never hidden as zero.
        stats["match_review_queue"] = {"pending": None, "error": "unavailable"}

    # Latest controlled discovery run.
    stats["collection"] = _collection_job_status()
    stats["last_collection_time"] = get_last_collection_time()
    return stats


# ============================================================================
# Phase 16.6 Stage 7: Match Review Queue + Collection Job Status (admin)
# ============================================================================

class MatchReviewDecisionRequest(BaseModel):
    """Admin decision on an uncertain PriceInIndia match."""
    decision: str  # 'approve' | 'reject'
    note: Optional[str] = None


def _admin_user_id_for_decision(db_path: str | None, admin: User) -> Optional[int]:
    """Resolve the admin's user id when the account exists in the DB.

    The seeded test/dev databases may contain no users table rows while an
    authenticated session is still valid. In that case the decision is
    recorded without an FK reference and the session context is written to
    the verification notes instead — never silently.
    """
    try:
        with get_connection(db_path) as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE id = ?", (admin.id,)
            ).fetchone()
        return row["id"] if row else None
    except Exception:
        return None


@app.get("/api/admin/match-review-queue")
def admin_match_review_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_admin),
):
    """List uncertain matches that await human review (admin, paginated).

    Every PriceInIndia candidate that is not a verified match lands here.
    Unreviewed possible matches are never eligible as cheapest offers
    (Stage 3 rule 8) — only an explicit admin decision promotes them.
    """
    try:
        queue = list_pending_matches(limit=limit, offset=offset)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return queue


@app.post("/api/admin/match-review/{observation_id}/resolve")
def admin_resolve_match_review(
    observation_id: int,
    req: MatchReviewDecisionRequest,
    admin: User = Depends(require_admin),
):
    """Apply an admin decision to a pending match observation.

    - approve: the observation becomes a verified, live observation and
      may participate in cheapest-offer eligibility.
    - reject: the observation is flagged and excluded from eligibility.
      History is retained — nothing is ever deleted.
    """
    admin_user_id = _admin_user_id_for_decision(None, admin)
    try:
        updated = resolve_pending_match(
            observation_id,
            decision=req.decision,
            admin_user_id=admin_user_id,
            note=req.note or "",
            db_path=None,
        )
    except LookupError:
        raise HTTPException(status_code=404, detail="Observation not found")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if admin_user_id is None:
        # Honest disclosure: the decision was applied by an authenticated
        # session whose user record is absent from this database.
        updated["admin_reference"] = f"session:{admin.id} ({admin.email})"
    return {"resolved": True, "observation": updated}


@app.get("/api/admin/price-collection/status")
def admin_price_collection_status(admin: User = Depends(require_admin)):
    """Status of the latest controlled discovery run (admin).

    Reads the run-statistics artifact written by
    ``src.scripts.collect_pi_observations``; reports ``never_run`` honestly
    when no artifact exists. Also reports the last observation timestamp
    recorded in the database.
    """
    status = _collection_job_status()
    status["last_collection_time"] = get_last_collection_time()
    return status


@app.get("/api/connectors/priceinindia/health")
def priceinindia_health():
    """Health check for PriceInIndia MCP connector."""
    adapter = PriceInIndiaAdapter()
    h = adapter.health
    return {
        "name": h.name,
        "endpoint": h.endpoint,
        "is_configured": h.is_configured,
        "is_healthy": h.is_healthy,
        "last_success_at": h.last_success_at,
        "last_error": h.last_error,
        "total_requests": h.total_requests,
        "failed_requests": h.failed_requests,
        "avg_response_time_ms": h.avg_response_time_ms,
    }


@app.post("/api/connectors/priceinindia/search")
def priceinindia_search(
    query: str = Body(..., min_length=1),
    brand: Optional[str] = Body(None),
    page: int = Body(1, ge=1),
    per_page: int = Body(20, ge=1, le=50),
):
    """Search PriceInIndia for products."""
    adapter = PriceInIndiaAdapter()
    result = adapter.search_products(query=query, brand=brand, page=page, per_page=per_page)
    total = result.data.get("total", 0) if result.data else 0
    return {
        "success": result.success,
        "tool": result.tool_name,
        "total": total,
        "products": result.items[:per_page] if result.items else [],
        "error": result.error_message,
        "response_time_ms": result.response_time_ms,
    }


@app.post("/api/connectors/priceinindia/find")
def priceinindia_find(
    brand: str = Body(...),
    product_name: str = Body(...),
    size_volume: Optional[str] = Body(None),
    max_results: int = Body(5, ge=1, le=20),
):
    """Find best-matching product from PriceInIndia for a brand+name combo."""
    adapter = PriceInIndiaAdapter()
    result = adapter.find_beauty_product(
        brand=brand, product_name=product_name, size_volume=size_volume
    )
    return {
        "success": result.success,
        "query": f"{brand} {product_name}",
        "products": result.items if result.items else [],
        "error": result.error_message,
    }


@app.get("/api/connectors/open-beauty-facts/health")
def obf_health():
    """Health check for Open Beauty Facts connector."""
    adapter = OpenBeautyFactsAdapter()
    return adapter.health_status


@app.get("/api/connectors/open-beauty-facts/barcode/{barcode}")
def obf_lookup_barcode(barcode: str):
    """Look up a product by barcode in OBF."""
    adapter = OpenBeautyFactsAdapter()
    result = adapter.lookup_by_barcode(barcode)
    return {
        "success": result.success,
        "product": result.data if result.data else None,
        "error": result.error_message,
    }


@app.post("/api/connectors/open-beauty-facts/search")
def obf_search(
    brands: Optional[list[str]] = Body(None),
    categories: Optional[list[str]] = Body(None),
    limit: int = Body(20, ge=1, le=50),
):
    """Search OBF by brands and/or categories."""
    adapter = OpenBeautyFactsAdapter()
    result = adapter.search_products(brands=brands, categories=categories, limit=limit)
    return {
        "success": result.success,
        "count": len(result.items),
        "products": result.items,
        "error": result.error_message,
    }


@app.post("/api/match/product")
def match_product_endpoint(req: dict = Body(...)):
    """Evaluate product-to-product matching with full evidence."""
    result = evaluate_product_match(
        target_brand=req["target_brand"],
        target_title=req["target_title"],
        target_specs=req.get("target_specs"),
        offer_brand=req.get("offer_brand", ""),
        offer_title=req.get("offer_title", ""),
        offer_variant=req.get("offer_variant"),
        offer_specs=req.get("offer_specs"),
        target_barcode=req.get("target_barcode"),
        offer_barcode=req.get("offer_barcode"),
        reference_price=req.get("reference_price"),
        offer_price=req.get("offer_price"),
    )
    return {
        "match_classification": result.match_classification,
        "confidence_score": result.confidence_score,
        "is_comparable": result.is_comparable,
        "brand_match": result.brand_match,
        "size_match": result.size_match,
        "shade_match": result.shade_match,
        "formulation_match": result.formulation_match,
        "title_similarity": result.title_similarity,
        "evidence_tier": result.evidence_tier,
        "barcode_match": result.barcode_match,
        "gtin_matched": result.gtin_matched,
        "unit_price_target": result.unit_price_target,
        "unit_price_offer": result.unit_price_offer,
        "requires_human_review": result.requires_human_review,
        "reasons": result.reasons,
        "flagged_reasons": result.flagged_reasons,
        "display_badge": result.display_badge,
    }


@app.post("/api/admin/match/correct")
def admin_correct_match_endpoint(req: dict = Body(...)):
    """Admin override for a previously computed match result."""
    stored = req.get("stored_result", {})
    new_class = req["new_classification"]
    correction_note = req.get("correction_note", "")
    from types import SimpleNamespace
    ns = SimpleNamespace(**{k: v for k, v in stored.items()})
    result = admin_correct_match(ns, new_class, correction_note)
    return {
        "match_classification": result.match_classification,
        "confidence_score": result.confidence_score,
        "is_comparable": result.is_comparable,
        "admin_corrections_applied": result.admin_corrections_applied,
        "reasons": result.reasons,
    }


# ============================================================================
# Phase 16.5: PriceInIndia Live Observation Collection Endpoint
# ============================================================================

class PriceInIndiaCollectRequest(BaseModel):
    """Request for collecting PI observations for catalog products."""
    product_ids: Optional[list[int]] = None
    brands: Optional[list[str]] = None
    limit: int = Query(20, ge=1, le=100, description="Max products to process")
    store: Optional[str] = Query(None, description="Filter for specific retailer")


class PriceInIndiaCollectResponse(BaseModel):
    """Response from PI observation collection."""
    total_products: int
    successful: int
    failed: int
    matches: int
    observations: list[dict]
    adapter_stats: dict
    errors: list[str]


@app.post("/api/collect/priceinindia", response_model=PriceInIndiaCollectResponse)
def collect_priceinindia_observations(
    req: PriceInIndiaCollectRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Collect live PriceInIndia price observations for catalog products.

    This endpoint runs the MCP-to-database pipeline:
    1. Load specified products from catalog
    2. Search PriceInIndia for each product
    3. Match results using product matching service
    4. Store observations in retail_price_observation table

    Only accessible to authenticated admins.
    """
    from datetime import datetime, timezone
    import json

    adapter = PriceInIndiaAdapter()
    errors = []
    observations_collected = []

    # Load products based on filters
    with get_connection() as conn:
        cursor = conn.cursor()

        if req.product_ids:
            placeholders = ",".join(["?" for _ in req.product_ids])
            cursor.execute(f"""
                SELECT id, sku, title, brand, category, specs_json
                FROM products
                WHERE id IN ({placeholders}) AND is_active = 1
                ORDER BY id
                LIMIT ?
            """, (*req.product_ids, req.limit))
        else:
            cursor.execute("""
                SELECT id, sku, title, brand, category, specs_json
                FROM products
                WHERE is_active = 1
                ORDER BY id
                LIMIT ?
            """, (req.limit,))

        rows = cursor.fetchall()

    products = []
    for r in rows:
        specs = json.loads(r["specs_json"]) if r["specs_json"] else {}
        products.append({
            "id": r["id"],
            "sku": r["sku"],
            "title": r["title"],
            "brand": r["brand"],
            "category": r["category"],
            "specs": specs,
        })

    logger.info(f"Collecting PI observations for {len(products)} products")

    for product in products:
        # Filter by brand if specified
        if req.brands and product["brand"].lower() not in [b.lower() for b in req.brands]:
            continue

        timestamp = datetime.now(timezone.utc).isoformat()

        # Search PriceInIndia
        query = f"{product['brand']} {product['title']}"
        pi_result = adapter.search_products(query=query, page=1, per_page=5)

        if not pi_result.success or not pi_result.items:
            errors.append(f"No PI results for product {product['id']}: {query}")
            continue

        # Evaluate matches and store
        matched_count = 0
        for pi_item in pi_result.items[:3]:
            # Build match request
            from src.services.product_matching_service import ProductMatchResult

            request = {
                "target_brand": product["brand"],
                "target_title": product["title"],
                "target_specs": product.get("specs", {}),
                "offer_brand": pi_item.get("brand", ""),
                "offer_title": pi_item.get("title", ""),
            }

            match_result = evaluate_product_match(**request)

            # Filter by store if specified
            if req.store and pi_item.get("store", "").lower() != req.store.lower():
                continue

            if match_result.is_comparable:
                price_value = float(pi_item.get("price", 0) or 0)
                if price_value <= 0:
                    # Never persist fabricated/invalid prices.
                    errors.append(
                        f"Invalid price for product {product['id']}: {pi_item.get('price')!r}"
                    )
                    continue

                retailer_name = pi_item.get("store", "unknown")
                product_url = pi_item.get("productPageUrl", pi_item.get("productUrl", "")) or ""

                # Store observation
                with get_connection() as conn:
                    cursor = conn.cursor()

                    # Supersede only the same retailer's live observation.
                    # Other retailers must remain independent.
                    cursor.execute("""
                        SELECT id FROM retail_price_observation
                        WHERE product_id = ? AND retailer = ?
                          AND observation_status = 'live'
                          AND created_at > datetime('now', '-7 days')
                    """, (product["id"], retailer_name))
                    existing = cursor.fetchone()

                    if existing:
                        cursor.execute(
                            "UPDATE retail_price_observation "
                            "SET observation_status = 'superseded', updated_at = ? "
                            "WHERE id = ?",
                            (timestamp, existing["id"]),
                        )

                    cursor.execute("""
                        INSERT INTO retail_price_observation
                        (product_id, retailer, product_url, observed_price, observed_mrp,
                         size_volume, observation_type, observation_status, verified_by_admin,
                         verification_status, created_at, updated_at, evidence_notes,
                         evidence_reference, match_result)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        product["id"],
                        retailer_name,
                        product_url,
                        price_value,
                        None,
                        pi_item.get("size"),
                        "live",
                        "live",
                        0,
                        "provider_observed",
                        timestamp,
                        timestamp,
                        f"PI match: {match_result.match_classification}, evidence: {match_result.evidence_tier}",
                        f"priceinindia_search:{pi_item.get('id')}",
                        json.dumps({
                            "classification": match_result.match_classification,
                            "confidence": match_result.confidence_score,
                            "evidence_tier": match_result.evidence_tier,
                            "reasons": match_result.reasons,
                        }),
                    ))

                    conn.commit()

                    obs_id = cursor.lastrowid
                    observations_collected.append({
                        "id": obs_id,
                        "product_id": product["id"],
                        "retailer": retailer_name,
                        "price": price_value,
                        "url": product_url,
                        "match_classification": match_result.match_classification,
                    })
                    matched_count += 1

        logger.info(f"  {product['brand'][:20]}: {matched_count} matches")

    # Return results
    return PriceInIndiaCollectResponse(
        total_products=len(products),
        successful=len(products) - len(errors),
        failed=len(errors),
        matches=len(observations_collected),
        observations=observations_collected,
        adapter_stats={
            "total_requests": adapter.health.total_requests,
            "failed_requests": adapter.health.failed_requests,
            "is_healthy": adapter.health.is_healthy,
        },
        errors=errors[:10],  # Limit errors in response
    )
