#!/usr/bin/env python3
"""Trigger a timeout against a separately fault-configured local mock network."""

import argparse
import uuid
from datetime import UTC, datetime

from demo_http import Api, add_connection_arguments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    args = parser.parse_args()
    api = Api(args.base_url, args.no_auth)
    tag = uuid.uuid4().hex[:12]
    customer = api.post(
        "/api/customers",
        {
            "externalReference": f"DEMO-TIMEOUT-C-{tag}",
            "displayName": "Synthetic Timeout Customer",
        },
    )
    account = api.post(
        "/api/accounts",
        {
            "customerId": customer["id"],
            "accountReference": f"DEMO-TIMEOUT-A-{tag}",
            "currency": "USD",
        },
    )
    tx = api.post(
        "/api/transactions",
        {
            "externalReference": f"DEMO-TIMEOUT-{tag}",
            "transactionType": "CARD_PURCHASE",
            "amountMinor": 100,
            "currency": "USD",
            "sourceAccountId": account["id"],
            "counterpartyReference": "DEMO-MERCHANT",
            "businessDate": datetime.now(UTC).date().isoformat(),
        },
        key=f"timeout:{tag}",
    )
    result, status, headers = api.call("POST", f"/api/transactions/{tx['id']}/authorize", expected=(503,))
    current = api.get(f"/api/transactions/{tx['id']}")
    assert current["status"] == "RECEIVED"
    print(
        f"PASS: HTTP {status}; transactionId={tx['id']}; status={current['status']}; requestId={result.get('requestId', headers.get('X-Request-ID', 'unavailable'))}"
    )
    print(
        "The downstream outcome remains ambiguous. Investigate by stable transaction reference before retrying."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
