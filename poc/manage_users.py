#!/usr/bin/env python3
"""
manage_users.py — Local CLI to manage accounts in poc/data/users.json

Use this BEFORE deploying to create the client test account (or any other
user) without touching JSON by hand. The password is hashed with PBKDF2-SHA256
(200k iterations) — the plaintext is never stored.

Usage
-----
    python3 poc/manage_users.py list
    python3 poc/manage_users.py add <username> [<display-name>] [--role user|admin]
    python3 poc/manage_users.py remove <username>
    python3 poc/manage_users.py reset-password <username>

Examples
--------
    # Create a client test account (will prompt for password)
    python3 poc/manage_users.py add client "Yohann (CETIE)"

    # Promote a user to admin
    python3 poc/manage_users.py add yohann --role admin

    # Inspect existing users (no passwords shown)
    python3 poc/manage_users.py list
"""

import argparse
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path

USERS_PATH = Path(__file__).parent / "data" / "users.json"


def _hash_password(password: str) -> str:
    salt = os.urandom(16).hex()
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"{salt}:{dk.hex()}"


def _load() -> list[dict]:
    if not USERS_PATH.exists():
        return []
    return json.loads(USERS_PATH.read_text())


def _save(users: list[dict]) -> None:
    USERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    USERS_PATH.write_text(json.dumps(users, indent=2, ensure_ascii=False))


def _prompt_password(prompt: str = "Password: ") -> str:
    while True:
        p1 = getpass.getpass(prompt)
        if len(p1) < 6:
            print("  Password must be at least 6 characters. Try again.")
            continue
        p2 = getpass.getpass("Confirm: ")
        if p1 != p2:
            print("  Mismatch. Try again.")
            continue
        return p1


def cmd_list(args):
    users = _load()
    if not users:
        print("(no users)")
        return
    print(f"{'username':<20} {'role':<10} {'display name'}")
    print("─" * 60)
    for u in users:
        print(f"{u.get('username',''):<20} {u.get('role','user'):<10} {u.get('display_name','')}")


def cmd_add(args):
    users = _load()
    username = args.username.strip().lower()
    if any(u.get("username") == username for u in users):
        print(f"User '{username}' already exists. Use reset-password to change their password.")
        sys.exit(1)
    display_name = args.display_name or username
    password = _prompt_password(f"Password for '{username}': ")
    users.append({
        "username":     username,
        "display_name": display_name,
        "role":         args.role,
        "password":     _hash_password(password),
    })
    _save(users)
    print(f"✓ Added {args.role} user: {username}")


def cmd_remove(args):
    users = _load()
    before = len(users)
    users = [u for u in users if u.get("username") != args.username.strip().lower()]
    if len(users) == before:
        print(f"No such user: {args.username}")
        sys.exit(1)
    _save(users)
    print(f"✓ Removed {args.username}")


def cmd_reset(args):
    users = _load()
    username = args.username.strip().lower()
    target = next((u for u in users if u.get("username") == username), None)
    if not target:
        print(f"No such user: {username}")
        sys.exit(1)
    password = _prompt_password(f"New password for '{username}': ")
    target["password"] = _hash_password(password)
    _save(users)
    print(f"✓ Password reset for {username}")


def main():
    p = argparse.ArgumentParser(description="Manage users.json")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List all users").set_defaults(func=cmd_list)

    a = sub.add_parser("add", help="Add a new user (prompts for password)")
    a.add_argument("username")
    a.add_argument("display_name", nargs="?", default=None)
    a.add_argument("--role", choices=["user", "admin"], default="user")
    a.set_defaults(func=cmd_add)

    r = sub.add_parser("remove", help="Remove a user")
    r.add_argument("username")
    r.set_defaults(func=cmd_remove)

    rp = sub.add_parser("reset-password", help="Change a user's password")
    rp.add_argument("username")
    rp.set_defaults(func=cmd_reset)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
