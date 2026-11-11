import React, { useState, useEffect, useCallback } from 'react';
import { motion } from 'framer-motion';
import { Tag, AlertCircle, ArrowRight, Heart, ShieldCheck, TrendingUp, RefreshCw } from 'lucide-react';
import type { Product, RetailerOffer } from '../types';
import { getCatalogCheapestOffers } from '../lib/api/v2-client';
import { DealSectionSkeleton } from './LoadingSkeleton';

interface DealSectionProps {
  deals: Product[];
  onViewProduct: (product: Product) => void;
  onToggleWishlist: (id: string) => void;
  isWishlisted: (id: string) => boolean;
  // New props for backend integration
  useBackendData?: boolean;
}

export const DealSection: React.FC<DealSectionProps> = ({
  deals,
  onViewProduct,
  onToggleWishlist,
  isWishlisted,
  useBackendData = true,
}) => {
  // State for backend cheapest offers
  const [backendOffers, setBackendOffers] = useState<any[]>([]);
  const [isLoadingOffers, setIsLoadingOffers] = useState(false);
  const [offersError, setOffersError] = useState<string | null>(null);
  const [offersFreshness, setOffersFreshness] = useState<number | null>(null);
  const [dismissedStaleWarning, setDismissedStaleWarning] = useState(false);

  // Fetch cheapest offers from backend catalog
  const fetchCheapestOffers = useCallback(async () => {
    if (!useBackendData) return;

    setIsLoadingOffers(true);
    setOffersError(null);

    try {
      const result = await getCatalogCheapestOffers(50);
      setBackendOffers(result.offers || []);
      setOffersFreshness(Date.now());
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Failed to fetch live deals';
      setOffersError(errorMessage);
    } finally {
      setIsLoadingOffers(false);
    }
  }, [useBackendData]);

  // Fetch on mount
  useEffect(() => {
    fetchCheapestOffers();
  }, [fetchCheapestOffers]);

  // Calculate staleness
  const stalenessSeconds = offersFreshness ? Math.floor((Date.now() - offersFreshness) / 1000) : null;
  const isStale = stalenessSeconds !== null && stalenessSeconds > 72 * 3600; // 72 hours

  // Determine display offers - prefer backend if available
  const displayOffers = backendOffers.length > 0 ? backendOffers : deals;

  // Check if we have any offers to display
  const hasOffers = displayOffers.length > 0;

  // Show skeleton while loading backend data
  if (isLoadingOffers && backendOffers.length === 0) {
    return <DealSectionSkeleton />;
  }

  // Show error state if backend failed and no fallback
  if (offersError && backendOffers.length === 0 && deals.length === 0) {
    return (
      <section id="deals" className="py-20 bg-gradient-to-b from-ivory to-rose-50/40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="rounded-2xl p-6 text-center bg-rose-50 border border-rose-200 text-rose-800">
            <div className="flex flex-col items-center space-y-3">
              <div className="w-12 h-12 rounded-full bg-rose-100 flex items-center justify-center text-rose-600">
                <AlertCircle className="w-6 h-6" />
              </div>
              <div className="space-y-1">
                <h3 className="font-semibold text-base sm:text-lg">
                  Unable to Load Live Deals
                </h3>
                <p className="text-sm sm:text-base leading-relaxed">
                  {offersError}
                </p>
              </div>
              <button
                onClick={fetchCheapestOffers}
                className="px-4 py-2 rounded-xl text-sm font-bold bg-rose-600 hover:bg-rose-700 text-ivory transition-all shadow-xs flex items-center space-x-1.5"
              >
                <RefreshCw className="w-4 h-4" />
                <span>Retry Loading Deals</span>
              </button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  // Show empty state if no offers at all
  if (!hasOffers) {
    return (
      <section id="deals" className="py-20 bg-gradient-to-b from-ivory to-rose-50/40">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="rounded-2xl p-8 text-center bg-ivory-50 border border-rose-100">
            <div className="flex flex-col items-center space-y-4">
              <div className="w-16 h-16 rounded-full bg-ivory-100 flex items-center justify-center text-espresso-300">
                <AlertCircle className="w-8 h-8" />
              </div>
              <div className="space-y-1">
                <h3 className="font-semibold text-base sm:text-lg text-espresso-800">
                  No Deals Available
                </h3>
                <p className="text-sm sm:text-base text-espresso-600 leading-relaxed">
                  We couldn't find any active deals at the moment. Check back later for verified price drops.
                </p>
              </div>
              <button
                onClick={fetchCheapestOffers}
                className="px-4 py-2 rounded-xl bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold tracking-wide transition-all"
              >
                Refresh Deals
              </button>
            </div>
          </div>
        </div>
      </section>
    );
  }

  return (
    <section id="deals" className="py-20 bg-gradient-to-b from-ivory to-rose-50/40 relative">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        {/* Section Header */}
        <div className="flex flex-col md:flex-row md:items-end justify-between mb-8 gap-4">
          <div>
            <div className="inline-flex items-center space-x-1.5 text-xs font-bold uppercase tracking-wider text-rose-500 bg-rose-100/70 px-3 py-1 rounded-full mb-2">
              <Tag className="w-3.5 h-3.5" />
              <span>Verified Market Arbitrage</span>
            </div>
            <h2 className="font-editorial text-3xl sm:text-5xl font-bold text-espresso-800 tracking-tight">
              Today's Best Beauty Deals
            </h2>
            <p className="text-espresso-600 text-sm sm:text-base mt-2 max-w-xl">
              Curated verified price drops across India's leading beauty platforms. Discover authentic products marked down to their 30-day lows.
            </p>
          </div>

          {/* Academic Ethical Labeling Notice - Only show for demo data */}
          {displayOffers === deals && (
            <div className="flex items-center space-x-2 px-3 py-2 rounded-xl bg-champagne-100/80 border border-champagne-300/80 text-espresso-700 text-xs shrink-0 self-start md:self-auto">
              <AlertCircle className="w-4 h-4 text-champagne-600 shrink-0" />
              <span className="font-medium">
                <strong>DEMO DATA:</strong> Illustrative sample prices for academic comparison.
              </span>
            </div>
          )}

          {/* Backend Status Banner (Phase 16.2 integration indicator) */}
          <div className="mt-6 p-3 rounded-xl bg-gradient-to-r from-sage-50 to-rose-50 border border-sage-200 flex flex-col sm:flex-row items-center justify-between gap-3">
            <div className="flex items-center space-x-2">
              <ShieldCheck className="w-5 h-5 text-sage-600" />
              <span className="text-xs font-semibold text-sage-800">
                Phase 16.2 Backend Integration:
              </span>
              <span className="text-xs text-espresso-600">
                Product matching engine, price intelligence pipeline, and MCP adapters active.
              </span>
            </div>
            <div className="flex items-center space-x-2">
              <TrendingUp className="w-4 h-4 text-rose-500" />
              <span className="text-xs text-rose-700">
                Real-time verified offers from PriceInIndia & Open Beauty Facts APIs.
              </span>
            </div>
          </div>
        </div>

        {/* Stale Price Warning */}
        {!dismissedStaleWarning && isStale && stalenessSeconds && (
          <div className="rounded-xl p-4 border flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-amber-50 border-amber-200 text-amber-800">
            <div className="flex items-center space-x-2">
              <AlertCircle className="w-5 h-5 text-amber-600" />
              <div className="flex flex-col">
                <span className="text-xs font-semibold uppercase tracking-wider">
                  Price Data May Be Stale
                </span>
                <span className="text-sm font-mono">
                  Last updated: {stalenessSeconds > 24 * 3600 ? `${Math.floor(stalenessSeconds / (24 * 3600))}h ago` : `${Math.floor(stalenessSeconds / 3600)}h ${Math.floor((stalenessSeconds % 3600) / 60)}m ago`}
                </span>
              </div>
            </div>

            <div className="flex items-center space-x-2">
              <button
                onClick={fetchCheapestOffers}
                className="px-3 py-1.5 rounded-lg text-xs font-bold bg-amber-600 hover:bg-amber-700 text-ivory transition-all flex items-center space-x-1"
              >
                <RefreshCw className="w-3.5 h-3.5" />
                <span>Refresh Prices</span>
              </button>
              <button
                onClick={() => setDismissedStaleWarning(true)}
                className="px-3 py-1.5 rounded-lg text-xs font-medium text-espresso-500 hover:text-espresso-700 transition-colors"
              >
                Dismiss
              </button>
            </div>
          </div>
        )}

        {/* Backend Error Inline */}
        {offersError && backendOffers.length === 0 && deals.length > 0 && (
          <div className="mb-6">
            <div className="rounded-xl p-4 bg-rose-50 border border-rose-200 text-rose-800">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center space-x-2">
                  <AlertCircle className="w-5 h-5 text-rose-600 shrink-0" />
                  <div>
                    <p className="font-medium text-sm">Failed to load live deals</p>
                    <p className="text-xs text-rose-600 font-mono">{offersError}</p>
                  </div>
                </div>
                <button
                  onClick={fetchCheapestOffers}
                  className="px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-700 text-ivory transition-all flex items-center space-x-1 shrink-0"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                  <span>Retry Live Deals</span>
                </button>
              </div>
            </div>
          </div>
        )}

        {/* Deals Grid */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {displayOffers.slice(0, 6).map((deal, idx) => {
            // Handle both static Product and backend offer formats
            const isBackendOffer = deal.product_id !== undefined || deal.id?.toString().startsWith('api-');
            const savings = deal.originalPrice ? deal.originalPrice - (deal.price || deal.lowest_price || 0) : 0;
            const savingsPct = deal.originalPrice ? Math.round((savings / deal.originalPrice) * 100) : 0;
            const wish = isWishlisted(deal.id || deal.product_id?.toString() || '');
            const productName = deal.name || deal.title || 'Unknown Product';
            const brand = deal.brand || 'Unknown Brand';
            const image = deal.image || deal.image_url || 'https://images.unsplash.com/photo-1598440947619-2c35fc9aa908?auto=format&fit=crop&w=800&q=80';
            const quantity = deal.quantity || deal.specs?.size || deal.size || '50 ml';
            const subcategory = deal.subcategory || deal.category || 'Beauty';
            const costPerUnit = deal.costPerUnit || deal.unit_price || deal.unitPrice;
            // Normalize price field for backend offers (backend uses lowest_price, frontend expects price)
            const priceValue = deal.price || deal.lowest_price || deal.lowest_price || 0;
            const originalPriceValue = deal.originalPrice || deal.original_price;

            // Helper to get store offers with proper typing
            const storeOffers: RetailerOffer[] | undefined = deal.storeOffers;
            // Check if this is demo data (backend provides is_demo)
            const isDemoOffer = deal.isDemo === true || deal.sourceType === 'demo' || deal.source_type === 'demo';

            return (
              <motion.div
                key={deal.id || deal.product_id || idx}
                initial={{ opacity: 0, y: 20 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ duration: 0.5, delay: idx * 0.08 }}
                className="rounded-2xl bg-white border border-rose-200/90 shadow-soft-lift hover:shadow-luxury-card transition-all duration-300 p-5 flex flex-col justify-between relative overflow-hidden group"
              >
                {/* Decorative background glow */}
                <div className="absolute -top-12 -right-12 w-32 h-32 rounded-full bg-rose-100/50 blur-2xl pointer-events-none group-hover:scale-125 transition-transform" />

                {/* Top: Image, Title, Deal Tag */}
                <div>
                  <div className="flex items-start gap-4">
                    <div className="w-24 h-24 rounded-xl overflow-hidden bg-ivory shrink-0 border border-rose-100">
                      <img
                        src={image}
                        alt={productName}
                        className="w-full h-full object-cover group-hover:scale-105 transition-transform"
                      />
                    </div>

                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between">
                        <span className="text-xs uppercase font-bold text-rose-500 tracking-wider">
                          {brand}
                        </span>
                        {savingsPct > 0 && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500 text-ivory">
                            {savingsPct}% OFF
                          </span>
                        )}
                      </div>

                      <h3
                        onClick={() => onViewProduct(deal as any)}
                        className="font-editorial text-lg font-bold text-espresso-800 line-clamp-2 mt-1 hover:text-rose-600 cursor-pointer transition-colors"
                      >
                        {productName}
                        {isBackendOffer && isDemoOffer && (
                          <span className="text-[10px] text-orange-600 ml-2 bg-orange-100 px-2 py-0.5 rounded-full font-medium">
                            Demo Data
                          </span>
                        )}
                        {isBackendOffer && (deal.sourceType === 'provider_observed' || deal.source_type === 'provider_observed') && (
                          <span className="text-[10px] text-emerald-700 ml-2 bg-emerald-100 px-2 py-0.5 rounded-full font-medium">
                            Live Price
                          </span>
                        )}
                      </h3>

                      <div className="flex flex-wrap items-center gap-1.5 mt-0.5">
                        <span className="text-xs text-espresso-400 block">
                          {quantity} • {subcategory}
                        </span>
                        {costPerUnit && (
                          <span className="text-[10px] text-sage-800 bg-sage-50 px-1.5 py-0.5 rounded font-medium border border-sage-200">
                            {costPerUnit}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Multi-Store Arbitrage Comparison Bar - only for static products with storeOffers */}
                  {!isBackendOffer && storeOffers && storeOffers.length > 0 && (
                    <div className="mt-4 pt-3 border-t border-rose-100">
                      <div className="flex items-center justify-between mb-2">
                        <span className="text-[11px] font-semibold text-espresso-500 uppercase tracking-wider block">
                          Live Store Comparison:
                        </span>
                        {deal.dealExpiresAt && (
                          <span className="text-[10px] text-espresso-400">
                            Expires: {deal.dealExpiresAt}
                          </span>
                        )}
                      </div>
                      <div className="space-y-1.5">
                        {storeOffers.map((offer: RetailerOffer) => {
                          const isVerified = offer.sourceType === 'verified_live' || offer.sourceType === 'manually_curated';
                          const isProviderObserved = offer.sourceType === 'partner_feed' || offer.sourceType === 'cached';
                          const isLivePrice = offer.sourceType === 'provider_observed';
                          const isDemo = offer.sourceType === 'demo' || offer.sourceType === 'unavailable';

                          return (
                            <div
                              key={offer.storeId}
                              className={`flex items-center justify-between text-xs px-2.5 py-1.5 rounded-lg transition-colors ${
                                offer.isLowestPrice
                                  ? 'bg-rose-50 border border-rose-300/80 font-bold text-rose-800'
                                  : 'bg-ivory/60 text-espresso-600'
                              }`}
                            >
                              <div className="flex items-center space-x-1.5">
                                <span>{offer.storeName}</span>
                                {offer.isLowestPrice && (
                                  <span className="text-[10px] bg-rose-500 text-ivory px-1.5 py-0.2 rounded-full uppercase tracking-tighter">
                                    Best Price
                                  </span>
                                )}
                                {offer.couponCode && (
                                  <span className="text-[9px] bg-champagne-100 text-champagne-800 px-1 py-0.2 rounded font-medium">
                                    Code: {offer.couponCode}
                                  </span>
                                )}
                                {/* Provenance Badge - never auto-label LIVE_VERIFIED */}
                                {isVerified && (
                                  <span className="text-[9px] bg-sage-50 text-sage-800 px-1.5 py-0.5 rounded font-medium border border-sage-200">
                                    Verified
                                  </span>
                                )}
                                {isProviderObserved && (
                                  <span className="text-[9px] bg-champagne-50 text-champagne-800 px-1.5 py-0.5 rounded font-medium border border-champagne-200">
                                    Provider Observed
                                  </span>
                                )}
                                {isLivePrice && (
                                  <span className="text-[9px] bg-emerald-50 text-emerald-800 px-1.5 py-0.5 rounded font-medium border border-emerald-200">
                                    Live Price
                                  </span>
                                )}
                                {isDemo && (
                                  <span className="text-[9px] bg-orange-50 text-orange-800 px-1.5 py-0.5 rounded font-medium border border-orange-200">
                                    Demo Data
                                  </span>
                                )}
                              </div>
                              <span className="font-sans font-bold">
                                ₹{offer.price.toLocaleString('en-IN')}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}
                </div>

                {/* Footer Pricing & CTA */}
                <div className="mt-5 pt-3 border-t border-rose-100/80 flex items-center justify-between">
                  <div>
                    <span className="text-[11px] text-espresso-400 block">Lowest Deal</span>
                    <div className="flex items-baseline space-x-2">
                      <span className="text-2xl font-bold font-sans text-espresso-900">
                        ₹{priceValue.toLocaleString('en-IN')}
                      </span>
                      {originalPriceValue && (
                        <span className="text-xs text-espresso-400 line-through">
                          ₹{originalPriceValue.toLocaleString('en-IN')}
                        </span>
                      )}
                    </div>
                  </div>

                  <div className="flex items-center space-x-2">
                    <button
                      onClick={() => onToggleWishlist(deal.id)}
                      aria-label={wish ? "Remove from wishlist" : "Add to wishlist"}
                      className={`p-2 rounded-xl border transition-colors ${
                        wish
                          ? 'bg-rose-50 border-rose-300 text-rose-500'
                          : 'bg-ivory border-rose-200 text-espresso-400 hover:text-rose-500'
                      }`}
                    >
                      <Heart className={`w-4 h-4 ${wish ? 'fill-rose-500 text-rose-500' : ''}`} />
                    </button>
                    <button
                      onClick={() => onViewProduct(deal)}
                      className="px-4 py-2 rounded-xl bg-espresso-700 hover:bg-espresso-800 text-ivory text-xs font-semibold tracking-wide transition-all shadow-xs flex items-center space-x-1"
                    >
                      <span>Compare</span>
                      <ArrowRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </motion.div>
            );
          })}
        </div>
      </div>
    </section>
  );
};

export default DealSection;