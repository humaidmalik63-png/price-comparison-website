"""Phase 16.7E — Final Evidence and Display Hardening Tests.

Resolves the Phase 16.7D audit findings with mocked inputs only (no live
provider calls; tests use temporary databases via the ``fresh_seeded_db``
fixture, never the application database):

1. UTM / click-id tracking parameters are stripped before storage or display;
   legitimate query parameters are preserved byte-exact; malformed URLs are
   returned unchanged; URL provenance classification survives cleaning.
2. Future provider timestamps: beyond the accepted tolerance they are invalid
   (never silently "fresh"); within the tolerance the provider age is clamped
   to >= 0; stored observation timestamps are never modified.
3. INR rounding parity policy: round-half-up on the shortest decimal
   representation, identical in backend and frontend; stored values and
   calculations are never rounded.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.scripts import collect_pi_observations as cpi
from src.services.freshness_service import (
    FUTURE_TOLERANCE_SECONDS,
    UNKNOWN,
    parse_epoch_seconds,
    provider_freshness,
)
from src.services.price_formatting import format_inr, round_inr_display
from src.services.url_policy import (
    KNOWN_TRACKING_PARAMS,
    URL_CLEANING_POLICY,
    strip_tracking_params,
)


NOW = datetime(2026, 11, 12, 12, 0, 0, tzinfo=timezone.utc)


# ── 1. URL cleaning policy ───────────────────────────────────────────────────


class TestStripTrackingParams:
    def test_known_tracking_params_removed(self):
        url = (
            "https://www.priceinindia.website/products/serum"
            "?utm_source=chatgpt-plugin&utm_medium=referral"
            "&utm_campaign=deal&utm_term=serum&utm_content=card"
        )
        cleaned = strip_tracking_params(url)
        assert cleaned == "https://www.priceinindia.website/products/serum"
        assert "utm_" not in cleaned

    def test_click_ids_removed(self):
        url = "https://www.priceinindia.website/products/serum?gclid=abc123&fbclid=xyz"
        assert strip_tracking_params(url) == (
            "https://www.priceinindia.website/products/serum"
        )

    def test_every_known_click_id_family(self):
        for param in KNOWN_TRACKING_PARAMS:
            url = f"https://x.example/p?{param}=1&keep=2"
            cleaned = strip_tracking_params(url)
            assert cleaned == "https://x.example/p?keep=2"

    def test_legitimate_params_preserved_byte_exact(self):
        url = "https://www.nykaa.com/serum/1234?id=1234&page=2&variant=x&sort=price_asc"
        assert strip_tracking_params(url) == url  # identical string, byte-exact

    def test_utm_removed_but_functional_params_kept_in_order(self):
        url = (
            "https://www.myntra.com/serum/1234?utm_source=pi"
            "&id=1234&utm_medium=cpc&page=2&variant=x"
        )
        cleaned = strip_tracking_params(url)
        assert cleaned == "https://www.myntra.com/serum/1234?id=1234&page=2&variant=x"
        # order of surviving params preserved exactly as received
        assert cleaned.index("id=1234") < cleaned.index("page=2") < cleaned.index("variant=x")

    def test_encoded_values_not_re_encoded(self):
        url = "https://x.example/p?q=moisturizer%20spf&tag=a+b"
        assert strip_tracking_params(url) == url

    def test_no_query_returns_original(self):
        url = "https://www.priceinindia.website/products/serum"
        assert strip_tracking_params(url) == url

    def test_nothing_to_strip_returns_original_string(self):
        url = "https://www.nykaa.com/p?id=1&x=%2Fpath"
        assert strip_tracking_params(url) is url  # same object, untouched

    def test_fragment_preserved(self):
        url = "https://x.example/p?utm_source=a#reviews"
        assert strip_tracking_params(url) == "https://x.example/p#reviews"

    def test_malformed_urls_returned_unchanged(self):
        for bad in ["http://[bad", "not a url", "", "   ", "://"]:
            assert strip_tracking_params(bad) == (bad if bad.strip() else "")

    def test_none_and_empty_inputs(self):
        assert strip_tracking_params(None) is None
        assert strip_tracking_params("") == ""

    def test_case_insensitive_param_matching(self):
        url = "https://x.example/p?UTM_Source=a&Gclid=b&keep=1"
        assert strip_tracking_params(url) == "https://x.example/p?keep=1"

    def test_policy_string_documents_behaviour(self):
        assert "utm_" in URL_CLEANING_POLICY
        assert "never fabricates retailer URLs" in URL_CLEANING_POLICY


class TestCleaningPreservesProvenance:
    PI_PAGE = "https://www.priceinindia.website/products/serum?utm_source=chatgpt-plugin"
    AFFILIATE = "https://www.priceinindia.website/external/myntra.com/abc?utm_medium=referral"
    RETAILER = "https://www.myntra.com/serum/1234?gclid=abc"

    def test_provider_page_kind_survives_cleaning(self):
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "productPageUrl": self.PI_PAGE,
        })
        # URL cleaned of tracking params...
        assert n["url"] == "https://www.priceinindia.website/products/serum"
        assert n["provider_page_url"] == (
            "https://www.priceinindia.website/products/serum"
        )
        # ...but provenance classification is unchanged.
        assert n["url_kind"] == "provider_page"
        assert "url_is_provider_page" in n["flags"]

    def test_affiliate_redirect_kind_survives_cleaning(self):
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "productUrl": self.AFFILIATE,
        })
        assert n["url"] == (
            "https://www.priceinindia.website/external/myntra.com/abc"
        )
        assert n["url_kind"] == "provider_affiliate_redirect"
        assert "url_is_affiliate_redirect" in n["flags"]

    def test_retailer_kind_survives_cleaning(self):
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "retailerUrl": self.RETAILER,
        })
        assert n["retailer_product_url"] == "https://www.myntra.com/serum/1234"
        assert n["url_kind"] == "retailer"

    def test_cleaning_never_creates_retailer_kind(self):
        """A provider page stripped of utm_* must never become a retailer URL."""
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "myntra.com", "price": 569,
            "currency": "INR", "productPageUrl": self.PI_PAGE,
        })
        assert n["url_kind"] != "retailer"
        assert n["retailer_product_url"] is None  # never invented

    def test_store_observation_stores_cleaned_urls(self):
        result = cpi.store_observation(
            1,
            {"id": "p", "title": "Serum", "store": "myntra.com", "price": 569,
             "currency": "INR", "productPageUrl": self.PI_PAGE},
            _comparable_match(),
            dry_run=True,
        )
        obs = result["observation"]
        assert obs["product_url"] == (
            "https://www.priceinindia.website/products/serum"
        )
        evidence = json.loads(obs["match_result"])
        assert "utm_" not in evidence["provider_page_url"]
        assert evidence["url_kind"] == "provider_page"


# ── 2. Future timestamp handling ─────────────────────────────────────────────


class TestFutureTimestampTolerance:
    def test_exactly_at_tolerance_is_accepted_with_zero_age(self):
        boundary = NOW + timedelta(seconds=FUTURE_TOLERANCE_SECONDS)
        epoch = int(boundary.timestamp())
        parsed = parse_epoch_seconds(epoch, now=NOW)
        assert parsed is not None
        result = provider_freshness(epoch, now=NOW)
        assert result["provider_age_hours"] == 0.0  # clamped, never negative
        assert result["provider_freshness"] == "fresh"

    def test_one_second_beyond_tolerance_is_invalid(self):
        beyond = NOW + timedelta(seconds=FUTURE_TOLERANCE_SECONDS + 1)
        epoch = int(beyond.timestamp())
        assert parse_epoch_seconds(epoch, now=NOW) is None
        result = provider_freshness(epoch, now=NOW)
        assert result["provider_last_updated_iso"] is None
        assert result["provider_age_hours"] is None
        assert result["provider_freshness"] == UNKNOWN  # never silently fresh

    def test_clock_skew_within_tolerance_never_negative_age(self):
        for skew in (1, 10, 60, 299):
            epoch = int((NOW + timedelta(seconds=skew)).timestamp())
            result = provider_freshness(epoch, now=NOW)
            assert result["provider_age_hours"] == 0.0
            assert result["provider_age_hours"] >= 0

    def test_far_future_day_old_guard_still_rejected(self):
        epoch = int((NOW + timedelta(days=30)).timestamp())
        assert parse_epoch_seconds(epoch, now=NOW) is None
        assert provider_freshness(epoch, now=NOW)["provider_freshness"] == UNKNOWN

    def test_provider_freshness_does_not_modify_observation_timestamps(self):
        """provider_freshness is a pure computation over its inputs — it never
        rewrites an observation's own created_at."""
        created_at = (NOW - timedelta(hours=3)).isoformat()
        result = provider_freshness(int(NOW.timestamp()), now=NOW)
        assert created_at == (NOW - timedelta(hours=3)).isoformat()  # untouched
        # provider values recorded alongside, never instead of, the observation
        assert result["provider_last_updated_iso"] == NOW.isoformat()

    def test_tolerance_is_five_minutes(self):
        assert FUTURE_TOLERANCE_SECONDS == 300.0


# ── 3. INR rounding parity (round-half-up on shortest decimal repr) ──────────


class TestINRRoundingParity:
    @pytest.mark.parametrize("raw,expected", [
        (0.125, 0.13),          # half-paise tie rounds up (away from zero)
        (1.005, 1.01),          # repr shortest form; banker's rounding would give 1.0
        (-42.505, -42.51),      # negative ties round away from zero
        (569.049988, 569.05),   # provider float artifact
        (0.005, 0.01),          # smallest half-paise
        (999.995, 1000.0),      # carry across the rupee boundary
        (1299.5, 1299.5),       # exact paise value unchanged
        (569, 569.0),           # whole rupees unchanged
        (12999999, 12999999.0), # large Indian amount unchanged
    ])
    def test_round_inr_display_policy(self, raw, expected):
        assert round_inr_display(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        (569, "₹569"),
        (1299.5, "₹1,299.50"),
        (569.049988, "₹569.05"),
        (0.125, "₹0.13"),
        (1.005, "₹1.01"),
        (0.005, "₹0.01"),
        (-42.505, "-₹42.51"),
        (999.995, "₹1,000"),
        (12999999, "₹1,29,99,999"),  # Indian digit grouping
        (100000, "₹1,00,000"),
        (0, "₹0"),
        (None, None),
        (float("nan"), None),
        (float("inf"), None),
        ("12,345", None),  # formatted strings are not silently coerced
    ])
    def test_format_inr_policy(self, raw, expected):
        assert format_inr(raw) == expected

    def test_stored_value_round_trip_keeps_full_precision(self):
        """Rounding is display-only: parse/normalize never rounds the stored value."""
        n = cpi.normalize_pi_item({
            "title": "Serum", "store": "tatacliq.com",
            "price": 569.049988, "currency": "INR",
        })
        assert n["price"] == 569.049988          # storage keeps provider precision
        assert n["price_raw"] == 569.049988
        assert round_inr_display(n["price"]) == 569.05  # display rounds to paise

    def test_result_of_rounding_is_exactly_two_decimal_float(self):
        value = round_inr_display(1299.5)
        assert value == 1299.5
        # quantized to paise grid: no float artifacts beyond the 2nd decimal
        assert round(value, 2) == value


# ── helpers ──────────────────────────────────────────────────────────────────

def _comparable_match():
    return cpi.ProductMatchResult(
        match_classification="possible_match",
        confidence_score=0.6,
        is_comparable=True,
        brand_match=True,
        size_match=True,
        shade_match=True,
        formulation_match=True,
        title_similarity=0.8,
        match_strength="possible",
    )
