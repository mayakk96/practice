#!/usr/bin/env python3
"""Generate local demonstration credentials without displaying or overwriting them."""

import os
import secrets
from pathlib import Path


def main():
    target = Path(__file__).resolve().parents[1] / ".env"
    body = (
        "# Local synthetic demo only. This file is ignored; do not commit it.\n"
        + "\n".join(
            [
                f"DATABASE_PASSWORD={secrets.token_urlsafe(32)}",
                "APP_API_USERNAME=operator",
                f"APP_API_PASSWORD={secrets.token_urlsafe(32)}",
                "APP_READONLY_USERNAME=reader",
                f"APP_READONLY_PASSWORD={secrets.token_urlsafe(32)}",
            ]
        )
        + "\n"
    )
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise SystemExit(".env already exists; refusing to overwrite existing local credentials")
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(body)
    print("Created ignored .env with local operator/reader/database credentials; values were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
