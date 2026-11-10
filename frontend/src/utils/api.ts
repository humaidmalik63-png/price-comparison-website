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
  const envUrl = ((import.meta.env.VITE_API_BASE_URL || import.meta.env.VITE_API_URL) as string | undefined)?.trim();
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
  sourceType: 'verified_live' | 'cached' | 'demo' | 'unavailable';
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
          sourceType: (o.source_type as LiveRetailerOffer['sourceType']) || 'verified_live',
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

// =====================================================================
// Phase 8E: Beauty Intelligence Types & Endpoints
// =====================================================================

export interface IngredientInfo {
  name: string;
  function?: string;
  benefits: string[];
  concerns?: string[];
  compatible_with?: string[];
  avoid_with?: string[];
  concentration_range?: string | null;
  safety_rating?: string | null;
  source?: string;
  purpose?: string;
  safety?: string;
  description?: string;
}

export interface IngredientAnalysisResponse {
  product_id: number;
  product_name: string;
  ingredients: IngredientInfo[];
  key_actives?: string[];
  allergens_irritants?: string[];
  potential_conflicts?: string[];
  routine_order_recommendation?: string[];
  compatibility_notes?: string[];
  usage_instructions?: string | null;
  extraction_source?: string;
  source?: string;
  confidence_score?: number;
  routine_compatibility?: Record<string, string[]>;
  cached?: boolean;
  model_name?: string | null;
}

export interface SkinConcernMatch {
  product_id: number;
  product_name: string;
  brand: string;
  category: string;
  price: number;
  primary_concern?: string;
  suitability_score: number;
  reasons?: string[];
  explanation?: string;
  key_ingredients?: string[];
  matched_ingredients?: string[];
  cautions?: string[];
  source?: string;
}

export interface SkinConcernAnalysisResponse {
  skin_type?: string;
  concerns?: string[];
  matches: SkinConcernMatch[];
  general_advice?: string[];
  ingredients_to_look_for?: string[];
  ingredients_to_avoid?: string[];
  has_live_data?: boolean;
  source?: string;
  cached?: boolean;
  model_name?: string | null;
}

export interface AlternativeProduct {
  alternative_product_id?: number;
  product_id?: number;
  alternative_product_name?: string;
  product_name?: string;
  name?: string;
  alternative_brand?: string;
  brand?: string;
  alternative_price?: number;
  price?: number;
  original_product_price?: number;
  price_difference?: number;
  price_difference_pct?: number;
  price_verified?: boolean;
  savings_amount?: number;
  savings_percentage?: number;
  similarity_score: number;
  suitability_score: number;
  explanation?: string;
  recommendation_reason?: string;
  matched_attributes?: string[];
  differences?: string[];
  shared_key_ingredients?: string[];
  ingredient_comparison?: string[];
  tradeoffs?: string[];
  source?: string;
}

export interface AlternativeFinderResponse {
  original_product_id?: number;
  original_product_name?: string;
  alternatives: AlternativeProduct[];
  extraction_source?: string;
  source?: string;
  cached?: boolean;
  model_name?: string | null;
}

export interface RoutineStepRecommendation {
  step_number: number;
  step_name: string;
  category?: string;
  product_id?: number | null;
  product_name: string;
  brand?: string | null;
  price?: number | null;
  product_type?: string;
  key_ingredients?: string[];
  why_recommended?: string;
  instructions?: string;
  usage_instructions?: string;
  precautions?: string;
  frequency?: string;
  wait_time_minutes?: number | null;
  source?: string;
}

export interface RoutineRecommendationResponse {
  routine_type: string;
  skin_type: string;
  concerns: string[];
  steps: RoutineStepRecommendation[];
  total_estimated_cost?: number;
  routine_summary?: string;
  generation_source?: string;
  sunscreen_required?: boolean;
  source?: string;
  cached?: boolean;
  model_name?: string | null;
}

export interface BeautyIntelligenceUsageResponse {
  user_id?: number;
  requests_today?: number;
  daily_limit?: number;
  resets_at?: string;
  rate_limit?: {
    daily_quota?: number;
    used_today?: number;
    today_count?: number;
    remaining?: number;
    resets_in_hours?: number;
  };
}

export interface BeautyIntelligenceAdminStatsResponse {
  total_requests: number;
  successful_requests: number;
  cache_hits: number;
  fallbacks: number;
}

export async function analyzeProductIngredients(
  productId: number,
  forceRefresh = false
): Promise<{ success: boolean; data?: IngredientAnalysisResponse; error?: string }> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/beauty/analyze-ingredients/${productId}?force_refresh=${forceRefresh}`,
      { headers: getAuthHeaders() }
    );
    if (!res.ok) return { success: false, error: 'Failed to analyze ingredients' };
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function matchSkinConcerns(
  concernsOrPayload: string[] | { skin_type: string; concerns: string[]; budget_range?: [number, number] },
  skinType?: string,
  budgetRange?: [number, number]
): Promise<{ success: boolean; data?: SkinConcernAnalysisResponse; error?: string }> {
  try {
    let payload;
    if (Array.isArray(concernsOrPayload)) {
      payload = {
        concerns: concernsOrPayload,
        skin_type: skinType || 'all',
        budget_range: budgetRange,
      };
    } else {
      payload = concernsOrPayload;
    }
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/match-skin-concerns`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) return { success: false, error: 'Failed to match skin concerns' };
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function findProductAlternatives(
  productId: number,
  optionsOrMaxBudget?: { max_price_ratio?: number; min_similarity?: number } | number
): Promise<{ success: boolean; data?: AlternativeFinderResponse; error?: string }> {
  try {
    let url = `${API_BASE_URL}/api/beauty/find-alternatives/${productId}`;
    if (typeof optionsOrMaxBudget === 'number') {
      url += `?max_budget=${optionsOrMaxBudget}`;
    }
    const res = await fetchWithTimeout(url, { headers: getAuthHeaders() });
    if (!res.ok) return { success: false, error: 'Failed to find product alternatives' };
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function generateBeautyRoutine(
  routineType: 'AM' | 'PM' | string,
  options: {
    skin_type: string;
    skin_concerns: string[];
    existing_products?: number[];
    budget_range?: [number, number] | number[];
  }
): Promise<{ success: boolean; data?: RoutineRecommendationResponse; error?: string }> {
  try {
    const payload = {
      routine_type: routineType,
      skin_type: options.skin_type,
      skin_concerns: options.skin_concerns,
      existing_products: options.existing_products,
      budget_range: options.budget_range,
    };
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/generate-routine/${encodeURIComponent(routineType)}`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    if (!res.ok) return { success: false, error: 'Failed to generate beauty routine' };
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function getBeautyUsage(): Promise<{ success: boolean; data?: BeautyIntelligenceUsageResponse; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/usage`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) return { success: false, error: 'Failed to fetch usage' };
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function getBeautyAdminStats(days = 30): Promise<{ success: boolean; data?: BeautyIntelligenceAdminStatsResponse; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/admin/stats?days=${days}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) return { success: false, error: 'Failed to fetch admin stats' };
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function clearBeautyCache(): Promise<{ success: boolean; data?: { deleted_entries: number }; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/cache/clear`, {
      method: 'POST',
      headers: getAuthHeaders(),
    });
    if (!res.ok) return { success: false, error: 'Failed to clear cache' };
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

// =====================================================================
// Phase 9: Advanced Price Intelligence, History, Deals & Alerts
// =====================================================================

export interface PricePointDto {
  date: string;
  price: number;
  retailer_name: string;
  recorded_at: string;
  data_source: string;
  data_status: string;
}

export interface ProductPriceAnalyticsResponse {
  product_id: number;
  product_slug: string;
  product_title: string;
  window_days: number;
  points: PricePointDto[];
  lowest_recorded_price: number | null;
  highest_recorded_price: number | null;
  average_recorded_price: number | null;
  current_lowest_price: number | null;
  price_movement_pct: number | null;
  price_trend: 'downward' | 'upward' | 'stable' | 'volatile' | 'insufficient_data';
  observation_count: number;
  is_sufficient_history: boolean;
  currency: string;
  history_data_status: string;
  is_simulated: boolean;
  disclaimer: string;
}

export interface CouponValidation {
  code: string;
  is_valid: boolean;
  discount_amount: number;
  discount_pct: number;
  min_spend: number;
  description: string;
  rejection_reason?: string | null;
  expires_at?: string | null;
  is_expired: boolean;
  source: string;
  is_simulated?: boolean;
  disclaimer?: string;
}

export interface TotalPurchaseCostBreakdown {
  retailer_name: string;
  base_price: number;
  shipping_fee?: number | null;
  is_shipping_known: boolean;
  shipping_label: string;
  coupon_applied?: CouponValidation | null;
  final_payable_price: number;
  is_final_exact: boolean;
  payable_state_note: string;
  reference_mrp?: number | null;
  mrp_discount?: number;
  confirmed_savings: number;
  simulated_coupon_savings?: number;
  coupon_savings: number;
  total_potential_savings: number;
  genuine_verified_market_savings?: number;
  currency: string;
  data_status: string;
  calculated_at: string;
}

export interface DealFactorExplanation {
  factor_name: string;
  points_awarded: number;
  max_points: number;
  explanation: string;
}

export interface DealIntelligenceResponse {
  product_id: number;
  product_title: string;
  retailer_name: string;
  current_price: number;
  deal_score: number;
  deal_grade: string;
  deal_classification: string;
  is_simulated_deal: boolean;
  source_status: string;
  verified_deal_eligible: boolean;
  confidence_score: number;
  factors: DealFactorExplanation[];
  landed_cost_breakdown: TotalPurchaseCostBreakdown;
  summary_verdict: string;
}

export interface PriceTrackingItem {
  id: number;
  user_id: number;
  product_id: number;
  product_title: string;
  target_price: number;
  current_price: number;
  status: string;
  alert_trigger_type: string;
  note?: string | null;
  created_at: string;
  last_observed_price?: number | null;
  last_alert_at?: string | null;
}

export interface PriceAlertItem {
  id: number;
  user_id: number;
  product_id: number;
  product_title: string;
  alert_type: string;
  observed_price: number;
  previous_price?: number | null;
  target_price: number;
  message: string;
  created_at: string;
  is_read: boolean;
  is_demo: boolean;
}

/**
 * Fetch product price history across 7, 30, or 90 days.
 */
export async function fetchProductPriceHistory(
  slugOrId: string | number,
  windowDays = 30
): Promise<{ success: boolean; data?: ProductPriceAnalyticsResponse; error?: string }> {
  try {
    const res = await fetchWithTimeout(
      `${API_BASE_URL}/api/products/${slugOrId}/price-history?window_days=${windowDays}`
    );
    if (!res.ok) {
      return { success: false, error: 'Failed to retrieve price history.' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Fetch transparent deal score and intelligence.
 */
export async function fetchDealIntelligence(
  slugOrId: string | number,
  retailer?: string,
  couponCode?: string
): Promise<{ success: boolean; data?: DealIntelligenceResponse; error?: string }> {
  try {
    const params = new URLSearchParams();
    if (retailer) params.append('retailer', retailer);
    if (couponCode) params.append('coupon_code', couponCode);
    const query = params.toString() ? `?${params.toString()}` : '';

    const res = await fetchWithTimeout(`${API_BASE_URL}/api/products/${slugOrId}/deal-intelligence${query}`);
    if (!res.ok) {
      return { success: false, error: 'Failed to retrieve deal intelligence.' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Calculate landed purchase cost breakdown.
 */
export async function calculateLandedCost(
  slugOrId: string | number,
  payload: {
    retailer_name?: string;
    coupon_code?: string;
    custom_price?: number;
    custom_shipping?: number;
  }
): Promise<{ success: boolean; data?: TotalPurchaseCostBreakdown; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/products/${slugOrId}/total-cost`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to calculate total purchase cost.' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Fetch authenticated user's active tracked products.
 */
export async function fetchTrackedProducts(): Promise<{
  success: boolean;
  data?: PriceTrackingItem[];
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/price-tracking`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to load tracked products' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Add or update tracked product with target price.
 */
export async function addTrackedProduct(
  productId: number,
  targetPrice: number,
  note?: string,
  alertTriggerType = 'target_or_drop'
): Promise<{ success: boolean; message?: string; tracking_id?: number; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/price-tracking`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({
        product_id: productId,
        target_price: targetPrice,
        note,
        alert_trigger_type: alertTriggerType,
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Failed to save tracking rule.' };
    }
    return { success: true, message: data.message, tracking_id: data.tracking_id };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Remove tracked product.
 */
export async function removeTrackedProduct(
  productIdOrTrackingId: number
): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/price-tracking/${productIdOrTrackingId}`, {
      method: 'DELETE',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const data = await res.json();
      return { success: false, error: data.detail || 'Failed to remove tracked product' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Fetch authenticated user's price alerts.
 */
export async function fetchPriceAlerts(unreadOnly = false): Promise<{
  success: boolean;
  data?: PriceAlertItem[];
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/price-alerts?unread_only=${unreadOnly}`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to load price alerts' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Mark a price alert as read.
 */
export async function markPriceAlertRead(alertId: number): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/price-alerts/${alertId}/read`, {
      method: 'PUT',
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to mark alert as read' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

// ============================================================================
// Phase 10: Advanced Beauty Intelligence Types & API
// ============================================================================

export interface MasterIngredient {
  id: string;
  name: string;
  inci_name: string;
  category: string;
  description: string;
  what_it_does: string;
  why_used: string;
  benefits: string[];
  potential_irritations: string[];
  skin_suitability: string[];
  evidence_level: 'established' | 'moderate' | 'preliminary';
  optimal_ph: string;
  typical_concentration: string;
}

export interface IngredientInteractionWarning {
  ingredient_a: string;
  ingredient_b: string;
  severity: 'high_irritation_risk' | 'formulation_incompatibility' | 'moderate_caution' | 'synergistic_pair';
  title: string;
  explanation: string;
  scientific_rationale: string;
  recommendation: string;
  routine_separation_advice: string;
}

export interface IngredientCompatibilityResponse {
  analyzed_ingredients: Array<{
    id: string;
    name: string;
    category: string;
    evidence_level: string;
  }>;
  overall_status: 'compatible' | 'moderate' | 'caution';
  safety_score: number;
  summary: string;
  warnings: IngredientInteractionWarning[];
  synergies: IngredientInteractionWarning[];
  total_conflicts: number;
  total_synergies: number;
  medical_disclaimer: string;
}

export interface RoutineCheckerStepInput {
  step_name: string;
  product_name?: string;
  custom_product_name?: string;
  key_ingredients?: string[];
}

export interface RoutineConflictItem {
  routine: 'AM' | 'PM';
  type: string;
  severity: string;
  title: string;
  description: string;
  recommendation: string;
}

export interface ActiveOverloadItem {
  ingredient: string;
  count: number;
  risk: string;
  recommendation: string;
}

export interface RoutineCheckerResponse {
  overall_score: number;
  irritation_risk: 'Low' | 'Moderate' | 'High';
  safety_rating: string;
  total_conflicts: number;
  conflicts: RoutineConflictItem[];
  active_overloads: ActiveOverloadItem[];
  optimization_steps: string[];
  am_active_count: number;
  pm_active_count: number;
  sunscreen_compliant: boolean;
  medical_disclaimer: string;
}

export interface ClimateProfile {
  code: string;
  name: string;
  regions: string;
  temperature_range: string;
  humidity_level: string;
  skin_impact: string;
  cleanser_guidance: string;
  moisturizer_guidance: string;
  sunscreen_guidance: string;
  hydration_strategy: string;
  makeup_base_guidance: string;
  recommended_actives: string[];
  avoid_or_caution: string[];
}

export interface ClimateSkincareResponse {
  climate_profile: ClimateProfile;
  user_context: {
    skin_type: string;
    concerns: string[];
  };
  matched_catalog_products: Array<{
    id: number;
    title: string;
    brand: string;
    category: string;
    product_type: string;
    image_url: string;
    key_ingredients: string[];
    relevance_score: number;
    climate_rationale: string;
  }>;
  medical_disclaimer: string;
}

export interface FoundationCatalogMatch {
  product_id: number;
  product_title: string;
  brand: string;
  image_url: string;
  catalog_shade: string;
  recommended_shade_code: string;
  finish: string;
  confidence_score: number;
  match_label: string;
  oxidation_advisory: string;
  mac_equivalent: string;
  loreal_equivalent: string;
  fenty_equivalent: string;
}

export interface FoundationMatchResponse {
  user_profile: {
    skin_depth: string;
    undertone: string;
    coverage_preference?: string;
    finish_preference?: string;
    reference_shade_provided?: string;
  };
  shade_benchmark: {
    description: string;
    mac_shade: string;
    maybelline_shade: string;
    loreal_shade: string;
    fenty_shade: string;
  };
  matches: FoundationCatalogMatch[];
  undertone_guidance: string;
  disclaimer: string;
}

export interface AdvancedDiscoveryProduct {
  id: number;
  title: string;
  brand: string;
  category: string;
  brand_tier: string;
  price: number;
  reference_mrp: number;
  image_url: string;
  key_ingredients: string[];
  skin_type: string;
  finish?: string;
  match_score: number;
  matching_tags: string[];
  is_dupe_candidate: boolean;
}

export interface AdvancedDiscoveryResponse {
  total_results: number;
  products: AdvancedDiscoveryProduct[];
  active_filters: Record<string, unknown>;
}

/**
 * Fetch master active ingredients encyclopedia.
 */
export async function fetchMasterIngredients(): Promise<{
  success: boolean;
  data?: { total: number; ingredients: MasterIngredient[] };
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/ingredients`);
    if (!res.ok) {
      return { success: false, error: 'Failed to fetch ingredients' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Check pairwise ingredient compatibility and clash warnings.
 */
export async function checkIngredientCompatibility(ingredients: string[]): Promise<{
  success: boolean;
  data?: IngredientCompatibilityResponse;
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/ingredient-compatibility`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ingredients }),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to evaluate compatibility' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Analyze AM and PM routine safety, duplicate active overload, and SPF compliance.
 */
export async function checkRoutineSafety(
  amSteps: RoutineCheckerStepInput[],
  pmSteps: RoutineCheckerStepInput[],
  userSkinType = 'Combination'
): Promise<{
  success: boolean;
  data?: RoutineCheckerResponse;
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/routine-checker`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        am_steps: amSteps,
        pm_steps: pmSteps,
        user_skin_type: userSkinType,
      }),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to analyze routine safety' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Fetch Indian climate-tailored routine and matched catalog products.
 */
export async function fetchClimateRecommendations(
  climateCode: string,
  skinType = 'Combination',
  concerns: string[] = []
): Promise<{
  success: boolean;
  data?: ClimateSkincareResponse;
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/climate-recommendations`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        climate_code: climateCode,
        skin_type: skinType,
        concerns,
      }),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to fetch climate recommendations' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Match foundation depth, undertone, and oxidation profile.
 */
export async function matchFoundationShade(params: {
  skinDepth: string;
  undertone: string;
  coverage?: string;
  finish?: string;
  referenceBrand?: string;
  referenceShade?: string;
}): Promise<{
  success: boolean;
  data?: FoundationMatchResponse;
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/beauty/foundation-matcher`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        skin_depth: params.skinDepth,
        undertone: params.undertone,
        coverage: params.coverage || 'Medium',
        finish: params.finish || 'Matte',
        reference_brand: params.referenceBrand,
        reference_shade: params.referenceShade,
      }),
    });
    if (!res.ok) {
      return { success: false, error: 'Failed to match foundation shade' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/**
 * Advanced multi-criteria catalog search and filtering.
 */
export async function searchAdvancedDiscovery(
  filters: Record<string, string | number | undefined>
): Promise<{
  success: boolean;
  data?: AdvancedDiscoveryResponse;
  error?: string;
}> {
  try {
    const params = new URLSearchParams();
    Object.entries(filters).forEach(([key, val]) => {
      if (val !== undefined && val !== null && val !== '') {
        params.append(key, String(val));
      }
    });
    const url = `${API_BASE_URL}/api/beauty/advanced-discovery?${params.toString()}`;
    const res = await fetchWithTimeout(url);
    if (!res.ok) {
      return { success: false, error: 'Failed to perform discovery search' };
    }
    const data = await res.json();
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

/* =========================================================================
 * PHASE 11B: Hybrid Price Collection, Evidence & Admin Verification API
 * ========================================================================= */

export interface RetailerPolicyStatus {
  retailer_key: string;
  retailer_name: string;
  domain: string;
  store_id: number;
  policy_status: string;
  circuit_breaker_active: boolean;
  explanation: string;
  permitted_methods: string[];
}

export interface ProductRetailerSource {
  offer_id: number;
  retailer_name: string;
  store_id: number;
  product_url: string;
  current_price: number;
  original_price?: number | null;
  discount_pct: number;
  currency: string;
  variant_name: string;
  availability: string;
  verification_status: string;
  last_verified_at?: string | null;
  last_checked_at?: string | null;
  policy_status: string;
  requires_manual_verification: boolean;
}

export interface AdminVerificationItem {
  id: number;
  user_id: number;
  user_name?: string;
  user_email?: string;
  product_id: number;
  product_title?: string;
  product_brand?: string;
  retailer: string;
  product_url: string;
  user_submitted_price?: number;
  submitted_price?: number;
  submitted_mrp?: number;
  verified_price?: number;
  verified_mrp?: number;
  size_volume?: string;
  shade?: string;
  formulation?: string;
  notes?: string;
  status: string;
  verification_status?: string;
  submitted_at?: string;
  created_at?: string;
  evidence?: Array<{
    id: number;
    evidence_url: string;
    evidence_type: string;
    description?: string;
    uploaded_at: string;
  }>;
}

export async function getRetailerPolicies(): Promise<RetailerPolicyStatus[]> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/prices/retailer-status`);
    if (res.ok) {
      const data = await res.json();
      return data.retailers || [];
    }
  } catch {
    // fallback
  }
  return [];
}

export async function getProductRetailerSources(productId: number): Promise<ProductRetailerSource[]> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/prices/sources/${productId}`);
    if (res.ok) {
      const data = await res.json();
      return data.sources || [];
    }
  } catch {
    // fallback
  }
  return [];
}

export async function collectProductPrices(productId: number, forceRefresh = false): Promise<any> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/prices/collect/${productId}?force_refresh=${forceRefresh}`, {
      method: 'POST',
    });
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // fallback
  }
  return null;
}

export async function uploadEvidenceFile(file: File): Promise<{ success: boolean; evidenceUrl?: string; error?: string }> {
  try {
    const formData = new FormData();
    formData.append('file', file);
    const token = getAuthToken();
    const headers: Record<string, string> = {};
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const res = await fetch(`${API_BASE_URL}/api/verification/upload-evidence`, {
      method: 'POST',
      headers,
      body: formData,
    });

    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Upload failed' };
    }
    return { success: true, evidenceUrl: data.evidence_url };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function submitProductManualVerification(payload: {
  product_id: number;
  retailer: string;
  product_url: string;
  user_submitted_price?: number;
  size_volume?: string;
  shade?: string;
  formulation?: string;
  notes?: string;
  evidence_url?: string;
}): Promise<{ success: boolean; data?: any; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/verification/manual`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Submission failed' };
    }
    return { success: true, data };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function getAdminVerificationQueue(): Promise<{
  success: boolean;
  manualVerifications: AdminVerificationItem[];
  priceCorrections: AdminVerificationItem[];
  totalPending: number;
  error?: string;
}> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/admin/verifications`, {
      headers: getAuthHeaders(),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, manualVerifications: [], priceCorrections: [], totalPending: 0, error: data.detail || 'Failed to fetch queue' };
    }
    return {
      success: true,
      manualVerifications: data.pending_manual_verifications || [],
      priceCorrections: data.pending_price_corrections || [],
      totalPending: data.total_pending || 0,
    };
  } catch (err: unknown) {
    return { success: false, manualVerifications: [], priceCorrections: [], totalPending: 0, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function approveManualVerificationRequest(
  requestId: number,
  payload: { verified_price?: number; verified_mrp?: number; notes?: string }
): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/admin/verifications/${requestId}/approve`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Approval failed' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function rejectManualVerificationRequest(
  requestId: number,
  rejectionReason: string
): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/admin/verifications/${requestId}/reject`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ rejection_reason: rejectionReason }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Rejection failed' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function approvePriceCorrectionSubmission(
  submissionId: number,
  payload: { verified_price?: number; verified_mrp?: number; notes?: string }
): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/admin/price-corrections/${submissionId}/approve`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Approval failed' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}

export async function rejectPriceCorrectionSubmission(
  submissionId: number,
  rejectionReason: string
): Promise<{ success: boolean; error?: string }> {
  try {
    const res = await fetchWithTimeout(`${API_BASE_URL}/api/admin/price-corrections/${submissionId}/reject`, {
      method: 'POST',
      headers: getAuthHeaders(),
      body: JSON.stringify({ rejection_reason: rejectionReason }),
    });
    const data = await res.json();
    if (!res.ok) {
      return { success: false, error: data.detail || 'Rejection failed' };
    }
    return { success: true };
  } catch (err: unknown) {
    return { success: false, error: err instanceof Error ? err.message : 'Network error' };
  }
}




