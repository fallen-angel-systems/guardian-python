"""FAS Guardian Python SDK — Protect your AI in 3 lines of code."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import requests


class ScanVerdict(str, Enum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass
class Threat:
    """Individual threat detected in the scan."""
    pattern_id: str
    pattern_name: str
    category: str
    severity: str
    matched_text: str


@dataclass
class ScanResult:
    """Result from a Guardian scan."""
    verdict: ScanVerdict
    blocked: bool
    score: float
    confidence: float
    scan_time_ms: float
    engine: str
    pattern_count: int
    threats: list[Threat] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    # V2 engine details (when available)
    lieutenant_verdict: Optional[str] = None
    lieutenant_score: Optional[float] = None
    spectre_verdict: Optional[str] = None
    spectre_confidence: Optional[float] = None
    arc_verdict: Optional[str] = None
    arc_score: Optional[float] = None
    raw: dict = field(default_factory=dict)


@dataclass
class BatchResult:
    """Result from a batch scan."""
    results: list[ScanResult]
    total: int
    blocked: int
    allowed: int


class GuardianError(Exception):
    """Base exception for Guardian SDK errors."""
    def __init__(self, message: str, status_code: int = None, response: dict = None):
        self.message = message
        self.status_code = status_code
        self.response = response
        super().__init__(self.message)


class AuthenticationError(GuardianError):
    """Raised when API key is invalid or missing."""
    pass


class RateLimitError(GuardianError):
    """Raised when rate limit is exceeded."""
    def __init__(self, message: str, retry_after: float = None, **kwargs):
        self.retry_after = retry_after
        super().__init__(message, **kwargs)


class Guardian:
    """
    FAS Guardian client — AI security in 3 lines of code.

    Usage:
        from fas_guardian import Guardian

        guardian = Guardian(api_key="fsg_your_key_here")

        result = guardian.scan("user input here")
        if result.blocked:
            print("Threat detected!")
    """

    DEFAULT_BASE_URL = "https://api.fallenangelsystems.com"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = None,
        timeout: float = 10.0,
        version: str = "v2",
    ):
        """
        Initialize the Guardian client.

        Args:
            api_key: Your FAS Guardian API key (starts with fsg_)
            base_url: API base URL (default: https://api.fallenangelsystems.com)
            timeout: Request timeout in seconds (default: 10)
            version: API version to use — "v1" or "v2" (default: "v2")
        """
        if not api_key:
            raise AuthenticationError(
                "\n"
                "╔══════════════════════════════════════════════════╗\n"
                "║  🛡️  FAS Guardian — API Key Required             ║\n"
                "╠══════════════════════════════════════════════════╣\n"
                "║                                                  ║\n"
                "║  Get your API key:                               ║\n"
                "║  → https://fallenangelsystems.com/#pricing       ║\n"
                "║                                                  ║\n"
                "║  Then use it like this:                          ║\n"
                "║  guardian = Guardian(api_key='fsg_your_key')     ║\n"
                "║                                                  ║\n"
                "╚══════════════════════════════════════════════════╝"
            )

        self.api_key = api_key
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self.timeout = timeout
        self.version = version
        self._session = requests.Session()
        self._session.headers.update({
            "X-Api-Key": self.api_key,
            "Content-Type": "application/json",
            "User-Agent": f"fas-guardian-python/1.0.0",
        })

    def scan(self, text: str) -> ScanResult:
        """
        Scan text for prompt injection and other threats.

        Args:
            text: The text to scan (typically user input)

        Returns:
            ScanResult with verdict, score, and threat details

        Raises:
            AuthenticationError: Invalid or inactive API key
            RateLimitError: Rate limit exceeded
            GuardianError: Other API errors
        """
        endpoint = f"{self.base_url}/{self.version}/scan"
        return self._do_scan(endpoint, {"text": text})

    def scan_batch(self, texts: list[str]) -> BatchResult:
        """
        Scan multiple texts in a single request (V1 only).

        Args:
            texts: List of texts to scan

        Returns:
            BatchResult with individual results and summary counts
        """
        endpoint = f"{self.base_url}/v1/scan/batch"
        resp = self._request("POST", endpoint, json={"texts": texts})
        data = resp.json()

        results = []
        for item in data.get("results", []):
            results.append(self._parse_scan_result(item))

        blocked = sum(1 for r in results if r.blocked)
        return BatchResult(
            results=results,
            total=len(results),
            blocked=blocked,
            allowed=len(results) - blocked,
        )

    def usage(self) -> dict:
        """Get current usage statistics for your API key."""
        endpoint = f"{self.base_url}/v1/usage"
        resp = self._request("GET", endpoint)
        return resp.json()

    def health(self) -> dict:
        """Check API health status."""
        endpoint = f"{self.base_url}/{self.version}/health"
        resp = self._request("GET", endpoint)
        return resp.json()

    def _do_scan(self, endpoint: str, payload: dict) -> ScanResult:
        """Execute a scan request and parse the result."""
        resp = self._request("POST", endpoint, json=payload)
        data = resp.json()
        return self._parse_scan_result(data)

    def _parse_scan_result(self, data: dict) -> ScanResult:
        """Parse a scan response into a ScanResult."""
        verdict = ScanVerdict(data.get("verdict", "ALLOW"))
        threats = [
            Threat(
                pattern_id=t.get("pattern_id", ""),
                pattern_name=t.get("pattern_name", ""),
                category=t.get("category", ""),
                severity=t.get("severity", ""),
                matched_text=t.get("matched_text", ""),
            )
            for t in data.get("threats", [])
        ]

        return ScanResult(
            verdict=verdict,
            blocked=verdict == ScanVerdict.BLOCK,
            score=data.get("score", data.get("confidence", 0)),
            confidence=data.get("confidence", data.get("score", 0)),
            scan_time_ms=data.get("scan_time_ms", 0),
            engine=data.get("engine", "unknown"),
            pattern_count=data.get("pattern_count", 0),
            threats=threats,
            categories=data.get("categories", []),
            lieutenant_verdict=data.get("lieutenant_verdict"),
            lieutenant_score=data.get("lieutenant_score"),
            spectre_verdict=data.get("spectre_verdict"),
            spectre_confidence=data.get("spectre_confidence"),
            arc_verdict=data.get("arc_verdict"),
            arc_score=data.get("arc_score"),
            raw=data,
        )

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        """Make an HTTP request with error handling."""
        kwargs.setdefault("timeout", self.timeout)
        try:
            resp = self._session.request(method, url, **kwargs)
        except requests.ConnectionError:
            raise GuardianError(f"Could not connect to {self.base_url}")
        except requests.Timeout:
            raise GuardianError(f"Request timed out after {self.timeout}s")

        if resp.status_code == 200:
            return resp

        # Handle errors
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text

        if resp.status_code in (401, 403):
            raise AuthenticationError(
                f"{detail}\n\n"
                "🔑 Need an API key? → https://fallenangelsystems.com/#pricing\n"
                "📖 Docs: https://fallenangelsystems.com/docs",
                status_code=resp.status_code,
            )
        elif resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            raise RateLimitError(
                f"Rate limit exceeded: {detail}",
                retry_after=float(retry_after) if retry_after else None,
                status_code=429,
            )
        else:
            raise GuardianError(
                f"API error ({resp.status_code}): {detail}",
                status_code=resp.status_code,
            )

    def __repr__(self) -> str:
        masked = self.api_key[:8] + "..." if len(self.api_key) > 8 else "***"
        return f"Guardian(api_key='{masked}', version='{self.version}')"
