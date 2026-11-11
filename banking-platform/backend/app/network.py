"""Fictional payment-network protocol with bounded, reference-safe retries."""

from __future__ import annotations

import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from prometheus_client import Counter, Histogram

from app.errors import DomainError

log = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 4096
MAX_RETRY_DELAY = 1.0
NETWORK_FAILURES = Counter(
    "banking_external_network_failures_total", "Failed provider attempts", ["category"]
)
NETWORK_RETRIES = Counter("banking_external_network_retries_total", "Bounded provider retries")
NETWORK_LATENCY = Histogram(
    "banking_external_network_latency_seconds", "Authorization operation latency", ["mode"]
)


@dataclass(frozen=True)
class NetworkDecision:
    approved: bool
    network_reference: str


@dataclass(frozen=True)
class NetworkSettings:
    mode: str = "stub"
    base_url: str = "http://127.0.0.1:8091"
    connect_timeout_seconds: float = 0.5
    read_timeout_seconds: float = 1.0
    max_attempts: int = 3
    backoff_seconds: float = 0.1

    def __post_init__(self) -> None:
        url = urlsplit(self.base_url)
        if self.mode not in {"stub", "http"}:
            raise ValueError("NETWORK_MODE must be stub or http")
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError("NETWORK_BASE_URL must be HTTP(S) without credentials, query or fragment")
        if not 0 < self.connect_timeout_seconds <= 5 or not 0 < self.read_timeout_seconds <= 10:
            raise ValueError("Network connect/read timeouts must be positive and bounded by 5/10 seconds")
        if not 1 <= self.max_attempts <= 3 or not 0 <= self.backoff_seconds <= 1:
            raise ValueError("Network attempts must be 1..3 and backoff 0..1 seconds")

    @classmethod
    def from_env(cls) -> NetworkSettings:
        return cls(
            mode=os.getenv("NETWORK_MODE", "stub"),
            base_url=os.getenv("NETWORK_BASE_URL", "http://127.0.0.1:8091"),
            connect_timeout_seconds=float(os.getenv("NETWORK_CONNECT_TIMEOUT_SECONDS", "0.5")),
            read_timeout_seconds=float(os.getenv("NETWORK_READ_TIMEOUT_SECONDS", "1")),
            max_attempts=int(os.getenv("NETWORK_MAX_ATTEMPTS", "3")),
            backoff_seconds=float(os.getenv("NETWORK_BACKOFF_SECONDS", "0.1")),
        )


class PaymentNetworkClient:
    def __init__(
        self,
        settings: NetworkSettings | None = None,
        http_client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ):
        self.settings = settings or NetworkSettings.from_env()
        self.http_client = http_client
        self.sleep = sleep
        self.now = now or (lambda: datetime.now(UTC))

    def authorize(
        self, transaction_id: str, amount_minor: int, currency: str, correlation_id: str | None = None
    ) -> NetworkDecision:
        reference = str(UUID(str(transaction_id)))
        if type(amount_minor) is not int or not 0 < amount_minor <= 1_000_000_000_000:
            raise ValueError("A positive bounded integer amount is required")
        if currency not in {"USD", "EUR", "GBP"}:
            raise ValueError("Unsupported currency")
        with NETWORK_LATENCY.labels(mode=self.settings.mode).time():
            if self.settings.mode == "stub":
                return NetworkDecision(amount_minor != 13, f"stub-{reference}")
            if self.http_client is not None:
                return self._authorize(self.http_client, reference, amount_minor, currency, correlation_id)
            timeout = httpx.Timeout(
                connect=self.settings.connect_timeout_seconds,
                read=self.settings.read_timeout_seconds,
                write=1.0,
                pool=1.0,
            )
            # Redirects are disabled: references remain on the configured origin.
            with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=True) as client:
                return self._authorize(client, reference, amount_minor, currency, correlation_id)

    def _authorize(
        self, client: httpx.Client, reference: str, amount: int, currency: str, correlation_id: str | None
    ) -> NetworkDecision:
        headers = {
            "Idempotency-Key": reference,
            "Accept": "application/json",
            "User-Agent": "educational-banking-platform/1.0",
        }
        if correlation_id and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", correlation_id):
            headers["X-Request-ID"] = correlation_id
        payload = {"transactionId": reference, "amountMinor": amount, "currency": currency}
        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                with client.stream(
                    "POST",
                    self.settings.base_url.rstrip("/") + "/authorizations",
                    json=payload,
                    headers=headers,
                ) as response:
                    status = response.status_code
                    if status == 429 or 500 <= status <= 599:
                        NETWORK_FAILURES.labels(category="RATE_LIMIT" if status == 429 else "HTTP_5XX").inc()
                        delay = self._retry_delay(attempt, response.headers.get("Retry-After"))
                        category = f"HTTP_{status}"
                    elif status != 200:
                        NETWORK_FAILURES.labels(category="PERMANENT").inc()
                        raise DomainError(502, f"Payment network rejected the request (HTTP {status}).")
                    else:
                        raw = bytearray()
                        for chunk in response.iter_bytes(chunk_size=MAX_RESPONSE_BYTES):
                            raw.extend(chunk)
                            if len(raw) > MAX_RESPONSE_BYTES:
                                NETWORK_FAILURES.labels(category="INVALID_RESPONSE").inc()
                                raise DomainError(502, "Payment network returned an invalid response.")
                        try:
                            import json

                            body = json.loads(raw)
                        except (ValueError, UnicodeError):
                            NETWORK_FAILURES.labels(category="INVALID_RESPONSE").inc()
                            raise DomainError(
                                502, "Payment network returned an unreadable response."
                            ) from None
                        if (
                            not isinstance(body, dict)
                            or set(body) != {"approved", "networkReference"}
                            or type(body["approved"]) is not bool
                            or not isinstance(body["networkReference"], str)
                            or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", body["networkReference"])
                        ):
                            NETWORK_FAILURES.labels(category="INVALID_RESPONSE").inc()
                            raise DomainError(502, "Payment network returned an invalid response.")
                        return NetworkDecision(body["approved"], body["networkReference"])
            except httpx.TransportError:
                NETWORK_FAILURES.labels(category="TRANSPORT").inc()
                # Timeout is ambiguous: the stable reference may already have been accepted.
                category = "TRANSPORT"
                delay = self._retry_delay(attempt, None)
            except httpx.DecodingError:
                NETWORK_FAILURES.labels(category="INVALID_RESPONSE").inc()
                raise DomainError(502, "Payment network returned an unreadable response.") from None
            if attempt == self.settings.max_attempts or delay > MAX_RETRY_DELAY:
                log.warning(
                    "payment_network_unavailable",
                    extra={"transaction_id": reference, "attempt": attempt, "category": category},
                )
                raise DomainError(
                    503,
                    "Payment network is temporarily unavailable; retry with the same transaction reference.",
                )
            log.info(
                "payment_network_retry",
                extra={
                    "transaction_id": reference,
                    "attempt": attempt,
                    "category": category,
                    "delay_seconds": delay,
                },
            )
            NETWORK_RETRIES.inc()
            self.sleep(delay)
        raise AssertionError("Retry loop exhausted without a result")

    def _retry_delay(self, attempt: int, retry_after: str | None) -> float:
        backoff = min(self.settings.backoff_seconds * 2 ** (attempt - 1), MAX_RETRY_DELAY)
        if retry_after is None:
            return backoff
        try:
            seconds = int(retry_after)
            # A provider's very large integer must not overflow float conversion.
            return min(seconds, 2) if seconds >= 0 else backoff
        except ValueError:
            try:
                date = parsedate_to_datetime(retry_after)
                if date.tzinfo is None:
                    return backoff
                return max(0.0, (date - self.now()).total_seconds())
            except (ValueError, TypeError, OverflowError):
                return backoff
