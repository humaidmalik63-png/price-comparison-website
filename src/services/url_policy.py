"""URL cleaning policy — Phase 16.7E.

Provider- and retailer-facing URLs can carry tracking parameters
(``utm_source=chatgpt-plugin&…`` was observed in the Phase 16.7B live test).
This module defines the cleaning policy applied BEFORE URLs are stored or
displayed:

1. Known tracking parameters are removed (the ``utm_*`` family plus common
   ad-click identifiers). Everything else — product identifiers, pagination,
   variant and other functional query parameters — is preserved byte-exactly.
2. Malformed URLs are returned unchanged; a URL is never "reconstructed" into
   something else when parsing fails.
3. Cleaning never changes WHAT a URL points at: a provider page stays a
   provider page and an affiliate redirect stays an affiliate redirect.
   Provenance classification (``url_kind``) therefore happens on the cleaned
   URL and is unaffected.
4. A retailer product URL is never invented or reconstructed from a provider
   URL — this module can only REMOVE query parameters, never add, redirect
   or rewrite hosts/paths.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import unquote_plus, urlsplit, urlunsplit

# Known tracking-parameter families. Anything whose decoded parameter name is
# in this set (or starts with a prefix in TRACKING_PARAM_PREFIXES) is removed.
KNOWN_TRACKING_PARAMS = frozenset({
    "gclid",      # Google Ads click id
    "fbclid",     # Meta/Facebook click id
    "msclkid",    # Microsoft Ads click id
    "mc_cid",     # Mailchimp campaign id
    "mc_eid",     # Mailchimp email id
})

TRACKING_PARAM_PREFIXES = ("utm_",)

URL_CLEANING_POLICY = (
    "Known tracking parameters (utm_* family plus common ad-click ids) are "
    "removed before storage or display. All other query parameters are "
    "preserved exactly. Malformed URLs are returned unchanged. Cleaning never "
    "changes URL provenance and never fabricates retailer URLs."
)


def _is_tracking_param(name: str) -> bool:
    lowered = name.strip().lower()
    if not lowered:
        return False
    if lowered in KNOWN_TRACKING_PARAMS:
        return True
    return any(lowered.startswith(prefix) for prefix in TRACKING_PARAM_PREFIXES)


def strip_tracking_params(url: Any) -> Optional[str]:
    """Remove known tracking parameters from a URL; return it otherwise intact.

    - None/empty input maps to None/"" (never guessed into a value).
    - Only query parameters are touched; scheme, host, path and fragment are
      preserved exactly.
    - Legitimate parameters keep their original encoding byte-for-byte.
    - When no tracking parameter is present, the ORIGINAL string is returned
      (no re-encoding, no cosmetic changes).
    - Malformed URLs (e.g. unparseable host brackets) are returned unchanged.
    """
    if url is None:
        return None
    text = str(url).strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        raw_pairs = parts.query.split("&") if parts.query else []
    except ValueError:
        # Malformed URL — return unchanged, never reconstructed.
        return text

    kept: list[str] = []
    removed_any = False
    for raw_pair in raw_pairs:
        name = unquote_plus(raw_pair.split("=", 1)[0])
        if _is_tracking_param(name):
            removed_any = True
        else:
            kept.append(raw_pair)

    if not removed_any:
        return text
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "&".join(kept), parts.fragment))
