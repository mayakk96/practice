#!/usr/bin/env python3
"""Create local demonstration credentials without displaying or committing them."""
from pathlib import Path
import secrets
import sys


def main():
    target = Path(__file__).resolve().parents[1] / ".env"
    try:
        with target.open("x", encoding="utf-8") as output:
            target.chmod(0o600)
            output.write("# Local demo credentials. Do not commit this file.\n")
            for name, value in {
                "DATABASE_PASSWORD": secrets.token_urlsafe(32),
                "APP_API_USERNAME": "operator",
                "APP_API_PASSWORD": secrets.token_urlsafe(32),
                "APP_READONLY_USERNAME": "reader",
                "APP_READONLY_PASSWORD": secrets.token_urlsafe(32),
            }.items():
                output.write(f"{name}={value}\n")
    except FileExistsError:
        print(".env already exists; preserving its contents.", file=sys.stderr)
        return 1
    print("Created .env with local demo credentials. Values were not printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
