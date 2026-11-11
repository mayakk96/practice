#!/usr/bin/env python3
"""Exercise synthetic payments from receipt to settlement, reconciliation and investigation."""

import argparse
import json

from demo_http import Api, add_connection_arguments


def find_transaction_evidence(api, path, transaction_id):
    """Read bounded pages until this demo's record is found, never an older unrelated issue."""
    page = 0
    while True:
        response = api.get(f"{path}?page={page}&size=100")
        match = next((row for row in response["items"] if row.get("transactionId") == transaction_id), None)
        if match is not None:
            return match
        if (page + 1) * response["size"] >= response["total"]:
            return None
        page += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument(
        "--run-id",
        default="portfolio-demo",
        help="Use a fresh ID or reset the local demo database before rerunning",
    )
    parser.add_argument("--business-date", default="2026-11-08")
    args = parser.parse_args()
    api = Api(args.base_url, args.no_auth)
    api.get("/health")
    tag, date = args.run_id, args.business_date
    print("1. Create synthetic customers and accounts (no real customer/account data).")
    accounts = []
    for n in range(1, 4):
        customer = api.post(
            "/api/customers",
            {
                "externalReference": f"DEMO-CUSTOMER-{tag}-{n}",
                "displayName": f"Synthetic Customer {n}",
            },
        )
        accounts.append(
            api.post(
                "/api/accounts",
                {
                    "customerId": customer["id"],
                    "accountReference": f"DEMO-ACCOUNT-{tag}-{n}",
                    "currency": "USD",
                },
            )
        )

    def create(label, amount, account=0):
        request = {
            "externalReference": f"DEMO-{tag}-{label}",
            "transactionType": "CARD_PURCHASE",
            "amountMinor": amount,
            "currency": "USD",
            "sourceAccountId": accounts[account]["id"],
            "counterpartyReference": "DEMO-MERCHANT",
            "businessDate": date,
        }
        key = f"{tag}:{label}"
        created = api.post("/api/transactions", request, key=key)
        return created, request, key

    print("2. Submit $500.00; replay its idempotency key and reject a conflicting body.")
    payment, request, key = create("mismatch", 50000)
    replay, replay_status, _ = api.call(
        "POST", "/api/transactions", request, {"Idempotency-Key": key}, (200,)
    )
    assert replay["id"] == payment["id"] and replay_status == 200
    _, conflict_status, _ = api.call(
        "POST",
        "/api/transactions",
        dict(request, amountMinor=50001),
        {"Idempotency-Key": key},
        (409,),
    )
    assert conflict_status == 409
    matched, _, _ = create("matched", 10000, 1)
    payments = [payment, matched]
    print("3. Authorize, capture, and confirm clearing for two payments.")
    for tx in payments:
        api.post(f"/api/transactions/{tx['id']}/authorize")
        captured = api.post(f"/api/transactions/{tx['id']}/capture")
        api.post(
            "/api/clearing/records",
            {
                "transactionId": tx["id"],
                "networkReference": captured["networkReference"],
                "amountMinor": tx["amountMinor"],
                "currency": "USD",
                "businessDate": date,
            },
        )
    print("4. Create a settlement batch and advance OPEN → READY → SUBMITTED → CONFIRMED.")
    batch = api.post("/api/settlements", {"businessDate": date, "currency": "USD", "maxItems": 100})
    for command in ("ready", "submit", "confirm"):
        batch = api.post(
            f"/api/settlements/{batch['id']}/{command}",
            {
                "expectedVersion": batch["version"],
                "reason": "Synthetic end-to-end demonstration",
            },
        )
    assert batch["status"] == "CONFIRMED"
    print("5. Add a deterministic decline and a captured reversal.")
    decline, _, _ = create("declined", 13, 2)
    assert api.post(f"/api/transactions/{decline['id']}/authorize")["status"] == "DECLINED"
    reversed_tx, _, _ = create("reversal", 2500, 2)
    api.post(f"/api/transactions/{reversed_tx['id']}/authorize")
    api.post(f"/api/transactions/{reversed_tx['id']}/capture")
    assert (
        api.post(
            f"/api/transactions/{reversed_tx['id']}/reverse",
            {"reason": "Synthetic reversal example"},
        )["status"]
        == "REVERSED"
    )
    print("6. Import external evidence: $450.00 against $500.00 internal, plus one exact match.")
    records = [
        {
            "externalReference": tx["externalReference"],
            "amountMinor": 45000 if tx["id"] == payment["id"] else tx["amountMinor"],
            "currency": "USD",
            "status": "SETTLED",
            "businessDate": date,
            "receivedDate": date,
        }
        for tx in payments
    ]
    api.post("/api/reconciliation/external-records", {"records": records})
    run = api.post("/api/reconciliation/runs", {"businessDate": date, "currency": "USD"})
    mismatch = find_transaction_evidence(
        api, f"/api/reconciliation/runs/{run['id']}/mismatches", payment["id"]
    )
    assert mismatch and "AMOUNT_MISMATCH" in mismatch["classifications"], mismatch
    assert mismatch["varianceMinor"] == 5000, mismatch
    exception = find_transaction_evidence(api, "/api/exceptions", payment["id"])
    assert exception, "The current payment mismatch must create an operational exception."
    print("7. Inspect this payment's immutable mismatch, exception and read-only incident evidence.")
    assistant = api.get(f"/api/assistant/exceptions/{exception['id']}")
    print("8. Create and capture a full refund child; the first reconciliation snapshot stays intact.")
    refund = api.post(
        f"/api/transactions/{matched['id']}/refund",
        {"reason": "Synthetic full refund example"},
        key=f"{tag}:full-refund",
    )
    api.post(f"/api/transactions/{refund['id']}/authorize")
    refund = api.post(f"/api/transactions/{refund['id']}/capture")
    api.post(
        "/api/clearing/records",
        {
            "transactionId": refund["id"],
            "networkReference": refund["networkReference"],
            "amountMinor": refund["amountMinor"],
            "currency": "USD",
            "businessDate": date,
        },
    )
    refund_batch = api.post("/api/settlements", {"businessDate": date, "currency": "USD", "maxItems": 100})
    for command in ("ready", "submit", "confirm"):
        refund_batch = api.post(
            f"/api/settlements/{refund_batch['id']}/{command}",
            {
                "expectedVersion": refund_batch["version"],
                "reason": "Synthetic refund settlement",
            },
        )
    refund = api.get(f"/api/transactions/{refund['id']}")
    assert refund["status"] == "SETTLED" and refund_batch["netSettlementMinor"] == -10000
    print("9. Query operational analytics (projection source is explicitly identified).")
    analytics = api.get("/api/analytics/daily?page=0&size=20")
    print(
        json.dumps(
            {
                "transactionId": payment["id"],
                "settlementBatch": batch,
                "reconciliationRun": run,
                "mismatch": mismatch,
                "exception": exception,
                "assistant": assistant,
                "analytics": analytics,
                "refund": refund,
                "refundBatch": refund_batch,
            },
            indent=2,
        )
    )
    print(
        "PASS: duplicate protection, authorization, capture, clearing, settlement, mismatch, exception, analytics and read-only explanation."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
