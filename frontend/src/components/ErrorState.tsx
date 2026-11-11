/**
 * Error State Components for Phase 16.4
 *
 * Reusable error states for API failures, stale data warnings, and retry controls.
 */

import React from 'react';
import { AlertCircle, RefreshCw, Info, ShieldCheck, XCircle, WifiOff, Clock } from 'lucide-react';

interface ErrorStateProps {
  title?: string;
  message: string;
  onRetry?: () => void;
  retryLabel?: string;
  icon?: React.ReactNode;
  className?: string;
  showRetry?: boolean;
  isStale?: boolean;
  stalenessMessage?: string;
  onDismissStale?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Unable to Load Data',
  message,
  onRetry,
  retryLabel = 'Try Again',
  icon,
  className = '',
  showRetry = true,
  isStale = false,
  stalenessMessage,
  onDismissStale,
}) => {
  return (
    <div
      className={`rounded-2xl p-6 text-center border transition-all ${
        isStale
          ? 'bg-amber-50 border-amber-200 text-amber-800'
          : 'bg-rose-50 border-rose-200 text-rose-800'
      } ${className}`}
      role="alert"
    >
      <div className="flex flex-col items-center space-y-3">
        {icon || (
          <div
            className={`w-12 h-12 rounded-full flex items-center justify-center ${
              isStale ? 'bg-amber-100 text-amber-600' : 'bg-rose-100 text-rose-600'
            }`}
          >
            {isStale ? (
              <Clock className="w-6 h-6" />
            ) : (
              <AlertCircle className="w-6 h-6" />
            )}
          </div>
        )}

        <div className="space-y-1">
          <h3 className="font-semibold text-base sm:text-lg">
            {title}
          </h3>
          <p className="text-sm sm:text-base leading-relaxed">
            {message}
          </p>
        </div>

        {isStale && stalenessMessage && (
          <div className="flex items-center justify-center space-x-2 p-3 rounded-xl bg-amber-100/60 border border-amber-200 text-amber-700 text-sm">
            <Info className="w-4 h-4 shrink-0" />
            <span>{stalenessMessage}</span>
            {onDismissStale && (
              <button
                onClick={onDismissStale}
                className="ml-2 text-amber-600 hover:text-amber-800 font-medium underline"
              >
                Dismiss
              </button>
            )}
          </div>
        )}

        {showRetry && onRetry && (
          <button
            onClick={onRetry}
            className={`px-4 py-2 rounded-xl text-sm font-bold transition-all shadow-xs flex items-center space-x-1.5 ${
              isStale
                ? 'bg-amber-600 hover:bg-amber-700 text-ivory'
                : 'bg-rose-600 hover:bg-rose-700 text-ivory'
            }`}
          >
            <RefreshCw className="w-4 h-4" />
            <span>{retryLabel}</span>
          </button>
        )}
      </div>
    </div>
  );
};

export const EmptyState: React.FC<{
  title?: string;
  message: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
}> = ({
  title = 'No Data Available',
  message,
  icon,
  action,
  className = '',
}) => (
  <div className={`rounded-2xl p-8 text-center bg-ivory-50 border border-rose-100 ${className}`}>
    <div className="flex flex-col items-center space-y-4">
      {icon || (
        <div className="w-16 h-16 rounded-full bg-ivory-100 flex items-center justify-center text-espresso-300">
          <XCircle className="w-8 h-8" />
        </div>
      )}
      <div className="space-y-1">
        <h3 className="font-semibold text-base sm:text-lg text-espresso-800">
          {title}
        </h3>
        <p className="text-sm sm:text-base text-espresso-600 leading-relaxed">
          {message}
        </p>
      </div>
      {action && (
        <div className="pt-2">
          {action}
        </div>
      )}
    </div>
  </div>
);

export const StalePriceWarning: React.FC<{
  freshnessSeconds: number;
  onRefresh?: () => void;
  onDismiss?: () => void;
  className?: string;
}> = ({ freshnessSeconds, onRefresh, onDismiss, className = '' }) => {
  const hours = Math.floor(freshnessSeconds / 3600);
  const minutes = Math.floor((freshnessSeconds % 3600) / 60);

  const formatStaleness = () => {
    if (hours > 0) return `${hours}h ${minutes}m ago`;
    if (minutes > 0) return `${minutes}m ago`;
    return 'Just now';
  };

  const isVeryStale = freshnessSeconds > 24 * 3600; // > 24 hours
  const isStale = freshnessSeconds > 72 * 3600; // > 72 hours (STALE_AFTER_HOURS)

  return (
    <div
      className={`rounded-xl p-4 border flex flex-col sm:flex-row sm:items-center justify-between gap-3 ${
        isVeryStale
          ? 'bg-amber-50 border-amber-300 text-amber-900'
          : isStale
            ? 'bg-amber-50 border-amber-200 text-amber-800'
            : 'bg-sage-50 border-sage-200 text-sage-800'
      } ${className}`}
      role="status"
      aria-live="polite"
    >
      <div className="flex items-center space-x-2">
        {isStale ? (
          <Clock className="w-5 h-5 text-amber-600" />
        ) : (
          <ShieldCheck className="w-5 h-5 text-sage-600" />
        )}
        <div className="flex flex-col">
          <span className="text-xs font-semibold uppercase tracking-wider">
            {isVeryStale ? 'Price Data Very Stale' : isStale ? 'Price Data May Be Stale' : 'Data Freshness'}
          </span>
          <span className="text-sm font-mono">
            Last updated: {formatStaleness()}
          </span>
        </div>
      </div>

      <div className="flex items-center space-x-2">
        {onRefresh && (
          <button
            onClick={onRefresh}
            className={`px-3 py-1.5 rounded-lg text-xs font-bold transition-all flex items-center space-x-1 ${
              isStale
                ? 'bg-amber-600 hover:bg-amber-700 text-ivory'
                : 'bg-sage-600 hover:bg-sage-700 text-ivory'
            }`}
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>Refresh Prices</span>
          </button>
        )}
        {onDismiss && (
          <button
            onClick={onDismiss}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-espresso-500 hover:text-espresso-700 transition-colors"
          >
            Dismiss
          </button>
        )}
      </div>
    </div>
  );
};

export const ConnectivityStatus: React.FC<{
  isOnline: boolean;
  isBackendAvailable: boolean;
  lastChecked?: string;
  onRetry?: () => void;
  className?: string;
}> = ({ isOnline, isBackendAvailable, lastChecked, onRetry, className = '' }) => {
  if (isOnline && isBackendAvailable) {
    return (
      <div className={`flex items-center space-x-2 text-xs text-sage-700 bg-sage-50 border border-sage-200 rounded-xl px-3 py-2 ${className}`}>
        <ShieldCheck className="w-4 h-4 text-sage-600" />
        <span>Backend connected • Live data available</span>
        {lastChecked && (
          <span className="text-espresso-400 ml-2">(checked {lastChecked})</span>
        )}
      </div>
    );
  }

  if (!isOnline) {
    return (
      <div className={`flex items-center space-x-2 text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-xl px-3 py-2 ${className}`}>
        <WifiOff className="w-4 h-4 text-rose-600" />
        <span>You appear to be offline</span>
        {onRetry && (
          <button
            onClick={onRetry}
            className="ml-2 text-rose-600 hover:text-rose-800 font-medium underline text-xs"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div className={`flex items-center space-x-2 text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-xl px-3 py-2 ${className}`}>
      <AlertCircle className="w-4 h-4 text-amber-600" />
      <span>Backend temporarily unavailable • Using cached data</span>
      {lastChecked && (
        <span className="text-espresso-400 ml-2">(last checked {lastChecked})</span>
      )}
      {onRetry && (
        <button
          onClick={onRetry}
          className="ml-2 text-amber-600 hover:text-amber-800 font-medium underline text-xs"
        >
          Retry
        </button>
      )}
    </div>
  );
};

export const ApiFailureInline: React.FC<{
  error?: Error | string | null;
  onRetry?: () => void;
  retryLabel?: string;
  fallbackMessage?: string;
  className?: string;
}> = ({ error, onRetry, retryLabel = 'Retry', fallbackMessage = 'Failed to load data', className = '' }) => {
  if (!error) return null;

  const message = error instanceof Error ? error.message : error;

  return (
    <div className={`rounded-xl p-4 bg-rose-50 border border-rose-200 text-rose-800 ${className}`} role="alert">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center space-x-2">
          <AlertCircle className="w-5 h-5 text-rose-600 shrink-0" />
          <div>
            <p className="font-medium text-sm">{fallbackMessage}</p>
            <p className="text-xs text-rose-600 font-mono">{message}</p>
          </div>
        </div>
        {onRetry && (
          <button
            onClick={onRetry}
            className="px-3 py-1.5 rounded-lg text-xs font-bold bg-rose-600 hover:bg-rose-700 text-ivory transition-all flex items-center space-x-1 shrink-0"
          >
            <RefreshCw className="w-3.5 h-3.5" />
            <span>{retryLabel}</span>
          </button>
        )}
      </div>
    </div>
  );
};