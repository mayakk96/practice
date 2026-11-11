import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from uuid import uuid4

from server import NetworkState, Settings, handler_for


class MockNetworkTest(unittest.TestCase):
    def setUp(self):
        self.state = NetworkState(Settings())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler_for(self.state))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)

    def call(self, method, path, body=None, key=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        headers = {"Content-Type": "application/json"}
        if key:
            headers["Idempotency-Key"] = key
        connection.request(method, path, json.dumps(body) if body is not None else None, headers)
        response = connection.getresponse()
        status, raw = response.status, response.read()
        connection.close()
        return status, json.loads(raw)

    def payload(self, amount=100):
        return {"transactionId": str(uuid4()), "amountMinor": amount, "currency": "USD"}

    def test_same_reference_returns_original_decision_and_conflicting_body_is_rejected(
        self,
    ):
        body = self.payload()
        original = self.call("POST", "/authorizations", body, body["transactionId"])
        self.assertEqual(original, self.call("POST", "/authorizations", body, body["transactionId"]))
        body["amountMinor"] = 101
        self.assertEqual(409, self.call("POST", "/authorizations", body, body["transactionId"])[0])
        self.assertEqual(1, len(self.state.decisions))

    def test_decline_and_lookup_are_synthetic_and_deterministic(self):
        body = self.payload(13)
        status, decision = self.call("POST", "/authorizations", body, body["transactionId"])
        self.assertEqual(200, status)
        self.assertFalse(decision["approved"])
        self.assertEqual(
            (200, decision),
            self.call("GET", "/authorizations/" + body["transactionId"]),
        )

    def test_fault_can_happen_after_decision_was_saved_and_retry_reuses_result(self):
        self.state.settings = Settings("500", 1)
        body = self.payload()
        self.assertEqual(500, self.call("POST", "/authorizations", body, body["transactionId"])[0])
        self.assertEqual(1, len(self.state.decisions))
        self.assertEqual(200, self.call("POST", "/authorizations", body, body["transactionId"])[0])
        self.assertEqual(1, len(self.state.decisions))

    def test_invalid_rows_missing_key_unknown_currency_and_float_are_rejected(self):
        for field, value in [
            ("amountMinor", 1.5),
            ("amountMinor", True),
            ("currency", "JPY"),
        ]:
            body = self.payload()
            body[field] = value
            self.assertEqual(
                400,
                self.call("POST", "/authorizations", body, body["transactionId"])[0],
            )
        self.assertEqual(400, self.call("POST", "/authorizations", self.payload())[0])
        self.assertFalse(self.state.decisions)

    def test_health_and_unknown_routes(self):
        self.assertEqual((200, {"status": "ok"}), self.call("GET", "/health"))
        self.assertEqual(404, self.call("GET", "/missing")[0])


if __name__ == "__main__":
    unittest.main()
