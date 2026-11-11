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
