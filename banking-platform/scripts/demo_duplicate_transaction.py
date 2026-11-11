#!/usr/bin/env python3
"""Race identical synthetic submissions; require one transaction and one original creation."""

import argparse
import concurrent.futures
import json
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
            "externalReference": f"DEMO-DUP-C-{tag}",
            "displayName": "Synthetic Duplicate Customer",
        },
    )
    account = api.post(
        "/api/accounts",
        {
            "customerId": customer["id"],
            "accountReference": f"DEMO-DUP-A-{tag}",
            "currency": "USD",
        },
    )
    body = {
        "externalReference": f"DEMO-DUP-{tag}",
        "transactionType": "CARD_PURCHASE",
        "amountMinor": 10000,
        "currency": "USD",
        "sourceAccountId": account["id"],
        "counterpartyReference": "DEMO-MERCHANT",
        "businessDate": datetime.now(UTC).date().isoformat(),
    }

    def send(_):
        return api.call(
            "POST",
            "/api/transactions",
            body,
            {"Idempotency-Key": f"duplicate:{tag}"},
            (200, 201),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(send, range(8)))
    assert len({result[0]["id"] for result in results}) == 1
    assert sum(result[1] == 201 for result in results) == 1
    print(
        json.dumps(
            {
                "transactionId": results[0][0]["id"],
                "requests": len(results),
                "created": 1,
                "replayed": 7,
            }
        )
    )
    print("PASS: eight simultaneous requests produced one financial transaction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
