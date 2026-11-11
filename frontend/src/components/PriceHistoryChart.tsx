import React, { useState, useMemo } from 'react';
import { Calendar, AlertCircle } from 'lucide-react';
import type { PriceTrendPoint } from '../types';

interface PriceHistoryChartProps {
  priceHistory?: PriceTrendPoint[];
  currentPrice: number;
  originalPrice?: number;
  targetPrice?: number;
  productName: string;
  // Phase 16.6 Stage 8: provenance of the plotted points.
  // 'demo' (default) keeps the historic demo-dataset presentation;
  // 'provider_observed' renders real live observations honestly — the badge
  // and copy must never claim DEMO for real data, nor LIVE for demo data.
  dataSource?: 'demo' | 'provider_observed';
}

type TimeRange = '7d' | '30d' | '90d' | 'all';

export const PriceHistoryChart: React.FC<PriceHistoryChartProps> = ({
  priceHistory,
  currentPrice,
  targetPrice,
  productName,
  dataSource = 'demo',
}) => {
  const isProviderObserved = dataSource === 'provider_observed';
  const [selectedRange, setSelectedRange] = useState<TimeRange>('90d');

  // Filter observations by selected range
  const filteredPoints = useMemo(() => {
    if (!priceHistory || priceHistory.length === 0) {
      return [];
    }

    // Sort chronologically
    const sorted = [...priceHistory].sort(
      (a, b) => new Date(a.date).getTime() - new Date(b.date).getTime()
    );

    if (selectedRange === 'all') return sorted;

    const days = selectedRange === '7d' ? 7 : selectedRange === '30d' ? 30 : 90;
    // Fixed benchmark date only for the demo dataset (stability); real
    // provider-observed observations are filtered against the current time.
    const now = isProviderObserved ? new Date() : new Date('2026-11-01');
    const cutoff = new Date(now.getTime() - days * 24 * 60 * 60 * 1000);

    return sorted.filter((p) => new Date(p.date) >= cutoff);
  }, [priceHistory, selectedRange, isProviderObserved]);

  // Sufficient history threshold is >= 2 distinct observations
  const hasSufficientData = filteredPoints.length >= 2;

  // Calculate metrics ONLY when sufficient records exist
  const stats = useMemo(() => {
    if (!hasSufficientData) return null;
    const prices = filteredPoints.map((p) => p.price);
    const min = Math.min(...prices);
    const max = Math.max(...prices);
    const avg = Math.round(prices.reduce((sum, p) => sum + p, 0) / prices.length);
    const minPoint = filteredPoints.find((p) => p.price === min);

    return { min, max, avg, lowestStore: minPoint?.store || 'Verified Store' };
  }, [filteredPoints, hasSufficientData]);

  // Chart dimensions
  const width = 640;
  const height = 180;
  const paddingX = 40;
  const paddingY = 24;

  const chartData = useMemo(() => {
    if (!hasSufficientData) return null;

    const allPrices = filteredPoints.map((p) => p.price);
    if (targetPrice) allPrices.push(targetPrice);

    const minP = Math.min(...allPrices);
    const maxP = Math.max(...allPrices);
    const pSpread = maxP - minP || 1;

    // Coordinate mapping
    const points = filteredPoints.map((pt, i) => {
      const x = paddingX + (i / (filteredPoints.length - 1)) * (width - 2 * paddingX);
      const y = height - paddingY - ((pt.price - minP) / pSpread) * (height - 2 * paddingY);
      return { ...pt, x, y };
    });

    const targetY = targetPrice
      ? height - paddingY - ((targetPrice - minP) / pSpread) * (height - 2 * paddingY)
      : null;

    // SVG path string
    const pathD = points.reduce(
      (acc, pt, i) => `${acc} ${i === 0 ? 'M' : 'L'} ${pt.x} ${pt.y}`,
      ''
    );

    return { points, pathD, targetY, minP, maxP };
  }, [filteredPoints, hasSufficientData, targetPrice]);

  return (
    <div className="relative rounded-2xl bg-white border border-rose-100 p-5 shadow-soft-lift space-y-4">
      {/* Top Header & Range Switcher */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-rose-100/70 pb-3">
        <div>
          <div className="flex items-center space-x-2">
            <h4 className="font-editorial text-lg font-bold text-espresso-900">
              Recorded Price Volatility & History
            </h4>
            {isProviderObserved ? (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 border border-emerald-300">
                PROVIDER OBSERVED
              </span>
            ) : (
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-champagne-100 text-espresso-800 border border-champagne-300">
                DEMO DATASET
              </span>
            )}
          </div>
          <p className="text-xs text-espresso-500 mt-0.5">
            {isProviderObserved
              ? 'Timestamped observations from live price collection. Includes superseded rows — history is never deleted. Observation age is shown with every value.'
              : 'Timestamped observations across Indian retail feeds. Never fabricated.'}
          </p>
        </div>

        {/* Range Buttons */}
        <div className="flex items-center space-x-1 bg-ivory-100 p-1 rounded-xl border border-rose-100 self-start sm:self-auto">
          {(['7d', '30d', '90d', 'all'] as TimeRange[]).map((range) => (
            <button
              key={range}
              type="button"
              onClick={() => setSelectedRange(range)}
              className={`px-3 py-1 rounded-lg text-xs font-semibold uppercase tracking-wider transition-all ${
                selectedRange === range
                  ? 'bg-espresso-800 text-ivory shadow-2xs'
                  : 'text-espresso-600 hover:text-espresso-900'
              }`}
            >
              {range === 'all' ? 'All' : range.toUpperCase()}
            </button>
          ))}
        </div>
      </div>

      {/* Summary Metrics Bar (rendered only if data is sufficient) */}
      {hasSufficientData && stats ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-ivory-50 p-2.5 rounded-xl border border-rose-100/60">
            <span className="text-[10px] uppercase font-bold text-espresso-400 block">Current Best</span>
            <span className="text-base font-extrabold text-espresso-950">₹{currentPrice.toLocaleString('en-IN')}</span>
            <span className="text-[10px] text-sage-600 block">
              {isProviderObserved ? 'Latest observed' : 'Verified Active'}
            </span>
          </div>

          <div className="bg-ivory-50 p-2.5 rounded-xl border border-rose-100/60">
            <span className="text-[10px] uppercase font-bold text-espresso-400 block">Recorded Low</span>
            <span className="text-base font-extrabold text-rose-600">₹{stats.min.toLocaleString('en-IN')}</span>
            <span className="text-[10px] text-rose-500 block">at {stats.lowestStore}</span>
          </div>

          <div className="bg-ivory-50 p-2.5 rounded-xl border border-rose-100/60">
            <span className="text-[10px] uppercase font-bold text-espresso-400 block">Window Average</span>
            <span className="text-base font-extrabold text-espresso-800">₹{stats.avg.toLocaleString('en-IN')}</span>
            <span className="text-[10px] text-espresso-400 block">{filteredPoints.length} snapshots</span>
          </div>

          <div className="bg-ivory-50 p-2.5 rounded-xl border border-rose-100/60">
            <span className="text-[10px] uppercase font-bold text-espresso-400 block">Recorded High</span>
            <span className="text-base font-extrabold text-espresso-700">₹{stats.max.toLocaleString('en-IN')}</span>
            <span className="text-[10px] text-espresso-400 block">Peak Recorded</span>
          </div>
        </div>
      ) : (
        /* Honest Empty State for Insufficient History */
        <div className="p-6 rounded-xl bg-ivory-50 border border-dashed border-rose-200 text-center space-y-2">
          <AlertCircle className="w-6 h-6 text-espresso-400 mx-auto" />
          <h5 className="text-xs font-bold text-espresso-800">
            Insufficient Historical Observations ({selectedRange.toUpperCase()})
          </h5>
          <p className="text-xs text-espresso-500 max-w-md mx-auto">
            We require at least 2 verified observation points to compute statistical averages and volatility trends without fabricating data.
            Try selecting a broader time range such as <strong>90D</strong> or <strong>ALL</strong>.
          </p>
        </div>
      )}

      {/* Interactive SVG Chart Canvas */}
      {hasSufficientData && chartData && (
        <div className="relative pt-2">
          <svg
            viewBox={`0 0 ${width} ${height}`}
            className="w-full h-44 overflow-visible"
            role="img"
            aria-label={`Price trend chart for ${productName}`}
          >
            {/* Grid baseline */}
            <line
              x1={paddingX}
              y1={height - paddingY}
              x2={width - paddingX}
              y2={height - paddingY}
              stroke="#F3E4E6"
              strokeWidth="1.5"
            />

            {/* Target Price Reference Line if set */}
            {chartData.targetY !== null && (
              <g>
                <line
                  x1={paddingX}
                  y1={chartData.targetY}
                  x2={width - paddingX}
                  y2={chartData.targetY}
                  stroke="#ef4444"
                  strokeWidth="1.5"
                  strokeDasharray="4,4"
                />
                <text
                  x={width - paddingX}
                  y={chartData.targetY - 5}
                  fontSize="10"
                  fill="#ef4444"
                  fontWeight="bold"
                  textAnchor="end"
                >
                  Target ₹{targetPrice}
                </text>
              </g>
            )}

            {/* Trend line */}
            <path
              d={chartData.pathD}
              fill="none"
              stroke="#C98991"
              strokeWidth="2.5"
              strokeLinecap="round"
              strokeLinejoin="round"
            />

            {/* Data points */}
            {chartData.points.map((pt, idx) => (
              <g key={idx} className="group">
                <circle
                  cx={pt.x}
                  cy={pt.y}
                  r="4.5"
                  className="fill-white stroke-rose-500 stroke-2 hover:r-6 hover:fill-rose-500 transition-all cursor-pointer"
                />
                <text
                  x={pt.x}
                  y={pt.y - 10}
                  fontSize="10"
                  fontWeight="bold"
                  fill="#302724"
                  textAnchor="middle"
                >
                  ₹{pt.price}
                </text>
                <text
                  x={pt.x}
                  y={height - paddingY + 14}
                  fontSize="9"
                  fill="#9E948F"
                  textAnchor="middle"
                >
                  {pt.date.slice(5)}
                </text>
              </g>
            ))}
          </svg>

          {/* Chart footer legend */}
          <div className="flex items-center justify-between text-[11px] text-espresso-400 pt-2 border-t border-rose-100/50">
            <span className="flex items-center space-x-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-rose-400 inline-block"></span>
              <span>Monitored Store Offer</span>
            </span>
            {targetPrice && (
              <span className="flex items-center space-x-1.5 text-rose-600 font-medium">
                <span className="w-3 h-0.5 bg-rose-500 inline-block border-b border-dashed"></span>
                <span>Your Active Target (₹{targetPrice})</span>
              </span>
            )}
            <span className="flex items-center space-x-1">
              <Calendar className="w-3 h-3 text-espresso-400" />
              <span>Range: {selectedRange.toUpperCase()}</span>
            </span>
          </div>
        </div>
      )}
    </div>
  );
};

