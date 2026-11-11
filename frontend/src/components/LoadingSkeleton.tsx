/**
 * Loading Skeleton Components for Phase 16.4
 *
 * Reusable skeleton loaders for consistent loading states across the app.
 */

import React from 'react';

interface SkeletonProps {
  className?: string;
  width?: string | number;
  height?: string | number;
  borderRadius?: string;
}

export const Skeleton: React.FC<SkeletonProps> = ({
  className = '',
  width = '100%',
  height = '1rem',
  borderRadius = 'rounded',
}) => (
  <div
    className={`animate-pulse bg-rose-100/50 ${borderRadius} ${className}`}
    style={{ width, height }}
  />
);

export const ProductCardSkeleton: React.FC = () => (
  <div className="rounded-2xl bg-white border border-rose-200/90 shadow-soft-lift p-5 flex flex-col justify-between relative overflow-hidden">
    {/* Image skeleton */}
    <div className="w-24 h-24 rounded-xl bg-rose-100/50 shrink-0 border border-rose-100" />

    {/* Brand/Title skeleton */}
    <div className="mt-3 space-y-2">
      <Skeleton width="40%" height="0.75rem" borderRadius="rounded-full" />
      <Skeleton width="70%" height="1.25rem" borderRadius="rounded" />
      <Skeleton width="50%" height="0.75rem" borderRadius="rounded" />
    </div>

    {/* Store comparison skeleton */}
    <div className="mt-4 pt-3 border-t border-rose-100 space-y-2">
      <Skeleton width="80%" height="0.75rem" borderRadius="rounded" />
      <Skeleton width="60%" height="0.75rem" borderRadius="rounded" />
      <Skeleton width="50%" height="0.75rem" borderRadius="rounded" />
    </div>

    {/* Footer skeleton */}
    <div className="mt-5 pt-3 border-t border-rose-100/80 flex items-center justify-between">
      <div className="space-y-1">
        <Skeleton width="40%" height="0.5rem" borderRadius="rounded" />
        <Skeleton width="60%" height="1.5rem" borderRadius="rounded" />
      </div>
      <div className="flex items-center space-x-2">
        <Skeleton width="2.5rem" height="2.5rem" borderRadius="rounded-xl" />
        <Skeleton width="5rem" height="2.5rem" borderRadius="rounded-xl" />
      </div>
    </div>
  </div>
);

export const RetailerOfferSkeleton: React.FC = () => (
  <div className="p-4 sm:p-5 flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-rose-100 last:border-b-0">
    <div className="flex items-center space-x-3.5">
      <Skeleton width="2.5rem" height="2.5rem" borderRadius="rounded-full" />
      <div className="space-y-1">
        <Skeleton width="8rem" height="1rem" borderRadius="rounded" />
        <div className="flex flex-wrap items-center gap-2">
          <Skeleton width="5rem" height="1rem" borderRadius="rounded-full" />
          <Skeleton width="6rem" height="1rem" borderRadius="rounded-full" />
          <Skeleton width="7rem" height="1rem" borderRadius="rounded-full" />
        </div>
      </div>
    </div>
    <div className="text-right space-y-1">
      <Skeleton width="6rem" height="1.5rem" borderRadius="rounded" />
      <Skeleton width="5rem" height="1rem" borderRadius="rounded" />
    </div>
  </div>
);

export const OfferCardSkeleton: React.FC = () => (
  <article className="rounded-2xl border border-rose-200 bg-white shadow-soft-lift p-5 space-y-4 animate-pulse">
    <div className="flex items-start justify-between">
      <div className="flex items-center space-x-3">
        <Skeleton width="2.5rem" height="2.5rem" borderRadius="rounded-full" />
        <div className="space-y-1">
          <Skeleton width="8rem" height="1rem" borderRadius="rounded" />
          <div className="flex items-center space-x-2">
            <Skeleton width="5rem" height="1rem" borderRadius="rounded-full" />
            <Skeleton width="5rem" height="1rem" borderRadius="rounded-full" />
          </div>
        </div>
      </div>
      <div className="text-right space-y-1">
        <Skeleton width="5rem" height="1.25rem" borderRadius="rounded" />
        <Skeleton width="4rem" height="1.25rem" borderRadius="rounded" />
      </div>
    </div>
    <div className="flex flex-wrap items-center gap-3">
      <Skeleton width="6rem" height="1rem" borderRadius="rounded" />
      <Skeleton width="5rem" height="1rem" borderRadius="rounded" />
      <Skeleton width="4rem" height="1rem" borderRadius="rounded" />
    </div>
    <Skeleton width="100%" height="2.5rem" borderRadius="rounded-xl" />
  </article>
);

export const PriceHistoryChartSkeleton: React.FC = () => (
  <div className="rounded-3xl bg-white p-6 border border-rose-200 shadow-soft-lift space-y-4 animate-pulse">
    <div className="flex items-center justify-between">
      <div className="space-y-1">
        <Skeleton width="10rem" height="1.25rem" borderRadius="rounded" />
        <Skeleton width="6rem" height="0.75rem" borderRadius="rounded" />
      </div>
      <Skeleton width="4rem" height="2rem" borderRadius="rounded-full" />
    </div>
    <div className="h-64 bg-rose-50/30 rounded-xl" />
    <div className="flex items-center justify-between">
      <Skeleton width="8rem" height="1rem" borderRadius="rounded" />
      <Skeleton width="8rem" height="1rem" borderRadius="rounded" />
      <Skeleton width="8rem" height="1rem" borderRadius="rounded" />
    </div>
  </div>
);

export const ComparisonSectionSkeleton: React.FC = () => (
  <section className="space-y-4 pt-6 border-t border-rose-200">
    <div className="flex flex-col sm:flex-row sm:items-baseline justify-between gap-3">
      <div className="space-y-1">
        <Skeleton width="14rem" height="1.5rem" borderRadius="rounded" />
        <Skeleton width="20rem" height="0.75rem" borderRadius="rounded" />
      </div>
      <div className="flex items-center space-x-2">
        <Skeleton width="5rem" height="2rem" borderRadius="rounded-xl" />
        <Skeleton width="6rem" height="2rem" borderRadius="rounded-xl" />
      </div>
    </div>
    <div className="rounded-3xl border border-rose-200 overflow-hidden bg-white shadow-soft-lift divide-y divide-rose-100">
      {[...Array(5)].map((_, i) => (
        <RetailerOfferSkeleton key={i} />
      ))}
    </div>
  </section>
);

export const DealSectionSkeleton: React.FC = () => (
  <section className="py-20 bg-gradient-to-b from-ivory to-rose-50/40">
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div className="space-y-4 mb-8">
        <Skeleton width="12rem" height="1.75rem" borderRadius="rounded-full" />
        <Skeleton width="18rem" height="2.5rem" borderRadius="rounded" />
        <Skeleton width="30rem" height="1rem" borderRadius="rounded" />
      </div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {[...Array(6)].map((_, i) => (
          <ProductCardSkeleton key={i} />
        ))}
      </div>
    </div>
  </section>
);