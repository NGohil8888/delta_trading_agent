"""
agent/delta_transport.py -- the real network implementation of the
DeltaAPITransport protocol declared in agent/delta_client.py.

This is deliberately its own module, separate from delta_client.py: the
client's validation/normalization logic is transport-agnostic and is
tested against a FakeTransport (see tests/test_delta_client.py). Only this
module ever imports `requests` or touches HMAC signing.

Signing scheme is exactly as documented in KNOWLEDGE.md, distilled from
https://docs.delta.exchange/:
  signature = HMAC-SHA256(secret, method + timestamp + path[+query] + body)
sent as the `signature` header alongside `api-key` and `timestamp`. A
`User-Agent` header is required -- requests without one can be rejected at
the CDN layer with a generic 4xx that looks like a bad key or bad payload.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Mapping, Optional

import requests


class DeltaTransportError(RuntimeError):
    """Raised for network/HTTP-level failures, before DeltaClient ever
    gets to interpret a response body. Kept distinct from DeltaAPIError/
    DeltaResponseError (which are about the response *shape*) so callers
    can tell "couldn't reach Delta" apart from "Delta rejected the
    request"."""


class DeltaRequestsTransport:
    """Signed HTTP transport backed by `requests`, satisfying
    agent.delta_client.DeltaAPITransport (structural typing -- no explicit
    inheritance needed)."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        api_secret: str,
        timeout: float = 10.0,
        user_agent: str = "delta-trading-agent/1.0",
    ) -> None:
        if not api_key or not api_secret:
            raise DeltaTransportError(
                "DELTA_API_KEY and DELTA_API_SECRET are both required to "
                "make authenticated Delta API calls."
            )
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.api_secret = api_secret
        self.timeout = timeout
        self.user_agent = user_agent
        self.session = requests.Session()

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
        query_string = self._encode_query(params)
        headers = self._signed_headers("GET", path, query_string, "")
        response = self.session.get(
            self.base_url + path + query_string,
            headers=headers,
            timeout=self.timeout,
        )
        return self._parse(response)

    def post(self, path: str, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        body = json.dumps(dict(payload), separators=(",", ":")) if payload else ""
        headers = self._signed_headers("POST", path, "", body)
        response = self.session.post(
            self.base_url + path,
            headers=headers,
            data=body,
            timeout=self.timeout,
        )
        return self._parse(response)

    # ------------------------------------------------------------------
    def _signed_headers(self, method: str, path: str, query_string: str, body: str) -> dict:
        # Delta's server clock tolerance is tight (a few seconds) -- this
        # must be wall-clock time at send, not cached.
        timestamp = str(int(time.time()))
        message = method + timestamp + path + query_string + body
        signature = hmac.new(
            self.api_secret.encode("utf-8"),
            message.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "api-key": self.api_key,
            "timestamp": timestamp,
            "signature": signature,
            "User-Agent": self.user_agent,
            "Content-Type": "application/json",
        }

    @staticmethod
    def _encode_query(params: Optional[Mapping[str, Any]]) -> str:
        if not params:
            return ""
        # Built by hand (not requests' own param handling) because the
        # exact query string has to be signed AND sent identically --
        # letting requests re-encode params after signing risks a
        # mismatch that fails auth with a confusing error.
        parts = [f"{key}={value}" for key, value in params.items() if value is not None]
        return "?" + "&".join(parts) if parts else ""

    @staticmethod
    def _parse(response: "requests.Response") -> Mapping[str, Any]:
        try:
            return response.json()
        except ValueError as exc:
            raise DeltaTransportError(
                f"Delta API returned a non-JSON response (HTTP {response.status_code}): "
                f"{response.text[:200]!r}"
            ) from exc


__all__ = ["DeltaRequestsTransport", "DeltaTransportError"]
