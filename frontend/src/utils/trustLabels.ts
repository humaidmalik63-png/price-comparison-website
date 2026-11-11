/**
 * Trust label utilities — Phase 16.7 Stage 7.
 *
 * Single source of truth for the honest status mapping shown to users:
 *
 *   verified_live      — price verified live at the retailer (independently or by admin)
 *   provider_observed  — observed via provider feed, awaiting verification
 *   manual_verified    — entered and verified manually by an admin
 *   demo               — seeded demo data, never a real retailer price
 *   expired            — observation no longer current (superseded/expired/stale)
 *
 * The mapping is deliberately conservative: a status is only escalated when
 * the evidence supports it. Unknown inputs degrade to the honest
 * "unverified" label rather than a reassuring one.
 */

export type TrustLabelKey =
  | 'verified_live'
  | 'provider_observed'
  | 'provider_observed_verified'
  | 'manual_verified'
  | 'demo'
  | 'expired'
  | 'unverified';

export interface TrustLabel {
  key: TrustLabelKey;
  label: string;
  description: string;
  tone: 'positive' | 'caution' | 'neutral' | 'negative';
}

const LABELS: Record<TrustLabelKey, TrustLabel> = {
  verified_live: {
    key: 'verified_live',
    label: 'Verified Live Price',
    description: 'Observed at the retailer and independently verified.',
    tone: 'positive',
  },
  provider_observed: {
    key: 'provider_observed',
    label: 'Provider Observed — Awaiting Verification',
    description: 'Observed via a provider feed. Not independently re-checked yet.',
    tone: 'caution',
  },
  provider_observed_verified: {
    key: 'provider_observed_verified',
    label: 'Provider Observed — Admin Verified',
    description: 'Observed via a provider feed and confirmed by an administrator.',
    tone: 'positive',
  },
  manual_verified: {
    key: 'manual_verified',
    label: 'Manually Verified',
    description: 'Entered and verified manually by an administrator.',
    tone: 'positive',
  },
  demo: {
    key: 'demo',
    label: 'Demo Data',
    description: 'Seeded sample data for the demo — not a real retailer price.',
    tone: 'neutral',
  },
  expired: {
    key: 'expired',
    label: 'No Longer Current',
    description: 'This observation is no longer the current retailer price.',
    tone: 'negative',
  },
  unverified: {
    key: 'unverified',
    label: 'Unverified Price',
    description: 'Price present but not yet verified — treat with caution.',
    tone: 'caution',
  },
};

export interface TrustLabelInput {
  sourceType?: string | null;
  verificationStatus?: string | null;
  observationStatus?: string | null;
  isLiveVerified?: boolean;
  /** seconds since the observation; staleness beyond this is expired */
  freshnessSeconds?: number | null;
  staleAfterSeconds?: number;
}

/** Deterministic, evidence-based trust-label resolution. */
export function getTrustLabel(input: TrustLabelInput): TrustLabel {
  const {
    sourceType,
    verificationStatus,
    observationStatus,
    isLiveVerified = false,
    freshnessSeconds,
    staleAfterSeconds = 72 * 3600,
  } = input;

  // 1. Expired / not-current always wins — an old price is never "current".
  if (
    observationStatus === 'expired' ||
    observationStatus === 'superseded' ||
    (freshnessSeconds !== null &&
      freshnessSeconds !== undefined &&
      freshnessSeconds > staleAfterSeconds)
  ) {
    return LABELS.expired;
  }

  // 2. Demo data is always labelled demo.
  if (sourceType === 'demo') {
    return LABELS.demo;
  }

  // 3. Manual verification.
  if (sourceType === 'manual' || isLiveVerified) {
    return LABELS.manual_verified;
  }

  // 4. Provider-observed paths honour verification status.
  if (
    sourceType === 'provider_observed' ||
    sourceType === 'partner_feed' ||
    sourceType === 'cached'
  ) {
    if (verificationStatus === 'verified') {
      return LABELS.provider_observed_verified;
    }
    if (verificationStatus === 'pending' || verificationStatus === 'review_required') {
      return LABELS.provider_observed;
    }
    if (verificationStatus === 'provider_observed') {
      return LABELS.provider_observed;
    }
    return LABELS.unverified;
  }

  // 5. Live-verified source.
  if (sourceType === 'verified_live') {
    return LABELS.verified_live;
  }

  return LABELS.unverified;
}

/** Tailwind badge classes per tone (kept in one place for consistency). */
export function trustLabelToneClasses(tone: TrustLabel['tone']): string {
  switch (tone) {
    case 'positive':
      return 'bg-green-50 border-green-300 text-green-800';
    case 'caution':
      return 'bg-amber-50 border-amber-300 text-amber-800';
    case 'negative':
      return 'bg-rose-50 border-rose-300 text-rose-800';
    default:
      return 'bg-gray-50 border-gray-300 text-gray-700';
  }
}
