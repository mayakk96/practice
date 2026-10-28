#!/usr/bin/env python3
"""Exercise a fictional onboarding workflow over real local HTTP requests."""
import argparse
import base64
import json
import os
from pathlib import Path
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


def local_settings():
    settings = {}
    path = Path(__file__).resolve().parents[1] / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line and not line.lstrip().startswith("#") and "=" in line:
                name, value = line.split("=", 1)
                settings[name.strip()] = value.strip()
    settings.update({name: os.environ[name] for name in (
        "APP_API_USERNAME", "APP_API_PASSWORD"
    ) if name in os.environ})
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--no-auth", action="store_true", help="Use only for the local demo profile")
    args = parser.parse_args()
    target = urllib.parse.urlsplit(args.base_url)
    if target.hostname not in {"localhost", "127.0.0.1", "::1"}:
        parser.error("This demonstration script only sends credentials to a loopback address")
    settings = local_settings()
    auth = None
    if not args.no_auth:
        username, password = settings.get("APP_API_USERNAME"), settings.get("APP_API_PASSWORD")
        if not username or not password:
            parser.error("Set local APP_API_USERNAME/APP_API_PASSWORD or run with --no-auth for demo")
        auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(method, path, body=None, headers=None):
        request_headers = {"Accept": "application/json"}
        if auth:
            request_headers["Authorization"] = auth
        if body is not None:
            request_headers["Content-Type"] = "application/json"
        request_headers.update(headers or {})
        request = urllib.request.Request(
            args.base_url.rstrip("/") + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers=request_headers,
            method=method,
        )
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            return response.status, response.headers, json.loads(raw) if raw else None

    for _ in range(60):
        try:
            status, _, health = call("GET", "/actuator/health")
            if status == 200 and health["status"] == "UP":
                break
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(1)
    else:
        raise AssertionError("Application never became healthy")

    unique = str(uuid.uuid4())
    payload = {
        "firstName": "Demo",
        "lastName": "Applicant",
        "email": f"demo-{unique}@example.com",
        "assignedTeam": "ONBOARDING",
    }
    header = {"Idempotency-Key": unique}
    status, headers, case = call("POST", "/api/onboarding/cases", payload, header)
    assert status == 201, (status, case)
    case_id = case["id"]
    location = f"/api/onboarding/cases/{case_id}"
    assert headers["Location"].endswith(location)
    assert case["status"] == "CREATED"
    status, headers, replay = call("POST", "/api/onboarding/cases", payload, header)
    assert status == 200 and replay["id"] == case_id
    assert headers.get("Idempotency-Replayed", "").lower() == "true"
    status, _, problem = call(
        "POST", "/api/onboarding/cases", dict(payload, firstName="Different"), header
    )
    assert status == 409 and problem["status"] == 409
    status, _, saved = call("GET", location)
    assert status == 200 and saved["id"] == case_id

    def transition(new_status, expected=200):
        status, _, body = call("PATCH", location + "/status", {
            "status": new_status, "reason": "Fictional automated smoke workflow"
        })
        assert status == expected, (status, body)
        return body

    transition("COMPLETED", 409)
    transition("DOCUMENTS_PENDING")
    for document_type in ("IDENTITY_PROOF", "ADDRESS_PROOF"):
        body = {"documentType": document_type, "reference": f"DEMO-{document_type}"}
        status, _, document = call("POST", location + "/documents", body)
        assert status == 201, (status, document)
        status, _, duplicate = call("POST", location + "/documents", body)
        assert status == 409 and duplicate["status"] == 409
    transition("UNDER_REVIEW")
    transition("APPROVED")
    completed = transition("COMPLETED")
    assert completed["status"] == "COMPLETED"
    status, _, history = call("GET", location + "/history")
    assert status == 200 and history[-1]["newStatus"] == "COMPLETED"
    status, _, missing = call("GET", f"/api/onboarding/cases/{uuid.uuid4()}")
    assert status == 404 and missing["status"] == 404
    print("PASS: real HTTP create/read, idempotency replay/conflict, transition policy,")
    print("required documents, safe duplicate documents, completion, history and 404.")
    print("Created one fictional COMPLETED case; history is retained for inspection.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
