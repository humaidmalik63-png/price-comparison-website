"""MCP Adapter Infrastructure for PriceWise AI Beauty (Phase 16.2 Stage 4).

Provides a unified interface for external data providers via Streamable HTTP MCP:
- PriceInIndia (https://mcp.priceinindia.website/mcp)
- Open Beauty Facts (https://world.openbeautyfacts.org/)

Adapters use httpx for HTTP, with timeouts, retries, rate limiting, and
structured error reporting. No provider data is fabricated — all results
come from genuine API responses or are clearly marked unavailable.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import time
from typing import Any, Optional

import httpx

logger = logging.getLogger("pricewise.adapters.mcp")

# ── Shared constants ─────────────────────────────────────────────────────────

DEFAULT_TIMEOUT_SECONDS = 8.0
DEFAULT_MAX_RETRIES = 2
DEFAULT_RATE_LIMIT_PER_MINUTE = 20  # MCP servers tend to be slower than direct APIs


# ── Result models ────────────────────────────────────────────────────────────

@dataclass
class McpCallResult:
    """Standardized result from an MCP tool call."""
    success: bool
    tool_name: str
    data: Optional[dict[str, Any]] = None
    items: list[dict[str, Any]] = field(default_factory=list)
    error_message: Optional[str] = None
    response_time_ms: float = 0.0
    retry_count: int = 0
    cached: bool = False

    @property
    def is_empty(self) -> bool:
        return not self.success or (not self.data and not self.items)

    @property
    def source_type(self) -> str:
        if self.cached:
            return "cached"
        if self.success:
            return "provider_observed"
        return "unavailable"


@dataclass
class McpConnectorHealth:
    """Health status for an MCP connector."""
    name: str
    endpoint: str
    is_configured: bool
    is_healthy: bool = True
    last_success_at: Optional[str] = None
    last_error: Optional[str] = None
    total_requests: int = 0
    failed_requests: int = 0
    avg_response_time_ms: float = 0.0
    _response_times: list[float] = field(default_factory=list, repr=False)


# ============================================================================
# Base MCP Adapter
# ============================================================================

class BaseMcpAdapter(ABC):
    """Base adapter for Streamable HTTP MCP endpoints."""

    def __init__(
        self,
        name: str,
        mcp_endpoint: str,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_retries: int = DEFAULT_MAX_RETRIES,
        rate_limit_per_minute: int = DEFAULT_RATE_LIMIT_PER_MINUTE,
    ):
        self.name = name
        self.mcp_endpoint = mcp_endpoint
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.rate_limit_per_minute = rate_limit_per_minute
        self._client: Optional [httpx.Client] = None
        self._request_timestamps: list[float] = []
        self._health = McpConnectorHealth(name=name, endpoint=mcp_endpoint, is_configured=True)

    @property
    def health(self) -> McpConnectorHealth:
        return self._health

    @property
    def status(self) -> str:
        if not self._health.is_healthy:
            return "error"
        if not self._health.last_success_at:
            return "never_run"
        return "healthy"

    # ── Rate limiting ───────────────────────────────────────────────────────

    def check_rate_limit(self) -> tuple[bool, Optional[str]]:
        now = time.time()
        self._request_timestamps = [t for t in self._request_timestamps if now - t < 60.0]
        if len(self._request_timestamps) >= self.rate_limit_per_minute:
            return False, f"Rate limit exceeded for {self.name}"
        self._request_timestamps.append(now)
        return True, None

    # ── HTTP helper ─────────────────────────────────────────────────────────

    def _make_post(
        self,
        payload: dict[str, Any],
        headers: Optional[dict[str, str]] = None,
    ) -> McpCallResult:
        """Send a POST to the MCP endpoint with retry logic."""
        url = self.mcp_endpoint
        attempt_headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            **(headers or {}),
        }
        start_ms = time.time() * 1000
        last_err: Optional[str] = None

        for attempt in range(self.max_retries + 1):
            try:
                allowed, err_msg = self.check_rate_limit()
                if not allowed:
                    self._track_failure(err_msg or "rate_limited")
                    return McpCallResult(success=False, tool_name="", error_message=err_msg or "rate_limited")

                with httpx.Client(timeout=self.timeout_seconds) as client:
                    resp = client.post(url, json=payload, headers=attempt_headers)
                    resp.raise_for_status()

                elapsed_ms = (time.time() * 1000) - start_ms
                self._health.total_requests += 1
                self._health._response_times.append(elapsed_ms)
                if len(self._health._response_times) > 100:
                    self._health._response_times = self._health._response_times[-100:]
                self._health.avg_response_time_ms = round(
                    sum(self._health._response_times) / len(self._health._response_times), 1
                )
                self._health.last_success_at = datetime.now(timezone.utc).isoformat()
                self._health.failed_requests = max(0, self._health.failed_requests - 1)
                self._health.is_healthy = True

                return self._parse_response(resp.text, resp.status_code, elapsed_ms)

            except httpx.TimeoutException:
                last_err = f"Timeout after {self.timeout_seconds}s"
            except httpx.HTTPStatusError as e:
                last_err = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            except httpx.RequestError as e:
                last_err = f"Request error: {type(e).__name__}: {e}"
            except Exception as e:
                last_err = f"Unexpected: {type(e).__name__}: {e}"

            if attempt < self.max_retries:
                wait = 0.5 * (2 ** attempt)  # exponential backoff: 0.5s, 1s
                logger.warning(f"{self.name} attempt {attempt+1}/{self.max_retries} failed: {last_err}. Retrying in {wait}s...")
                time.sleep(wait)

        self._track_failure(last_err or "max_retries_exhausted")
        return McpCallResult(
            success=False,
            tool_name="",
            error_message=last_err,
            response_time_ms=time.time() * 1000 - start_ms,
            retry_count=self.max_retries,
        )

    def _track_failure(self, error: str) -> None:
        self._health.total_requests += 1
        self._health.failed_requests += 1
        self._health.last_error = error
        self._health.is_healthy = False

    def _parse_response(self, text: str, status: int, elapsed_ms: float) -> McpCallResult:
        """Parse MCP response — handles both JSON and SSE streams."""
        try:
            # Try direct JSON parse first (some MCP implementations return JSON)
            data = json.loads(text)
            return self._extract_from_json(data, elapsed_ms)
        except json.JSONDecodeError:
            pass

        # Parse SSE stream: each event is "data: {...}\n\n"
        events: list[dict[str, Any]] = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            payload_str = line[5:].strip()
            if not payload_str:
                continue
            try:
                obj = json.loads(payload_str)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                events.append(obj)

        if not events:
            return McpCallResult(
                success=False,
                tool_name="",
                error_message="Unparseable MCP response",
                response_time_ms=elapsed_ms,
            )

        # JSON-RPC envelopes must be unwrapped exactly like a direct JSON
        # response; otherwise the raw envelope is mistaken for a product row.
        extracted_items: list[dict[str, Any]] = []
        data_payloads: list[Any] = []
        saw_jsonrpc = False
        for obj in events:
            if "jsonrpc" in obj or isinstance(obj.get("result"), dict):
                saw_jsonrpc = True
                sub = self._extract_from_json(obj, elapsed_ms)
                if sub.items:
                    extracted_items.extend(sub.items)
                elif sub.data:
                    data_payloads.append(sub.data)
            else:
                # Legacy/raw event shape: keep the event as a result item.
                extracted_items.append(obj)

        if not saw_jsonrpc:
            return McpCallResult(
                success=True,
                tool_name="",
                items=extracted_items,
                response_time_ms=elapsed_ms,
            )

        if len(data_payloads) == 1:
            data: Optional[dict[str, Any]] = data_payloads[0]
        elif data_payloads:
            data = {"responses": data_payloads}
        else:
            data = None

        return McpCallResult(
            success=bool(extracted_items or data),
            tool_name="",
            data=data,
            items=extracted_items,
            response_time_ms=elapsed_ms,
        )

    def _extract_from_json(
        self, data: dict[str, Any], elapsed_ms: float
    ) -> McpCallResult:
        """Extract tool result from a JSON MCP response.

        Handles multiple MCP response shapes:
        - Standard content array with text/JSON
        - structuredContent wrapper (PriceInIndia style)
        - Direct data/products/results keys
        """
        result = data.get("result", data)
        if not isinstance(result, dict):
            return McpCallResult(success=False, tool_name=data.get("tool_name",""),
                                 error_message=f"Unexpected result type: {type(result)}")

        # ── Priority 1: structuredContent (common in MCP tool results) ───────
        sc = result.get("structuredContent")
        if isinstance(sc, dict):
            for key in ("products", "results", "items", "data"):
                val = sc.get(key)
                if isinstance(val, list) and val:
                    return McpCallResult(
                        success=True, tool_name=data.get("tool_name", ""),
                        data=sc, items=val, response_time_ms=elapsed_ms,
                    )
            # structuredContent itself might be the payload
            if len(sc) > 1 or ("text" not in sc and "message" not in sc):
                return McpCallResult(
                    success=True, tool_name=data.get("tool_name", ""),
                    data=sc, response_time_ms=elapsed_ms,
                )

        # ── Priority 2: content array ────────────────────────────────────────
        contents = result.get("content", [])
        if contents:
            texts = [c.get("text", "") for c in contents if c.get("type") == "text"]
            if texts:
                try:
                    inner = json.loads(texts[0])
                    return McpCallResult(
                        success=True, tool_name=data.get("tool_name", ""),
                        data=inner, response_time_ms=elapsed_ms,
                    )
                except json.JSONDecodeError:
                    # Return raw text + structuredContent if available
                    extra: dict[str, Any] = {"_raw_text": texts[0][:500]}
                    if sc:
                        extra["_structured_content"] = sc
                    return McpCallResult(
                        success=True, tool_name=data.get("tool_name", ""),
                        data=extra, response_time_ms=elapsed_ms,
                    )

        # ── Priority 3: direct nested keys ───────────────────────────────────
        for key in ("data", "products", "results", "items", "catalog"):
            val = result.get(key)
            if isinstance(val, list) and val:
                return McpCallResult(
                    success=True, tool_name=data.get("tool_name", ""),
                    items=val, response_time_ms=elapsed_ms,
                )
            if isinstance(val, dict):
                return McpCallResult(
                    success=True, tool_name=data.get("tool_name", ""),
                    data=val, response_time_ms=elapsed_ms,
                )

        return McpCallResult(
            success=True, tool_name=data.get("tool_name", ""),
            data=result, response_time_ms=elapsed_ms,
        )

    # ── Public tool invocation ──────────────────────────────────────────────

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> McpCallResult:
        """Invoke an MCP tool with the given arguments.

        Uses the MCP Streamable HTTP protocol:
        POST <endpoint> with JSON-RPC 2.0 envelope containing tool call.
        """
        logger.debug(f"{self.name}: calling tool '{tool_name}' with {arguments}")
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        result = self._make_post(payload)
        result.tool_name = tool_name
        return result

    # ── Discovery ───────────────────────────────────────────────────────────

    def list_tools(self) -> McpCallResult:
        """List available tools on this MCP server."""
        payload = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "tools/list",
            "params": {},
        }
        return self._make_post(payload)
