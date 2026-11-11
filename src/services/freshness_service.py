"""Price Freshness Service — Phase 16.6 Stage 5.

Implements the application's freshness policy over real observations:

- fresh:  observed within ``FRESHNESS_FRESH_HOURS`` (default 24h)
- aging:  older than the fresh threshold, within ``FRESHNESS_AGING_HOURS``
- stale:  older than the aging threshold
- unknown: observation has no parsable timestamp (reported honestly)

Thresholds are configurable (env: ``PRICEWISE_FRESH_HOURS`` /
``PRICEWISE_AGING_HOURS``) so no freshness assumption is hardcoded across
the application. These are application policies — never guarantees of
retailer availability. Stale observations must not be presented as
currently available; age is always reported with the value itself.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from src.config import FRESHNESS_AGING_HOURS, FRESHNESS_FRESH_HOURS

FRESH = "fresh"
AGING = "aging"
STALE = "stale"
UNKNOWN = "unknown"

FRESHNESS_LABELS = {
    FRESH: "Observed within the last {fresh}h",
    AGING: "Observed {fresh}-{aging}h ago",
    STALE: "Older than {aging}h — may no longer reflect the retailer price",
    UNKNOWN: "Observation age unknown",
}


@dataclass(frozen=True)
class FreshnessPolicy:
    """Configurable freshness thresholds in hours."""

    fresh_hours: float = FRESHNESS_FRESH_HOURS
    aging_hours: float = FRESHNESS_AGING_HOURS

    def __post_init__(self):
        if self.fresh_hours <= 0 or self.aging_hours <= self.fresh_hours:
            raise ValueError(
                "freshness thresholds require 0 < fresh_hours < aging_hours "
                f"(got fresh={self.fresh_hours}, aging={self.aging_hours})"
            )

    @classmethod
    def from_env(cls) -> "FreshnessPolicy":
        return cls(
            fresh_hours=float(os.environ.get("PRICEWISE_FRESH_HOURS", FRESHNESS_FRESH_HOURS)),
            aging_hours=float(os.environ.get("PRICEWISE_AGING_HOURS", FRESHNESS_AGING_HOURS)),
        )

    def describe(self) -> str:
        return FRESHNESS_LABELS[FRESH].format(fresh=self.fresh_hours)


DEFAULT_POLICY = FreshnessPolicy()


def parse_observation_time(raw: Any) -> Optional[datetime]:
    """Parses an observation timestamp; returns None when absent/unparsable."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def observation_age_hours(
    created_at: Any,
    now: Optional[datetime] = None,
) -> Optional[float]:
    """Age of an observation in hours, or None when the timestamp is missing
    or unparsable (never guessed)."""
    parsed = parse_observation_time(created_at)
    if parsed is None:
        return None
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    age = (moment - parsed).total_seconds() / 3600.0
    return round(age, 4)


def classify_freshness(
    age_hours: Optional[float],
    policy: FreshnessPolicy = DEFAULT_POLICY,
) -> str:
    """Classify an observation age into fresh / aging / stale / unknown."""
    if age_hours is None:
        return UNKNOWN
    if age_hours <= policy.fresh_hours:
        return FRESH
    if age_hours <= policy.aging_hours:
        return AGING
    return STALE


def annotate(
    row: dict[str, Any],
    timestamp_key: str = "created_at",
    policy: FreshnessPolicy = DEFAULT_POLICY,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Add freshness fields to a copy of an observation/offer dict.

    Adds: observed_age_hours (float|None), freshness (fresh|aging|stale|
    unknown). The raw age is always included so the UI can report age
    honestly rather than only a label.
    """
    out = dict(row)
    age = observation_age_hours(out.get(timestamp_key), now=now)
    out["observed_age_hours"] = age
    out["freshness"] = classify_freshness(age, policy)
    return out


def freshness_distribution(
    observations: list[dict[str, Any]],
    timestamp_key: str = "created_at",
    policy: FreshnessPolicy = DEFAULT_POLICY,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Count observations per freshness bucket over an iterable of dicts."""
    counts = {FRESH: 0, AGING: 0, STALE: 0, UNKNOWN: 0}
    for row in observations:
        counts[classify_freshness(observation_age_hours(row.get(timestamp_key), now=now), policy)] += 1
    total = len(observations)
    return {
        "total": total,
        "counts": counts,
        "policy": {
            "fresh_hours": policy.fresh_hours,
            "aging_hours": policy.aging_hours,
        },
    }


def stale_cutoff(policy: FreshnessPolicy = DEFAULT_POLICY, now: Optional[datetime] = None) -> str:
    """ISO timestamp before which observations are stale under the policy."""
    moment = now or datetime.now(timezone.utc)
    return (moment - timedelta(hours=policy.aging_hours)).isoformat()


# ── Phase 16.7C: provider-reported freshness (PriceInIndia lastUpdated) ──────
# Phase 16.7E: timestamps beyond the future tolerance are INVALID (never
# accepted and silently classified as fresh). Within the tolerance — assumed
# clock skew — the age is clamped to zero so provider_age_hours can never be
# negative.

_MS_EPOCH_THRESHOLD = 10**12  # epochs above this are treated as milliseconds

# Accepted future tolerance: small clock-skew margin between our clock and the
# provider's. Anything further in the future than this is treated as invalid.
FUTURE_TOLERANCE_SECONDS = 300.0  # 5 minutes


def parse_epoch_seconds(raw: Any, now: Optional[datetime] = None) -> Optional[datetime]:
    """Parse a provider ``lastUpdated`` epoch value into an aware UTC datetime.

    Accepts unix seconds (e.g. 1794375906) or milliseconds (auto-detected via
    magnitude, e.g. 1794375906000), ints/floats or numeric strings.
    Returns None for anything absent, non-numeric, non-finite, non-positive,
    or further in the future than ``FUTURE_TOLERANCE_SECONDS`` (5 minutes of
    assumed clock skew) — never guessed.
    """
    if raw is None or isinstance(raw, bool):
        return None
    if isinstance(raw, str):
        text = raw.strip()
        if not text or not text.replace(".", "", 1).isdigit():
            return None
        try:
            value = float(text)
        except ValueError:
            return None
    else:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            return None
    if not math.isfinite(value) or value <= 0:
        return None
    if value >= _MS_EPOCH_THRESHOLD:  # milliseconds → seconds
        value /= 1000.0
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromtimestamp(value, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    if parsed > moment + timedelta(seconds=FUTURE_TOLERANCE_SECONDS):
        return None  # beyond the accepted future tolerance — invalid
    return parsed


def provider_freshness(
    last_updated: Any,
    policy: FreshnessPolicy = DEFAULT_POLICY,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    """Map a provider ``lastUpdated`` epoch into the observation freshness system.

    Returns a dict with provider_last_updated_iso (None when absent/unparsable
    — never guessed), provider_age_hours and provider_freshness using the same
    fresh/aging/stale/unknown buckets as application observations. The provider
    timestamp describes when the PROVIDER last refreshed the listing; it is
    recorded alongside — never instead of — the observation's own timestamp
    (stored observation timestamps are never modified by this function).

    ``provider_age_hours`` is clamped to >= 0: timestamps within the future
    tolerance (clock skew) are treated as "now", and anything further in the
    future is invalid (UNKNOWN), so a future timestamp can never silently make
    provider data appear newly observed with a negative age.
    """
    parsed = parse_epoch_seconds(last_updated, now=now)
    if parsed is None:
        return {
            "provider_last_updated_iso": None,
            "provider_age_hours": None,
            "provider_freshness": UNKNOWN,
        }
    age = observation_age_hours(parsed.isoformat(), now=now)
    if age is not None:
        age = max(0.0, age)  # clock-skew clamp: never a negative provider age
    return {
        "provider_last_updated_iso": parsed.isoformat(),
        "provider_age_hours": age,
        "provider_freshness": classify_freshness(age, policy),
    }
