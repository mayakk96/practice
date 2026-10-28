"""Fictional screening provider: local demo only, receives opaque case IDs, never PII."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import threading
import time
from uuid import UUID


class ScreeningServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, risk_level="LOW", failures_before_success=0, delay_ms=0):
        super().__init__(address, ScreeningHandler)
        if risk_level not in {"LOW", "MEDIUM", "HIGH"}:
            raise ValueError("MOCK_RISK_LEVEL must be LOW, MEDIUM, or HIGH")
        if not 0 <= failures_before_success <= 10 or not 0 <= delay_ms <= 10_000:
            raise ValueError("Mock failure count/delay exceeds its demo bounds")
        self.risk_level = risk_level
        self.failures_before_success = failures_before_success
        self.delay_ms = delay_ms
        self.attempts = {}
        self.responses = {}
        self.lock = threading.Lock()


class ScreeningHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.respond(404, {"error": "not_found"})
            return
        self.respond(200, {"status": "UP"})

    def do_POST(self):
        if self.path != "/screenings":
            self.respond(404, {"error": "not_found"})
            return
        if self.headers.get("Content-Length") is None:
            self.respond(411, {"error": "content_length_required"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 1024:
                raise ValueError("invalid body size")
            if self.headers.get_content_type() != "application/json":
                self.respond(415, {"error": "application_json_required"})
                return
            request = json.loads(self.rfile.read(size))
            if not isinstance(request, dict) or set(request) != {"caseId"}:
                raise ValueError("only caseId is accepted")
            case_id = str(UUID(request["caseId"]))
            if self.headers.get("Idempotency-Key") != case_id:
                raise ValueError("idempotency key must match caseId")
        except (ValueError, TypeError, AttributeError, UnicodeDecodeError):
            self.respond(400, {"error": "invalid_screening_request"})
            return

        with self.server.lock:
            if case_id in self.server.responses:
                response = self.server.responses[case_id]
                should_fail = False
            else:
                attempts = self.server.attempts.get(case_id, 0) + 1
                self.server.attempts[case_id] = attempts
                should_fail = attempts <= self.server.failures_before_success
                response = {
                    "riskLevel": self.server.risk_level,
                    "providerReference": "demo-" + case_id,
                }
                if not should_fail:
                    self.server.responses[case_id] = response
        if self.server.delay_ms:
            time.sleep(self.server.delay_ms / 1000)
        if should_fail:
            self.respond(503, {"error": "simulated_temporary_unavailability"})
            return
        self.respond(200, response)

    def respond(self, status, payload):
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            # The application may correctly abandon a slow provider response after its timeout.
            pass

    def log_request(self, code="-", size="-"):
        print(json.dumps({"event": "mock_risk_request", "method": self.command, "status": code}), flush=True)

    def log_message(self, format, *args):
        # BaseHTTPRequestHandler messages can include raw request paths; do not emit them.
        pass


if __name__ == "__main__":
    server = ScreeningServer(
        ("0.0.0.0", int(os.environ.get("PORT", "8090"))),
        risk_level=os.environ.get("MOCK_RISK_LEVEL", "LOW"),
        failures_before_success=int(os.environ.get("MOCK_RISK_FAILURES_BEFORE_SUCCESS", "0")),
        delay_ms=int(os.environ.get("MOCK_RISK_DELAY_MS", "0")),
    )
    print(json.dumps({"event": "mock_risk_started", "port": server.server_port}), flush=True)
    server.serve_forever()
