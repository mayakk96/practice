"""Small loopback-only HTTP helper shared by the educational demonstrations."""

import base64
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


class Api:
    def __init__(self, base_url="http://127.0.0.1:8080", no_auth=False):
        target = urllib.parse.urlsplit(base_url)
        if target.scheme not in {"http", "https"} or target.hostname not in {
            "localhost",
            "127.0.0.1",
            "::1",
        }:
            raise ValueError("Demo scripts send requests and credentials only to loopback HTTP(S) addresses")
        if target.username or target.password or target.query or target.fragment:
            raise ValueError("Base URL must not contain credentials, query parameters or a fragment")
        self.base_url = base_url.rstrip("/")
        settings = {}
        env_file = Path(__file__).resolve().parents[1] / ".env"
        if env_file.is_file():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.strip() and not line.lstrip().startswith("#") and "=" in line:
                    name, value = line.split("=", 1)
                    settings[name.strip()] = value.strip().strip("\"'")
        settings.update(os.environ)
        self.headers = {"Accept": "application/json"}
        if not no_auth:
            user = settings.get("APP_API_USERNAME") or settings.get("API_OPERATOR_USERNAME")
            password = settings.get("APP_API_PASSWORD") or settings.get("API_OPERATOR_PASSWORD")
            if not user or not password:
                raise ValueError(
                    "Set APP_API_USERNAME/APP_API_PASSWORD in .env or use --no-auth for local demo"
                )
            self.headers["Authorization"] = (
                "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
            )
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, method, path, body=None, headers=None, expected=(200,), timeout=30):
        request_headers = dict(self.headers)
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = urllib.request.Request(
            self.base_url + path,
            method=method,
            headers=request_headers,
            data=json.dumps(body).encode() if body is not None else None,
        )
        try:
            response = self.opener.open(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            data = json.loads(raw) if raw else None
            status, returned_headers = response.status, response.headers
        if expected and status not in expected:
            detail = data.get("detail", "Request failed") if isinstance(data, dict) else "Request failed"
            request_id = data.get("requestId", "unavailable") if isinstance(data, dict) else "unavailable"
            raise RuntimeError(f"{method} {path}: HTTP {status}; {detail}; requestId={request_id}")
        return data, status, returned_headers

    def get(self, path):
        return self.call("GET", path)[0]

    def post(self, path, body=None, key=None, expected=(200, 201)):
        return self.call("POST", path, body, {"Idempotency-Key": key} if key else None, expected)[0]


def add_connection_arguments(parser):
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--no-auth",
        action="store_true",
        help="Only for the loopback unauthenticated demo",
    )
