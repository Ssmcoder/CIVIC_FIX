"""Admin bootstrap CLI (CF-01).

  python -m app.cli create-superadmin --username admin --email a@b.c
  python -m app.cli disable-default-admins
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from .auth import hash_password
from .database import SessionLocal, engine
from .models import Admin
from .security import validate_password_policy


async def _admins_with_password(pw: str):
    async with SessionLocal() as db:
        res = await db.execute(select(Admin))
        out = []
        for a in res.scalars().all():
            from .security import verify_password
            if verify_password(pw, a.password_hash):
                out.append(a)
        return out


async def create_superadmin(username: str, email: str, password: str | None):
    pw = password or os.environ.get("BOOTSTRAP_ADMIN_PASSWORD")
    if not pw:
        pw = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Confirm: ")
        if pw != pw2:
            print("Passwords do not match", file=sys.stderr)
            sys.exit(2)
    errs = validate_password_policy(pw, username)
    if errs:
        print("Password policy: " + "; ".join(errs), file=sys.stderr)
        sys.exit(2)
    async with SessionLocal() as db:
        exists = await db.execute(select(Admin).where(
            (Admin.username == username) | (Admin.email == email)))
        if exists.scalar_one_or_none():
            print("Admin already exists", file=sys.stderr)
            sys.exit(1)
        a = Admin(email=email, username=username, password_hash=hash_password(pw),
                  full_name=username, role="super_admin", must_change_password=True)
        db.add(a)
        await db.commit()
        print(f"Created super_admin '{username}' — must change password at first login")


async def disable_default_admins():
    admins = await _admins_with_password("admin123")
    async with SessionLocal() as db:
        for a in admins:
            a.is_active = False
            a.must_change_password = True
            print(f"Disabled default admin: {a.username}")
        await db.commit()
    if not admins:
        print("No admins with the default password found")


async def main_async(args):
    if args.cmd == "create-superadmin":
        await create_superadmin(args.username, args.email, args.password)
    elif args.cmd == "disable-default-admins":
        await disable_default_admins()


def main():
    p = argparse.ArgumentParser(prog="app.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create-superadmin")
    c.add_argument("--username", required=True)
    c.add_argument("--email", required=True)
    c.add_argument("--password", default=None, help="or set BOOTSTRAP_ADMIN_PASSWORD")
    sub.add_parser("disable-default-admins")
    args = p.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
