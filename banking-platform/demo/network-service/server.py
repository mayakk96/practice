"""Synthetic local provider. In-memory references survive retries, not process restarts."""

import json
import os
import re
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID


@dataclass(frozen=True)
class Settings:
    scenario: str = "normal"
    failures_before_success: int = -1
    delay_ms: int = 1500

    @classmethod
    def from_env(cls):
        value = cls(
            os.getenv("MOCK_NETWORK_SCENARIO", "normal"),
            int(os.getenv("MOCK_NETWORK_FAILURES_BEFORE_SUCCESS", "-1")),
            int(os.getenv("MOCK_NETWORK_DELAY_MS", "1500")),
        )
        if value.scenario not in {"normal", "timeout", "429", "500", "malformed"}:
            raise ValueError("Unsupported mock network scenario")
        if not -1 <= value.failures_before_success <= 100 or not 0 <= value.delay_ms <= 10000:
            raise ValueError("Unbounded mock fault configuration")
        return value


class NetworkState:
    def __init__(self, settings=None):
        self.settings = settings or Settings.from_env()
        self.lock = threading.Lock()
        self.decisions = {}
        self.attempts = {}

    def authorize(self, key, payload):
        with self.lock:
            previous = self.decisions.get(key)
            if previous and previous[0] != payload:
                return (
                    409,
                    {"error": "Reference already used for another request"},
                    False,
                )
            decision = {
                "approved": payload["amountMinor"] != 13,
                "networkReference": "net-" + key,
            }
            # Cache before responding: a caller timeout does not undo a provider decision.
            self.decisions[key] = (payload, decision)
            attempts = self.attempts.get(key, 0) + 1
            self.attempts[key] = attempts
            fault = self.settings.scenario != "normal" and (
                self.settings.failures_before_success == -1
                or attempts <= self.settings.failures_before_success
            )
            return 200, decision, fault


def handler_for(state):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def reply(self, status, body, retry_after=None):
            raw = json.dumps(body).encode() if not isinstance(body, bytes) else body
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            if retry_after is not None:
                self.send_header("Retry-After", str(retry_after))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            if self.path == "/health":
                return self.reply(200, {"status": "ok"})
            match = re.fullmatch(r"/authorizations/([a-f0-9-]{36})", self.path)
            if match:
                with state.lock:
                    found = state.decisions.get(match.group(1))
                if found:
                    return self.reply(200, found[1])
            self.reply(404, {"error": "Not found"})

        def do_POST(self):
            if self.path != "/authorizations":
                return self.reply(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 4096:
                    return self.reply(400, {"error": "Bounded content length required"})
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict) or set(body) != {
                    "transactionId",
                    "amountMinor",
                    "currency",
                }:
                    raise ValueError()
                key = str(UUID(body["transactionId"]))
                if key != body["transactionId"] or self.headers.get("Idempotency-Key") != key:
                    raise ValueError()
                if type(body["amountMinor"]) is not int or not 0 < body["amountMinor"] <= 1_000_000_000_000:
                    raise ValueError()
                if body["currency"] not in {"USD", "EUR", "GBP"}:
                    raise ValueError()
            except (ValueError, TypeError, KeyError, UnicodeError, AttributeError):
                return self.reply(400, {"error": "Invalid synthetic authorization"})
            status, decision, fault = state.authorize(key, body)
            if fault:
                if state.settings.scenario == "timeout":
                    time.sleep(state.settings.delay_ms / 1000)
                elif state.settings.scenario == "429":
                    return self.reply(429, {"error": "Synthetic rate limit"}, retry_after=0)
                elif state.settings.scenario == "500":
                    return self.reply(500, {"error": "Synthetic unavailable"})
                elif state.settings.scenario == "malformed":
                    return self.reply(200, b"{malformed")
            self.reply(status, decision)

    return Handler


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8091), handler_for(NetworkState())).serve_forever()
