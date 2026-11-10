import React, { useState, useMemo, useEffect, useCallback } from 'react';
import { useParams, useNavigate, Link } from 'react-router-dom';
import {
  Heart,
  Bell,
  ArrowLeft,
  Share2,
  CheckCircle2,
  Info,
  Star,
  AlertTriangle,
  Sparkles,
  DollarSign,
  Brain,
  Tag,
} from 'lucide-react';

import { PRODUCTS_DATA } from '../data/products';
import { findProductBySlugOrId, generateProductSlug, toNumericProductId } from '../utils/slug';
import { PriceHistoryChart } from '../components/PriceHistoryChart';
import { DealScoreCard } from '../components/DealScoreCard';
import { PriceTrackingModal } from '../components/PriceTrackingModal';
import { ReviewIntelligenceHub } from '../components/ReviewIntelligenceHub';
import { LiveRetailerPriceComparison } from '../components/LiveRetailerPriceComparison';
import { IngredientAnalysisSection } from '../components/IngredientAnalysisSection';
import { AlternativesSection } from '../components/AlternativesSection';
import { BeautyUsageGuide } from '../components/BeautyUsageGuide';
import { ProductImage } from '../components/ProductImage';
import { useWishlist } from '../hooks/useWishlist';
import { usePriceTracker } from '../hooks/usePriceTracker';

type DetailSectionId = 'overview' | 'pricing' | 'ingredients' | 'alternatives' | 'reviews';

interface NavSectionItem {
  id: DetailSectionId;
  label: string;
  shortLabel: string;
  icon: React.ComponentType<{ className?: string }>;
}

const DETAIL_SECTIONS: NavSectionItem[] = [
  { id: 'overview', label: 'Overview & Usage', shortLabel: 'Overview', icon: Sparkles },
  { id: 'pricing', label: 'Live Price Comparison', shortLabel: 'Prices', icon: DollarSign },
  { id: 'ingredients', label: 'Ingredient Intelligence', shortLabel: 'Ingredients', icon: Brain },
  { id: 'alternatives', label: 'Cheaper Dupes & Alternatives', shortLabel: 'Alternatives', icon: Tag },
  { id: 'reviews', label: 'Reviews & Community', shortLabel: 'Reviews', icon: Star },
];

export const ProductDetailPage: React.FC = () => {
  const { slugOrId } = useParams<{ slugOrId: string }>();
  const navigate = useNavigate();

  // Wishlist and Price Tracking Hooks
  const { isWishlisted, toggleWishlist } = useWishlist();
  const { isTracking, getTrackedRecord, startTracking, stopTracking } = usePriceTracker();

  // Modal & Interactive State
  const [isTrackerModalOpen, setIsTrackerModalOpen] = useState(false);
  const [copiedUrl, setCopiedUrl] = useState(false);
  const [activeSection, setActiveSection] = useState<DetailSectionId>('overview');

  // Lookup product
  const product = useMemo(() => {
    return findProductBySlugOrId(PRODUCTS_DATA, slugOrId || '');
  }, [slugOrId]);

  // Smooth scroll to section
  const scrollToSection = useCallback((sectionId: DetailSectionId) => {
    setActiveSection(sectionId);
    const element = document.getElementById(`section-${sectionId}`);
    if (element) {
      const navOffset = 118; // Offset for sticky breadcrumb + sticky sub-nav
      const elementPosition = element.getBoundingClientRect().top + window.pageYOffset;
      window.scrollTo({
        top: Math.max(0, elementPosition - navOffset),
        behavior: 'smooth',
      });
    }
  }, []);

  // Update active section on scroll
  useEffect(() => {
    const handleScroll = () => {
      const scrollPosition = window.scrollY + 140;
      for (let i = DETAIL_SECTIONS.length - 1; i >= 0; i--) {
        const sectionId = DETAIL_SECTIONS[i].id;
        const el = document.getElementById(`section-${sectionId}`);
        if (el && el.offsetTop <= scrollPosition) {
          setActiveSection(sectionId);
          break;
        }
      }
    };

    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

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
            className="px-6 py-3 rounded-xl bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold tracking-wide transition-all shadow-xs flex items-center space-x-2 cursor-pointer"
          >
            <ArrowLeft className="w-4 h-4" />
            <span>Return to Product Discovery</span>
          </button>
        </div>
      </div>
    );
  }

  const isTracked = isTracking(product.id);
  const trackingRecord = getTrackedRecord(product.id);
  const wishlisted = isWishlisted(product.id);
  const numericProductId = product.dbId || toNumericProductId(product.id);

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
      {/* Breadcrumbs Top Bar */}
      <div className="border-b border-rose-100 bg-white/60 backdrop-blur-xs sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3 flex items-center justify-between">
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
            className="px-3 py-1.5 rounded-lg bg-ivory-100 hover:bg-ivory-200 text-espresso-700 text-xs font-semibold flex items-center space-x-1.5 transition-colors shrink-0 cursor-pointer"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span className="hidden sm:inline">Back to Catalog</span>
          </button>
        </div>
      </div>

      {/* Task 1: Sticky Product Intelligence Sub-Navigation Bar */}
      <div className="sticky top-11 z-25 bg-ivory/90 backdrop-blur-md border-b border-rose-100/90 py-2.5 shadow-2xs">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center space-x-2 overflow-x-auto no-scrollbar scroll-smooth">
            {DETAIL_SECTIONS.map((sec) => {
              const Icon = sec.icon;
              const isActive = activeSection === sec.id;
              return (
                <button
                  key={sec.id}
                  onClick={() => scrollToSection(sec.id)}
                  className={`px-3.5 py-1.5 rounded-full text-xs font-semibold whitespace-nowrap transition-all flex items-center space-x-1.5 cursor-pointer shrink-0 ${
                    isActive
                      ? 'bg-rose-500 text-ivory shadow-xs font-bold'
                      : 'bg-white/90 hover:bg-rose-50/80 text-espresso-700 border border-rose-200/60'
                  }`}
                  aria-current={isActive ? 'true' : undefined}
                >
                  <Icon className={`w-3.5 h-3.5 ${isActive ? 'text-ivory' : 'text-rose-500'}`} />
                  <span className="hidden md:inline">{sec.label}</span>
                  <span className="md:hidden">{sec.shortLabel}</span>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-6 sm:pt-8 space-y-12">
        {/* SECTION 1: Overview */}
        <section id="section-overview" className="scroll-mt-32 space-y-8">
          {/* Main Product Hero Grid */}
          <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
            {/* Left Column: Image & Size */}
            <div className="lg:col-span-5 space-y-4">
              <div className="aspect-square w-full rounded-3xl overflow-hidden bg-white border border-rose-200/90 shadow-luxury-card relative">
                <ProductImage
                  src={product.image}
                  alt={product.name}
                  brand={product.brand}
                  category={product.category}
                  status={product.imageStatus || 'placeholder'}
                  showBadge={true}
                  priority={true}
                  className="w-full h-full"
                />

                {/* Floating Badges */}
                <div className="absolute top-4 left-4 flex flex-col gap-1.5 pointer-events-none">
                  <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-espresso-900 text-champagne-300 shadow-xs">
                    {product.brandTier}
                  </span>
                  {product.dealTag && (
                    <span className="px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider bg-rose-500 text-ivory shadow-xs">
                      {product.dealTag}
                    </span>
                  )}
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

              {product.dataSource ? (
                <div className={`flex items-center space-x-2 text-xs px-3 py-1.5 rounded-xl border ${
                  product.dataStatus === 'catalog_verified'
                    ? 'text-emerald-800 bg-emerald-50/90 border-emerald-200/90'
                    : 'text-amber-800 bg-amber-50/90 border-amber-200/90'
                }`}>
                  <CheckCircle2 className={`w-3.5 h-3.5 shrink-0 ${
                    product.dataStatus === 'catalog_verified' ? 'text-emerald-600' : 'text-amber-600'
                  }`} />
                  <span>
                    <strong className="font-semibold">
                      {product.dataStatus === 'catalog_verified'
                        ? 'Verified Product Specification:'
                        : 'Partially Verified Specifications:'}
                    </strong>{' '}
                    {product.dataSource}
                  </span>
                </div>
              ) : (
                <div className="flex items-center space-x-2 text-xs text-espresso-700 bg-espresso-50/80 border border-espresso-200 px-3 py-1.5 rounded-xl">
                  <Info className="w-3.5 h-3.5 text-espresso-500 shrink-0" />
                  <span>
                    <strong className="font-semibold">Product Information Available:</strong> Commercial catalog listing. Packaging filing reference pending verification.
                  </span>
                </div>
              )}

              {/* Price Box */}
              <div className="bg-white p-5 rounded-3xl border border-rose-200/80 shadow-soft-lift space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold uppercase tracking-wider text-espresso-400 block">
                    Catalog Baseline Offer
                  </span>
                  <span className="text-[10px] font-semibold text-amber-800 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200">
                    Demo Price
                  </span>
                </div>

                <div className="flex items-baseline space-x-3">
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
                    className={`px-4 py-2.5 rounded-xl text-xs font-bold flex items-center space-x-2 transition-all border cursor-pointer ${
                      wishlisted
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
                    className={`px-4 py-2.5 rounded-xl text-xs font-bold flex items-center space-x-2 transition-all border cursor-pointer ${
                      isTracked
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
                    className="px-3.5 py-2.5 rounded-xl bg-white hover:bg-ivory-100 text-espresso-600 border border-rose-200 text-xs font-semibold flex items-center space-x-1.5 transition-colors cursor-pointer"
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

          {/* Beauty Usage Guide */}
          <BeautyUsageGuide product={product} />
        </section>

        {/* SECTION 2: Price Comparison & Trends */}
        <section id="section-pricing" className="scroll-mt-32 space-y-6 pt-4 border-t border-rose-100">
          <div className="flex items-center space-x-2 text-rose-500 text-xs font-bold uppercase tracking-wider">
            <DollarSign className="w-4 h-4" />
            <span>Retailer Transparency & Market Trends</span>
          </div>

          {/* Phase 15: the manufacturer's own product page.
              This is a brand page recorded in the curated catalogue, NOT a
              retailer offer. It is shown so a shopper has a genuine place to
              read the specification, clearly separated from the retailer
              price comparison below. */}
          {product.officialUrl && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-rose-100 bg-ivory-50 px-4 py-3">
              <div className="min-w-0">
                <p className="text-xs font-bold uppercase tracking-wider text-espresso-500">
                  Official product page
                </p>
                <p className="mt-1 text-xs text-espresso-600">
                  The manufacturer&apos;s own page for this product. Retailer
                  prices below are catalogue data until a live retailer feed is
                  connected.
                </p>
              </div>
              <a
                href={product.officialUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 rounded-xl border border-espresso-200 bg-white px-4 py-2 text-xs font-semibold tracking-wide text-espresso-800 transition-colors hover:border-espresso-400"
              >
                View on the official {product.brand} site
              </a>
            </div>
          )}

          {/* Automatic Multi-Retailer Live Price Comparison */}
          <LiveRetailerPriceComparison
            productId={numericProductId}
            slug={product.slug || slugOrId || ''}
            productName={product.name}
            brand={product.brand}
            targetVariant={product.quantity}
            fallbackOffers={product.storeOffers}
          />

          {/* Phase 9: Algorithmic Deal Scoring & Landed Cost Breakdown */}
          <DealScoreCard
            productId={numericProductId}
            retailerName={product.storeOffers?.[0]?.storeName || 'Nykaa'}
          />

          {/* Phase 9: Historical Price Analytics & Trends Chart */}
          <PriceHistoryChart
            productId={numericProductId}
            priceHistory={product.priceHistory}
            currentPrice={product.price}
            originalPrice={product.originalPrice}
            targetPrice={trackingRecord?.targetPrice}
            productName={product.name}
          />
        </section>

        {/* SECTION 3: Ingredient Intelligence */}
        <section id="section-ingredients" className="scroll-mt-32 pt-4 border-t border-rose-100">
          <IngredientAnalysisSection
            productId={numericProductId}
            productName={product.name}
            brand={product.brand}
            category={product.category}
            subcategory={product.subcategory}
          />
        </section>

        {/* SECTION 4: Cheaper Alternatives & Dupe Finder */}
        <section id="section-alternatives" className="scroll-mt-32 pt-4 border-t border-rose-100">
          <AlternativesSection
            productId={numericProductId}
            productName={product.name}
            brand={product.brand}
            price={product.price}
            originalPrice={product.originalPrice}
            image={product.image}
            quantity={product.quantity}
            category={product.category}
            subcategory={product.subcategory}
          />
        </section>

        {/* SECTION 5: Reviews Intelligence */}
        <section id="section-reviews" className="scroll-mt-32 pt-4 border-t border-rose-100">
          <ReviewIntelligenceHub product={product} />
        </section>
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
