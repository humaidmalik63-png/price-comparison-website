/**
 * OfferCard Component for Phase 16.4 Frontend Integration
 *
 * Displays a single retailer offer with match classification, pricing, and provenance badges.
 * Shows provider-observed vs independently verified distinction, never auto-labels LIVE_VERIFIED.
 */

import React from 'react';
import { ExternalLink, ShieldCheck, AlertCircle, CheckCircle2, Clock, Tag } from 'lucide-react';
import type { RetailerOffer } from '../types';
import { OfferCardSkeleton } from './LoadingSkeleton';
import { ErrorState, StalePriceWarning } from './ErrorState';

interface OfferCardProps {
  offer: RetailerOffer | null;
  matchClassification?: 'verified_match' | 'possible_match' | 'incompatible_mismatch';
  isLiveVerified?: boolean; // Manually determined, never auto-labeled from PriceInIndia
  sourceProvenanced?: boolean; // Distinguishes provider-observed vs indep. verified
  isLoading?: boolean;
  error?: string | null;
  freshnessSeconds?: number | null;
  onRefresh?: () => void;
  onDismissStale?: () => void;
}

export const OfferCard: React.FC<OfferCardProps> = ({
  offer,
  matchClassification = 'verified_match',
  isLiveVerified = false,
  sourceProvenanced = false,
  isLoading = false,
  error = null,
  freshnessSeconds = null,
  onRefresh,
  onDismissStale,
}) => {
  // Show skeleton while loading
  if (isLoading && !offer) {
    return <OfferCardSkeleton />;
  }

  // Show error state if no offer and error
  if (!offer && error) {
    return (
      <ErrorState
        title="Offer Unavailable"
        message={error}
        onRetry={onRefresh}
        retryLabel="Retry"
        className="p-4"
      />
    );
  }

  // Show empty state if no offer
  if (!offer) {
    return (
      <div className="rounded-2xl border border-rose-200 bg-white shadow-soft-lift p-5">
        <div className="text-center py-4 text-espresso-500 text-sm">
          No offer data available
        </div>
      </div>
    );
  }

  // Calculate staleness
  const isStale = freshnessSeconds !== null && freshnessSeconds > 72 * 3600; // 72 hours

  const getClassificationColor = (classification: string) => {
    switch (classification) {
      case 'verified_match':
        return 'bg-green-50 border-green-300 text-green-800';
      case 'possible_match':
        return 'bg-yellow-50 border-yellow-300 text-yellow-800';
      case 'incompatible_mismatch':
        return 'bg-red-50 border-red-300 text-red-800';
      default:
        return 'bg-gray-50 border-gray-300 text-gray-800';
    }
  };

  const getClassificationIcon = (classification: string) => {
    switch (classification) {
      case 'verified_match':
        return <CheckCircle2 className="w-4 h-4 text-green-600" />;
      case 'possible_match':
        return <AlertCircle className="w-4 h-4 text-yellow-600" />;
      case 'incompatible_mismatch':
        return <AlertCircle className="w-4 h-4 text-red-600" />;
      default:
        return <AlertCircle className="w-4 h-4 text-gray-600" />;
    }
  };

  const getClassificationLabel = (classification: string) => {
    switch (classification) {
      case 'verified_match':
        return 'Verified Match';
      case 'possible_match':
        return 'Possible Match';
      case 'incompatible_mismatch':
        return 'Incompatible';
      default:
        return classification.replace('_', ' ');
    }
  };

  const getSourceTypeBadge = (sourceType: string) => {
    switch (sourceType) {
      case 'verified_live':
        return {
          label: 'Live Source',
          color: 'bg-blue-50 border-blue-300 text-blue-800',
          icon: <ShieldCheck className="w-3 h-3" />,
        };
      case 'manual':
        return {
          label: 'Manual Entry',
          color: 'bg-purple-50 border-purple-300 text-purple-800',
          icon: <Clock className="w-3 h-3" />,
        };
      case 'partner_feed':
        return {
          label: 'Partner Feed',
          color: 'bg-indigo-50 border-indigo-300 text-indigo-800',
          icon: <Tag className="w-3 h-3" />,
        };
      case 'demo':
        return {
          label: 'Demo Data',
          color: 'bg-orange-50 border-orange-300 text-orange-800',
          icon: <AlertCircle className="w-3 h-3" />,
        };
      case 'provider_observed':
        return {
          label: 'Live Price',
          color: 'bg-emerald-50 border-emerald-300 text-emerald-800',
          icon: <AlertCircle className="w-3 h-3" />,
        };
      default:
        return {
          label: sourceType,
          color: 'bg-gray-50 border-gray-300 text-gray-800',
          icon: null,
        };
    }
  };

  const sourceBadge = getSourceTypeBadge(offer.sourceType || 'demo');

  return (
    <article className="rounded-2xl border border-rose-200 bg-white shadow-soft-lift hover:shadow-luxury-card transition-all duration-300 p-5 space-y-4">
      {/* Header with Retailer Info & Classification */}
      <div className="flex items-start justify-between">
        <div className="flex items-center space-x-3">
          <div className="w-10 h-10 rounded-full bg-ivory border border-rose-200 flex items-center justify-center font-bold text-sm text-espresso-900">
            {offer.storeName[0]}
          </div>
          <div>
            <h3 className="font-semibold text-base text-espresso-900">{offer.storeName}</h3>
            <div className="flex items-center space-x-2 mt-0.5">
              <span className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${getClassificationColor(matchClassification)}`}>
                {getClassificationIcon(matchClassification)}
                <span className="ml-1">{getClassificationLabel(matchClassification)}</span>
              </span>
              <span className={`inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium border ${sourceBadge.color}`}>
                {sourceBadge.icon}
                <span className="ml-1">{sourceBadge.label}</span>
              </span>
              {!isLiveVerified && offer.sourceType !== 'provider_observed' && (
                <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-champagne-50 border border-champagne-300 text-champagne-800">
                  <AlertCircle className="w-3 h-3" />
                  <span>Provider Observed</span>
                </span>
              )}
              {sourceProvenanced && (
                <span className="inline-flex items-center space-x-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-sage-50 border border-sage-300 text-sage-800">
                  <ShieldCheck className="w-3 h-3" />
                  <span>Independent Verified</span>
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Pricing */}
        <div className="text-right">
          {offer.totalCost !== null && offer.totalCost !== undefined && (
            <div>
              <span className="text-xs text-espresso-400 block">Total Cost</span>
              <span className="text-lg font-bold text-espresso-900">₹{offer.totalCost.toLocaleString('en-IN')}</span>
            </div>
          )}
          {offer.totalCost === null && offer.price !== undefined && (
            <div>
              <span className="text-xs text-espresso-400 block">Base Price</span>
              <span className="text-lg font-bold text-espresso-900">₹{offer.price.toLocaleString('en-IN')}</span>
            </div>
          )}
          {offer.originalPrice && offer.originalPrice > (offer.totalCost || offer.price || 0) && (
            <div>
              <span className="text-xs text-espresso-400 block line-through">₹{offer.originalPrice.toLocaleString('en-IN')}</span>
              <span className="text-xs font-semibold text-rose-600">
                {offer.totalCost !== null && offer.totalCost !== undefined
                  ? Math.round(((offer.totalCost - (offer.originalPrice || 0)) / (offer.originalPrice || 0)) * 100) + '%'
                  : Math.round(((offer.price - (offer.originalPrice || 0)) / (offer.originalPrice || 0)) * 100) + '%'
                } off
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Stock Status & Metadata */}
      <div className="flex flex-wrap items-center gap-3 text-xs text-espresso-600">
        <div className="flex items-center space-x-1">
          {offer.inStock ? (
            <>
              <div className="w-2 h-2 rounded-full bg-green-500" />
              <span>In Stock</span>
            </>
          ) : (
            <>
              <div className="w-2 h-2 rounded-full bg-red-500" />
              <span>{offer.stockStatus || 'Out of Stock'}</span>
            </>
          )}
        </div>
        {offer.deliveryDays && (
          <div className="flex items-center space-x-1">
            <Clock className="w-3 h-3 text-espresso-400" />
            <span>{offer.deliveryDays}</span>
          </div>
        )}
        {offer.couponCode && (
          <div className="flex items-center space-x-1 text-rose-600 font-medium">
            <Tag className="w-3 h-3" />
            <span>{offer.couponCode} (-₹{offer.couponDiscount})</span>
          </div>
        )}
        {offer.lastUpdated && (
          <div className="flex items-center space-x-1 text-espresso-400">
            <span>Updated: {offer.lastUpdated}</span>
          </div>
        )}
      </div>

      {/* Action Button */}
      {offer.inStock && offer.purchaseUrl && (
        <a
          href={offer.purchaseUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="w-full py-2.5 px-4 rounded-xl bg-espresso-800 hover:bg-espresso-950 text-ivory text-xs font-bold tracking-wide transition-all shadow-xs flex items-center justify-center space-x-1.5"
        >
          <span>View Offer</span>
          <ExternalLink className="w-3.5 h-3.5" />
        </a>
      )}

      {/* Warnings */}
      {!offer.inStock && (
        <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-xs text-rose-700 flex items-start space-x-2">
          <AlertCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>This retailer currently has limited stock. Availability changes frequently.</span>
        </div>
      )}

      {/* Stale Price Warning */}
      {isStale && freshnessSeconds && (
        <StalePriceWarning
          freshnessSeconds={freshnessSeconds}
          onRefresh={onRefresh}
          onDismiss={onDismissStale}
          className="mt-2"
        />
      )}
    </article>
  );
};
