from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

from .app import build
from .config import Config, ConfigError, load_dotenv


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vectiq", description="Vectiq, a community bot for Vector")
    ap.add_argument("--config", help="path to config.yaml (default: ./config.yaml)")
    ap.add_argument("--check", action="store_true", help="validate config.yaml and exit")
    ap.add_argument("-v", "--verbose", action="store_true")
    users = ap.add_argument_group("dashboard logins")
    users.add_argument("--add-user", metavar="USERNAME", help="create a dashboard login (asks for the password)")
    users.add_argument("--npub", help="the Vector npub the new login belongs to (decides what it may manage)")
    users.add_argument("--set-password", metavar="USERNAME", help="set a new password for a dashboard login")
    users.add_argument("--delete-user", metavar="USERNAME", help="delete a dashboard login")
    users.add_argument("--list-users", action="store_true", help="list dashboard logins")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    load_dotenv(os.environ.get("VECTIQ_ENV", ".env"))
    try:
        config = Config.load(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.check:
        print(f"config ok: {config.path} ({sum(config.enabled(m) for m in config['modules'])} modules on, "
              f"{len(config.hooks)} webhooks)")
        return 0
    if args.add_user or args.set_password or args.delete_user or args.list_users:
        return asyncio.run(_users(config, args))
    if not config.nsec:
        print("VECTOR_NSEC is not set (put it in .env)", file=sys.stderr)
        return 2

    async def run() -> None:
        bot = await build(config)
        await bot.start(config.nsec)

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    return 0


async def _users(config: Config, args) -> int:
    import getpass

    from .dashboard.access import clean_npub
    from .db import Database
    from .stores.dashboard import DashboardStore, PasswordError

    db = await Database(config.db_path).connect()
    store = DashboardStore(db)

    def ask() -> str:
        if not sys.stdin.isatty():
            return sys.stdin.readline().rstrip("\n")      # for scripts: password on stdin
        first = getpass.getpass("Password (10+ characters): ")
        if first != getpass.getpass("Again: "):
            raise PasswordError("The passwords don't match.")
        return first

    try:
        if args.list_users:
            rows = await store.users()
            for r in rows:
                print(f"{r['username']:<24} {r['npub']}")
            if not rows:
                print("No dashboard logins yet. Add one with --add-user NAME --npub npub1...")
        elif args.add_user:
            npub = clean_npub(args.npub or "")
            if npub is None:
                print("--add-user needs --npub npub1... (the Vector account this login is for)", file=sys.stderr)
                return 2
            await store.create_user(args.add_user, npub, ask(), created_by="command line")
            print(f"Created {args.add_user}. It can sign in while {npub[:16]}… is an admin of a community the bot "
                  "serves, or a bot owner.")
        elif args.set_password:
            if await store.user(args.set_password) is None:
                print("No such user.", file=sys.stderr)
                return 2
            await store.set_password(args.set_password, ask())
            print("Password changed (and the account unlocked).")
        elif args.delete_user:
            print("Deleted." if await store.delete_user(args.delete_user) else "No such user.")
    except PasswordError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    finally:
        await db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
