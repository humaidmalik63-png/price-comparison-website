/**
 * Phase 16.7C/16.7E — Safe INR display-formatting policy (frontend mirror of
 * `src/services/price_formatting.py`).
 *
 * Storage keeps full provider precision (e.g. 569.049988); display values are
 * rounded to at most 2 decimal places (paise) and rendered in INR with Indian
 * digit grouping (₹1,29,99,999). No currency conversion ever happens here.
 * Absence is never rendered as a made-up number.
 *
 * ROUNDING POLICY (Phase 16.7E, shared verbatim with the backend): round-half-up
 * applied to the value's shortest decimal representation. Half-paise ties round
 * away from zero — 0.125 → 0.13, 1.005 → 1.01, -42.505 → -42.51,
 * 569.049988 → 569.05. Implemented as decimal-string arithmetic on
 * String(abs(value)) so the tie behavior matches what a human reads (avoiding
 * float artifacts like 1.005 * 100 === 100.49999...), then the sign is
 * re-applied. The backend quantizes Decimal(repr(number)) with ROUND_HALF_UP,
 * which is the identical policy.
 */

export const INR_SYMBOL = '₹';

/** True when the value can be displayed as an INR amount (finite number). */
export function isINRAmount(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

/** Expand an exponent-form decimal string ("5e-07") to plain digits ("0.0000005").
 * Mirrors what the backend's Decimal(repr(number)) sees: the same shortest
 * decimal digits, just in a different notation. */
function expandExponentForm(text: string): string | null {
  const m = text.match(/^(\d+)(?:\.(\d*))?[eE]([+-]?\d+)$/);
  if (!m) return null;
  const intPart = m[1];
  const fracPart = m[2] || '';
  const exp = Number(m[3]);
  const digits = intPart + fracPart;
  const point = intPart.length + exp;
  if (point <= 0) return `0.${'0'.repeat(-point)}${digits}`;
  if (point >= digits.length) return digits + '0'.repeat(point - digits.length);
  return `${digits.slice(0, point)}.${digits.slice(point)}`;
}

/** Display-precision INR amount: at most 2 decimals, or null (never guessed). */
export function roundINRDisplay(value: unknown): number | null {
  if (!isINRAmount(value)) return null;
  const negative = value < 0;
  // String() of a finite JS number gives the shortest decimal that
  // round-trips — the same representation the backend's repr() produces.
  // Exponent-form strings (e.g. "1e+21", "5e-7") are expanded to plain
  // digits so the identical digit algorithm applies (no float multiply,
  // which loses precision at extreme magnitudes).
  let text = String(Math.abs(value));
  if (text.includes('e') || text.includes('E')) {
    text = expandExponentForm(text) ?? text;
  }
  const dotIndex = text.indexOf('.');
  const whole = dotIndex < 0 ? text : text.slice(0, dotIndex);
  const fraction = dotIndex < 0 ? '' : text.slice(dotIndex + 1);

  let carried = false;
  let wholeDigits = whole.replace(/^0+(?=\d)/, '') || '0';
  let paise: number;
  if (fraction.length <= 2) {
    paise = Number(fraction.padEnd(2, '0') || '0');
  } else {
    // Round the paise digits half-up on the digits beyond the 2nd.
    const kept = fraction.slice(0, 2);
    const rest = fraction.slice(2);
    paise = Number(kept);
    if (rest[0] >= '5') {
      paise += 1;
      if (paise === 100) {
        paise = 0;
        carried = true;
      }
    }
  }
  if (carried) {
    wholeDigits = String(Number(wholeDigits) + 1);
  }

  const magnitude = Number(`${wholeDigits}.${String(paise).padStart(2, '0')}`);
  const rounded = negative ? -magnitude : magnitude;
  // Guard against any residual float artifact in the reconstruction.
  return Math.abs(Math.round(magnitude * 100) - magnitude * 100) < 1e-9
    ? rounded
    : Math.round(rounded * 100) / 100;
}

/** Format for display: "₹569", "₹1,299.50", 569.049988 → "₹569.05". */
export function formatINR(value: unknown, includeSymbol = true): string | null {
  const rounded = roundINRDisplay(value);
  if (rounded === null) return null;
  // Match the backend exactly: paise are shown when non-zero ("₹1,299.50"),
  // and dropped entirely when the value is a whole rupee amount ("₹569").
  // Number.isInteger avoids float-multiply artifacts on huge magnitudes.
  const hasPaise = !Number.isInteger(rounded);
  const formatter = new Intl.NumberFormat('en-IN', {
    minimumFractionDigits: hasPaise ? 2 : 0,
    maximumFractionDigits: 2,
  });
  const text = formatter.format(Math.abs(rounded));
  const body = `${includeSymbol ? INR_SYMBOL : ''}${text}`;
  return rounded < 0 ? `-${body}` : body;
}
