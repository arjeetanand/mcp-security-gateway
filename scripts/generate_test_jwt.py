#!/usr/bin/env python3
"""generate_test_jwt.py – Mint a signed test JWT for local gateway development.

Usage
-----
1. Make sure PyJWT is installed:
       pip install PyJWT

2. Set the same secret you put in your .env (JWT_SECRET):
       export JWT_SECRET="change_me_to_a_long_random_secret"

3. Run the script, optionally overriding roles and subject:
       python3 scripts/generate_test_jwt.py
       python3 scripts/generate_test_jwt.py --roles admin,viewer --sub alice@example.com

The printed token can be pasted directly into an Authorization header:
       curl -H "Authorization: Bearer <token>" http://localhost:8000/...
"""
from __future__ import annotations

import argparse
import os
import time

import jwt


ROLES_CLAIM = os.getenv("JWT_ROLES_CLAIM", "https://mcp-gateway/roles")
ALGORITHM   = os.getenv("JWT_ALGORITHM", "HS256")
SECRET      = os.getenv("JWT_SECRET", "")
AUDIENCE    = os.getenv("JWT_AUDIENCE", "")


def mint(
    sub: str,
    roles: list[str],
    ttl_seconds: int = 3600,
) -> str:
    if not SECRET:
        raise SystemExit(
            "ERROR: JWT_SECRET is not set. "
            "Export it or add it to a .env file before running this script."
        )

    now = int(time.time())
    payload: dict = {
        "sub": sub,
        "name": sub.split("@")[0].capitalize(),
        "email": sub if "@" in sub else f"{sub}@example.com",
        ROLES_CLAIM: roles,
        "iat": now,
        "exp": now + ttl_seconds,
    }
    if AUDIENCE:
        payload["aud"] = AUDIENCE

    return jwt.encode(payload, SECRET, algorithm=ALGORITHM)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mint a test JWT for the MCP Security Gateway.")
    parser.add_argument("--sub",   default="dev-user@example.com", help="Subject (user ID)")
    parser.add_argument("--roles", default="viewer",               help="Comma-separated roles")
    parser.add_argument("--ttl",   default=3600, type=int,         help="Validity in seconds (default 3600)")
    args = parser.parse_args()

    roles = [r.strip() for r in args.roles.split(",") if r.strip()]
    token = mint(sub=args.sub, roles=roles, ttl_seconds=args.ttl)

    print("\n✅  Test JWT\n")
    print(f"   Subject : {args.sub}")
    print(f"   Roles   : {roles}")
    print(f"   TTL     : {args.ttl}s\n")
    print("─" * 72)
    print(token)
    print("─" * 72)
    print("\nUse it with curl:")
    print(f'  curl -H "Authorization: Bearer {token}" http://localhost:8000/mcp\n')


if __name__ == "__main__":
    main()
