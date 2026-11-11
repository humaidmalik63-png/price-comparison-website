/**
 * Centralized API Client for PriceWise AI Beauty (Phase 6A).
 * 
 * Provides communication with the FastAPI backend bridge with automatic fallback
 * to static catalog data (PRODUCTS_DATA) when the backend is offline or unreachable.
 */

import type {
  Product,
  RetailerOffer,
  User,
  UserProfile,
  Routine,
  RoutineItem,
  RecommendedProduct,
} from '../types';
import { PRODUCTS_DATA } from '../data/products';
import { findProductBySlugOrId } from './slug';

// Read API base URL from Vite environment or default to local FastAPI port
const getBaseApiUrl = (): string => {
  const envUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
  if (envUrl) {
    return envUrl;
  }
  // When running in a browser, use the same hostname (localhost or 127.0.0.1) on port 8000
  if (typeof window !== 'undefined' && window.location && window.location.hostname) {
    return `http://${window.location.hostname}:8000`;
  }
  return 'http://127.0.0.1:8000';
};
const API_BASE_URL = getBaseApiUrl();
const DEFAULT_TIMEOUT_MS = 4000;

export interface HealthCheckResult {
  status: string;
  app_name: string;
  version: string;
  database: string;
  record_count: number;
}

export interface BackendOffer {
  id: number;
  product_id: number;
  store_id: string;
  store_name: string;
  store_rating?: number;
  current_price: number;
  original_price?: number;
  shipping_cost?: number;
  is_shipping_disclosed: boolean;
  currency: string;
  availability: string;
  variant_name?: string;
  condition: string;
  offer_url: string;
  coupon_code?: string;
  coupon_discount?: number;
  total_cost?: number;
  source_type: string;
  last_checked?: string;
}

export interface BackendProduct {
  id: number;
  sku: string;
  slug?: string;
  title: string;
  brand: string;
  category: string;
  description?: string;
  image_url?: string;
  lowest_price?: number;
  highest_price?: number;
  lowest_total_cost?: number;
  currency_symbol: string;
  available_offer_count: number;
  specs?: Record<string, unknown>;
  offers?: BackendOffer[];
  created_at?: string;
}

/**
 * Fetch with automatic AbortSignal timeout.
 */
async function fetchWithTimeout(url: string, options: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<Response> {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      credentials: 'include',
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    throw error;
  }
}

/**
 * Check backend API health and database connectivity.
 */
export async function getHealth(): Promise<HealthCheckResult | null> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/health`, { method: 'GET' });
    if (!res.ok) return null;
    return (await res.json()) as HealthCheckResult;
  } catch {
    return null;
  }
}

/**
 * Helper to check whether backend API is responsive.
 */
export async function isApiAvailable(): Promise<boolean> {
  const health = await getHealth();
  return health !== null && health.status === 'ok';
}

/**
 * Map backend Offer model to frontend RetailerOffer model.
 */
function mapBackendOfferToFrontend(offer: BackendOffer): RetailerOffer {
  const storeNameMap: Record<string, RetailerOffer['storeName']> = {
    nykaa: 'Nykaa',
    tira: 'Tira',
    purplle: 'Purplle',
    amazon: 'Amazon India',
    'amazon india': 'Amazon India',
    myntra: 'Myntra',
  };

  const normalizedStore = storeNameMap[offer.store_id.toLowerCase()] || 'Nykaa';

  return {
    storeId: offer.store_id,
    storeName: normalizedStore,
    price: offer.current_price,
    originalPrice: offer.original_price,
    shippingFee: offer.shipping_cost ?? 0,
    isShippingDisclosed: offer.is_shipping_disclosed,
    couponCode: offer.coupon_code,
    couponDiscount: offer.coupon_discount,
    totalCost: offer.total_cost ?? offer.current_price,
    deliveryDays: '2-4 Days',
    inStock: offer.availability.toLowerCase().includes('stock'),
    stockStatus: offer.availability.toLowerCase().includes('stock') ? 'In Stock' : 'Out of Stock',
    purchaseUrl: offer.offer_url,
    sourceType: (offer.source_type as RetailerOffer['sourceType']) || 'demo',
    lastUpdated: offer.last_checked ? new Date(offer.last_checked).toLocaleDateString('en-GB') : undefined,
    matchClassification: 'verified_match',
  };
}

/**
 * Retrieve catalog products.
 * Tries the backend API bridge first; seamlessly falls back to static PRODUCTS_DATA.
 */
export async function getProducts(params?: {
  category?: string;
  search?: string;
  limit?: number;
}): Promise<Product[]> {
  try {
    const queryParams = new URLSearchParams();
    if (params?.category) queryParams.set('category', params.category);
    if (params?.search) queryParams.set('search', params.search);

    const url = `${API_BASE_URL}/api/products${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;
    const res = await fetchWithTimeout(url);

    if (res.ok) {
      const data = (await res.json()) as BackendProduct[];
      if (Array.isArray(data) && data.length > 0) {
        // Find matching detailed products from PRODUCTS_DATA or augment
        const matched = data.map((bp) => {
          const local = findProductBySlugOrId(PRODUCTS_DATA, bp.slug || bp.sku);
          if (local) return local;

          // If no local match, construct standard product structure
          return {
            id: `api-${bp.id}`,
            slug: bp.slug || bp.sku,
            name: bp.title,
            brand: bp.brand,
            brandTier: 'Premium' as const,
            category: (bp.category.toLowerCase() as Product['category']) || 'skincare',
            subcategory: 'Face Wash' as const,
            quantity: (bp.specs?.size as string) || '50 ml',
            price: bp.lowest_price || 0,
            originalPrice: bp.highest_price,
            image: bp.image_url || 'https://images.unsplash.com/photo-1598440947619-2c35fc9aa908?auto=format&fit=crop&w=800&q=80',
            description: bp.description || bp.title,
            keyIngredients: [],
            howToUse: {
              routine: 'AM & PM' as const,
              stepNumber: 1,
              instructions: 'Apply gently to damp skin.',
            },
            storeOffers: [],
          } satisfies Product;
        });

        if (params?.limit && params.limit > 0) {
          return matched.slice(0, params.limit);
        }
        return matched;
      }
    }
  } catch {
    // Backend unavailable or timed out; fall through to static data
  }

  // Fallback to static PRODUCTS_DATA
  let results = [...PRODUCTS_DATA];
  if (params?.category) {
    const cat = params.category.toLowerCase();
    results = results.filter((p) => p.category.toLowerCase() === cat || p.subcategory.toLowerCase() === cat);
  }
  if (params?.search) {
    const q = params.search.toLowerCase();
    results = results.filter(
      (p) => p.name.toLowerCase().includes(q) || p.brand.toLowerCase().includes(q)
    );
  }
  if (params?.limit && params.limit > 0) {
    results = results.slice(0, params.limit);
  }
  return results;
}

/**
 * Retrieve a single product by slug or id.
 * Tries the backend API bridge first; seamlessly falls back to static PRODUCTS_DATA.
 */
export async function getProductBySlug(slugOrId: string): Promise<Product | undefined> {
  if (!slugOrId) return undefined;

  // Static catalog search as immediate baseline
  const localProduct = findProductBySlugOrId(PRODUCTS_DATA, slugOrId);

  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/products/${encodeURIComponent(slugOrId)}`);
    if (res.ok) {
      const data = (await res.json()) as BackendProduct;
      if (localProduct) {
        // Augment local rich product with latest offers from backend if available
        if (data.offers && data.offers.length > 0) {
          const augmentedOffers = data.offers.map(mapBackendOfferToFrontend);
          return {
            ...localProduct,
            storeOffers: augmentedOffers.length > 0 ? augmentedOffers : localProduct.storeOffers,
          };
        }
        return localProduct;
      }
    }
  } catch {
    // Backend offline or error; return static product
  }

  return localProduct;
}

// ============================================================================
// Phase 6: Automatic Live Retailer Price Comparison Engine Client
// ============================================================================

export interface LiveRetailerOffer {
  retailerName: string;
  storeId: string;
  status: 'retrieved' | 'unavailable' | 'unsupported' | 'restricted' | 'mismatch';
  listedPrice?: number | null;
  mrp?: number | null;
  discountPct: number;
  shippingFee?: number | null;
  isShippingDisclosed: boolean;
  couponCode?: string | null;
  couponDiscount: number;
  totalCost?: number | null;
  stockStatus: string;
  inStock: boolean;
  purchaseUrl: string;
  variantDetected?: string | null;
  matchClassification: 'verified_match' | 'possible_match' | 'incompatible_mismatch';
  isLowestListed: boolean;
  isLowestTotal: boolean;
  sourceType: 'verified_live' | 'cached' | 'demo' | 'provider_observed' | 'catalog_verified' | 'partner_feed' | 'manually_curated' | 'unavailable';
  retrievedAt: string;
  validationNotes?: string | null;
}

export interface LiveComparisonSummary {
  lowestListedPrice?: number | null;
  lowestListedRetailer?: string | null;
  lowestTotalCost?: number | null;
  lowestTotalRetailer?: string | null;
  retailersChecked: number;
  retailersRetrieved: number;
  retailersUnavailable: number;
  retailersUnsupported: number;
  retailersRestricted: number;
  cheapestSavingsAmount: number;
  cheapestSavingsPercent: number;
}

export interface LiveComparisonResult {
  productId?: number | null;
  productTitle: string;
  brand: string;
  targetVariant: string;
  isCached: boolean;
  freshnessSeconds: number;
  retrievalTimestamp: string;
  offers: LiveRetailerOffer[];
  summary: LiveComparisonSummary;
}

export interface ManualUrlCheckResult {
  retailerName: string;
  storeId: string;
  productUrl: string;
  verificationStatus: string;
  listedPrice?: number | null;
  mrp?: number | null;
  shippingFee?: number | null;
  isShippingDisclosed: boolean;
  totalCost?: number | null;
  inStock: boolean;
  stockStatus: string;
  productName?: string | null;
  retrievedAt: string;
  validationNotes?: string | null;
}

interface RawLiveComparisonBackendResponse {
  product_id?: number | null;
  product_title: string;
  brand: string;
  target_variant: string;
  is_cached: boolean;
  freshness_seconds: number;
  retrieval_timestamp: string;
  offers: Array<{
    retailer_name: string;
    store_id: string;
    status: string;
    listed_price?: number | null;
    mrp?: number | null;
    discount_pct: number;
    shipping_fee?: number | null;
    is_shipping_disclosed: boolean;
    coupon_code?: string | null;
    coupon_discount: number;
    total_cost?: number | null;
    stock_status: string;
    in_stock: boolean;
    purchase_url: string;
    variant_detected?: string | null;
    match_classification: string;
    is_lowest_listed: boolean;
    is_lowest_total: boolean;
    source_type: string;
    retrieved_at: string;
    validation_notes?: string | null;
  }>;
  summary: {
    lowest_listed_price?: number | null;
    lowest_listed_retailer?: string | null;
    lowest_total_cost?: number | null;
    lowest_total_retailer?: string | null;
    retailers_checked: number;
    retailers_retrieved: number;
    retailers_unavailable: number;
    retailers_unsupported: number;
    retailers_restricted: number;
    cheapest_savings_amount: number;
    cheapest_savings_percent: number;
  };
}

/**
 * Fetch automatic live retailer price comparison.
 * Initiated in the background when opening a product detail page.
 */
export async function getAutoLiveComparison(
  productId?: number,
  slug?: string,
  forceRefresh = false
): Promise<LiveComparisonResult | null> {
  const queryParams = new URLSearchParams();
  if (productId) queryParams.set('product_id', String(productId));
  if (slug) queryParams.set('slug', slug);
  if (forceRefresh) queryParams.set('force_refresh', 'true');

  const url = `${API_BASE_URL}/api/compare/auto?${queryParams.toString()}`;

  try {
    const res = await fetchWithTimeout(url, { method: 'GET' }, 12000);
    if (res.ok) {
      const data = (await res.json()) as RawLiveComparisonBackendResponse;
      return {
        productId: data.product_id,
        productTitle: data.product_title,
        brand: data.brand,
        targetVariant: data.target_variant,
        isCached: data.is_cached,
        freshnessSeconds: data.freshness_seconds,
        retrievalTimestamp: data.retrieval_timestamp,
        offers: data.offers.map((o) => ({
          retailerName: o.retailer_name,
          storeId: o.store_id,
          status: o.status as LiveRetailerOffer['status'],
          listedPrice: o.listed_price,
          mrp: o.mrp,
          discountPct: o.discount_pct,
          shippingFee: o.shipping_fee,
          isShippingDisclosed: o.is_shipping_disclosed,
          couponCode: o.coupon_code,
          couponDiscount: o.coupon_discount,
          totalCost: o.total_cost,
          stockStatus: o.stock_status,
          inStock: o.in_stock,
          purchaseUrl: o.purchase_url,
          variantDetected: o.variant_detected,
          matchClassification: (o.match_classification as LiveRetailerOffer['matchClassification']) || 'verified_match',
          isLowestListed: o.is_lowest_listed,
          isLowestTotal: o.is_lowest_total,
          // Honest provenance: never default a missing source to 'verified_live'.
          // Unknown provenance falls back to 'demo' so it is flagged, not trusted.
          sourceType: (o.source_type as LiveRetailerOffer['sourceType']) || 'demo',
          retrievedAt: o.retrieved_at,
          validationNotes: o.validation_notes,
        })),
        summary: {
          lowestListedPrice: data.summary.lowest_listed_price,
          lowestListedRetailer: data.summary.lowest_listed_retailer,
          lowestTotalCost: data.summary.lowest_total_cost,
          lowestTotalRetailer: data.summary.lowest_total_retailer,
          retailersChecked: data.summary.retailers_checked,
          retailersRetrieved: data.summary.retailers_retrieved,
          retailersUnavailable: data.summary.retailers_unavailable,
          retailersUnsupported: data.summary.retailers_unsupported,
          retailersRestricted: data.summary.retailers_restricted,
          cheapestSavingsAmount: data.summary.cheapest_savings_amount,
          cheapestSavingsPercent: data.summary.cheapest_savings_percent,
        },
      };
    }
  } catch {
    // Backend offline or timed out
  }

  // Graceful fallback to static product offers if backend bridge is offline
  if (slug) {
    const local = findProductBySlugOrId(PRODUCTS_DATA, slug);
    if (local && local.storeOffers && local.storeOffers.length > 0) {
      const fallbackOffers: LiveRetailerOffer[] = local.storeOffers.map((so) => ({
        retailerName: so.storeName,
        storeId: so.storeId,
        status: 'retrieved',
        listedPrice: so.price,
        mrp: so.originalPrice,
        discountPct: so.originalPrice && so.originalPrice > so.price ? Math.round(((so.originalPrice - so.price) / so.originalPrice) * 100) : 0,
        shippingFee: so.shippingFee,
        isShippingDisclosed: so.isShippingDisclosed ?? true,
        couponCode: so.couponCode,
        couponDiscount: so.couponDiscount || 0,
        totalCost: so.totalCost,
        stockStatus: so.stockStatus || (so.inStock ? 'In Stock' : 'Out of Stock'),
        inStock: so.inStock,
        purchaseUrl: so.purchaseUrl,
        variantDetected: local.quantity,
        matchClassification: 'verified_match',
        isLowestListed: !!so.isLowestPrice,
        isLowestTotal: !!so.isLowestPrice,
        sourceType: 'demo',
        retrievedAt: new Date().toISOString(),
        validationNotes: 'Offline demo fallback (FastAPI bridge unavailable)',
      }));

      const inStockOffers = fallbackOffers.filter((o) => o.listedPrice && o.listedPrice > 0);
      const lowestListed = inStockOffers.length > 0 ? inStockOffers.reduce((min, o) => ((o.listedPrice || 0) < (min.listedPrice || Infinity) ? o : min), inStockOffers[0]) : null;
      const offersWithTotal = inStockOffers.filter((o) => o.totalCost !== null && o.totalCost !== undefined);
      const lowestTotal = offersWithTotal.length > 0 ? offersWithTotal.reduce((min, o) => ((o.totalCost || 0) < (min.totalCost || Infinity) ? o : min), offersWithTotal[0]) : null;

      if (lowestListed) lowestListed.isLowestListed = true;
      if (lowestTotal) lowestTotal.isLowestTotal = true;

      return {
        productId: null,
        productTitle: local.name,
        brand: local.brand,
        targetVariant: local.quantity,
        isCached: true,
        freshnessSeconds: 0,
        retrievalTimestamp: new Date().toISOString(),
        offers: fallbackOffers,
        summary: {
          lowestListedPrice: lowestListed?.listedPrice || null,
          lowestListedRetailer: lowestListed?.retailerName || null,
          lowestTotalCost: lowestTotal?.totalCost || null,
          lowestTotalRetailer: lowestTotal?.retailerName || null,
          retailersChecked: fallbackOffers.length,
          retailersRetrieved: inStockOffers.length,
          retailersUnavailable: 0,
          retailersUnsupported: 0,
          retailersRestricted: 0,
          cheapestSavingsAmount: 0,
          cheapestSavingsPercent: 0,
        },
      };
    }
  }

  return null;
}

/**
 * Check price on a user-submitted product URL.
 */
export async function checkManualUrlPrice(url: string): Promise<ManualUrlCheckResult | null> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/compare/url`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      },
      12000
    );

    if (res.ok) {
      const data = (await res.json()) as {
        retailer_name: string;
        store_id: string;
        product_url: string;
        verification_status: string;
        listed_price?: number | null;
        mrp?: number | null;
        shipping_fee?: number | null;
        is_shipping_disclosed: boolean;
        total_cost?: number | null;
        in_stock: boolean;
        stock_status: string;
        product_name?: string | null;
        retrieved_at: string;
        validation_notes?: string | null;
      };

      return {
        retailerName: data.retailer_name,
        storeId: data.store_id,
        productUrl: data.product_url,
        verificationStatus: data.verification_status,
        listedPrice: data.listed_price,
        mrp: data.mrp,
        shippingFee: data.shipping_fee,
        isShippingDisclosed: data.is_shipping_disclosed,
        totalCost: data.total_cost,
        inStock: data.in_stock,
        stockStatus: data.stock_status,
        productName: data.product_name,
        retrievedAt: data.retrieved_at,
        validationNotes: data.validation_notes,
      };
    }
  } catch {
    // Failed or timeout
  }
  return null;
}

/* =========================================================================
 * PHASE 7: Authentication, Profile, Routines & Watchlist API
 * ========================================================================= */

const AUTH_STORAGE_KEY = 'pw_auth_token';

export function getAuthToken(): string | null {
  try {
    return localStorage.getItem(AUTH_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setAuthToken(token: string | null): void {
  try {
    if (token) {
      localStorage.setItem(AUTH_STORAGE_KEY, token);
    } else {
      localStorage.removeItem(AUTH_STORAGE_KEY);
    }
  } catch {
    // Ignore storage errors in restricted contexts
  }
}

function getAuthHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...extraHeaders,
  };
  const token = getAuthToken();
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  return headers;
}

// ---------------------------------------------------------------------------
// Auth Endpoints
// ---------------------------------------------------------------------------

export async function registerUser(name: string, email: string, password: string): Promise<{ success: boolean; user?: User; token?: string; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/auth/register`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, password }),
    });
    let data: any = {};
    try {
      data = await res.json();
    } catch {
      data = {};
    }
    if (!res.ok) {
      return { success: false, error: data.detail || `Registration failed (HTTP ${res.status})` };
    }
    if (data.token) {
      setAuthToken(data.token);
    }
    return { success: true, user: data.user, token: data.token };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Network error';
    if (message.includes('Failed to fetch') || message.includes('NetworkError') || message.includes('AbortError')) {
      return {
        success: false,
        error: `Could not connect to backend server at ${API_BASE_URL}. Please ensure the backend is running on port 8000.`,
      };
    }
    return { success: false, error: message };
  }
}

export async function loginUser(email: string, password: string): Promise<{ success: boolean; user?: User; token?: string; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });
    let data: any = {};
    try {
      data = await res.json();
    } catch {
      data = {};
    }
    if (!res.ok) {
      return { success: false, error: data.detail || 'Invalid email or password' };
    }
    if (data.token) {
      setAuthToken(data.token);
    }
    return { success: true, user: data.user, token: data.token };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : 'Network error';
    if (message.includes('Failed to fetch') || message.includes('NetworkError') || message.includes('AbortError')) {
      return {
        success: false,
        error: `Could not connect to backend server at ${API_BASE_URL}. Please ensure the backend is running on port 8000.`,
      };
    }
    return { success: false, error: message };
  }
}

export async function logoutUser(): Promise<void> {
  try {
    await fetchWithTimeout(`${API_BASE_URL}/api/auth/logout`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
  } catch {
    // Best effort logout
  } finally {
    setAuthToken(null);
  }
}

export async function getCurrentUser(): Promise<User | null> {
  const token = getAuthToken();
  if (!token) return null;

  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/auth/me`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      if (res.status === 401) {
        setAuthToken(null);
      }
      return null;
    }
    const data = await res.json();
    return data.user as User;
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Beauty Profile Endpoints
// ---------------------------------------------------------------------------

export async function getUserProfile(): Promise<{ profile: UserProfile | null; disclaimer?: string; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/profile`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      return { profile: null, error: 'Failed to load profile' };
    }
    const data = await res.json();
    return { profile: data.profile, disclaimer: data.disclaimer };
  } catch (err: unknown) {
    return { profile: null, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function updateUserProfile(profile: Partial<UserProfile>): Promise<{ success: boolean; profile?: UserProfile; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/profile`, {
      method: 'PUT',
      headers: getAuthHeaders(),
      body: JSON.stringify(profile),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to update profile' };
    }
    return { success: true, profile: data.profile };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function resetUserProfile(): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/profile`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to reset profile' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

// ---------------------------------------------------------------------------
// Skincare Routines Endpoints
// ---------------------------------------------------------------------------

export async function getUserRoutines(): Promise<{ routines: Routine[]; disclaimer?: string; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/routines`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      return { routines: [], error: 'Failed to load routines' };
    }
    const data = await res.json();
    return { routines: data.routines || [], disclaimer: data.disclaimer };
  } catch (err: unknown) {
    return { routines: [], error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function createUserRoutine(name: string, routine_type: string, description?: string): Promise<{ success: boolean; routine?: Routine; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/routines`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ name, routine_type, description }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to create routine' };
    }
    return { success: true, routine: data.routine };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function updateUserRoutine(id: number, updates: { name?: string; routine_type?: string; description?: string; is_active?: boolean }): Promise<{ success: boolean; routine?: Routine; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/routines/${id}`, {
      method: 'PUT',
      headers: getAuthHeaders(),
      body: JSON.stringify(updates),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to update routine' };
    }
    return { success: true, routine: data.routine };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function deleteUserRoutine(id: number): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/routines/${id}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return { success: false, error: data.detail || 'Failed to delete routine' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function addRoutineItem(routineId: number, item: {
  step_name: string;
  category?: string;
  product_id?: number | null;
  custom_product_name?: string | null;
  usage_instructions?: string | null;
  precautions?: string | null;
  key_ingredients?: string[];
}): Promise<{ success: boolean; item?: RoutineItem; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/routines/${routineId}/items`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(item),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to add item' };
    }
    return { success: true, item: data.item };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function reorderRoutineItems(routineId: number, itemIds: number[]): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/routines/${routineId}/reorder`, {
      method: 'PUT',
      headers: getAuthHeaders(),
      body: JSON.stringify({ item_order: itemIds }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to reorder items' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function deleteRoutineItem(routineId: number, itemId: number): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/routines/${routineId}/items/${itemId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return { success: false, error: data.detail || 'Failed to remove item' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

// ---------------------------------------------------------------------------
// Watchlist Endpoints
// ---------------------------------------------------------------------------

export interface BackendWatchlistItem {
  id: number;
  user_id: number;
  product_id: number;
  target_price?: number | null;
  notify_drop: boolean;
  notes?: string | null;
  created_at?: string;
  product?: Product | null;
}

export async function getUserWatchlist(): Promise<{ items: BackendWatchlistItem[]; count: number; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/watchlist`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      return { items: [], count: 0, error: 'Failed to load watchlist' };
    }
    const data = await res.json();
    return { items: data.items || [], count: data.count || 0 };
  } catch (err: unknown) {
    return { items: [], count: 0, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function addToWatchlist(productId: number, targetPrice?: number, notes?: string): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/watchlist`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ product_id: productId, target_price: targetPrice, notes }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to add to watchlist' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function removeFromWatchlist(productId: number): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/watchlist/${productId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      return { success: false, error: data.detail || 'Failed to remove from watchlist' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function syncWatchlist(items: { product_id: number; target_price?: number; notes?: string }[]): Promise<{ success: boolean; synced_count: number; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/watchlist/sync`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ items }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, synced_count: 0, error: data.detail || 'Failed to sync watchlist' };
    }
    return { success: true, synced_count: data.synced_count || 0 };
  } catch (err: unknown) {
    return { success: false, synced_count: 0, error: err instanceof Error ? err.message : 'Network error' };
  }
}

// ---------------------------------------------------------------------------
// Personalized Recommendations Endpoints
// ---------------------------------------------------------------------------

export async function getPersonalizedRecommendations(limit = 8): Promise<{
  recommendations: RecommendedProduct[];
  userProfile?: UserProfile;
  disclaimer?: string;
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/recommendations/personalized?limit=${limit}`, {
      method: 'GET',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      return { recommendations: [], error: 'Failed to load recommendations' };
    }
    const data = await res.json();
    return {
      recommendations: data.recommendations || [],
      userProfile: data.user_profile,
      disclaimer: data.disclaimer,
    };
  } catch (err: unknown) {
    return { recommendations: [], error: err instanceof Error ? err.message : 'Network error' };
  }
}


