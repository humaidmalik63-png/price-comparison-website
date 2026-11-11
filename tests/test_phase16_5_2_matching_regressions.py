"""Phase 16.5.2 regression tests for the product matching engine.

These tests lock in the safety rules that were being violated by the
Stage 4 downgrade path: missing *unit price* is an analytics limitation, not
identity evidence, and must never turn an exact identity match into a
POSSIBLE_MATCH. They also assert that shade, concentration, formulation,
quantity and product-identity conflicts remain hard blockers.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.services.product_matching_service import (
    MatchClassification,
    evaluate_product_match,
    parse_concentration,
)


def _match(**kwargs):
    defaults = dict(
        target_brand="Dot & Key",
        target_title="Watermelon Cooling Sunscreen SPF 50+ PA++++",
        target_specs={"Net Quantity": "50g", "Product Type": "Gel Sunscreen"},
        offer_brand="Dot & Key",
        offer_title="Watermelon Cooling Sunscreen SPF 50+ PA++++",
        offer_variant="50g Standard",
        offer_specs={"Net Quantity": "50g", "Product Type": "Gel Sunscreen"},
    )
    defaults.update(kwargs)
    return evaluate_product_match(**defaults)


# ── Exact identity ───────────────────────────────────────────────────────────

def test_identical_product_and_variant_is_verified_without_prices():
    """Prices are analytics inputs, not identity evidence."""
    result = _match()
    assert result.match_classification == MatchClassification.VERIFIED_MATCH
    assert result.is_verified and result.is_comparable
    assert result.brand_match and result.size_match
    assert result.shade_match and result.formulation_match
    assert result.concentration_match
    assert not any("Unit price unavailable" in r for r in result.reasons)
    assert not any("Unit price unavailable" in r for r in result.flagged_reasons)


def test_identical_product_computes_unit_price_when_prices_supplied():
    result = _match(reference_price=599.0, offer_price=499.0)
    assert result.match_classification == MatchClassification.VERIFIED_MATCH
    assert result.unit_price_target == 11.98  # 599 / 50g
    assert result.unit_price_offer == 9.98    # 499 / 50g


# ── Shade ────────────────────────────────────────────────────────────────────

def test_different_shade_is_incompatible():
    result = _match(
        target_brand="M.A.C",
        target_title="Retro Matte Lipstick - Ruby Woo",
        target_specs={"Shade": "Ruby Woo", "Net Quantity": "3g"},
        offer_brand="M.A.C",
        offer_title="Retro Matte Lipstick - Velvet Teddy",
        offer_variant="",
        offer_specs={"Shade": "Velvet Teddy", "Net Quantity": "3g"},
    )
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
    assert result.shade_match is False
    assert any("Shade mismatch" in r for r in result.reasons)


# ── Concentration ────────────────────────────────────────────────────────────

def test_different_concentration_is_incompatible():
    result = _match(
        target_brand="Minimalist",
        target_title="Niacinamide 10% Serum 30ml",
        target_specs={"Net Quantity": "30ml"},
        offer_brand="Minimalist",
        offer_title="Niacinamide 5% Serum 30ml",
        offer_variant="",
        offer_specs={"Net Quantity": "30ml"},
    )
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
    assert result.concentration_match is False
    assert any("Concentration mismatch" in r for r in result.reasons)


def test_same_concentration_is_verified():
    result = _match(
        target_brand="Minimalist",
        target_title="Niacinamide 10% Serum 30ml",
        target_specs={"Net Quantity": "30ml"},
        offer_brand="Minimalist",
        offer_title="Niacinamide 10% Serum 30ml",
        offer_variant="",
        offer_specs={"Net Quantity": "30ml"},
    )
    assert result.match_classification == MatchClassification.VERIFIED_MATCH
    assert result.concentration_match is True


def test_parse_concentration_extracts_percentages():
    assert parse_concentration("Niacinamide 10% Serum") == frozenset({"10%"})
    assert parse_concentration("Retinol 0.3% Cream") == frozenset({"0.3%"})
    assert parse_concentration("Sunscreen SPF 50+ PA++++") is None


# ── Formulation ──────────────────────────────────────────────────────────────

def test_different_formulation_is_incompatible():
    result = _match(
        target_brand="Biotique",
        target_title="Morning Nectar Face Cream",
        target_specs={"Net Quantity": "50g", "Product Type": "Cream"},
        offer_brand="Biotique",
        offer_title="Morning Nectar Face Gel",
        offer_variant="",
        offer_specs={"Net Quantity": "50g", "Product Type": "Gel"},
    )
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
    assert result.formulation_match is False
    assert any("Formulation mismatch" in r for r in result.reasons)


def test_waterproof_vs_washable_is_still_incompatible():
    result = _match(
        target_brand="Maybelline",
        target_title="Lash Sensational Sky High Waterproof Mascara",
        target_specs={"Net Quantity": "7.2ml", "Formulation": "Waterproof"},
        offer_brand="Maybelline",
        offer_title="Lash Sensational Sky High Washable Mascara",
        offer_variant="Washable",
        offer_specs={"Net Quantity": "7.2ml", "Formulation": "Washable"},
    )
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
    assert result.formulation_match is False


# ── Quantity ─────────────────────────────────────────────────────────────────

def test_missing_quantity_is_not_verified():
    """Unknown size must never be silently treated as confirmed equivalence."""
    result = _match(
        target_specs={},
        offer_specs={},
        target_title="Watermelon Cooling Sunscreen",
        offer_title="Watermelon Cooling Sunscreen",
    )
    assert result.match_classification != MatchClassification.VERIFIED_MATCH
    assert result.match_classification in {
        MatchClassification.POSSIBLE_MATCH,
        MatchClassification.AMBIGUOUS_MATCH,
    }
    notes = [r.lower() for r in result.reasons + result.flagged_reasons]
    assert any("quantity missing" in r or "quantity not detected" in r for r in notes)


def test_size_mismatch_is_incompatible():
    result = _match(
        target_specs={"Net Quantity": "30ml"},
        offer_specs={"Net Quantity": "50ml"},
        target_title="Minimalist Niacinamide Serum",
        offer_title="Minimalist Niacinamide Serum",
    )
    assert result.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
    assert result.size_match is False


# ── Different product under same brand ───────────────────────────────────────

def test_different_product_same_brand_is_not_verified():
    result = _match(
        target_brand="Dot & Key",
        target_title="Vitamin C Brightening Serum 30ml",
        target_specs={"Net Quantity": "30ml"},
        offer_brand="Dot & Key",
        offer_title="Ceramide Moisturizer 30ml",
        offer_variant="",
        offer_specs={"Net Quantity": "30ml"},
    )
    assert result.match_classification != MatchClassification.VERIFIED_MATCH
    assert not result.is_verified
