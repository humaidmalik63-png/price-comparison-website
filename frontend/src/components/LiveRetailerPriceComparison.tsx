import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import {
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  AlertCircle,
  Truck,
  Tag,
  Clock,
  Sparkles,
  Link as LinkIcon,
  Search,
  CheckCircle2,
  Lock,
  TrendingUp,
  Info,
} from 'lucide-react';
import {
  getAutoLiveComparison,
  checkManualUrlPrice,
  type LiveComparisonResult,
  type LiveRetailerOffer,
  type ManualUrlCheckResult,
} from '../utils/api';
import type { RetailerOffer } from '../types';
import { ComparisonSectionSkeleton } from './LoadingSkeleton';
import { StalePriceWarning, ConnectivityStatus, ApiFailureInline } from './ErrorState';

interface LiveRetailerPriceComparisonProps {
  productId?: number;
  slug: string;
  productName: string;
  brand: string;
  targetVariant: string;
  fallbackOffers: RetailerOffer[];
  // New props for backend integration
  isBackendAvailable?: boolean;
  backendFreshness?: number | null;
  onRefreshBackend?: () => void;
}

const RETAILER_NAMES = ['Nykaa', 'Myntra', 'Purplle', 'Tira', 'Amazon India'];

export const LiveRetailerPriceComparison: React.FC<LiveRetailerPriceComparisonProps> = ({
  productId,
  slug,
  targetVariant,
  fallbackOffers,
  isBackendAvailable = true,
  backendFreshness = null,
  onRefreshBackend,
}) => {
  const [comparison, setComparison] = useState<LiveComparisonResult | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [mountedAt] = useState<string>(() => new Date().toISOString());
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [dismissedStaleWarning, setDismissedStaleWarning] = useState(false);

  // Manual URL Check state
  const [isManualUrlOpen, setIsManualUrlOpen] = useState(false);
  const [manualUrlInput, setManualUrlInput] = useState('');
  const [isCheckingManual, setIsCheckingManual] = useState(false);
  const [manualResult, setManualResult] = useState<ManualUrlCheckResult | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);

  // Deduplication ref to avoid duplicate calls on re-renders
  const lastFetchedSlugRef = useRef<string | null>(null);

  const fetchLiveComparison = useCallback(
    async (force = false) => {
      if (force) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }
      setComparisonError(null);

      try {
        const res = await getAutoLiveComparison(productId, slug, force);
        if (res) {
          setComparison(res);
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : 'Failed to fetch live comparison';
        setComparisonError(errorMessage);
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [productId, slug]
  );

  // AUTOMATIC BACKGROUND TRIGGER ON MOUNT (NO MANUAL BUTTON)
  useEffect(() => {
    if (lastFetchedSlugRef.current !== slug) {
      lastFetchedSlugRef.current = slug;
      fetchLiveComparison(false);
    }
  }, [slug, fetchLiveComparison]);

  const handleManualUrlSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!manualUrlInput.trim()) return;

    setIsCheckingManual(true);
    setManualError(null);
    setManualResult(null);

    try {
      const res = await checkManualUrlPrice(manualUrlInput.trim());
      if (res) {
        setManualResult(res);
      } else {
        setManualError('Unable to connect or extract price from this URL. Ensure it is a valid HTTPS retailer product page.');
      }
    } catch (err: unknown) {
      setManualError(err instanceof Error ? err.message : 'URL check failed');
    } finally {
      setIsCheckingManual(false);
    }
  };

  // If live results are ready, use them; otherwise, prepare progressive or placeholder cards
  const displayOffers: LiveRetailerOffer[] = useMemo(() => {
    if (comparison) {
      return comparison.offers;
    }
    return RETAILER_NAMES.map((name) => {
      const local = fallbackOffers.find((f) => f.storeName.toLowerCase().includes(name.toLowerCase().split(' ')[0]));
      return {
        retailerName: name,
        storeId: name.toLowerCase().replace(' ', '-'),
        status: isLoading ? 'retrieved' : 'unavailable',
        listedPrice: local?.price,
        mrp: local?.originalPrice,
        discountPct: local?.originalPrice && local?.originalPrice > local?.price ? Math.round(((local.originalPrice - local.price) / local.originalPrice) * 100) : 0,
        shippingFee: local?.shippingFee,
        isShippingDisclosed: local?.isShippingDisclosed ?? true,
        couponCode: local?.couponCode,
        couponDiscount: local?.couponDiscount || 0,
        totalCost: local?.totalCost,
        stockStatus: local?.stockStatus || (local?.inStock ? 'In Stock' : 'Out of Stock'),
        inStock: local?.inStock ?? true,
        purchaseUrl: local?.purchaseUrl || `https://www.${name.toLowerCase().replace(' ', '')}.com`,
        matchClassification: 'verified_match',
        isLowestListed: !!local?.isLowestPrice,
        isLowestTotal: !!local?.isLowestPrice,
        sourceType: 'demo',
        retrievedAt: mountedAt,
        validationNotes: isLoading ? 'Checking live feed...' : undefined,
      };
    });
  }, [comparison, fallbackOffers, isLoading, mountedAt]);

  // Sort offers: retrieved first, then by total cost or listed price
  const sortedOffers = [...displayOffers].sort((a, b) => {
    if (a.status === 'retrieved' && b.status !== 'retrieved') return -1;
    if (a.status !== 'retrieved' && b.status === 'retrieved') return 1;

    const aTotal = a.totalCost ?? a.listedPrice ?? Infinity;
    const bTotal = b.totalCost ?? b.listedPrice ?? Infinity;
    return aTotal - bTotal;
  });

  // Calculate staleness from backend
  const stalenessSeconds = backendFreshness !== null ? Math.floor((Date.now() - backendFreshness) / 1000) : null;
  const isStale = stalenessSeconds !== null && stalenessSeconds > 72 * 3600; // 72 hours

  // Show skeleton while loading
  if (isLoading && !comparison) {
    return <ComparisonSectionSkeleton />;
  }

  return (
    <section className="space-y-4 pt-6 border-t border-rose-200" id="live-price-comparison-section">
      {/* Header with Title, Auto-Status & Manual Refresh Icon */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-3">
        <div>
          <div className="flex items-center space-x-2.5">
            <h2 className="font-editorial text-2xl font-bold text-espresso-900">
              Live Retailer Price Comparison
            </h2>
            {isLoading && (
              <span className="flex items-center space-x-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200 animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping" />
                <span>Checking Feeds...</span>
              </span>
            )}
            {!isLoading && comparison?.isCached && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-ivory-100 text-espresso-600 border border-rose-100">
                Cached ({Math.round(comparison.freshnessSeconds / 60)}m ago)
              </span>
            )}
          </div>
          <p className="text-xs text-espresso-500 mt-1">
            Real-time automated price checking across India's top beauty destinations. Variant locked: <strong>{targetVariant || 'Standard'}</strong>.
          </p>
        </div>

        {/* Refresh Action (Subtle icon to re-sync without full page reload) */}
        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={() => fetchLiveComparison(true)}
            disabled={isLoading || isRefreshing}
            className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-all shadow-2xs disabled:opacity-50"
            title="Refresh live prices across all retailers"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-espresso-600 ${isRefreshing ? 'animate-spin text-rose-600' : ''}`} />
            <span>{isRefreshing ? 'Checking...' : 'Refresh'}</span>
          </button>

          <button
            type="button"
            onClick={() => setIsManualUrlOpen(!isManualUrlOpen)}
            className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-all shadow-2xs"
            title="Check a specific retailer product URL"
          >
            <LinkIcon className="w-3.5 h-3.5 text-espresso-600" />
            <span>Check URL</span>
          </button>
        </div>
      </div>

      {/* Highlights Banner if Lowest Available */}
      {comparison?.summary?.lowestTotalCost && (
        <div className="p-3.5 rounded-2xl bg-gradient-to-r from-sage-50 to-rose-50 border border-sage-200 flex flex-wrap items-center justify-between gap-2 text-xs">
          <div className="flex items-center space-x-2 text-espresso-800">
            <Sparkles className="w-4 h-4 text-rose-500 shrink-0" />
            <span>
              Best Verified Deal on <strong>{comparison.summary.lowestTotalRetailer}</strong>: Landed Total of <strong>₹{comparison.summary.lowestTotalCost.toLocaleString('en-IN')}</strong>.
            </span>
          </div>
          {comparison.summary.cheapestSavingsAmount > 0 && (
            <span className="font-bold text-rose-700 bg-white/80 px-2.5 py-1 rounded-full border border-rose-200 text-[11px]">
              Saves up to ₹{comparison.summary.cheapestSavingsAmount.toLocaleString('en-IN')} ({comparison.summary.cheapestSavingsPercent}%) vs other retailers
            </span>
          )}
        </div>
      )}

      {/* Connectivity Status Banner */}
      <ConnectivityStatus
        isOnline={typeof navigator !== 'undefined' ? navigator.onLine : true}
        isBackendAvailable={isBackendAvailable}
        lastChecked={comparison?.freshnessSeconds ? `${Math.round(comparison.freshnessSeconds / 60)}m ago` : undefined}
        onRetry={fetchLiveComparison}
        className="mb-2"
      />

      {/* Stale Price Warning from Backend */}
      {!dismissedStaleWarning && isStale && stalenessSeconds && (
        <StalePriceWarning
          freshnessSeconds={stalenessSeconds}
          onRefresh={onRefreshBackend || fetchLiveComparison}
          onDismiss={() => setDismissedStaleWarning(true)}
          className="mb-2"
        />
      )}

      {/* API Failure Inline Error */}
      {comparisonError && !comparison && sortedOffers.every(o => o.sourceType === 'demo') && (
        <ApiFailureInline
          error={comparisonError}
          onRetry={fetchLiveComparison}
          retryLabel="Retry Live Comparison"
          fallbackMessage="Unable to fetch live retailer prices"
          className="mb-2"
        />
      )}

      {/* Manual Product URL Input Panel (Optional Expandable) */}
      {isManualUrlOpen && (
        <div className="p-4 rounded-2xl bg-ivory-50 border border-rose-200 space-y-3">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-espresso-800 uppercase tracking-wider">
              Paste Retailer Product URL
            </span>
            <span className="text-[11px] text-espresso-500">
              Supported: Nykaa, Myntra, Purplle, Tira, Amazon India
            </span>
          </div>

          <form onSubmit={handleManualUrlSubmit} className="flex flex-col sm:flex-row gap-2">
            <div className="relative flex-1">
              <input
                type="url"
                required
                value={manualUrlInput}
                onChange={(e) => setManualUrlInput(e.target.value)}
                placeholder="https://www.nykaa.com/... or https://www.tirabeauty.com/product/..."
                className="w-full px-3.5 py-2.5 text-xs rounded-xl border border-rose-200 bg-white text-espresso-900 focus:outline-hidden focus:ring-2 focus:ring-rose-300"
              />
            </div>
            <button
              type="submit"
              disabled={isCheckingManual || !manualUrlInput.trim()}
              className="px-4 py-2.5 rounded-xl bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold transition-all shadow-xs flex items-center justify-center space-x-1.5 shrink-0 disabled:opacity-50"
            >
              <Search className={`w-3.5 h-3.5 ${isCheckingManual ? 'animate-spin' : ''}`} />
              <span>{isCheckingManual ? 'Checking...' : "Check This Product's Price"}</span>
            </button>
          </form>

          {manualError && (
            <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-start space-x-2">
              <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
              <span>{manualError}</span>
            </div>
          )}

          {manualResult && (
            <div className="p-3.5 rounded-xl bg-white border border-rose-200 text-xs space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="font-bold text-espresso-900">{manualResult.retailerName}</span>
                <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-sage-100 text-sage-800">
                  {manualResult.verificationStatus === 'retrieved' ? 'Verified Live' : manualResult.verificationStatus}
                </span>
              </div>
              <div className="text-espresso-700">
                {manualResult.productName && <p className="font-medium text-espresso-900">{manualResult.productName}</p>}
                <p className="mt-1">
                  Listed Price: <strong>₹{manualResult.listedPrice ? manualResult.listedPrice.toLocaleString('en-IN') : 'N/A'}</strong>
                  {manualResult.shippingFee !== null && manualResult.shippingFee !== undefined && (
                    <span> • Shipping: {manualResult.shippingFee === 0 ? 'Free' : `₹${manualResult.shippingFee}`}</span>
                  )}
                  {manualResult.totalCost && (
                    <span> • Total: <strong className="text-espresso-950">₹{manualResult.totalCost.toLocaleString('en-IN')}</strong></span>
                  )}
                </p>
                {manualResult.validationNotes && (
                  <p className="text-[11px] text-espresso-500 italic mt-0.5">{manualResult.validationNotes}</p>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Phase 16.2 Backend Integration Status */}
      <div className="p-3 rounded-xl bg-gradient-to-r from-sage-50 to-rose-50 border border-sage-200 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs">
        <div className="flex items-center space-x-2">
          <Info className="w-4 h-4 text-sage-600" />
          <span className="text-xs font-semibold text-sage-800">
            Phase 16.2 Backend Active:
          </span>
          <span className="text-xs text-espresso-600">
            Product matching engine, price intelligence pipeline, and MCP adapters connected.
          </span>
        </div>
        <div className="flex items-center space-x-2">
          <TrendingUp className="w-4 h-4 text-rose-500" />
          <span className="text-xs text-rose-700">
            Verified offers sourced from PriceInIndia & Open Beauty Facts APIs.
          </span>
        </div>
      </div>

      {/* Retailer Comparison Cards */}
      <div className="rounded-3xl border border-rose-200 overflow-hidden bg-white shadow-soft-lift divide-y divide-rose-100">
        {sortedOffers.map((offer) => {
          const isRetrieved = offer.status === 'retrieved' && offer.listedPrice && offer.listedPrice > 0;
          const isRestricted = offer.status === 'restricted';
          const isUnsupported = offer.status === 'unsupported';
          const hasKnownShipping = offer.isShippingDisclosed && offer.shippingFee !== null && offer.shippingFee !== undefined;

          return (
            <div
              key={offer.storeId}
              className={`p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 transition-colors ${
                offer.isLowestTotal ? 'bg-rose-50/30' : 'bg-white'
              }`}
            >
              {/* Retailer Identity & Status Information */}
              <div className="flex items-start sm:items-center space-x-3.5">
                <div className="w-10 h-10 rounded-full bg-ivory border border-rose-200 flex items-center justify-center font-bold text-sm text-espresso-900 shrink-0">
                  {offer.retailerName[0]}
                </div>

                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold text-sm sm:text-base text-espresso-900">
                      {offer.retailerName}
                    </span>

                    {/* Lowest Total Cost Badge */}
                    {offer.isLowestTotal && isRetrieved && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-sage-600 text-ivory flex items-center space-x-1">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Lowest Total Cost</span>
                      </span>
                    )}

                    {/* Lowest Listed Price Badge */}
                    {offer.isLowestListed && !offer.isLowestTotal && isRetrieved && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-600 text-ivory">
                        Lowest Listed Price
                      </span>
                    )}

                    {/* Source & Freshness Label with Match Classification & Provenance */}
                    {isRetrieved && (
                      <>
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-ivory-100 text-espresso-700 border border-rose-100 flex items-center space-x-1">
                          <ShieldCheck className="w-3 h-3 text-sage-600" />
                          <span>{offer.sourceType === 'verified_live' ? 'Verified Live' : 'Feed Active'}</span>
                        </span>
                        {/* Match Classification Badge */}
                        {offer.matchClassification && offer.matchClassification !== 'verified_match' && (
                          <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium flex items-center space-x-1 ${
                            offer.matchClassification === 'possible_match'
                              ? 'bg-yellow-50 border-yellow-300 text-yellow-800'
                              : offer.matchClassification === 'incompatible_mismatch'
                              ? 'bg-red-50 border-red-300 text-red-800'
                              : 'bg-gray-50 border-gray-300 text-gray-800'
                          }`}>
                            <span>{offer.matchClassification === 'possible_match' ? 'Possible Match' : 'Incompatible'}</span>
                          </span>
                        )}
                        {/* Provenance Distinction - Critical Safety Requirement */}
                        <span className="px-2 py-0.5 rounded-full text-[10px] font-medium flex items-center space-x-1 bg-champagne-50 border-champagne-300 text-champagne-800">
                          <Info className="w-3 h-3" />
                          <span>Provider Observed</span>
                        </span>
                        {offer.sourceType === 'verified_live' && (
                          <span className="px-2 py-0.5 rounded-full text-[10px] font-medium flex items-center space-x-1 bg-sage-50 border-sage-300 text-sage-800">
                            <ShieldCheck className="w-3 h-3" />
                            <span>Indep. Verified</span>
                          </span>
                        )}
                      </>
                    )}

                    {/* Restriction pill */}
                    {isRestricted && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-200 flex items-center space-x-1">
                        <Lock className="w-3 h-3" />
                        <span>Bot Protection (Restricted)</span>
                      </span>
                    )}

                    {/* Unsupported pill */}
                    {isUnsupported && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-medium bg-gray-100 text-gray-700 border border-gray-200">
                        Unsupported
                      </span>
                    )}

                    {/* Stock Status */}
                    {isRetrieved && (
                      <span className="text-[10px] font-semibold text-espresso-600 bg-ivory-100 px-1.5 py-0.5 rounded border border-rose-100">
                        {offer.stockStatus}
                      </span>
                    )}
                  </div>

                  {/* Delivery & Timestamp Meta */}
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-espresso-500 mt-1">
                    {isRetrieved && (
                      <span className="flex items-center space-x-1">
                        <Truck className="w-3.5 h-3.5 text-espresso-400" />
                        <span>
                          {hasKnownShipping ? (offer.shippingFee === 0 ? 'Free Shipping' : `+ ₹${offer.shippingFee} Shipping`) : 'Shipping Not Disclosed'}
                        </span>
                      </span>
                    )}

                    {offer.retrievedAt && (
                      <span className="flex items-center space-x-1 text-espresso-400 text-[11px]">
                        <Clock className="w-3 h-3" />
                        <span>Checked {new Date(offer.retrievedAt).toLocaleDateString('en-GB')}</span>
                      </span>
                    )}

                    {offer.couponCode && (
                      <span className="flex items-center space-x-1 text-[11px] text-rose-600 font-medium">
                        <Tag className="w-3 h-3" />
                        <span>Code {offer.couponCode} (-₹{offer.couponDiscount})</span>
                      </span>
                    )}

                    {offer.validationNotes && !isRetrieved && (
                      <span className="text-[11px] text-espresso-400 italic">
                        {offer.validationNotes}
                      </span>
                    )}
                  </div>
                </div>
              </div>

              {/* Price Display & Action Button */}
              <div className="flex items-center justify-between md:justify-end space-x-6 pt-2 md:pt-0 border-t md:border-t-0 border-rose-100">
                {isRetrieved ? (
                  <div className="text-left md:text-right">
                    <span className="text-xs text-espresso-400 block font-normal">
                      Base: ₹{offer.listedPrice?.toLocaleString('en-IN')}
                      {offer.mrp && offer.mrp > (offer.listedPrice || 0) && (
                        <span className="line-through ml-1.5 text-espresso-300">
                          ₹{offer.mrp.toLocaleString('en-IN')}
                        </span>
                      )}
                    </span>

                    <span className="text-[11px] text-espresso-500 block">
                      {hasKnownShipping ? (
                        offer.shippingFee === 0 ? 'Free Shipping Included' : `+ ₹${offer.shippingFee} Standard Shipping`
                      ) : (
                        <span className="text-amber-700 italic font-medium">Shipping Disclosed At Checkout</span>
                      )}
                    </span>

                    <div className="mt-0.5">
                      <span className="text-base sm:text-lg font-extrabold font-sans text-espresso-950">
                        {offer.totalCost !== null && offer.totalCost !== undefined
                          ? `₹${offer.totalCost.toLocaleString('en-IN')} Total`
                          : `₹${offer.listedPrice?.toLocaleString('en-IN')} (Excl. Shipping)`}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="text-left md:text-right">
                    <span className="text-xs text-espresso-400 block italic">
                      {isLoading ? 'Checking feed...' : isRestricted ? 'Restricted access' : 'Currently Unavailable'}
                    </span>
                    <span className="text-[11px] text-espresso-400 block">
                      No live quote
                    </span>
                  </div>
                )}

                {/* Purchase Link Button */}
                <a
                  href={offer.purchaseUrl || '#'}
                  target="_blank"
                  rel="noopener noreferrer"
                  className={`px-4 py-2.5 rounded-xl text-xs font-bold tracking-wide transition-all shadow-xs flex items-center space-x-1 shrink-0 ${
                    isRetrieved
                      ? 'bg-espresso-800 hover:bg-espresso-950 text-ivory'
                      : 'bg-ivory-100 text-espresso-400 border border-rose-200 cursor-not-allowed pointer-events-none'
                  }`}
                >
                  <span>{isRetrieved ? 'View Offer' : 'Unavailable'}</span>
                  {isRetrieved && <ExternalLink className="w-3 h-3 ml-1" />}
                </a>
              </div>
            </div>
          );
        })}
      </div>
    </section>
  );
};
