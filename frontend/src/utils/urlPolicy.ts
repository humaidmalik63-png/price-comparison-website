/**
 * URL cleaning policy — Phase 16.7E (frontend mirror of
 * `src/services/url_policy.py`).
 *
 * Known tracking parameters (the `utm_*` family plus common ad-click ids) are
 * removed before a URL is displayed. Everything else is preserved exactly:
 * scheme, host, path, fragment and every non-tracking query parameter,
 * byte-for-byte. When nothing is removed (or the URL cannot be parsed) the
 * ORIGINAL string is returned — a URL is never re-encoded or reconstructed,
 * provenance is never changed, and a retailer URL is never invented.
 */

const KNOWN_TRACKING_PARAMS = new Set([
  'gclid',   // Google Ads click id
  'fbclid',  // Meta/Facebook click id
  'msclkid', // Microsoft Ads click id
  'mc_cid',  // Mailchimp campaign id
  'mc_eid',  // Mailchimp email id
]);

const TRACKING_PARAM_PREFIXES = ['utm_'] as const;

function isTrackingParam(rawName: string): boolean {
  const name = rawName.trim().toLowerCase();
  if (!name) return false;
  if (KNOWN_TRACKING_PARAMS.has(name)) return true;
  return TRACKING_PARAM_PREFIXES.some((prefix) => name.startsWith(prefix));
}

/** Remove known tracking parameters from a URL; return it otherwise intact. */
export function stripTrackingParams(url: string | null | undefined): string | null {
  if (url === null || url === undefined) return null;
  const text = String(url).trim();
  if (!text) return '';

  let query: string;
  let beforeQuery: string;
  let hash = '';
  const hashIndex = text.indexOf('#');
  const noHash = hashIndex >= 0 ? text.slice(0, hashIndex) : text;
  if (hashIndex >= 0) hash = text.slice(hashIndex);
  const queryIndex = noHash.indexOf('?');
  if (queryIndex < 0) {
    return text; // no query — nothing to strip, return original
  }
  beforeQuery = noHash.slice(0, queryIndex);
  query = noHash.slice(queryIndex + 1);

  const rawPairs = query ? query.split('&') : [];
  const kept: string[] = [];
  let removedAny = false;
  for (const rawPair of rawPairs) {
    const namePart = rawPair.split('=', 1)[0];
    // Decode like the backend (unquote_plus: '+' means space).
    let name = namePart;
    try {
      name = decodeURIComponent(namePart.replace(/\+/g, ' '));
    } catch {
      // keep raw name — malformed escapes stay as-is
    }
    if (isTrackingParam(name)) {
      removedAny = true;
    } else {
      kept.push(rawPair);
    }
  }

  if (!removedAny) return text; // original string, byte-exact
  const rebuiltQuery = kept.join('&');
  return `${beforeQuery}${rebuiltQuery ? `?${rebuiltQuery}` : ''}${hash}`;
}
