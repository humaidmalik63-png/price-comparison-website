import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  RefreshCw,
  ExternalLink,
  ShieldCheck,
  AlertCircle,
  Truck,
  Tag,
  Clock,
  Link as LinkIcon,
  Search,
  CheckCircle2,
  PlusCircle,
  X,
} from 'lucide-react';
import {
  getAutoLiveComparison,
  checkManualUrlPrice,
  getProductRetailerSources,
  uploadEvidenceFile,
  submitProductManualVerification,
  type LiveComparisonResult,
  type ManualUrlCheckResult,
  type ProductRetailerSource,
} from '../utils/api';
import type { RetailerOffer } from '../types';
import { useAuth } from '../context/AuthContext';

interface LiveRetailerPriceComparisonProps {
  productId?: number;
  slug: string;
  productName?: string;
  brand?: string;
  targetVariant: string;
  fallbackOffers: RetailerOffer[];
}

const RETAILER_NAMES = ['Nykaa', 'Myntra', 'Purplle', 'Tira', 'Amazon India'];

export const LiveRetailerPriceComparison: React.FC<LiveRetailerPriceComparisonProps> = ({
  productId,
  slug,
  productName: _productName,
  brand: _brand,
  targetVariant,
  fallbackOffers,
}) => {
  const { user } = useAuth();
  const isAdmin = user && (user.id === 1 || user.email.toLowerCase().endsWith('@pricewise.ai') || (user as any).is_admin);

  const [comparison, setComparison] = useState<LiveComparisonResult | null>(null);
  const [sources, setSources] = useState<ProductRetailerSource[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isRefreshing, setIsRefreshing] = useState<boolean>(false);
  const [mountedAt] = useState<string>(() => new Date().toISOString());

  // Manual URL Check state
  const [isManualUrlOpen, setIsManualUrlOpen] = useState(false);
  const [manualUrlInput, setManualUrlInput] = useState('');
  const [isCheckingManual, setIsCheckingManual] = useState(false);
  const [manualResult, setManualResult] = useState<ManualUrlCheckResult | null>(null);
  const [manualError, setManualError] = useState<string | null>(null);

  // User Verification Submission Modal
  const [isVerifyModalOpen, setIsVerifyModalOpen] = useState(false);
  const [verifyRetailer, setVerifyRetailer] = useState('Nykaa');
  const [verifyUrl, setVerifyUrl] = useState('');
  const [verifyPrice, setVerifyPrice] = useState('');
  const [verifyMrp, setVerifyMrp] = useState('');
  const [verifySize, setVerifySize] = useState(targetVariant || '');
  const [verifyNotes, setVerifyNotes] = useState('');
  const [verifyFile, setVerifyFile] = useState<File | null>(null);
  const [isSubmittingVerify, setIsSubmittingVerify] = useState(false);
  const [verifySuccessMsg, setVerifySuccessMsg] = useState<string | null>(null);
  const [verifyErrorMsg, setVerifyErrorMsg] = useState<string | null>(null);

  // Deduplication ref to avoid duplicate calls on re-renders
  const lastFetchedSlugRef = useRef<string | null>(null);

  const fetchLiveComparison = useCallback(
    async (force = false) => {
      if (force) {
        setIsRefreshing(true);
      } else {
        setIsLoading(true);
      }

      try {
        const [liveRes, sourcesRes] = await Promise.all([
          getAutoLiveComparison(productId, slug, force),
          productId ? getProductRetailerSources(productId) : Promise.resolve([]),
        ]);

        if (liveRes) {
          setComparison(liveRes);
        }
        if (sourcesRes && sourcesRes.length > 0) {
          setSources(sourcesRes);
        }
      } catch {
        // Handled internally in api.ts with fallback
      } finally {
        setIsLoading(false);
        setIsRefreshing(false);
      }
    },
    [productId, slug]
  );

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
        setManualError('Unable to extract price from this URL. Ensure it is a valid HTTPS retailer product page.');
      }
    } catch (err: unknown) {
      setManualError(err instanceof Error ? err.message : 'URL check failed');
    } finally {
      setIsCheckingManual(false);
    }
  };

  const handleVerifySubmission = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!productId || !verifyUrl.trim() || !verifyPrice) {
      setVerifyErrorMsg('Please fill in required fields (Retailer, URL, Observed Price).');
      return;
    }

    const priceNum = parseFloat(verifyPrice);
    if (isNaN(priceNum) || priceNum <= 0) {
      setVerifyErrorMsg('Please enter a valid positive price.');
      return;
    }

    setIsSubmittingVerify(true);
    setVerifyErrorMsg(null);
    setVerifySuccessMsg(null);

    try {
      let uploadedEvidenceUrl: string | undefined = undefined;
      if (verifyFile) {
        const uploadRes = await uploadEvidenceFile(verifyFile);
        if (uploadRes.success) {
          uploadedEvidenceUrl = uploadRes.evidenceUrl;
        } else {
          setVerifyErrorMsg(`Evidence upload failed: ${uploadRes.error}`);
          setIsSubmittingVerify(false);
          return;
        }
      }

      const submitRes = await submitProductManualVerification({
        product_id: productId,
        retailer: verifyRetailer,
        product_url: verifyUrl.trim(),
        user_submitted_price: priceNum,
        size_volume: verifySize.trim() || undefined,
        notes: verifyNotes.trim() || undefined,
        evidence_url: uploadedEvidenceUrl,
      });

      if (submitRes.success) {
        setVerifySuccessMsg('Price verification submitted successfully! It is now pending admin review in the evidence queue.');
        setVerifyUrl('');
        setVerifyPrice('');
        setVerifyMrp('');
        setVerifyFile(null);
        setTimeout(() => {
          setIsVerifyModalOpen(false);
          setVerifySuccessMsg(null);
        }, 2500);
      } else {
        setVerifyErrorMsg(submitRes.error || 'Submission failed.');
      }
    } catch (err: unknown) {
      setVerifyErrorMsg(err instanceof Error ? err.message : 'Error submitting verification');
    } finally {
      setIsSubmittingVerify(false);
    }
  };

  // Helper to calculate unit price (₹/ml or ₹/g)
  const calculateUnitPrice = (price?: number | null, variantText?: string | null): string | null => {
    if (!price || price <= 0 || !variantText) return null;
    const match = variantText.match(/(\d+(?:\.\d+)?)\s*(ml|g|gm)/i);
    if (!match) return null;
    const qty = parseFloat(match[1]);
    const unit = match[2].toLowerCase() === 'gm' ? 'g' : match[2].toLowerCase();
    if (qty <= 0) return null;
    const perUnit = (price / qty).toFixed(2);
    return `₹${perUnit}/${unit}`;
  };

  // Prepare display offers, merging comparison and verified sources
  const displayOffers = useMemo(() => {
    return RETAILER_NAMES.map((name) => {
      const cleanKey = name.toLowerCase().split(' ')[0];
      const sourceMatch = sources.find((s) => s.retailer_name.toLowerCase().includes(cleanKey));
      const compOffer = comparison?.offers.find((o) => o.retailerName.toLowerCase().includes(cleanKey));
      const local = fallbackOffers.find((f) => f.storeName.toLowerCase().includes(cleanKey));

      const isRestrictedPolicy = sourceMatch?.requires_manual_verification || compOffer?.status === 'restricted';
      const verificationStatus = sourceMatch?.verification_status || (compOffer?.sourceType === 'verified_live' ? 'LIVE_VERIFIED' : 'DEMO');

      const listedPrice = sourceMatch?.current_price ?? compOffer?.listedPrice ?? local?.price;
      const mrp = sourceMatch?.original_price ?? compOffer?.mrp ?? local?.originalPrice;
      const discountPct = mrp && listedPrice && mrp > listedPrice ? Math.round(((mrp - listedPrice) / mrp) * 100) : 0;
      // Phase 14 Stage D: a retailer homepage is not a purchase link. The link
      // is only used when a source actually provided a product URL.
      const purchaseUrl = sourceMatch?.product_url ?? compOffer?.purchaseUrl ?? local?.purchaseUrl ?? '';

      return {
        retailerName: name,
        storeId: name.toLowerCase().replace(' ', '-'),
        status: isRestrictedPolicy ? 'restricted' : (listedPrice ? 'retrieved' : 'unavailable'),
        listedPrice,
        mrp,
        discountPct,
        shippingFee: compOffer?.shippingFee ?? local?.shippingFee,
        isShippingDisclosed: compOffer?.isShippingDisclosed ?? local?.isShippingDisclosed ?? true,
        couponCode: compOffer?.couponCode ?? local?.couponCode,
        couponDiscount: compOffer?.couponDiscount ?? local?.couponDiscount ?? 0,
        totalCost: compOffer?.totalCost ?? local?.totalCost ?? listedPrice,
        stockStatus: compOffer?.stockStatus ?? local?.stockStatus ?? 'In Stock',
        inStock: compOffer?.inStock ?? local?.inStock ?? true,
        purchaseUrl,
        matchClassification: compOffer?.matchClassification ?? 'EXACT_MATCH',
        isLowestListed: compOffer?.isLowestListed ?? local?.isLowestPrice ?? false,
        isLowestTotal: compOffer?.isLowestTotal ?? local?.isLowestPrice ?? false,
        sourceType: compOffer?.sourceType ?? (verificationStatus === 'LIVE_VERIFIED' ? 'verified_live' : 'demo'),
        verificationStatus,
        lastVerifiedAt: sourceMatch?.last_verified_at,
        retrievedAt: sourceMatch?.last_checked_at ?? compOffer?.retrievedAt ?? mountedAt,
        unitPrice: calculateUnitPrice(listedPrice, targetVariant),
      };
    });
  }, [comparison, sources, fallbackOffers, mountedAt, targetVariant]);

  // Sort offers: verified or lowest total first
  const sortedOffers = useMemo(() => {
    return [...displayOffers].sort((a, b) => {
      if (a.verificationStatus === 'LIVE_VERIFIED' && b.verificationStatus !== 'LIVE_VERIFIED') return -1;
      if (a.verificationStatus !== 'LIVE_VERIFIED' && b.verificationStatus === 'LIVE_VERIFIED') return 1;
      const aCost = a.totalCost ?? a.listedPrice ?? Infinity;
      const bCost = b.totalCost ?? b.listedPrice ?? Infinity;
      return aCost - bCost;
    });
  }, [displayOffers]);

  // Render Status Badge with strict truth-in-advertising colors
  const renderVerificationBadge = (status: string) => {
    switch (status) {
      case 'LIVE_VERIFIED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 flex items-center space-x-1">
            <ShieldCheck className="w-3 h-3 text-emerald-600" />
            <span>LIVE VERIFIED</span>
          </span>
        );
      case 'MANUAL_VERIFIED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-sky-100 text-sky-800 border border-sky-300 flex items-center space-x-1">
            <CheckCircle2 className="w-3 h-3 text-sky-600" />
            <span>MANUALLY VERIFIED</span>
          </span>
        );
      case 'CACHED':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300 flex items-center space-x-1">
            <Clock className="w-3 h-3 text-amber-600" />
            <span>CACHED PRICE</span>
          </span>
        );
      case 'HISTORICAL':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-800 border border-slate-300 flex items-center space-x-1">
            <span>HISTORICAL PRICE</span>
          </span>
        );
      case 'POSSIBLE_MATCH':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-purple-100 text-purple-800 border border-purple-300 flex items-center space-x-1">
            <span>POSSIBLE MATCH</span>
          </span>
        );
      case 'UNAVAILABLE':
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-800 border border-rose-300 flex items-center space-x-1">
            <span>UNAVAILABLE</span>
          </span>
        );
      case 'DEMO':
      default:
        return (
          <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-900 border border-amber-200 flex items-center space-x-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 inline-block" />
            <span>DEMO PRICE (Simulated)</span>
          </span>
        );
    }
  };

  return (
    <section className="space-y-4 pt-6 border-t border-rose-200" id="live-price-comparison-section">
      {/* Header with Title, Actions & Admin Queue Link */}
      <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-3">
        <div>
          <div className="flex items-center space-x-2.5">
            <h2 className="font-editorial text-2xl font-bold text-espresso-900">
              Retailer Price Comparison & Verification
            </h2>
            {isLoading && (
              <span className="flex items-center space-x-1.5 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200 animate-pulse">
                <span className="w-1.5 h-1.5 rounded-full bg-rose-500 animate-ping" />
                <span>Checking Retailer Feeds...</span>
              </span>
            )}
          </div>
          <p className="text-xs text-espresso-500 mt-1">
            Transparent price intelligence across India's top beauty destinations. Variant locked: <strong>{targetVariant || 'Standard'}</strong>.
          </p>
        </div>

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center gap-2">
          {isAdmin && (
            <Link
              to="/admin/verifications"
              className="px-3 py-1.5 rounded-xl border border-rose-300 bg-rose-50/80 hover:bg-rose-100 text-rose-800 text-xs font-bold flex items-center space-x-1.5 transition-all shadow-2xs"
            >
              <ShieldCheck className="w-3.5 h-3.5 text-rose-600" />
              <span>Admin Verification Queue</span>
            </Link>
          )}

          <button
            type="button"
            onClick={() => setIsVerifyModalOpen(true)}
            className="px-3 py-1.5 rounded-xl bg-espresso-900 hover:bg-espresso-950 text-ivory text-xs font-bold flex items-center space-x-1.5 transition-all shadow-2xs"
            title="Submit latest observed price and screenshot proof"
          >
            <PlusCircle className="w-3.5 h-3.5 text-rose-300" />
            <span>Verify Retailer Price</span>
          </button>

          <button
            type="button"
            onClick={() => fetchLiveComparison(true)}
            disabled={isLoading || isRefreshing}
            className="px-3 py-1.5 rounded-xl border border-rose-200 bg-white hover:bg-rose-50/70 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-all shadow-2xs disabled:opacity-50"
            title="Refresh prices"
          >
            <RefreshCw className={`w-3.5 h-3.5 text-espresso-600 ${isRefreshing ? 'animate-spin text-rose-600' : ''}`} />
            <span>{isRefreshing ? 'Refreshing...' : 'Refresh'}</span>
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

      {/* Retailer Comparison Cards */}
      <div className="rounded-3xl border border-rose-200 overflow-hidden bg-white shadow-soft-lift divide-y divide-rose-100">
        {sortedOffers.map((offer) => {
          const isRestricted = offer.status === 'restricted';
          const hasKnownShipping = offer.isShippingDisclosed && offer.shippingFee !== null && offer.shippingFee !== undefined;

          return (
            <div
              key={offer.storeId}
              className={`p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 transition-colors ${
                offer.isLowestTotal ? 'bg-rose-50/30' : 'bg-white'
              }`}
            >
              {/* Retailer Identity & Badges */}
              <div className="flex items-start sm:items-center space-x-3.5">
                <div className="w-10 h-10 rounded-full bg-ivory border border-rose-200 flex items-center justify-center font-bold text-sm text-espresso-900 shrink-0">
                  {offer.retailerName[0]}
                </div>

                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-bold text-sm sm:text-base text-espresso-900">
                      {offer.retailerName}
                    </span>

                    {/* Status Badge */}
                    {renderVerificationBadge(offer.verificationStatus)}

                    {/* Unit Price Normalization */}
                    {offer.unitPrice && (
                      <span className="text-[11px] font-semibold text-espresso-700 bg-ivory-100 px-2 py-0.5 rounded-md border border-rose-200">
                        {offer.unitPrice}
                      </span>
                    )}

                    {/* Lowest Price Tag */}
                    {offer.isLowestTotal && (
                      <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-sage-600 text-ivory flex items-center space-x-1">
                        <CheckCircle2 className="w-3 h-3" />
                        <span>Lowest Deal</span>
                      </span>
                    )}

                    {/* Stock Status */}
                    <span className="text-[10px] font-semibold text-espresso-600 bg-ivory-100 px-1.5 py-0.5 rounded border border-rose-100">
                      {offer.stockStatus}
                    </span>
                  </div>

                  {/* Restricted Retailer Explanatory Notice */}
                  {isRestricted ? (
                    <p className="text-xs text-amber-800 bg-amber-50/70 px-2.5 py-1 rounded-lg border border-amber-200 mt-1.5 max-w-xl">
                      Automatic price checking is currently unavailable for this retailer. Visit the retailer website to check its latest price.
                    </p>
                  ) : (
                    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-espresso-500 mt-1">
                      <span className="flex items-center space-x-1">
                        <Truck className="w-3.5 h-3.5 text-espresso-400" />
                        <span>
                          {hasKnownShipping ? (offer.shippingFee === 0 ? 'Free Shipping' : `+ ₹${offer.shippingFee} Shipping`) : 'Shipping Disclosed at Checkout'}
                        </span>
                      </span>

                      {offer.lastVerifiedAt ? (
                        <span className="flex items-center space-x-1 text-sky-800 text-[11px]">
                          <CheckCircle2 className="w-3 h-3 text-sky-600" />
                          <span>Verified {new Date(offer.lastVerifiedAt).toLocaleDateString('en-GB')}</span>
                        </span>
                      ) : offer.retrievedAt ? (
                        <span className="flex items-center space-x-1 text-espresso-400 text-[11px]">
                          <Clock className="w-3 h-3" />
                          <span>Checked {new Date(offer.retrievedAt).toLocaleDateString('en-GB')}</span>
                        </span>
                      ) : null}

                      {offer.couponCode && (
                        <span className="flex items-center space-x-1 text-[11px] text-rose-600 font-medium">
                          <Tag className="w-3 h-3" />
                          <span>Code {offer.couponCode} (-₹{offer.couponDiscount})</span>
                        </span>
                      )}
                    </div>
                  )}
                </div>
              </div>

              {/* Price Display & Action Button */}
              <div className="flex items-center justify-between md:justify-end space-x-6 pt-2 md:pt-0 border-t md:border-t-0 border-rose-100">
                {offer.listedPrice && offer.listedPrice > 0 ? (
                  <div className="text-left md:text-right">
                    <span className="text-xs text-espresso-400 block font-normal">
                      Base: ₹{offer.listedPrice.toLocaleString('en-IN')}
                      {offer.mrp && offer.mrp > offer.listedPrice && (
                        <span className="line-through ml-1.5 text-espresso-300">
                          ₹{offer.mrp.toLocaleString('en-IN')}
                        </span>
                      )}
                    </span>

                    <div className="mt-0.5">
                      <span className="text-base sm:text-lg font-extrabold font-sans text-espresso-950">
                        ₹{(offer.totalCost ?? offer.listedPrice).toLocaleString('en-IN')}
                      </span>
                    </div>
                  </div>
                ) : (
                  <div className="text-left md:text-right">
                    <span className="text-xs text-espresso-400 block italic">Check Retailer</span>
                  </div>
                )}

                {/* Direct Retailer Link - only rendered when a verified product URL exists */}
                {offer.purchaseUrl ? (
                  <a
                    href={offer.purchaseUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="px-4 py-2.5 rounded-xl text-xs font-bold tracking-wide transition-all shadow-xs flex items-center space-x-1.5 shrink-0 bg-espresso-900 hover:bg-espresso-950 text-ivory"
                  >
                    <span>Visit {offer.retailerName}</span>
                    <ExternalLink className="w-3 h-3 ml-0.5" />
                  </a>
                ) : (
                  <div
                    className="px-4 py-2.5 rounded-xl text-xs font-bold tracking-wide flex items-center space-x-1.5 shrink-0 bg-ivory-200 text-espresso-500 border border-rose-100"
                    title="No authorised retailer feed is connected, so no live product link is available"
                  >
                    <span>Live link unavailable</span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* User Price Verification Modal */}
      {isVerifyModalOpen && (
        <div className="fixed inset-0 z-50 bg-espresso-950/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-3xl max-w-lg w-full p-6 space-y-4 border border-rose-200 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-rose-100 pb-3">
              <div className="flex items-center space-x-2">
                <ShieldCheck className="w-5 h-5 text-rose-500" />
                <h3 className="font-editorial text-lg font-bold text-espresso-950">
                  Submit Retailer Price for Verification
                </h3>
              </div>
              <button
                type="button"
                onClick={() => setIsVerifyModalOpen(false)}
                className="text-espresso-400 hover:text-espresso-800"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <p className="text-xs text-espresso-600">
              Found a different or updated price on an official retailer website? Submit it with proof (e.g. screenshot or invoice) and our admins will verify it for the community.
            </p>

            {verifySuccessMsg && (
              <div className="p-3 rounded-2xl bg-sage-50 border border-sage-200 text-sage-800 text-xs flex items-center space-x-2">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-sage-600" />
                <span>{verifySuccessMsg}</span>
              </div>
            )}

            {verifyErrorMsg && (
              <div className="p-3 rounded-2xl bg-rose-50 border border-rose-200 text-rose-800 text-xs flex items-center space-x-2">
                <AlertCircle className="w-4 h-4 shrink-0 text-rose-600" />
                <span>{verifyErrorMsg}</span>
              </div>
            )}

            <form onSubmit={handleVerifySubmission} className="space-y-3 text-xs">
              <div>
                <label className="font-bold text-espresso-800 block mb-1">Retailer:</label>
                <select
                  value={verifyRetailer}
                  onChange={(e) => setVerifyRetailer(e.target.value)}
                  className="w-full px-3 py-2 rounded-xl border border-rose-200 bg-white text-espresso-900"
                >
                  {RETAILER_NAMES.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label className="font-bold text-espresso-800 block mb-1">Retailer Product URL *:</label>
                <input
                  type="url"
                  required
                  value={verifyUrl}
                  onChange={(e) => setVerifyUrl(e.target.value)}
                  placeholder="https://www.nykaa.com/... or https://www.tirabeauty.com/product/..."
                  className="w-full px-3 py-2 rounded-xl border border-rose-200 focus:outline-hidden focus:ring-2 focus:ring-rose-300"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-bold text-espresso-800 block mb-1">Observed Selling Price (₹) *:</label>
                  <input
                    type="number"
                    step="0.01"
                    required
                    value={verifyPrice}
                    onChange={(e) => setVerifyPrice(e.target.value)}
                    placeholder="e.g. 549"
                    className="w-full px-3 py-2 rounded-xl border border-rose-200 focus:outline-hidden focus:ring-2 focus:ring-rose-300"
                  />
                </div>

                <div>
                  <label className="font-bold text-espresso-800 block mb-1">MRP / List Price (₹):</label>
                  <input
                    type="number"
                    step="0.01"
                    value={verifyMrp}
                    onChange={(e) => setVerifyMrp(e.target.value)}
                    placeholder="e.g. 599"
                    className="w-full px-3 py-2 rounded-xl border border-rose-200 focus:outline-hidden focus:ring-2 focus:ring-rose-300"
                  />
                </div>
              </div>

              <div>
                <label className="font-bold text-espresso-800 block mb-1">Product Size / Volume / Shade:</label>
                <input
                  type="text"
                  value={verifySize}
                  onChange={(e) => setVerifySize(e.target.value)}
                  placeholder="e.g. 30ml, 50g, Ruby Woo"
                  className="w-full px-3 py-2 rounded-xl border border-rose-200 focus:outline-hidden focus:ring-2 focus:ring-rose-300"
                />
              </div>

              <div>
                <label className="font-bold text-espresso-800 block mb-1">Screenshot Proof (Optional, max 5MB):</label>
                <input
                  type="file"
                  accept="image/png,image/jpeg,image/webp"
                  onChange={(e) => setVerifyFile(e.target.files?.[0] || null)}
                  className="w-full text-xs text-espresso-500 file:mr-3 file:py-1.5 file:px-3 file:rounded-xl file:border-0 file:text-xs file:font-semibold file:bg-rose-50 file:text-rose-700 hover:file:bg-rose-100"
                />
              </div>

              <div>
                <label className="font-bold text-espresso-800 block mb-1">Additional Notes / Promo Details:</label>
                <textarea
                  rows={2}
                  value={verifyNotes}
                  onChange={(e) => setVerifyNotes(e.target.value)}
                  placeholder="e.g. Extra 10% coupon code applied during checkout"
                  className="w-full px-3 py-2 rounded-xl border border-rose-200 focus:outline-hidden focus:ring-2 focus:ring-rose-300"
                />
              </div>

              <div className="flex items-center justify-end space-x-2 pt-3 border-t border-rose-100">
                <button
                  type="button"
                  onClick={() => setIsVerifyModalOpen(false)}
                  className="px-4 py-2 rounded-xl border border-rose-200 text-espresso-700 text-xs font-semibold"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isSubmittingVerify}
                  className="px-5 py-2 rounded-xl bg-espresso-900 hover:bg-espresso-950 text-ivory text-xs font-bold disabled:opacity-50"
                >
                  {isSubmittingVerify ? 'Submitting...' : 'Submit Verification'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </section>
  );
};
