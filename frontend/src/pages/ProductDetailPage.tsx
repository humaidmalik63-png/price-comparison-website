import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  Heart,
  Bell,
  ArrowLeft,
  Share2,
  CheckCircle2,
  Sparkles,
  Star,
  AlertTriangle,
  ShieldCheck,
  TrendingUp,
} from 'lucide-react';

import { PRODUCTS_DATA } from '../data/products';
import { ALTERNATIVES_DATA } from '../data/alternatives';
import { findProductBySlugOrId, generateProductSlug } from '../utils/slug';
import { PriceHistoryChart } from '../components/PriceHistoryChart';
import { PriceTrackingModal } from '../components/PriceTrackingModal';
import { BeautyUsageGuide } from '../components/BeautyUsageGuide';
import { ReviewIntelligenceHub } from '../components/ReviewIntelligenceHub';
import { LiveRetailerPriceComparison } from '../components/LiveRetailerPriceComparison';
import { useWishlist } from '../hooks/useWishlist';
import { usePriceTracker } from '../hooks/usePriceTracker';
import { useBackendProducts } from '../hooks/useBackendProducts';

export const ProductDetailPage: React.FC = () => {
  const { slugOrId } = useParams<{ slugOrId: string }>();
  const navigate = useNavigate();

  // Wishlist and Price Tracking Hooks
  const { isWishlisted, toggleWishlist } = useWishlist();
  const { isTracking, getTrackedRecord, startTracking, stopTracking } = usePriceTracker();

  // Backend Products Hook for Phase 16.2 integration
  const {
    products: backendProducts,
    isLoading: isBackendLoading,
    error: backendError,
    isBackendAvailable,
    selectProduct: fetchBackendProduct,
    backendFreshness,
    refreshProductOffers,
  } = useBackendProducts();

  // Track backend data freshness for stale price warnings
  const [productFreshness, setProductFreshness] = useState<number | null>(null);

  // Modal State
  const [isTrackerModalOpen, setIsTrackerModalOpen] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);

  // Lookup product (try backend first, then static data)
  const product = useMemo(() => {
    // First try to find in backend products
    const backendMatch = backendProducts.find((p) => p.slug === slugOrId || p.id === slugOrId);
    if (backendMatch) return backendMatch;
    // Fall back to static products data
    return findProductBySlugOrId(PRODUCTS_DATA, slugOrId || '');
  }, [slugOrId, backendProducts]);

  // Fetch fresh product data from backend when page loads or slug changes
  useEffect(() => {
    if (slugOrId) {
      fetchBackendProduct(slugOrId);
    }
  }, [slugOrId, fetchBackendProduct]);

  // Track backend freshness
  useEffect(() => {
    if (backendFreshness !== null) {
      setProductFreshness(backendFreshness);
    }
  }, [backendFreshness]);

  // Also update freshness when we manually refresh
  const handleRefreshBackend = useCallback(async () => {
    if (slugOrId) {
      await refreshProductOffers(slugOrId);
      // The hook will update backendFreshness
    }
  }, [slugOrId, refreshProductOffers]);

  // Refresh product data from backend when page mounts
  // This must be BEFORE the early return for 404
  useEffect(() => {
    // Only refresh if we have a valid product that's not an API-only product
    if (!slugOrId || !product) return;
    if (product.id.startsWith('api-')) return;

    // Fetch fresh offers from backend for existing static products
    const refreshBackendData = async () => {
      try {
        // Import here to avoid circular dependencies
        const { getProductOffers } = await import('../lib/api/v2-client');
        // Try to parse numeric ID from product id or slug
        const numericId = parseInt(slugOrId.replace('prod-', ''), 10);
        if (!isNaN(numericId)) {
          const result = await getProductOffers(numericId);
          if (result.offers.length > 0) {
            console.log('[ProductDetailPage] Fresh data loaded from backend');
          }
        }
      } catch (err) {
        console.log('[ProductDetailPage] Using fallback static data:', err);
      }
    };

    refreshBackendData();
  }, [slugOrId, product]);

  // Polished 404 Not Found State
  if (!product) {
    return (
      <div className="min-h-[70vh] flex flex-col items-center justify-center p-6 text-center max-w-xl mx-auto space-y-4">
        <div className="w-16 h-16 rounded-full bg-rose-100 flex items-center justify-center text-rose-500 mb-2">
          <AlertTriangle className="w-8 h-8" />
        </div>
        <span className="text-xs font-bold uppercase tracking-widest text-rose-600">
          404 • Product Not Found
        </span>
        <h1 className="font-editorial text-3xl sm:text-4xl font-bold text-espresso-900">
          We Couldn't Find That Product
        </h1>
        <p className="text-sm text-espresso-600 leading-relaxed">
          The requested product route <code>"{slugOrId}"</code> may have been moved, renamed, or is currently unavailable in our curated Indian beauty catalog.
        </p>
        <div className="pt-4 flex flex-col sm:flex-row items-center gap-3">
          <button
            onClick={() => navigate('/')}
            className="px-6 py-3 rounded-xl bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold tracking-wide transition-all shadow-xs flex items-center space-x-2"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Return to Product Discovery</span>
          </button>
        </div>
      </div>
    );
  }

  // Linked alternative dupe
  const matchedDupe = ALTERNATIVES_DATA.find(
    (d) => d.originalProductId === product.id || d.alternativeProductId === product.id
  );

  const isTracked = isTracking(product.id);
  const trackingRecord = getTrackedRecord(product.id);
  const wishlisted = isWishlisted(product.id);

  const handleShare = () => {
    const canonicalSlug = product.slug || generateProductSlug(product);
    const fullUrl = `${window.location.origin}/product/${canonicalSlug}`;
    navigator.clipboard.writeText(fullUrl).then(() => {
      setCopiedUrl(true);
      setTimeout(() => setCopiedUrl(false), 2500);
    });
  };

  return (
    <div className="min-h-screen bg-ivory text-espresso-900 pb-20">
      {/* Breadcrumbs & Navigation Bar */}
      <div className="border-b border-rose-100 bg-white/60 backdrop-blur-xs sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex items-center justify-between">
          {/* Breadcrumbs */}
          <nav className="flex items-center space-x-2 text-xs text-espresso-500 overflow-x-auto">
            <Link to="/" className="hover:text-rose-600 transition-colors shrink-0">
              Discovery
            </Link>
            <span>/</span>
            <span className="capitalize shrink-0">{product.category}</span>
            <span>/</span>
            <span className="shrink-0">{product.subcategory}</span>
            <span>/</span>
            <span className="font-semibold text-espresso-800 truncate max-w-[200px]">
              {product.name}
            </span>
          </nav>

          {/* Quick Back Action */}
          <button
            onClick={() => navigate('/')}
            className="px-3 py-1.5 rounded-lg bg-ivory-100 hover:bg-ivory-200 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-colors shrink-0"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Back to Catalog</span>
          </button>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 sm:pt-10 space-y-10">
        {/* Main Product Hero Grid */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* Left Column: Image & Size */}
          <div className="lg:col-span-5 space-y-4">
            <div className="aspect-square w-full rounded-3xl overflow-hidden bg-white border border-rose-200/90 shadow-luxury-card relative">
              <img
                src={product.image}
                alt={product.name}
                className="w-full h-full object-cover object-center"
              />

              {/* Floating Badges */}
              <div className="absolute top-4 left-4 flex flex-col gap-1.5">
                <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-espresso-900 text-champagne-300 shadow-xs">
                  {product.brandTier}
                </span>
                {product.dealTag && (
                  <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-500 text-ivory shadow-xs">
                    {product.dealTag}
                  </span>
                )}
              </div>

              {/* Demo Data Label */}
              <div className="absolute bottom-4 left-4">
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-white/90 backdrop-blur-xs text-espresso-700 border border-rose-100">
                  DEMO DATA • INDIAN RETAILERS
                </span>
              </div>
            </div>

            {/* Size & Variant Notice */}
            <div className="bg-white p-3.5 rounded-2xl border border-rose-100 flex items-center justify-between text-xs text-espresso-600">
              <span>Standard Package Size:</span>
              <strong className="text-espresso-900 font-sans">{product.quantity}</strong>
            </div>

            <div className="text-[11px] text-sage-800 bg-sage-50 border border-sage-200/80 p-3 rounded-2xl flex items-center space-x-2">
              <CheckCircle2 className="w-4 h-4 text-sage-600 shrink-0" />
              <span>Exact size ({product.quantity}) and authentic formulation verified for comparison.</span>
            </div>
          </div>

          {/* Right Column: Meta, Pricing, & Action CTAs */}
          <div className="lg:col-span-7 space-y-6">
            <div>
              <div className="flex items-center space-x-2 text-xs font-bold uppercase tracking-wider text-rose-500 mb-1">
                <span>{product.brand}</span>
                <span>•</span>
                <span>{product.subcategory}</span>
              </div>

              <h1 className="font-editorial text-3xl sm:text-4xl font-bold text-espresso-950 leading-tight">
                {product.name}
              </h1>

              {/* Rating */}
              {product.rating && (
                <div className="flex items-center space-x-2 mt-2">
                  <div className="flex text-champagne-500">
                    <Star className="w-4 h-4 fill-champagne-500" />
                    <span className="text-xs font-bold text-espresso-800 ml-1.5">{product.rating}</span>
                  </div>
                  <span className="text-xs text-espresso-400">
                    ({product.reviewCount?.toLocaleString('en-IN')} verified customer reviews)
                  </span>
                </div>
              )}
            </div>

            {/* Price Box */}
            <div className="bg-white p-5 rounded-3xl border border-rose-200/80 shadow-soft-lift space-y-3">
              <span className="text-xs font-bold uppercase tracking-wider text-espresso-400 block">
                Lowest Available Offer
              </span>

              <div className="flex items-baseline space-x-3">
                {/* Show backend loading state */}
                {isBackendLoading && (
                  <div className="flex items-center space-x-2">
                    <div className="w-4 h-4 border-2 border-rose-500 border-t-transparent rounded-full animate-spin" />
                    <span className="text-xs text-rose-600">Loading from backend...</span>
                  </div>
                )}
                {backendError && !isBackendAvailable && (
                  <div className="flex items-center space-x-2">
                    <ShieldCheck className="w-4 h-4 text-amber-600" />
                    <span className="text-xs text-amber-700">Using cached data (backend unavailable)</span>
                  </div>
                )}
                {isBackendAvailable && backendFreshness !== null && (
                  <div className="flex items-center space-x-2">
                    <TrendingUp className="w-4 h-4 text-sage-600" />
                    <span className="text-xs text-sage-700">Live data available</span>
                  </div>
                )}
                <span className="text-3xl sm:text-4xl font-sans font-extrabold text-espresso-950">
                  ₹{product.price.toLocaleString('en-IN')}
                </span>

                {product.originalPrice && product.originalPrice > product.price && (
                  <span className="text-base font-sans text-espresso-400 line-through">
                    ₹{product.originalPrice.toLocaleString('en-IN')}
                  </span>
                )}

                {product.originalPrice && product.originalPrice > product.price && (
                  <span className="text-xs font-bold text-rose-600 bg-rose-50 px-2.5 py-1 rounded-full border border-rose-200">
                    Save ₹{(product.originalPrice - product.price).toLocaleString('en-IN')} (
                    {Math.round(((product.originalPrice - product.price) / product.originalPrice) * 100)}% OFF)
                  </span>
                )}
              </div>

              {/* Action Buttons: Wishlist, Price Alert, Share */}
              <div className="pt-2 flex flex-wrap gap-2.5">
                <button
                  type="button"
                  onClick={() => toggleWishlist(product.id)}
                  className={`px-4 py-2.5 rounded-xl text-xs font-bold flex items-center space-x-2 transition-all border ${wishlisted
                      ? 'bg-rose-50 text-rose-600 border-rose-300'
                      : 'bg-white hover:bg-rose-50/60 text-espresso-700 border-rose-200'
                    }`}
                >
                  <Heart className={`w-4 h-4 ${wishlisted ? 'fill-rose-500 text-rose-500' : ''}`} />
                  <span>{wishlisted ? 'Saved in Wishlist' : 'Add to Wishlist'}</span>
                </button>

                <button
                  type="button"
                  onClick={() => setIsTrackerModalOpen(true)}
                  className={`px-4 py-2.5 rounded-xl text-xs font-bold flex items-center space-x-2 transition-all border ${isTracked
                      ? 'bg-sage-50 text-sage-800 border-sage-300'
                      : 'bg-espresso-800 hover:bg-espresso-950 text-ivory border-espresso-900'
                    }`}
                >
                  <Bell className="w-4 h-4" />
                  <span>
                    {isTracked ? `Tracking (₹${trackingRecord?.targetPrice})` : 'Set Price-Drop Alert'}
                  </span>
                </button>

                <button
                  type="button"
                  onClick={handleShare}
                  className="px-3.5 py-2.5 rounded-xl bg-white hover:bg-ivory-100 text-espresso-600 border border-rose-200 text-xs font-semibold flex items-center space-x-1.5 transition-colors"
                  title="Copy shareable link"
                >
                  <Share2 className="w-3.5 h-3.5" />
                  <span>{copiedUrl ? 'Copied URL!' : 'Share'}</span>
                </button>
              </div>
            </div>

            {/* Description */}
            <p className="text-sm text-espresso-700 leading-relaxed">
              {product.description}
            </p>

            {/* Suitability Pills */}
            <div className="flex flex-wrap gap-2 text-xs">
              {product.skinType && (
                <div className="px-3 py-1.5 rounded-xl bg-sage-50 border border-sage-200 text-sage-800">
                  <strong>Skin Suitability:</strong> {product.skinType}
                </div>
              )}
              {product.finish && (
                <div className="px-3 py-1.5 rounded-xl bg-rose-50 border border-rose-200 text-rose-800">
                  <strong>Finish / Texture:</strong> {product.finish}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Phase 6: Automatic Multi-Retailer Live Price Comparison (No Manual Button) */}
        <LiveRetailerPriceComparison
          productId={product.id.startsWith('prod-') ? undefined : Number(product.id)}
          slug={product.slug || slugOrId || ''}
          productName={product.name}
          brand={product.brand}
          targetVariant={product.quantity}
          fallbackOffers={product.storeOffers}
          isBackendAvailable={isBackendAvailable}
          backendFreshness={productFreshness || backendFreshness}
          onRefreshBackend={handleRefreshBackend}
        />

        {/* Price History & Trends Section */}
        <section className="space-y-3">
          <PriceHistoryChart
            priceHistory={product.priceHistory}
            currentPrice={product.price}
            originalPrice={product.originalPrice}
            targetPrice={trackingRecord?.targetPrice}
            productName={product.name}
          />
        </section>

        {/* Beauty Product Usage Guide & Ingredient Intelligence */}
        <BeautyUsageGuide product={product} />

        {/* Cheapest Alternative Recommendation */}
        {matchedDupe && (
          <section className="pt-2">
            <div className="rounded-3xl bg-gradient-to-r from-champagne-100/70 to-rose-100/70 border border-champagne-300 p-6 flex flex-col sm:flex-row items-center justify-between gap-5">
              <div className="flex items-center space-x-3.5">
                <Sparkles className="w-7 h-7 text-champagne-600 shrink-0" />
                <div>
                  <span className="text-xs font-bold uppercase tracking-wider text-espresso-800 block">
                    Cheapest Alternative Available
                  </span>
                  <p className="text-xs text-espresso-800 mt-0.5">
                    Save ₹{matchedDupe.priceDifference.toLocaleString('en-IN')} ({matchedDupe.percentageSaved}% savings) with {matchedDupe.similarityScore}% formula similarity.
                  </p>
                  <p className="text-[11px] text-espresso-600 italic mt-0.5">
                    {matchedDupe.similarityExplanation}
                  </p>
                </div>
              </div>

              <button
                type="button"
                onClick={() => {
                  const altId = product.id === matchedDupe.originalProductId
                    ? matchedDupe.alternativeProductId
                    : matchedDupe.originalProductId;
                  const altProd = PRODUCTS_DATA.find((p) => p.id === altId);
                  if (altProd) {
                    navigate(`/product/${altProd.slug || altProd.id}`);
                  }
                }}
                className="px-5 py-2.5 rounded-xl bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold tracking-wide transition-colors shrink-0"
              >
                View Alternative ↗
              </button>
            </div>
          </section>
        )}

        {/* Phase 4: Reviews Intelligence & Multi-Platform Comparison Hub */}
        <ReviewIntelligenceHub product={product} />
      </div>

      {/* Target Price Tracking Modal */}
      <PriceTrackingModal
        isOpen={isTrackerModalOpen}
        onClose={() => setIsTrackerModalOpen(false)}
        product={product}
        existingRecord={trackingRecord}
        onSaveTarget={(target, note) => startTracking(product.id, target, note)}
        onRemoveTracking={() => stopTracking(product.id)}
      />
    </div>
  );
};
