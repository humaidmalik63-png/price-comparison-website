"""Product Matching & Variant Integrity Service for PriceWise AI Beauty (Phase 5).

Provides strict multi-factor matching across Indian beauty catalogs:
- Brand identification and normalization
- Exact volume / net quantity extraction and compatibility (30ml != 50ml)
- Makeup shade extraction and distinction (e.g., 'Ruby Woo' != 'Velvet Teddy')
- Formulation / finish integrity (e.g., 'Waterproof' != 'Washable', 'Gel' != 'Cream')
- Barcode / GTIN exact-match layer (strongest signal)
- Unit-price normalisation (per gram / ml) for volume-tier comparison
- 3-Tier Classification + ambiguous / admin-corrected states:
  1. verified_match: Confirmed identical SKU variant. Safe for direct price arbitrage.
  2. possible_match: High similarity with minor phrasing difference or unverified shade.
  3. incompatible_mismatch: Incompatible variant. Strictly excluded from comparison.
  4. ambiguous_match: Needs human review — brand/title similar but barcode/variant unclear.
"""

from dataclasses import dataclass, field
import difflib
import re
from typing import Any, Optional
from src.database.models import Offer, Product


# ============================================================================
# Enums / constants
# ============================================================================

class MatchClassification:
    VERIFIED_MATCH = "verified_match"
    POSSIBLE_MATCH = "possible_match"
    INCOMPATIBLE_MISMATCH = "incompatible_mismatch"
    AMBIGUOUS_MATCH = "ambiguous_match"


class MatchEvidenceTier:
    """Ordered list of evidence tiers used for matching confidence."""
    BARCODE_GTIN_EXACT = "barcode_gtin_exact"       # strongest
    MANUFACTURER_ID    = "manufacturer_id"
    EXACT_SKU          = "exact_sku"
    BRAND_AND_SIZE     = "brand_and_size"           # same brand + same qty/unit
    TITLE_SIMILARITY   = "title_similarity"          # fuzzy string
    NONE               = "none"                      # fallback


class MatchStrength:
    """Phase 16.7 explainable match-strength overlay.

    This is an EVIDENCE-STRENGTH overlay derived deterministically from the
    canonical MatchClassification + MatchEvidenceTier + audit flags.  It does
    NOT replace or conflict with the canonical classification strings
    (verified_match / possible_match / ambiguous_match / incompatible_mismatch)
    which remain the stored API values everywhere in the project.

    Mapping (deterministic, never threshold-only):
      verified_match  + barcode/GTIN evidence + no tolerance flags -> exact
      verified_match  + anything else                              -> strong
      possible_match                                               -> possible
      ambiguous_match                                              -> needs_manual_review
      incompatible_mismatch                                        -> rejected
    """
    EXACT               = "exact"
    STRONG              = "strong"
    POSSIBLE            = "possible"
    REJECTED            = "rejected"
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


# Flag-marker prefixes embedded in flagged_reasons / reasons strings so the
# strength derivation (and admin review UI) can detect these conditions from
# any construction site without changing existing call signatures.
_UNIT_TOLERANCE_FLAG = "unit-label-conflict:"
_BRAND_ALIAS_FLAG = "brand-alias:"


# ============================================================================
# Brand alias registry (Phase 16.7 Stage 1)
# ============================================================================
# Only aliases backed by recorded evidence may be registered here.  Each alias
# maps a normalised brand key (letters/digits only, lower case) to a small dict
# of {alias_normalised_key, evidence} where evidence cites the source of the
# equivalence.  A brand match established *only* through an alias can never
# reach the EXACT strength tier and is always flagged for transparency.

BRAND_ALIAS_REGISTRY: dict[str, list[dict[str, str]]] = {
    # Evidence: Phase 16.7 browser investigation (2026-11-11) — Myntra lists the
    # brand as "DOT & KEY" (normalises to "dotkey") while the Purplle product
    # URL slug and catalogue use "dot-and-key" / "Dot and Key" (normalises to
    # "dotandkey").  Same brand, both written forms observed in the wild.
    "dotkey": [
        {
            "alias": "dotandkey",
            "evidence": "Myntra listing renders brand as 'DOT & KEY'; Purplle product URL slug uses 'dot-and-key' (Phase 16.7 browser investigation, 2026-11-11)",
        },
    ],
    "dotandkey": [
        {
            "alias": "dotkey",
            "evidence": "Myntra listing renders brand as 'DOT & KEY'; Purplle product URL slug uses 'dot-and-key' (Phase 16.7 browser investigation, 2026-11-11)",
        },
    ],
}


def apply_brand_alias(target_norm: str, offer_norm: str) -> tuple[bool, str]:
    """Attempt to reconcile two normalised brand keys via the alias registry.

    Returns (matched, note).  The note is empty when no alias applies.
    Only exact registry entries are honoured — no fuzzy brand guessing.
    """
    t, o = target_norm, offer_norm
    for lookup in (t, o):
        for entry in BRAND_ALIAS_REGISTRY.get(lookup, []):
            other = o if lookup == t else t
            if entry["alias"] == other and other != lookup:
                note = (
                    f"{_BRAND_ALIAS_FLAG} applied: '{lookup}' ≡ '{other}' "
                    f"(evidence: {entry['evidence']})"
                )
                return True, note
    return False, ""


# ============================================================================
# New result dataclass (extends old ProductMatchResult with extra fields)
# ============================================================================

@dataclass
class ProductMatchResult:
    """Detailed evaluation result for product/offer pairing."""
    match_classification: str  # verified_match, possible_match, incompatible_mismatch, ambiguous_match
    confidence_score: float    # 0.0 to 1.0
    is_comparable: bool        # True only if verified_match (or acceptable possible_match)
    brand_match: bool
    size_match: bool
    shade_match: bool
    formulation_match: bool
    title_similarity: float
    reasons: list[str] = field(default_factory=list)
    target_size: Optional[str] = None
    offer_size: Optional[str] = None
    target_shade: Optional[str] = None
    offer_shade: Optional[str] = None
    concentration_match: bool = True
    # --- Stage 4 extras ---
    evidence_tier: str = MatchEvidenceTier.NONE
    barcode_match: bool = False
    gtin_matched: bool = False
    unit_price_target: Optional[float] = None      # price per g or ml for target
    unit_price_offer:  Optional[float] = None      # price per g or ml for offer
    requires_human_review: bool = False
    admin_corrections_applied: bool = False
    flagged_reasons: list[str] = field(default_factory=list)  # for ambiguous matches
    # --- Phase 16.7 Stage 1: explainable strength overlay ---
    match_strength: str = ""                     # derived if left empty (see __post_init__)
    strength_reasons: list[str] = field(default_factory=list)
    brand_alias_applied: bool = False
    unit_label_tolerance: bool = False

    def __post_init__(self) -> None:
        """Deterministically derive the strength overlay when not supplied.

        The canonical match_classification string is never modified.  The
        strength overlay is computed from recorded evidence only — no arbitrary
        confidence threshold can create an exact match.
        """
        # Detect audit flags from reason markers so every construction site
        # (including existing ones) contributes to the strength derivation.
        marker_pool = (*self.reasons, *self.flagged_reasons)
        if not self.brand_alias_applied:
            self.brand_alias_applied = any(_BRAND_ALIAS_FLAG in r for r in marker_pool)
        if not self.unit_label_tolerance:
            self.unit_label_tolerance = any(_UNIT_TOLERANCE_FLAG in r for r in marker_pool)
        if self.match_strength:
            return
        reasons: list[str] = []
        c = self.match_classification
        if c == MatchClassification.INCOMPATIBLE_MISMATCH:
            strength = MatchStrength.REJECTED
            reasons.append("Rejected: a critical variant attribute (brand, size, shade, formulation or concentration) contradicts the catalogue product.")
        elif c == MatchClassification.AMBIGUOUS_MATCH:
            strength = MatchStrength.NEEDS_MANUAL_REVIEW
            reasons.append("Needs manual review: evidence is too incomplete to accept or reject automatically.")
        elif c == MatchClassification.POSSIBLE_MATCH:
            strength = MatchStrength.POSSIBLE
            reasons.append("Possible match: plausible but unconfirmed; never counted as a verified offer.")
        elif c == MatchClassification.VERIFIED_MATCH:
            if (
                self.evidence_tier == MatchEvidenceTier.BARCODE_GTIN_EXACT
                and not self.brand_alias_applied
                and not self.unit_label_tolerance
            ):
                strength = MatchStrength.EXACT
                reasons.append("Exact: verified match backed by barcode/GTIN evidence with no tolerance flags.")
            else:
                strength = MatchStrength.STRONG
                if self.evidence_tier != MatchEvidenceTier.BARCODE_GTIN_EXACT:
                    reasons.append(f"Strong (not exact): verified match but evidence tier is '{self.evidence_tier}', not barcode/GTIN-exact.")
                if self.brand_alias_applied:
                    reasons.append("Strong (not exact): brand identity was established through a registered brand alias, not the brand string itself.")
                if self.unit_label_tolerance:
                    reasons.append("Strong (not exact): a unit-label conflict (e.g. g vs ml) was tolerated on an equal quantity.")
        else:
            strength = MatchStrength.NEEDS_MANUAL_REVIEW
            reasons.append(f"Unknown classification '{c}' treated as needing manual review.")
        self.match_strength = strength
        self.strength_reasons = reasons

    def explain(self) -> dict[str, Any]:
        """Return a human-readable, evidence-focused explanation dict (admin UI)."""
        return {
            "classification": self.match_classification,
            "match_strength": self.match_strength,
            "confidence_score": self.confidence_score,
            "evidence_tier": self.evidence_tier,
            "brand_match": self.brand_match,
            "size_match": self.size_match,
            "shade_match": self.shade_match,
            "formulation_match": self.formulation_match,
            "concentration_match": self.concentration_match,
            "title_similarity": self.title_similarity,
            "barcode_match": self.barcode_match,
            "gtin_matched": self.gtin_matched,
            "unit_price_target": self.unit_price_target,
            "unit_price_offer": self.unit_price_offer,
            "target_size": self.target_size,
            "offer_size": self.offer_size,
            "target_shade": self.target_shade,
            "offer_shade": self.offer_shade,
            "brand_alias_applied": self.brand_alias_applied,
            "unit_label_tolerance": self.unit_label_tolerance,
            "requires_human_review": self.requires_human_review,
            "reasons": list(self.reasons),
            "flagged_reasons": list(self.flagged_reasons),
            "strength_reasons": list(self.strength_reasons),
        }


    @property
    def is_verified(self) -> bool:
        return self.match_classification == MatchClassification.VERIFIED_MATCH

    @property
    def is_mismatch(self) -> bool:
        return self.match_classification == MatchClassification.INCOMPATIBLE_MISMATCH

    @property
    def display_badge(self) -> str:
        if self.match_classification == MatchClassification.VERIFIED_MATCH:
            return "Verified Exact Variant"
        elif self.match_classification == MatchClassification.POSSIBLE_MATCH:
            return "Possible Match (Verification Needed)"
        elif self.match_classification == MatchClassification.AMBIGUOUS_MATCH:
            return "Ambiguous Match — Review Required"
        else:
            return "Variant Incompatible"


# ============================================================================
# Barcode / GTIN helpers
# ============================================================================

def normalise_barcode(raw: Optional[str]) -> Optional[str]:
    """Normalise a barcode / GTIN value for comparison.

    Removes hyphens/spaces/prefixes like 'GTIN-', strips leading zeros,
    returns lower-case string.  Valid EAN-13 / UPC-A lengths are accepted;
    anything else is returned as-is so it can still be used for display.
    """
    if not raw:
        return None
    cleaned = str(raw).strip().lower().replace("-", "").replace(" ", "")
    # Strip common prefixes
    for prefix in ("gtin", "ean", "upc"):
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):]
    # Strip leading zeroes but keep at least one digit
    stripped = cleaned.lstrip("0") or "0"
    return stripped


def extract_barcode_from_title(title: str) -> Optional[str]:
    """Try to pull an 8-, 12-, 13- or 14-digit number out of a product title."""
    if not title:
        return None
    digits = re.findall(r"\b(\d{8,14})\b", title)
    if digits:
        return normalise_barcode(digits[-1])  # rightmost candidate wins
    return None


def extract_barcode_from_specs(specs: dict) -> Optional[str]:
    """Pull barcode / gtin / ean / upc from specs dict (case-insensitive keys)."""
    if not specs:
        return None
    key_map = {
        "barcode": "barcode",
        "gtin": "gtin",
        "ean": "ean",
        "upc": "upc",
        "isbn": "isbn",
        "item_number": "item_number",
        "sku_code": "sku_code",
    }
    low = {k.lower(): v for k, v in specs.items()}
    for map_key, spec_key in key_map.items():
        val = low.get(map_key)
        if val:
            nb = normalise_barcode(str(val))
            if nb and len(nb) >= 8:
                return nb
    return None


def compare_barcodes(a: Optional[str], b: Optional[str]) -> tuple[bool, str]:
    """Compare two barcodes. Returns (matched, note)."""
    na = normalise_barcode(a)
    nb = normalise_barcode(b)
    if not na and not nb:
        return False, "No barcodes available for either product"
    if not na or not nb:
        return False, f"Only one side has a barcode ({na!r} vs {nb!r})"
    if na == nb:
        return True, f"Barcode match: {na}"
    # Check containment (parent-child / multipack variants sometimes share prefix)
    if na in nb or nb in na:
        return False, f"Barcode prefix overlap but not exact: {na} vs {nb}"
    return False, f"Barcode mismatch: {na} vs {nb}"


# ============================================================================
# Unit-price normalisation
# ============================================================================

def compute_unit_price(price: Optional[float], qty_val: Optional[float], qty_unit: Optional[str]) -> Optional[float]:
    """Return price-per-unit-volume (₹/g or ₹/ml) or None if unavailable."""
    if price is None or price <= 0:
        return None
    if qty_val is None or qty_val <= 0:
        return None
    try:
        return round(price / qty_val, 4)
    except ZeroDivisionError:
        return None


def compatible_units(u1: Optional[str], u2: Optional[str]) -> bool:
    """Check whether two units can be compared directly."""
    u1s, u2s = (u1 or "").lower(), (u2 or "").lower()
    if u1s == u2s:
        return True
    # Same family conversions that we accept without multiplier
    same_family = {("ml", "ml"), ("g", "g")}
    return (u1s, u2s) in same_family


# ============================================================================
# Existing helpers (unchanged)
# ============================================================================

def parse_quantity_volume(text: str) -> tuple[Optional[float], Optional[str]]:
    """
    Extract normalized numerical amount and standard unit from text or specs.
    Recognizes ml, g, gm, grams, oz, kg, l.
    Examples:
      '50 ml' -> (50.0, 'ml')
      '3.8g' -> (3.8, 'g')
      '100 gm' -> (100.0, 'g')
    """
    if not text:
        return None, None

    cleaned = str(text).lower().replace(" ", "").replace(",", ".")
    # Match decimal or int followed by unit
    match = re.search(r"(\d+(?:\.\d+)?)(ml|gm|g|grams?|oz|kg|litres?|l)", cleaned)
    if not match:
        return None, None

    val = float(match.group(1))
    unit = match.group(2)
    if unit in ("gm", "grams", "gram"):
        unit = "g"
    elif unit in ("litres", "litre"):
        unit = "l"

    return val, unit


def parse_shade(text: str, specs: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Extract recognized beauty shade names."""
    known_shades = [
        "ruby woo",
        "velvet teddy",
        "reconstruct",
        "warm nude",
        "encourage",
        "midnight black",
        "russian red",
        "diva",
        "whirl",
        "pillow talk",
        "soft pinch",
        "berry pink",
        "cherry red",
        "caramel",
        "mocha",
        "ivory",
        "beige",
    ]
    if specs and "Shade" in specs:
        return str(specs["Shade"]).strip().title()

    combined = (text or "").lower()
    for shade in known_shades:
        if shade in combined:
            return shade.title()
    return None


# Formulation keywords that must never be merged with one another.
# Ordered longest-first so e.g. "waterproof" is not shadowed by a shorter token.
_FORMULATION_KEYWORDS = (
    "waterproof",
    "washable",
    "solution",
    "lotion",
    "powder",
    "stick",
    "cream",
    "serum",
    "mask",
    "foam",
    "balm",
    "gel",
)

_PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


def parse_formulation(text: str, specs: Optional[dict[str, Any]] = None) -> Optional[str]:
    """Extract formulation keywords (waterproof, washable, gel, cream, serum, etc.)."""
    if specs:
        for k in ["Product Type", "Formulation", "Finish"]:
            if k in specs and specs[k]:
                return str(specs[k]).strip()

    combined = (text or "").lower()
    if "waterproof" in combined:
        return "Waterproof"
    if "washable" in combined:
        return "Washable"
    if "gel" in combined:
        return "Gel"
    if "cream" in combined:
        return "Cream"
    if "serum" in combined:
        return "Serum"
    if "mask" in combined:
        return "Mask"
    if "solution" in combined:
        return "Solution"
    return None


def normalise_formulation(value: str) -> str:
    """Reduce a formulation string to its canonical keyword so that
    'Gel Sunscreen' and 'Gel' compare equal, while 'Gel' and 'Cream' do not."""
    lowered = (value or "").lower()
    for keyword in _FORMULATION_KEYWORDS:
        if keyword in lowered:
            return keyword
    return lowered.strip()


def parse_concentration(text: str, specs: Optional[dict[str, Any]] = None) -> Optional[frozenset[str]]:
    """Extract stated active-ingredient percentages (e.g. '10% Niacinamide').

    Returns a frozenset of normalised percentage tokens, or None when no
    concentration is stated anywhere. Two products with different stated
    concentrations must never be merged into a verified match.
    """
    values: set[str] = set()
    if text:
        for match in _PERCENT_RE.finditer(str(text)):
            values.add(f"{match.group(1)}%")
    if specs:
        for key in ("Concentration", "Strength"):
            raw = specs.get(key)
            if raw:
                for match in _PERCENT_RE.finditer(str(raw)):
                    values.add(f"{match.group(1)}%")
    return frozenset(values) if values else None


def evaluate_product_match(
    target_brand: str,
    target_title: str,
    target_specs: Optional[dict[str, Any]] = None,
    offer_brand: str = "",
    offer_title: str = "",
    offer_variant: str = "",
    offer_specs: Optional[dict[str, Any]] = None,
    target_barcode: Optional[str] = None,
    offer_barcode: Optional[str] = None,
    reference_price: Optional[float] = None,
    offer_price: Optional[float] = None,
) -> ProductMatchResult:
    """
    Perform multi-factor matching between a target beauty product and a retailer offer.
    Enforces that size/volume mismatches, shade clashes, or formulation clashes
    are never treated as comparable.

    Stage 4 enhancements:
    - Barcode/GTIN exact-match layer is checked first (strongest signal).
    - Unit-price normalisation computed for both sides when quantities are present.
    - Ambiguous matches flagged for human review instead of silently accepted.
    - Admin corrections can override classification.
    """
    reasons: list[str] = []
    flagged_reasons: list[str] = []
    t_specs = target_specs or {}
    o_specs = offer_specs or {}

    evidence_tier = MatchEvidenceTier.NONE
    barcode_matched = False
    gtin_matched = False

    # ── Stage 4: Barcode / GTIN pre-check (strongest evidence tier) ───────────
    tb = normalise_barcode(target_barcode or extract_barcode_from_specs(t_specs))
    ob = normalise_barcode(offer_barcode or extract_barcode_from_specs(o_specs))
    if tb or ob:
        bm, note = compare_barcodes(tb, ob)
        if bm:
            barcode_matched = True
            gtin_matched = bool(nb := (tb or ob or ""))
            if len(nb) in (12, 13, 14):
                evidence_tier = MatchEvidenceTier.BARCODE_GTIN_EXACT
            else:
                evidence_tier = MatchEvidenceTier.MANUFACTURER_ID
            reasons.append(note)
        else:
            # Barcodes exist but don't match → strong negative signal
            flagged_reasons.append(note)

    # ── 1. Brand Normalization & Check ────────────────────────────────────────
    norm_t_brand = re.sub(r"[^a-z0-9]", "", target_brand.lower())
    norm_o_brand = re.sub(r"[^a-z0-9]", "", offer_brand.lower())
    brand_match = True
    if norm_t_brand and norm_o_brand:
        if norm_t_brand not in norm_o_brand and norm_o_brand not in norm_t_brand:
            # Phase 16.7: fall back to the evidence-backed alias registry before
            # declaring a brand mismatch.  An alias-based match is always
            # flagged and can never yield the EXACT strength tier.
            alias_ok, alias_note = apply_brand_alias(norm_t_brand, norm_o_brand)
            if alias_ok:
                flagged_reasons.append(alias_note)
                reasons.append(
                    f"Brand matched via registered alias: '{target_brand}' ≡ '{offer_brand}' (flagged, evidence-cited)"
                )
            else:
                brand_match = False
                reasons.append(f"Brand mismatch: '{target_brand}' vs '{offer_brand}'")

    # ── 2. Net Quantity / Volume Check ────────────────────────────────────────
    target_qty_text = str(t_specs.get("Net Quantity") or t_specs.get("Size") or target_title)
    offer_qty_text = str(o_specs.get("Net Quantity") or o_specs.get("Size") or f"{offer_variant} {offer_title}")
    t_val, t_unit = parse_quantity_volume(target_qty_text)
    o_val, o_unit = parse_quantity_volume(offer_qty_text)

    size_match = True
    target_size_str = f"{t_val}{t_unit}" if t_val is not None else None
    offer_size_str = f"{o_val}{o_unit}" if o_val is not None else None

    if t_val is not None and o_val is not None:
        if t_unit == o_unit and abs(t_val - o_val) > 0.01:
            size_match = False
            reasons.append(
                f"Size mismatch: Target is {t_val}{t_unit} but offer is {o_val}{o_unit}. 30ml cannot be compared with 50ml."
            )
        elif t_unit != o_unit:
            if {t_unit, o_unit} == {"g", "ml"} and abs(t_val - o_val) <= 0.01:
                # Phase 16.7 browser evidence (2026-11-11): the same Dot & Key
                # Watermelon sunscreen SKU is labelled "50ml" on Nykaa but
                # "50g" on Myntra, Purplle and Amazon.  Equal quantity with a
                # differing unit label is therefore tolerated as the same-size
                # SKU — but always flagged, and it can never produce the EXACT
                # strength tier (density-dependent products are not blindly
                # interchangeable across g/ml).
                flagged_reasons.append(
                    f"{_UNIT_TOLERANCE_FLAG} target {t_val}{t_unit} vs offer {o_val}{o_unit} "
                    f"— equal quantity with differing retailer unit label, tolerated (observed retailer labelling inconsistency)"
                )
            else:
                size_match = False
                reasons.append(f"Unit mismatch: Target is in {t_unit} while offer is in {o_unit}")
    elif t_val is None or o_val is None:
        flagged_reasons.append("Quantity not detected on one side — unit price unavailable")

    # ── Compute unit prices ────────────────────────────────────────────────────
    unit_price_target = compute_unit_price(reference_price, t_val, t_unit)
    unit_price_offer  = compute_unit_price(offer_price,   o_val, o_unit)

    # ── 3. Makeup Shade Check ──────────────────────────────────────────────────
    t_shade = parse_shade(target_title, t_specs)
    o_shade = parse_shade(f"{offer_variant} {offer_title}", o_specs)
    shade_match = True
    if t_shade and o_shade and t_shade.lower() != o_shade.lower():
        shade_match = False
        reasons.append(f"Shade mismatch: Target is '{t_shade}' but offer is '{o_shade}'")

    # ── 4. Formulation / Finish Check ──────────────────────────────────────────
    t_form = parse_formulation(target_title, t_specs)
    o_form = parse_formulation(f"{offer_variant} {offer_title}", o_specs)
    formulation_match = True
    if t_form and o_form:
        t_f_norm = normalise_formulation(t_form)
        o_f_norm = normalise_formulation(o_form)
        if t_f_norm and o_f_norm and t_f_norm != o_f_norm:
            formulation_match = False
            reasons.append(
                f"Formulation mismatch: Target is '{t_form}' but offer is '{o_form}'"
            )

    # ── 4b. Concentration / Strength Check ─────────────────────────────────────
    t_conc = parse_concentration(target_title, t_specs)
    o_conc = parse_concentration(f"{offer_variant} {offer_title}", o_specs)
    concentration_match = True
    if t_conc and o_conc and t_conc != o_conc:
        concentration_match = False
        reasons.append(
            "Concentration mismatch: target states "
            f"{sorted(t_conc)} but offer states {sorted(o_conc)}"
        )

    # ── 5. Title Similarity Score ──────────────────────────────────────────────
    t_clean = re.sub(r"[^a-z0-9 ]", "", target_title.lower()).strip()
    o_clean = re.sub(r"[^a-z0-9 ]", "", offer_title.lower()).strip()
    seq = difflib.SequenceMatcher(None, t_clean, o_clean)
    title_similarity = round(seq.ratio(), 3)

    # Update evidence tier based on findings
    if evidence_tier == MatchEvidenceTier.NONE:
        if brand_match and size_match and unit_price_target is not None and unit_price_offer is not None:
            evidence_tier = MatchEvidenceTier.BRAND_AND_SIZE
        elif title_similarity >= 0.85:
            evidence_tier = MatchEvidenceTier.TITLE_SIMILARITY

    # ── 6. Overall Classification & Confidence Score ───────────────────────────
    confidence = 1.0

    # Incompatible mismatch if critical variant attributes contradict
    if (
        not brand_match
        or not size_match
        or not shade_match
        or not formulation_match
        or not concentration_match
    ):
        confidence = 0.2
        return ProductMatchResult(
            match_classification=MatchClassification.INCOMPATIBLE_MISMATCH,
            confidence_score=confidence,
            is_comparable=False,
            brand_match=brand_match,
            size_match=size_match,
            shade_match=shade_match,
            formulation_match=formulation_match,
            title_similarity=title_similarity,
            reasons=reasons,
            target_size=target_size_str,
            offer_size=offer_size_str,
            target_shade=t_shade,
            offer_shade=o_shade,
            concentration_match=concentration_match,
            evidence_tier=evidence_tier,
            barcode_match=barcode_matched,
            gtin_matched=gtin_matched,
            unit_price_target=unit_price_target,
            unit_price_offer=unit_price_offer,
            requires_human_review=False,
            flagged_reasons=flagged_reasons,
        )

    # ── Verify barcode non-match: always reject ───────────────────────────────
    if barcode_matched and not gtin_matched:
        pass  # already handled above
    if not barcode_matched and tb and ob and tb != ob:
        # Barcodes present on both sides but differ → hard mismatch
        return ProductMatchResult(
            match_classification=MatchClassification.INCOMPATIBLE_MISMATCH,
            confidence_score=0.1,
            is_comparable=False,
            brand_match=brand_match,
            size_match=size_match,
            shade_match=shade_match,
            formulation_match=formulation_match,
            title_similarity=title_similarity,
            reasons=reasons + flagged_reasons,
            target_size=target_size_str,
            offer_size=offer_size_str,
            target_shade=t_shade,
            offer_shade=o_shade,
            concentration_match=concentration_match,
            evidence_tier=evidence_tier,
            barcode_match=False,
            gtin_matched=False,
            unit_price_target=unit_price_target,
            unit_price_offer=unit_price_offer,
            requires_human_review=False,
            flagged_reasons=["Product barcodes do not match — likely different product"],
        )

    # ── Possible vs Verified vs Ambiguous ─────────────────────────────────────
    quality_issues: list[str] = []
    if title_similarity < 0.70:
        quality_issues.append(f"Low title similarity ({title_similarity})")
    if t_val is None or o_val is None:
        quality_issues.append("Net quantity missing on one or both sides")
    if t_shade and not o_shade:
        quality_issues.append(f"Target shade '{t_shade}' not found in offer text")
    # NOTE: missing unit price is an analytics limitation, not identity evidence.
    # It must never downgrade an otherwise exact identity match; unit-price values
    # are still computed and returned for display/comparison purposes.

    if quality_issues and not gtin_matched:
        # Decide: POSSIBLE_MATCH or AMBIGUOUS_MATCH
        has_critical_gap = (
            title_similarity < 0.55
            or (t_val is None and o_val is None)
            or (not t_shade and not o_shade and title_similarity < 0.65)
        )
        if has_critical_gap:
            classification = MatchClassification.AMBIGUOUS_MATCH
            confidence = round(max(0.30, min(0.55, title_similarity)), 2)
            flagged_reasons.extend(quality_issues)
            reasons.extend(quality_issues)
        else:
            classification = MatchClassification.POSSIBLE_MATCH
            confidence = round(max(0.60, min(0.85, title_similarity)), 2)
            flagged_reasons.extend(quality_issues)
            if not reasons:
                reasons.append("Close match with minor descriptive differences")

        return ProductMatchResult(
            match_classification=classification,
            confidence_score=confidence,
            is_comparable=(classification == MatchClassification.POSSIBLE_MATCH),
            brand_match=brand_match,
            size_match=size_match,
            shade_match=shade_match,
            formulation_match=formulation_match,
            title_similarity=title_similarity,
            reasons=reasons,
            target_size=target_size_str,
            offer_size=offer_size_str,
            target_shade=t_shade,
            offer_shade=o_shade,
            concentration_match=concentration_match,
            evidence_tier=evidence_tier,
            barcode_match=barcode_matched,
            gtin_matched=gtin_matched,
            unit_price_target=unit_price_target,
            unit_price_offer=unit_price_offer,
            requires_human_review=(classification == MatchClassification.AMBIGUOUS_MATCH),
            flagged_reasons=flagged_reasons,
        )

    # ── Verified Match ─────────────────────────────────────────────────────────
    match_reasons = [
        "Exact variant match confirmed across brand, volume, shade, formulation, and concentration."
    ]
    if gtin_matched:
        match_reasons.append(f"GTIN verified: {nb}")
    if unit_price_target is not None and unit_price_offer is not None:
        ratio = (
            round(unit_price_offer / unit_price_target, 3)
            if unit_price_target > 0 else None
        )
        if ratio is not None:
            match_reasons.append(
                f"Unit price ratio: ₹{ratio:.3f}/g or ₹{ratio:.3f}/ml (offer/target)"
            )
    reasons.extend(match_reasons)
    return ProductMatchResult(
        match_classification=MatchClassification.VERIFIED_MATCH,
        confidence_score=0.98 if gtin_matched else 0.95,
        is_comparable=True,
        brand_match=True,
        size_match=True,
        shade_match=True,
        formulation_match=True,
        title_similarity=title_similarity,
        reasons=reasons,
        target_size=target_size_str,
        offer_size=offer_size_str,
        target_shade=t_shade,
        offer_shade=o_shade,
        concentration_match=concentration_match,
        evidence_tier=evidence_tier,
        barcode_match=barcode_matched,
        gtin_matched=gtin_matched,
        unit_price_target=unit_price_target,
        unit_price_offer=unit_price_offer,
        requires_human_review=False,
        flagged_reasons=flagged_reasons,
    )


def admin_correct_match(
    result: ProductMatchResult,
    new_classification: str,
    correction_note: str = "",
) -> ProductMatchResult:
    """Apply an admin override to a previously computed match result.

    Only approved classifications may be set:
      verified_match, possible_match, ambiguous_match, incompatible_mismatch

    Returns a *new* ProductMatchResult with corrected fields.
    """
    approved = {
        MatchClassification.VERIFIED_MATCH,
        MatchClassification.POSSIBLE_MATCH,
        MatchClassification.AMBIGUOUS_MATCH,
        MatchClassification.INCOMPATIBLE_MISMATCH,
    }
    if new_classification not in approved:
        raise ValueError(
            f"Invalid classification '{new_classification}'. "
            f"Approved: {sorted(approved)}"
        )
    is_comparable = new_classification in (
        MatchClassification.VERIFIED_MATCH,
        MatchClassification.POSSIBLE_MATCH,
    )
    needs_review = new_classification == MatchClassification.AMBIGUOUS_MATCH
    reasons = list(result.reasons)
    if correction_note:
        reasons.append(f"[Admin override] {correction_note}")
    return ProductMatchResult(
        match_classification=new_classification,
        confidence_score=result.confidence_score,
        is_comparable=is_comparable,
        brand_match=result.brand_match,
        size_match=result.size_match,
        shade_match=result.shade_match,
        formulation_match=result.formulation_match,
        title_similarity=result.title_similarity,
        reasons=reasons,
        target_size=result.target_size,
        offer_size=result.offer_size,
        target_shade=result.target_shade,
        offer_shade=result.offer_shade,
        concentration_match=getattr(result, "concentration_match", True),
        evidence_tier=result.evidence_tier,
        barcode_match=result.barcode_match,
        gtin_matched=result.gtin_matched,
        unit_price_target=result.unit_price_target,
        unit_price_offer=result.unit_price_offer,
        requires_human_review=needs_review,
        admin_corrections_applied=True,
        flagged_reasons=result.flagged_reasons,
    )


def match_product_with_offer(product: Product, offer: Offer) -> ProductMatchResult:
    """Helper to match a Product against an Offer model."""
    specs = product.specs or {}
    return evaluate_product_match(
        target_brand=product.brand,
        target_title=product.title,
        target_specs=specs,
        offer_brand=product.brand,  # Offer belongs to the product in models
        offer_title=product.title,
        offer_variant=offer.variant_name,
        offer_specs=specs,
        reference_price=offer.current_price,
    )


# ============================================================================
# Cross-product matching (Stage 4: finding which catalog product a provider
# observation or external SKU refers to)
# ============================================================================

def match_external_to_catalog(
    *,
    external_brand: str,
    external_title: str,
    external_barcode: Optional[str] = None,
    external_specs: Optional[dict[str, Any]] = None,
    catalog_products: list[dict[str, Any]],
    catalog_key_barcode: str = "barcode",
    catalog_key_brand: str = "brand",
    catalog_key_title: str = "title",
    catalog_key_specs: str = "specs",
) -> ProductMatchResult:
    """Find the best-matching catalog product for an external provider product.

    Args:
        external_brand: Brand from provider (e.g. PriceInIndia).
        external_title: Product title from provider.
        external_barcode: Optional GTIN/barcode from provider.
        external_specs: Optional specs dict from provider.
        catalog_products: List of dicts with keys matching *catalog_key_* args.
        catalog_key_barcode: Key name for barcode field in catalog dicts.
        catalog_key_brand:   Key name for brand field.
        catalog_key_title:   Key name for title field.
        catalog_key_specs:   Key name for specs dict field.

    Returns:
        Best ProductMatchResult (with catalog values populated in target fields).
    """
    if not catalog_products:
        return ProductMatchResult(
            match_classification=MatchClassification.INCOMPATIBLE_MISMATCH,
            confidence_score=0.0,
            is_comparable=False,
            brand_match=False,
            size_match=False,
            shade_match=False,
            formulation_match=False,
            title_similarity=0.0,
            reasons=["No catalog products available for matching"],
            evidence_tier=MatchEvidenceTier.NONE,
            requires_human_review=False,
            flagged_reasons=["Empty catalog"],
        )

    ext_tb = normalise_barcode(external_barcode)
    best_result: Optional[ProductMatchResult] = None
    best_score = -1.0

    for cat_prod in catalog_products:
        cat_barcode = normalise_barcode(cat_prod.get(catalog_key_barcode))
        cat_brand   = str(cat_prod.get(catalog_key_brand, "")).strip()
        cat_title   = str(cat_prod.get(catalog_key_title, "")).strip()
        cat_specs   = cat_prod.get(catalog_key_specs) or {}

        # Exact barcode hit → instant verified match
        if ext_tb and cat_barcode and ext_tb == cat_barcode:
            r = evaluate_product_match(
                target_brand=cat_brand, target_title=cat_title, target_specs=cat_specs,
                offer_brand=external_brand, offer_title=external_title,
                offer_specs=external_specs,
                target_barcode=cat_barcode, offer_barcode=ext_tb,
            )
            # The barcode pre-check inside evaluate_product_match will set gtin_matched
            # and evidence_tier to BARCODE_GTIN_EXACT automatically
            if r.gtin_matched:
                return r  # definitive

        # Otherwise run standard evaluate and pick highest score
        r = evaluate_product_match(
            target_brand=cat_brand, target_title=cat_title, target_specs=cat_specs,
            offer_brand=external_brand, offer_title=external_title,
            offer_specs=external_specs,
        )
        score = r.confidence_score
        # Bonus for matching barcode even if not identical (prefix overlap handled inside)
        if ext_tb and cat_barcode:
            if ext_tb.startswith(cat_barcode) or cat_barcode.startswith(ext_tb):
                score = min(score + 0.05, 1.0)
        if score > best_score:
            best_score = score
            best_result = r

    if best_result is None:
        return ProductMatchResult(
            match_classification=MatchClassification.INCOMPATIBLE_MISMATCH,
            confidence_score=0.0,
            is_comparable=False,
            brand_match=False, size_match=False, shade_match=False, formulation_match=False,
            title_similarity=0.0,
            reasons=["No catalog products available for matching"],
            evidence_tier=MatchEvidenceTier.NONE,
            requires_human_review=False,
            flagged_reasons=["Empty catalog"],
        )
    return best_result

