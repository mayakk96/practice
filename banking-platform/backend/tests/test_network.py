import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from app.errors import DomainError
from app.network import NetworkDecision, NetworkSettings, PaymentNetworkClient

REFERENCE = "66c22679-29b8-45ec-82ea-260c536e5758"
VALID = {"approved": True, "networkReference": "net-123"}


def client_for(handler, **settings):
    delays = []
    client = PaymentNetworkClient(
        NetworkSettings(mode="http", base_url="https://network.example.test", **settings),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=delays.append,
        now=lambda: datetime(2026, 11, 9, tzinfo=UTC),
    )
    return client, delays


def test_stub_is_deterministic_and_needs_no_network():
    client = PaymentNetworkClient(NetworkSettings())
    assert client.authorize(REFERENCE, 100, "USD") == NetworkDecision(True, "stub-" + REFERENCE)
    assert client.authorize(REFERENCE, 13, "USD").approved is False


def test_serializes_only_reference_amount_currency_and_stable_headers():
    def provider(request):
        import json

        assert request.method == "POST"
        assert request.url.path == "/authorizations"
        assert request.headers["Idempotency-Key"] == REFERENCE
        assert request.headers["X-Request-ID"] == "correlation-1"
        assert json.loads(request.content) == {
            "transactionId": REFERENCE,
            "amountMinor": 500,
            "currency": "USD",
        }
        return httpx.Response(200, json=VALID)

    client, delays = client_for(provider)
    assert client.authorize(REFERENCE, 500, "USD", "correlation-1") == NetworkDecision(True, "net-123")
    assert delays == []


def test_retries_transient_failures_with_same_reference_exponential_backoff():
    calls = []

    def provider(request):
        calls.append(request.headers["Idempotency-Key"])
        return httpx.Response(500 if len(calls) < 3 else 200, json=VALID)

    client, delays = client_for(provider)
    assert client.authorize(REFERENCE, 100, "EUR").approved
    assert calls == [REFERENCE] * 3
    assert delays == [0.1, 0.2]


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409, 422, 301, 302])
def test_permanent_errors_and_redirects_never_retry_or_expose_provider_body(status):
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(status, content=b"private downstream details")

    client, delays = client_for(provider)
    with pytest.raises(DomainError) as error:
        client.authorize(REFERENCE, 100, "GBP")
    assert "private" not in str(error.value)
    assert len(calls) == 1
    assert delays == []


@pytest.mark.parametrize(
    "retry_after,expected",
    [("0", 0.0), ("1", 1.0), ("Mon, 09 Nov 2026 00:00:01 GMT", 1.0), ("invalid", 0.1), ("-2", 0.1)],
)
def test_retry_after_seconds_dates_and_invalid_fallback(retry_after, expected):
    calls = []

    def provider(request):
        calls.append(request)
        return (
            httpx.Response(429, headers={"Retry-After": retry_after})
            if len(calls) == 1
            else httpx.Response(200, json=VALID)
        )

    client, delays = client_for(provider)
    assert client.authorize(REFERENCE, 100, "USD").approved
    assert delays == [expected]


def test_does_not_retry_earlier_than_long_retry_after():
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(429, headers={"Retry-After": "60"})

    client, delays = client_for(provider)
    with pytest.raises(DomainError):
        client.authorize(REFERENCE, 100, "USD")
    assert len(calls) == 1
    assert delays == []


def test_extremely_large_retry_after_cannot_overflow_the_budget_parser():
    client, delays = client_for(lambda _request: httpx.Response(429, headers={"Retry-After": "9" * 1000}))
    with pytest.raises(DomainError):
        client.authorize(REFERENCE, 100, "USD")
    assert delays == []


@pytest.mark.parametrize(
    "body",
    [
        b"{broken",
        b"{}",
        b'{"approved":"true","networkReference":"a"}',
        b'{"approved":true,"networkReference":"unsafe\\n"}',
        b"[]",
        b"x" * 5000,
        b'{"approved":true,"networkReference":"a","private":"extra"}',
    ],
)
def test_malformed_or_oversized_responses_are_permanent(body):
    calls = []

    def provider(request):
        calls.append(request)
        return httpx.Response(200, content=body)

    client, delays = client_for(provider)
    with pytest.raises(DomainError):
        client.authorize(REFERENCE, 100, "USD")
    assert len(calls) == 1
    assert delays == []


def test_transport_timeout_has_bounded_retries_and_no_provider_details():
    calls = []

    def provider(request):
        calls.append(request)
        raise httpx.ReadTimeout("private network diagnostic")

    client, delays = client_for(provider)
    with pytest.raises(DomainError) as error:
        client.authorize(REFERENCE, 100, "USD")
    assert "private" not in str(error.value)
    assert len(calls) == 3
    assert delays == [0.1, 0.2]


def test_configured_read_timeout_is_enforced_with_real_loopback_socket():
    from time import monotonic, sleep

    calls = []

    class SlowProvider(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_POST(self):
            calls.append(self.headers["Idempotency-Key"])
            self.rfile.read(int(self.headers["Content-Length"]))
            sleep(0.3)
            try:
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"approved":true,"networkReference":"slow"}')
            except (BrokenPipeError, ConnectionResetError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), SlowProvider)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = PaymentNetworkClient(
            NetworkSettings(
                mode="http",
                base_url=f"http://127.0.0.1:{server.server_port}",
                read_timeout_seconds=0.05,
                max_attempts=2,
                backoff_seconds=0,
            )
        )
        start = monotonic()
        with pytest.raises(DomainError):
            client.authorize(REFERENCE, 100, "USD")
        assert monotonic() - start < 2
        assert calls == [REFERENCE, REFERENCE]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.mark.parametrize(
    "settings",
    [
        {"mode": "invalid"},
        {"max_attempts": 4},
        {"read_timeout_seconds": 60},
        {"backoff_seconds": -1},
        {"base_url": "https://user:password@example.test"},
        {"base_url": "https://example.test?secret=key"},
    ],
)
def test_rejects_unbounded_or_credential_bearing_configuration(settings):
    with pytest.raises(ValueError):
        NetworkSettings(**settings)
