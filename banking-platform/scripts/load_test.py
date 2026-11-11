#!/usr/bin/env python3
"""Optional local acceptance benchmark; results describe this machine, not production capacity."""

import argparse
import concurrent.futures
import json
import math
import time
import uuid
from datetime import UTC, datetime

from demo_http import Api, add_connection_arguments


def percentile(samples, p):
    ordered = sorted(samples)
    return ordered[max(0, math.ceil(len(ordered) * p) - 1)] if ordered else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_connection_arguments(parser)
    parser.add_argument("--count", type=int, choices=(100, 1000, 10000), default=100)
    parser.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args()
    if not 1 <= args.concurrency <= 64:
        parser.error("concurrency must be 1..64")
    api = Api(args.base_url, args.no_auth)
    tag = uuid.uuid4().hex[:12]
    customer = api.post(
        "/api/customers",
        {
            "externalReference": f"DEMO-LOAD-C-{tag}",
            "displayName": "Synthetic Load Customer",
        },
    )
    account = api.post(
        "/api/accounts",
        {
            "customerId": customer["id"],
            "accountReference": f"DEMO-LOAD-A-{tag}",
            "currency": "USD",
        },
    )
    date = datetime.now(UTC).date().isoformat()

    def submit(n):
        started = time.perf_counter()
        try:
            api.post(
                "/api/transactions",
                {
                    "externalReference": f"DEMO-LOAD-{tag}-{n}",
                    "transactionType": "CARD_PURCHASE",
                    "amountMinor": 100,
                    "currency": "USD",
                    "sourceAccountId": account["id"],
                    "counterpartyReference": "DEMO-LOAD-MERCHANT",
                    "businessDate": date,
                },
                key=f"load:{tag}:{n}",
            )
            return (time.perf_counter() - started) * 1000, True
        except (RuntimeError, OSError):
            return (time.perf_counter() - started) * 1000, False

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        results = list(pool.map(submit, range(args.count)))
    elapsed = time.perf_counter() - started
    durations = [duration for duration, _ in results]
    successes = sum(ok for _, ok in results)
    print(
        json.dumps(
            {
                "requests": args.count,
                "concurrency": args.concurrency,
                "elapsedSeconds": round(elapsed, 3),
                "attemptsPerSecond": round(args.count / elapsed, 2),
                "successfulRequestsPerSecond": round(successes / elapsed, 2),
                "p50Milliseconds": percentile(durations, 0.50),
                "p95Milliseconds": percentile(durations, 0.95),
                "p99Milliseconds": percentile(durations, 0.99),
                "errors": args.count - successes,
                "errorRate": (args.count - successes) / args.count,
                "scope": "Local transaction acceptance only; no authorization/clearing/settlement throughput claim",
            },
            indent=2,
        )
    )
    return 0 if successes == args.count else 1


if __name__ == "__main__":
    raise SystemExit(main())
