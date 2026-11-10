export type ProductCategory = 'skincare' | 'makeup' | 'haircare' | 'bodycare';

export type SkincareSubcategory = 
  | 'Face Wash'
  | 'Moisturiser'
  | 'Sunscreen'
  | 'Serums'
  | 'Toners'
  | 'Face Masks'
  | 'Eye Care'
  | 'Lip Care'
  | 'Makeup Remover';

export type MakeupSubcategory = 
  | 'Foundation'
  | 'Concealer'
  | 'Lipstick'
  | 'Blush'
  | 'Mascara'
  | 'Eyeliner'
  | 'Highlighter'
  | 'Makeup Palettes';

export type OtherSubcategory = 'Haircare' | 'Body Care';

export type Subcategory = SkincareSubcategory | MakeupSubcategory | OtherSubcategory;

export interface RetailerOffer {
  storeId: string;
  storeName: 'Nykaa' | 'Tira' | 'Purplle' | 'Amazon India' | 'Myntra';
  storeLogo?: string;
  price: number;
  originalPrice?: number;
  shippingFee: number | null; // 0 for free, null if unknown/not disclosed
  isShippingDisclosed?: boolean; // false if retailer doesn't disclose shipping beforehand
  couponDiscount?: number; // discount in INR, only set when the coupon has
  // been validated against a recorded source - never an invented code
  couponCode?: string; // coupon code, only present when validated
  couponTerms?: string; // terms for the validated coupon
  totalCost?: number | null; // price + shipping - coupon (when shipping is known)
  deliveryDays: string;
  inStock: boolean;
  stockStatus?: 'In Stock' | 'Limited Stock' | 'Out of Stock';
  purchaseUrl: string;
  isLowestPrice?: boolean;
  lastUpdated?: string;
  sourceType?: 'verified_live' | 'partner_feed' | 'cached' | 'manually_curated' | 'demo' | 'unavailable';
  dealExpiresAt?: string; // ISO date string or human readable
  matchClassification?: 'verified_match' | 'possible_match' | 'incompatible_mismatch';
  // Phase 14 Stage D: link provenance. A purchase link is only shown when it
  // has been verified to resolve to this exact product.
  linkStatus?: 'verified' | 'demo_not_verified' | 'unavailable';
  linkCheckedAt?: string;
}

export interface ReviewItem {
  id: string;
  author: string;
  platform: 'Nykaa' | 'Tira' | 'Purplle' | 'Amazon India' | 'Myntra';
  rating: number; // out of 5
  ratingScale?: number; // default 5
  date: string;
  verifiedBuyer: boolean;
  title: string;
  comment: string;
  skinType?: string; // e.g. "Oily", "Dry", "Combination", "Sensitive", "Normal"
  sourceUrl?: string; // Link to actual retailer product / review page
  dataStatus?: 'demo' | 'verified_retailer' | 'manually_curated';
  lastVerified?: string;
}

export interface PlatformRatingSummary {
  platform: 'Nykaa' | 'Tira' | 'Purplle' | 'Amazon India' | 'Myntra';
  averageRating: number | null; // null if unavailable
  reviewCount: number | null; // null if unavailable
  ratingScale: number; // usually 5
  dataSource: 'Retailer Feed (Demo)' | 'Authorized API (Pending)' | 'Curated' | 'Data Unavailable';
  lastUpdated?: string;
  productUrl?: string;
  isAvailable: boolean;
}

export interface WeightedReviewScore {
  score: number | null;
  totalReviews: number;
  platformsIncluded: number;
  calculationMethod: string;
  explanation: string;
}

export interface KeyActiveDetail {
  name: string;
  concentration?: string;
  benefit: string;
}

export interface ProductUsageDetails {
  routine: 'AM' | 'PM' | 'AM & PM';
  stepNumber: number;
  stepName?: string;
  frequency?: string;
  instructions: string;
  precautions?: string;
  patchTestRecommendation?: string;
  sunSafetyWarning?: string;
  keyActives?: KeyActiveDetail[];
  sourceReference?: string;
}

export interface PriceTrendPoint {
  date: string; // "YYYY-MM-DD" or "DD MMM YYYY"
  price: number;
  store: string;
  variant?: string; // variant, size, or shade
}

export interface Product {
  id: string;
  dbId?: number; // Corresponding SQLite database product id
  slug?: string; // Canonical URL-friendly slug (e.g. 'watermelon-cooling-sunscreen-spf-50')
  name: string;
  brand: string;
  brandTier: 'Luxury' | 'Premium' | 'Affordable' | 'Drugstore';
  category: ProductCategory;
  subcategory: Subcategory;
  quantity: string;
  dataSource?: string;
  dataStatus?: 'catalog_verified' | 'partially_verified' | 'demo' | 'verified_retailer';
  evidenceType?: string;
  officialUrl?: string; // the manufacturer's own product page, recorded
  // in the curated catalogue specifications (a brand page, not a retailer offer)
  price: number; // Lowest current price in INR
  originalPrice?: number; // MRP
  rating?: number;
  reviewCount?: number;
  image: string;
  // Phase 14 Stage C: image provenance. 'placeholder' means no authentic
  // packaging photograph has been verified for this product yet.
  imageStatus?: 'verified_exact' | 'permission_review' | 'unverified' | 'placeholder';
  imageSourceName?: string;
  imageSourceUrl?: string;
  imageLastChecked?: string;
  description: string;
  skinType?: string; // For skincare (e.g. "Oily, Combination, Acne-Prone")
  finish?: string; // For makeup (e.g. "Matte, Luminous, Dewy")
  keyIngredients: string[];
  howToUse: ProductUsageDetails;
  isTrending?: boolean;
  isBestDeal?: boolean;
  dealScore?: number; // Real deal intelligence score (0-100)
  productType?: string; // e.g. "Gel", "Serum", "Cream", "Liquid", "Bullet"
  dealTag?: string; // e.g. "28% OFF", "Lowest in 30 Days"
  costPerUnit?: string; // e.g. "₹9.00 / ml", "₹21.00 / ml"
  verifiedMatchLabel?: string; // "Lowest among available verified offers"
  dealExpiresAt?: string;
  storeOffers: RetailerOffer[];
  reviews?: ReviewItem[];
  platformRatings?: PlatformRatingSummary[];
  priceHistory?: PriceTrendPoint[];
  dupeId?: string; // Link to an affordable alternative
}

export interface TrackedProduct {
  id: string;
  productId: string;
  targetPrice: number;
  currency: 'INR' | 'USD';
  isTracking: boolean;
  addedAt: string;
  lastNotifiedAt?: string;
  note?: string;
}

export interface PriceAlertNotification {
  id: string;
  trackingId: string;
  productId: string;
  productName: string;
  productImage: string;
  alertType: 'target_reached' | 'price_drop';
  currentPrice: number;
  previousPrice?: number;
  targetPrice: number;
  storeName: string;
  message: string;
  timestamp: string;
  isRead: boolean;
  deliveryStatus: 'in_app_delivered' | 'email_unconfigured';
}

export interface DupeComparison {
  id: string;
  originalProductId: string;
  alternativeProductId: string;
  originalProduct: {
    name: string;
    brand: string;
    price: number;
    quantity: string;
    costPerUnit: string;
    image: string;
  };
  alternativeProduct: {
    name: string;
    brand: string;
    price: number;
    quantity: string;
    costPerUnit: string;
    image: string;
  };
  priceDifference: number;
  percentageSaved: number;
  similarityScore: number; // e.g. 92%
  similarityExplanation: string;
  keySharedIngredients: string[];
}

export interface RoutineStep {
  step: number;
  title: string;
  time: 'AM' | 'PM' | 'Both';
  category: Subcategory;
  purpose: string;
  tip: string;
  iconName: string;
}

export interface FilterOptions {
  searchQuery: string;
  category: ProductCategory | 'all';
  subcategory: Subcategory | 'all';
  brand: string | 'all';
  skinType: string | 'all';
  productType: string | 'all';
  minBudget?: number;
  maxBudget?: number;
  sortBy: 'featured' | 'price-asc' | 'price-desc' | 'name-asc' | 'rating' | 'best-deal';
  priceRange: [number, number];
}

/* =========================================================================
 * PHASE 7: User, Profile, Routine & Personalization Types
 * ========================================================================= */

export interface User {
  id: number;
  email: string;
  name: string;
  is_active: boolean;
  created_at: string;
  updated_at?: string;
}

export interface MakeupPreferences {
  finish_preference?: 'matte' | 'dewy' | 'natural' | 'any';
  coverage_preference?: 'light' | 'medium' | 'full' | 'any';
  undertone?: 'warm' | 'cool' | 'neutral' | 'olive' | 'unsure';
  lipstick_finish?: 'matte' | 'liquid' | 'creamy' | 'gloss' | 'tint';
}

export interface UserProfile {
  user_id: number;
  skin_type: 'oily' | 'dry' | 'combination' | 'normal' | 'sensitive' | 'unsure';
  skin_concerns: string[];
  preferred_brands: string[];
  preferred_categories: string[];
  budget_min: number;
  budget_max: number;
  makeup_preferences: MakeupPreferences;
  ingredient_avoidances: string[];
  created_at?: string;
  updated_at?: string;
}

export interface RoutineItem {
  id: number;
  routine_id: number;
  step_number: number;
  step_name: string;
  category?: string;
  product_id?: number | null;
  custom_product_name?: string | null;
  usage_instructions?: string | null;
  precautions?: string | null;
  key_ingredients?: string[];
  created_at?: string;
  product?: Product | null;
}

export interface RoutineConflict {
  conflict_type: string;
  description: string;
  severity: string;
  recommendation: string;
}

export interface Routine {
  id: number;
  user_id: number;
  name: string;
  routine_type: 'AM' | 'PM' | 'weekly' | 'custom';
  description?: string;
  is_active: boolean;
  created_at?: string;
  items: RoutineItem[];
  conflicts?: RoutineConflict[];
}

export interface RecommendedProduct {
  id: number;
  name: string;
  brand: string;
  category: string;
  price: number;
  original_price?: number;
  rating?: number;
  image?: string;
  recommendation_score: number;
  matched_reasons: string[];
  suitable_skin_types: string[];
  addressed_concerns: string[];
}
