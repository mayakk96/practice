import json
import threading
import unittest
import urllib.error
import urllib.request
from uuid import uuid4

from server import ScreeningServer


class ScreeningProviderTest(unittest.TestCase):
    def setUp(self):
        self.server = ScreeningServer(("127.0.0.1", 0), failures_before_success=1)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, body=None, key=None):
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Content-Type": "application/json", "Idempotency-Key": key or ""},
        )
        try:
            response = self.opener.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_health(self):
        self.assertEqual((200, {"status": "UP"}), self.request("/health"))

    def test_retry_and_idempotent_response(self):
        case_id = str(uuid4())
        self.assertEqual(503, self.request("/screenings", {"caseId": case_id}, case_id)[0])
        status, result = self.request("/screenings", {"caseId": case_id}, case_id)
        self.assertEqual(200, status)
        self.assertEqual("LOW", result["riskLevel"])
        self.assertEqual((status, result), self.request("/screenings", {"caseId": case_id}, case_id))
        self.assertEqual(2, self.server.attempts[case_id])

    def test_rejects_extra_personal_fields_and_mismatched_key(self):
        case_id = str(uuid4())
        self.assertEqual(400, self.request("/screenings", {"caseId": case_id, "email": "demo@example.com"}, case_id)[0])
        self.assertEqual(400, self.request("/screenings", {"caseId": case_id}, str(uuid4()))[0])

    def test_requires_fixed_length_instead_of_silently_misreading_chunked_json(self):
        case_id = str(uuid4())
        request = urllib.request.Request(
            self.base_url + "/screenings",
            data=iter([json.dumps({"caseId": case_id}).encode()]),
            headers={"Content-Type": "application/json", "Idempotency-Key": case_id},
            method="POST",
        )
        with self.assertRaises(urllib.error.HTTPError) as raised:
            self.opener.open(request, timeout=3)
        with raised.exception as response:
            self.assertEqual(411, response.code)
            self.assertEqual({"error": "content_length_required"}, json.load(response))


if __name__ == "__main__":
    unittest.main()
