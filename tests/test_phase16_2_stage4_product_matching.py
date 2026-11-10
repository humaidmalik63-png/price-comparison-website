"""Tests for Phase 16.2 Stage 4: Product Matching Engine.

Verifies barcode/GTIN matching, unit-price normalisation, ambiguous-detection,
admin correction of matches, and cross-catalog product matching with evidence
tiers. No fabricated data — only algorithmic validation against real schemas.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from src.services.product_matching_service import (
    MatchClassification,
    MatchEvidenceTier,
    evaluate_product_match,
    admin_correct_match,
    match_external_to_catalog,
    compare_barcodes,
    compute_unit_price,
    normalise_barcode,
    parse_quantity_volume,
)


# ── Barcode helpers ───────────────────────────────────────────────────────────

class TestBarcodeHelpers:
    def test_normalise_strips_hyphens_and_spaces(self):
        assert normalise_barcode("890-123456-7890") == "8901234567890"
        assert normalise_barcode("890 123456 7890") == "8901234567890"

    def test_normalise_strips_ean_upc_prefixes(self):
        """EAN/UPC/GTIN prefixes are stripped when followed by hyphen/space."""
        assert normalise_barcode("EAN-8901234567890") == "8901234567890"
        assert normalise_barcode("UPC-8901234567890") == "8901234567890"
        assert normalise_barcode("GTIN-8901234567890") == "8901234567890"
        # 'isbn' is deliberately NOT stripped
        assert normalise_barcode("ISBN-978-0-123456-78-9").startswith("isbn")

    def test_normalise_leading_zeros_removed(self):
        assert normalise_barcode("00008901234567890") == "8901234567890"

    def test_normalise_returns_none_for_empty_input(self):
        assert normalise_barcode("") is None
        assert normalise_barcode(None) is None
        # non-empty garbage is returned as-is (no digit-only validation here)
        assert normalise_barcode("not-a-barcode!") == "notabarcode!"

    def test_compare_barcodes_same_exact(self):
        matched, note = compare_barcodes("8901234567890", "890-123456-7890")
        assert matched is True
        assert "match" in note.lower()   # note format: "Barcode match: ..."

    def test_compare_barcodes_different(self):
        matched, note = compare_barcodes("8901234567890", "1234567890123")
        assert matched is False
        assert "mismatch" in note.lower()  # note format: "Barcode mismatch: ..."

    def test_compare_barcodes_one_none(self):
        matched, _ = compare_barcodes("8901234567890", None)
        assert matched is False

    def test_compare_barcodes_both_none(self):
        matched, _ = compare_barcodes(None, None)
        assert matched is False


# ── Unit price computation ────────────────────────────────────────────────────

class TestUnitPrice:
    @pytest.mark.parametrize("qty_text,expected_val,expected_unit", [
        ("50 ml", 50.0, "ml"),
        ("100g", 100.0, "g"),
        ("75 mL", 75.0, "ml"),
        ("200 Grams", 200.0, "g"),
        ("abc", None, None),
    ])
    def test_parse_quantity_volume(self, qty_text, expected_val, expected_unit):
        val, unit = parse_quantity_volume(qty_text)
        assert val == expected_val
        assert unit == expected_unit

    @pytest.mark.parametrize("price,qty_val,qty_unit,expected", [
        (500.0, 50.0, "ml", 10.0),
        (1000.0, 100.0, "g", 10.0),
        (0, 50.0, "ml", None),
        (500.0, None, None, None),
    ])
    def test_compute_unit_price(self, price, qty_val, qty_unit, expected):
        result = compute_unit_price(price, qty_val, qty_unit)
        assert result == expected

    def test_compatible_units_ml_ml(self):
        from src.services.product_matching_service import compatible_units
        assert compatible_units("ml", "ml") is True
        assert compatible_units("mL", "ml") is True

    def test_compatible_units_g_g(self):
        from src.services.product_matching_service import compatible_units
        assert compatible_units("g", "g") is True
        assert compatible_units("Grams", "Grams") is True

    def test_compatible_units_cross_family_false(self):
        from src.services.product_matching_service import compatible_units
        assert compatible_units("ml", "g") is False
        assert compatible_units("g", "oz") is False  # different family


# ── evaluate_product_match ────────────────────────────────────────────────────

class TestEvaluateProductMatch:
    def test_gtin_exact_match_yields_verified(self):
        """GTIN exact match → verified_match, confidence ≈ 0.98."""
        res = evaluate_product_match(
            target_brand="The Ordinary",
            target_title="Niacinamide 10% + Zinc 1%",
            offer_brand="The Ordinary",
            offer_title="Niacinamide 10% + Zinc 1%",
            target_barcode="8901234567890",
            offer_barcode="8901234567890",
            reference_price=399.0,
            offer_price=299.0,
        )
        assert res.match_classification == MatchClassification.VERIFIED_MATCH
        assert res.confidence_score >= 0.95
        assert res.gtin_matched is True
        assert res.barcode_match is True
        assert res.is_comparable is True

    def test_gtin_mismatch_different_brands(self):
        """Different brands + different GTIN → incompatible_mismatch."""
        res = evaluate_product_match(
            target_brand="Nykaa",
            target_title="Coconut Hair Oil 200ml",
            offer_brand="Kesh",
            offer_title="Coconut Hair Oil 200ml",
            target_barcode="8901111111111",
            offer_barcode="8902222222222",
            reference_price=200.0,
            offer_price=180.0,
        )
        assert res.brand_match is False
        assert res.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH

    def test_brand_only_match(self):
        """Same brand, no size/specs → possible or ambiguous."""
        res = evaluate_product_match(
            target_brand="Minimalist",
            target_title="Hyaluronic Acid Serum",
            offer_brand="Minimalist",
            offer_title="Hyaluronic Acid + Vitamin B5 Serum",
            reference_price=599.0,
            offer_price=549.0,
        )
        assert res.brand_match is True

    def test_shade_mismatch_causes_incompatible(self):
        """Same product but different shades → incompatible_mismatch."""
        res = evaluate_product_match(
            target_brand="Maybelline",
            target_title="Fit Me Matte + Poreless Foundation",
            target_specs={"Shade": "Fair"},
            offer_brand="Maybelline",
            offer_title="Fit Me Matte + Poreless Foundation",
            offer_variant="SPF 18",
            offer_specs={"Shade": "Medium"},
            reference_price=499.0,
            offer_price=449.0,
        )
        # Shade conflict drives classification to incompatible
        assert res.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert res.formulation_match is True

    def test_formulation_conflict(self):
        """Solution vs Mask on same acid → cannot be verified_match."""
        res = evaluate_product_match(
            target_brand="The Ordinary",
            target_title="Salicylic Acid 2% Solution",
            target_specs={"Formulation": "Solution"},
            offer_brand="The Ordinary",
            offer_title="Salicylic Acid 2% Mask",
            offer_specs={"Formulation": "Mask"},
            reference_price=399.0,
            offer_price=499.0,
        )
        # Classification must differ from VERIFIED (formulation is a hard blocker)
        assert res.match_classification != MatchClassification.VERIFIED_MATCH
        assert len(res.reasons) > 0

    def test_empty_brands_no_crash(self):
        """Both empty brands is an edge case — at minimum does not crash."""
        res = evaluate_product_match(target_brand="", target_title="X")
        assert isinstance(res.match_classification, str)
        assert isinstance(res.reasons, list)

    def test_size_match_with_quantity(self):
        res = evaluate_product_match(
            target_brand="Biotique",
            target_title="Morning Nectar Face Cream",
            target_specs={"Size": "50 ml"},
            offer_brand="Biotique",
            offer_title="Morning Nectar Face Cream",
            offer_specs={"Size": "50 ml"},
            reference_price=300.0,
            offer_price=280.0,
        )
        assert res.size_match is True


# ── Admin correct match ───────────────────────────────────────────────────────

class TestAdminCorrectMatch:
    def _make_result(self, **overrides):
        defaults = {
            "match_classification": MatchClassification.POSSIBLE_MATCH,
            "confidence_score": 0.55,
            "brand_match": True,
            "size_match": True,
            "shade_match": True,
            "formulation_match": True,
            "title_similarity": 0.9,
            "evidence_tier": MatchEvidenceTier.BRAND_AND_SIZE,
            "barcode_match": False,
            "gtin_matched": False,
            "is_comparable": True,
            "requires_human_review": False,
            "reasons": ["Brand and size match"],
            "flagged_reasons": [],
            "display_badge": "possible_match",
            "target_size": None,
            "offer_size": None,
            "target_shade": None,
            "offer_shade": None,
            "unit_price_target": None,
            "unit_price_offer": None,
        }
        defaults.update(overrides)
        from types import SimpleNamespace
        return SimpleNamespace(**defaults)

    def test_upgrade_possible_to_verified(self):
        stored = self._make_result()
        res = admin_correct_match(stored, MatchClassification.VERIFIED_MATCH, "Manual review confirmed identical product")
        assert res.match_classification == MatchClassification.VERIFIED_MATCH
        assert res.admin_corrections_applied is True
        assert any("Admin override" in r for r in res.reasons)

    def test_reject_flagged_match(self):
        stored = self._make_result(match_classification=MatchClassification.POSSIBLE_MATCH,
                                   is_comparable=False, requires_human_review=True,
                                   reasons=["Size/shade mismatch"], flagged_reasons=["Possible shade conflict"])
        res = admin_correct_match(stored, MatchClassification.INCOMPATIBLE_MISMATCH, "Confirmed different variant by admin")
        assert res.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert res.requires_human_review is False

    def test_invalid_classification_rejected(self):
        stored = self._make_result()
        with pytest.raises(ValueError, match="Invalid classification"):
            admin_correct_match(stored, "banana", "test note")


# ── match_external_to_catalog ─────────────────────────────────────────────────

class TestMatchExternalToCatalog:
    def test_empty_catalog_returns_incompatible(self):
        """Passing an empty catalog list yields an incompatible_mismatch."""
        res = match_external_to_catalog(
            external_brand="TestBrand",
            external_title="Test Product",
            catalog_products=[],
        )
        assert res.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH
        assert res.confidence_score == 0.0
        assert "No catalog products" in res.reasons[0]

    def test_barcode_match_within_catalog(self):
        """A catalog entry whose barcode matches external gets highest score."""
        res = match_external_to_catalog(
            external_brand="TestBrand",
            external_title="Serum 30ml",
            external_barcode="8901234567890",
            external_specs={"Net Quantity": "30 ml"},
            catalog_products=[
                {
                    "brand": "TestBrand",
                    "title": "Serum 30ml",
                    "specs": {"Net Quantity": "30 ml"},
                    "barcode": "8901234567890",
                }
            ],
        )
        # Should get VERIFIED_MATCH because barcode matched exactly
        assert res.gtin_matched is True
        assert res.match_classification == MatchClassification.VERIFIED_MATCH