/**
 * MatchBadge Component for Phase 16.4 Product Matching Integration
 *
 * Displays visual indicators of product match confidence for offers.
 * Shows classification (verified_match, possible_match, ambiguous_match, incompatible_mismatch)
 * with color coding and explanation.
 */

import React from 'react';
import { CheckCircle2, AlertCircle, XCircle, HelpCircle } from 'lucide-react';

interface MatchBadgeProps {
  classification: 'verified_match' | 'possible_match' | 'ambiguous_match' | 'incompatible_mismatch' | null;
  confidence?: number; // 0.0 to 1.0
  reasons?: string[];
  flaggedReasons?: string[];
  onReview?: () => void;
  size?: 'sm' | 'md' | 'lg';
}

export const MatchBadge: React.FC<MatchBadgeProps> = ({
  classification,
  confidence = 0,
  reasons = [],
  flaggedReasons = [],
  onReview,
  size = 'md',
}) => {
  if (!classification) {
    return (
      <span className="inline-flex items-center space-x-1 px-2 py-1 rounded-full text-[10px] font-medium bg-gray-50 border border-gray-300 text-gray-600">
        <HelpCircle className="w-3 h-3" />
        <span>No Match</span>
      </span>
    );
  }

  const getClassificationConfig = () => {
    switch (classification) {
      case 'verified_match':
        return {
          bg: 'bg-green-50',
          border: 'border-green-300',
          text: 'text-green-800',
          icon: <CheckCircle2 className="w-3 h-3 text-green-600" />,
          label: 'Verified Match',
          description: 'This product is an exact match with confidence',
        };
      case 'possible_match':
        return {
          bg: 'bg-yellow-50',
          border: 'border-yellow-300',
          text: 'text-yellow-800',
          icon: <AlertCircle className="w-3 h-3 text-yellow-600" />,
          label: 'Possible Match',
          description: 'This product may match but needs verification',
        };
      case 'ambiguous_match':
        return {
          bg: 'bg-orange-50',
          border: 'border-orange-300',
          text: 'text-orange-800',
          icon: <AlertCircle className="w-3 h-3 text-orange-600" />,
          label: 'Ambiguous Match',
          description: 'This product may be similar but uncertain',
        };
      case 'incompatible_mismatch':
        return {
          bg: 'bg-red-50',
          border: 'border-red-300',
          text: 'text-red-800',
          icon: <XCircle className="w-3 h-3 text-red-600" />,
          label: 'Incompatible',
          description: 'This product is different from the target',
        };
      default:
        return {
          bg: 'bg-gray-50',
          border: 'border-gray-300',
          text: 'text-gray-800',
          icon: <HelpCircle className="w-3 h-3 text-gray-600" />,
          label: 'Unknown',
          description: 'Classification not available',
        };
    }
  };

  const config = getClassificationConfig();

  // Size variants
  const sizeClasses = {
    sm: 'px-1.5 py-0.5 text-[9px]',
    md: 'px-2 py-1 text-[10px]',
    lg: 'px-2.5 py-1.5 text-xs',
  };

  return (
    <div className="relative inline-block group">
      <span
        className={`inline-flex items-center space-x-1 ${sizeClasses[size]} rounded-full border ${config.bg} ${config.border} ${config.text} font-medium transition-all hover:shadow-sm`}
      >
        {config.icon}
        <span className="ml-1">{config.label}</span>
        {confidence > 0 && (
          <span className="ml-1 text-current opacity-75">({Math.round(confidence * 100)}%)</span>
        )}
      </span>

      {/* Tooltip on hover */}
      <div className="absolute bottom-full left-1/2 transform -translate-x-1/2 mb-2 hidden group-hover:block z-10 w-max max-w-xs p-2 bg-espresso-900 text-ivory text-[10px] rounded-lg shadow-lg pointer-events-none">
        <div className="font-semibold mb-1">{config.description}</div>
        {reasons.length > 0 && (
          <div>
            <div className="font-medium mb-0.5">Reasons:</div>
            <ul className="list-disc list-inside space-y-0.5 text-ivory-300">
              {reasons.slice(0, 3).map((reason, idx) => (
                <li key={idx}>{reason}</li>
              ))}
              {reasons.length > 3 && <li>...and {reasons.length - 3} more</li>}
            </ul>
          </div>
        )}
        {flaggedReasons.length > 0 && (
          <div className="mt-1 pt-1 border-t border-ivory-700">
            <div className="font-medium text-rose-400">Flags:</div>
            <ul className="list-disc list-inside space-y-0.5 text-rose-300">
              {flaggedReasons.slice(0, 2).map((reason, idx) => (
                <li key={idx}>{reason}</li>
              ))}
            </ul>
          </div>
        )}
        {onReview && (
          <div className="mt-1 pt-1 border-t border-ivory-700">
            <button
              onClick={onReview}
              className="text-ivory-100 hover:text-ivory font-medium underline cursor-pointer"
            >
              Review classification
            </button>
          </div>
        )}
      </div>
    </div>
  );
};