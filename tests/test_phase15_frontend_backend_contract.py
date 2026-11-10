"""Phase 15 — frontend/backend API contract regression test.

The React client (``frontend/src/utils/api.ts``) hard-codes the API paths it
calls. A path that drifts away from the FastAPI router is invisible in the
backend test suite and only surfaces in the deployed application as a 404.

That is exactly what happened during Phase 15:

* the client called ``/api/beauty/match-concerns`` while the router serves
  ``/api/beauty/match-skin-concerns``;
* the client called ``/api/beauty/generate-routine`` while the router serves
  ``/api/beauty/generate-routine/{routine_type}``.

Both features (skin-concern matching and routine generation) were therefore
broken in the deployed application while every backend test still passed.

This test compares every path the client uses with the real FastAPI routes and
fails when one of them does not resolve.
"""

import re
import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

API_CLIENT = BASE_DIR / "frontend" / "src" / "utils" / "api.ts"

# Path segments the client interpolates; they match any single backend segment.
PARAM = "{p}"


def _backend_routes():
    from src.api.main import app

    routes = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            if method in ("GET", "POST", "PUT", "DELETE", "PATCH"):
                routes.setdefault(path, set()).add(method)
    return routes


def _clean_raw_path(raw: str) -> str:
    """Reduce a raw template-literal fragment to the path it starts with.

    The client builds paths such as
    ``/api/products/${slug}/deal-intelligence${query ? `?${query}` : ''}``,
    so the captured fragment can contain an unterminated template expression
    and a query string. Both are stripped here.
    """
    # Stop at the first character that cannot occur inside a URL path.
    for stop_char in (" ", "\t", "`", '"', "'", "\n"):
        index = raw.find(stop_char)
        if index != -1:
            raw = raw[:index]

    # Drop a trailing template expression that never closes.
    last_open = raw.rfind("${")
    if last_open != -1 and "}" not in raw[last_open:]:
        raw = raw[:last_open]

    # Drop the query string.
    raw = raw.split("?")[0]

    # A template expression appended directly to a segment (for example
    # "/products/{id}/deal-intelligence${query}") builds the query string, not
    # a path segment. Path parameters always occupy a whole segment between
    # two slashes.
    raw = re.sub(r"(?<!/)\$\{[^}]*\}$", "", raw)

    return raw


def _normalise(path: str) -> str:
    """Collapse interpolated segments to a placeholder and drop the query."""
    path = path.split("?")[0]
    path = re.sub(r"\$\{[^}]*\}", PARAM, path)
    path = re.sub(r"\{[^}]*\}", PARAM, path)
    return path.rstrip("/") or "/"


def _client_paths():
    """Extract every API path the React client calls."""
    text = API_CLIENT.read_bytes().decode("utf-8")
    paths = set()
    for match in re.finditer(r"\$\{API_BASE_URL\}([^\`\"\n]*)", text):
        raw = _clean_raw_path(match.group(1))
        # Skip prose from error messages that merely mention the variable.
        if not raw.startswith("/"):
            continue
        normalised = _normalise(raw)
        if "${" in normalised:
            continue
        paths.add(normalised)
    return paths


def _resolves(client_path: str, backend_paths) -> bool:
    """True when a backend route matches the client path segment by segment."""
    client_segments = client_path.split("/")
    for backend_path in backend_paths:
        backend_segments = backend_path.split("/")
        if len(client_segments) != len(backend_segments):
            continue
        if all(
            c == b or c == PARAM or b == PARAM
            for c, b in zip(client_segments, backend_segments)
        ):
            return True
    return False


@pytest.fixture(scope="module")
def client_paths():
    return _client_paths()


@pytest.fixture(scope="module")
def backend_paths():
    return set(_backend_routes().keys())


def test_client_and_router_share_at_least_thirty_endpoints(client_paths, backend_paths):
    """Guard against the comparison silently becoming trivial."""
    assert len(client_paths) >= 30, (
        f"only {len(client_paths)} client paths were extracted - the extraction "
        "is probably broken"
    )
    assert len(backend_paths) >= 50, (
        f"only {len(backend_paths)} backend routes were found - the router "
        "introspection is probably broken"
    )


@pytest.mark.parametrize("client_path", sorted(_client_paths()))
def test_every_client_path_resolves_to_a_backend_route(client_path, backend_paths):
    """Each path the client calls must exist on the router."""
    assert _resolves(client_path, backend_paths), (
        f"the frontend calls '{client_path}' but the FastAPI router serves no "
        "matching route - the feature would return 404 in production"
    )


def test_known_regressions_stay_fixed():
    """The two paths that broke the deployed application."""
    client_paths = _client_paths()
    assert "/api/beauty/match-skin-concerns" in client_paths, (
        "the skin-concern matcher must call /api/beauty/match-skin-concerns, "
        "which is the route the router serves"
    )
    assert "/api/beauty/match-concerns" not in client_paths

    assert "/api/beauty/generate-routine/{p}" in client_paths, (
        "routine generation must call /api/beauty/generate-routine/{routine_type}"
    )
    assert "/api/beauty/generate-routine" not in client_paths


def test_router_serves_the_routes_the_client_relies_on(backend_paths):
    """Spot-check the routes behind the two repaired features."""
    assert "/api/beauty/match-skin-concerns" in backend_paths
    assert "/api/beauty/generate-routine/{routine_type}" in backend_paths


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
