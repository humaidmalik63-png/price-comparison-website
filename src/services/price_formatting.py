"""INR price display formatting policy — Phase 16.7C/16.7E.

Provider prices (e.g. PriceInIndia) can arrive with full float precision
("569.049988") or as formatted text ("₹1,299"). The storage layer preserves
the provider value exactly — precision is never silently lost. This module
defines the safe DISPLAY policy only:

1. Stored/compared values keep full provider precision.
2. Displayed values are rounded to at most 2 decimal places (paise precision).
3. ROUNDING POLICY (Phase 16.7E, shared verbatim with the frontend
   implementation in ``frontend/src/utils/inrPrice.ts``): round-half-up applied
   to the value's shortest decimal (``repr``) representation. Half-paise ties
   round away from zero — 0.125 -> 0.13, 1.005 -> 1.01, -42.505 -> -42.51,
   569.049988 -> 569.05. This removes Python banker's-rounding surprises and
   makes backend and frontend display byte-identical.
4. Amounts are rendered with Indian digit grouping (₹1,299.50) and the ₹
   symbol — never a fallback "?" glyph.
5. Nothing is ever invented: None / non-finite input yields None, and the
   caller decides how to render absence (e.g. em dash).

No currency conversion ever happens here, and no stored value or price
calculation is ever changed by this module.
"""

from __future__ import annotations

import decimal
import math
from decimal import Decimal
from typing import Any, Optional

INR_SYMBOL = "₹"

INR_DISPLAY_POLICY = (
    "Prices are stored with full provider precision; display values are "
    "rounded to at most 2 decimal places (paise) using round-half-up applied "
    "to the shortest decimal representation — the identical policy is "
    "implemented in the frontend (frontend/src/utils/inrPrice.ts) so both "
    "layers display the same value. Indian digit grouping is applied and no "
    "currency conversion is ever applied."
)


def is_inr_amount(value: Any) -> bool:
    """True when the value can be displayed as an INR amount (finite number)."""
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        try:
            value = float(text)
        except ValueError:
            return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number)


def round_inr_display(value: Any) -> Optional[float]:
    """Display-precision INR amount: at most 2 decimals, or None (never guessed).

    The storage value keeps full provider precision; this rounding is for
    display/API presentation only.

    Rounding policy (Phase 16.7E): round-half-up on the value's shortest
    decimal (``repr``) representation, quantized to exactly 2 decimal places.
    ``Decimal(repr(number))`` captures the shortest string that round-trips
    the float (e.g. repr(1.005) == "1.005"), so the tie behavior matches what
    a human reads — 1.005 -> 1.01, 0.125 -> 0.13, -42.505 -> -42.51 — instead
    of Python's default banker's rounding. The frontend TS implementation
    mirrors this exactly (decimal-string arithmetic on String(abs(value))).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip())
        except ValueError:
            return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    # repr() gives the shortest decimal that round-trips the float; Decimal
    # parses it exactly, so quantize sees the value a human reads.
    quantized = Decimal(repr(number)).quantize(
        Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
    )
    return float(quantized)


def format_inr(value: Any, *, include_symbol: bool = True) -> Optional[str]:
    """Format a numeric value as a display INR string.

    569        -> "₹569"
    1299.5     -> "₹1,299.50"
    569.049988 -> "₹569.05"   (float artifact rounded for display only)
    None/NaN   -> None        (absence is never rendered as a made-up number)

    Indian digit grouping is applied via the en-IN locale convention
    (last 3 digits, then pairs: 1,29,999). Implemented explicitly so the
    output is deterministic regardless of platform locale data.
    """
    rounded = round_inr_display(value)
    if rounded is None:
        return None
    negative = rounded < 0
    amount = abs(rounded)
    whole = int(amount)
    fraction = round((amount - whole) * 100)
    if fraction == 100:  # rounding carried over (e.g. 569.999 -> 570.00)
        whole += 1
        fraction = 0

    # Indian grouping: last 3 digits, then groups of 2 working right-to-left
    # (12999999 -> "1,29,99,999").
    digits = str(whole)
    if len(digits) > 3:
        last3 = digits[-3:]
        rest = digits[:-3]
        chunks = []
        while rest:
            chunks.append(rest[-2:])
            rest = rest[:-2]
        grouped = ",".join(reversed(chunks)) + "," + last3
    else:
        grouped = digits

    text = f"{grouped}.{fraction:02d}" if fraction else grouped
    body = f"{INR_SYMBOL}{text}" if include_symbol else text
    return f"-{body}" if negative else body
