from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace

from .app import build
from .config import Config, ConfigError, load_dotenv


def json_module_cli(args) -> int:
    """--check-module, --import-module and --export-module: JSON modules without the dashboard."""
    from .jsonmods import fmt
    from .jsonmods.library import Library, reserved
    from .jsonmods.manager import JsonModules

    load_dotenv(os.environ.get("VECTIQ_ENV", ".env"))
    try:
        config = Config.load(args.config) if args.import_module or args.export_module else None
        if args.export_module:
            jm = JsonModules(SimpleNamespace(config=config, extensions={}))
            text = fmt.dumps(jm.export(args.export_module, with_settings=args.with_settings))
            if args.out:
                Path(args.out).write_text(text, "utf-8")
                print(f"wrote {args.out}")
            else:
                print(text, end="")
            return 0
        path = args.check_module or args.import_module
        result = fmt.validate(Path(path).read_bytes(), reserved=reserved())
        for w in result.warnings:
            print(f"note: {w}")
        if not result.ok:
            for e in result.errors:
                print(f"❌ {e}", file=sys.stderr)
            return 2
        s = fmt.summary(result.module)
        print(f"{s['name']} ({s['id']} {s['release']}): {s['summary']}")
        facts = (("commands", ", ".join("!" + c for c in s["commands"])), ("autoresponders", s["autoresponders"]),
                 ("timers", s["timers"]), ("settings", ", ".join(s["settings"])), ("runs Python", " ".join(s["files"])))
        for label, value in facts:
            if value:
                print(f"  {label}: {value}")
        if args.check_module:
            return 0
        if s["kind"] == "code" and not (args.allow_code or config.get("marketplace.allow_code")):
            print("❌ this module runs Python on this computer. Read it, then add --allow-code if you trust it.", file=sys.stderr)
            return 2
        where = Library(config.data_dir).save(result.module, source=f"file {Path(path).name}")
        print(f"added as {where}. It's off: `!module on {s['id']}` (or the dashboard) switches it on.")
        return 0
    except (OSError, ConfigError, RuntimeError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vectiq", description="Vectiq, a community bot for Vector")
    ap.add_argument("--config", help="path to config.yaml (default: ./config.yaml)")
    ap.add_argument("--check", action="store_true", help="validate config.yaml and exit")
    ap.add_argument("--version", action="store_true", help="print the version and exit")
    ap.add_argument("--init", nargs="?", const=".", metavar="FOLDER",
                    help="create config.yaml and .env in FOLDER (default: here), then run the setup wizard with --setup")
    ap.add_argument("--setup", action="store_true", help="answer a few questions to fill in config.yaml")
    io = ap.add_argument_group("settings files")
    io.add_argument("--export-config", metavar="FILE",
                    help="write every setting (with dashboard changes) to FILE, or - for the screen")
    io.add_argument("--import-config", metavar="FILE", help="show what FILE would change in config.yaml, then apply it")
    io.add_argument("--yes", action="store_true", help="with --import-config: apply without asking")
    bk = ap.add_argument_group("backups")
    bk.add_argument("--backup", nargs="?", const=True, metavar="DESCRIPTION",
                    help="make a restore point now, with an optional description")
    bk.add_argument("--list-backups", action="store_true", help="list restore points, newest first")
    bk.add_argument("--restore", metavar="POINT", help="roll back to a restore point (its number or id). Stop the bot first.")
    pl = ap.add_argument_group("modules and plugins")
    pl.add_argument("--modules", action="store_true", help="list every module, plugins included, and exit")
    pl.add_argument("--install-module", metavar="PACKAGE", help="pip install a plugin package (name, name==1.2, git+https://...)")
    pl.add_argument("--uninstall-module", metavar="NAME", help="uninstall the package a plugin module came from")
    pl.add_argument("--new-module", metavar="NAME", help="create a starter plugin in modules/NAME to edit")
    pl.add_argument("--check-module", metavar="FILE", help="check a JSON module file and say what it does")
    pl.add_argument("--import-module", metavar="FILE", help="add a JSON module file (it starts switched off)")
    pl.add_argument("--export-module", metavar="NAME", help="write a JSON module or folder plugin as a JSON module file")
    pl.add_argument("--with-settings", action="store_true",
                     help="with --export-module: use your current settings as its defaults")
    pl.add_argument("--allow-code", action="store_true", help="with --import-module: allow a module that runs Python")
    pl.add_argument("--out", metavar="FILE", help="with --export-module: where to write it (default: print it)")
    pl.add_argument("--mcp", action="store_true",
                    help="speak MCP over stdio for Claude Desktop and similar apps (the bot must be running)")
    pl.add_argument("--install-sentire", action="store_true",
                    help="download and build the Sentire moderation bot (needs Rust); also updates it")
    pl.add_argument("--tee", action="store_true", help="with --install-sentire: build with confidential inference")
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
    if args.version:
        from . import __version__

        print(f"vectiq {__version__}")
        return 0
    if args.init is not None:
        from .scaffold import init

        for path, created in init(args.init):
            print(f"{'created' if created else 'kept   '} {path}")
        print("\nNext: put the bot's VECTOR_NSEC in .env, run `vectiq --setup` to fill in config.yaml, then `vectiq`.")
        return 0
    if args.new_module:
        from .plugin_template import create

        try:
            path = create(args.new_module, args.config)
        except ValueError as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        print(f"created {path}\nEdit it, then in chat: `module scan` and `module on {args.new_module}` "
              f"(after changes: `module reload {args.new_module}`).")
        return 0
    if args.mcp:
        load_dotenv(os.environ.get("VECTIQ_ENV", ".env"))
        try:
            from .mcp_server import bridge, token_for
        except ImportError:
            print('MCP needs FastMCP: pip install "vectiq[mcp]"', file=sys.stderr)
            return 2
        cfg = Config.load(args.config)
        c = cfg["mcp"]
        host = "127.0.0.1" if c["host"] in ("0.0.0.0", "::") else c["host"]
        asyncio.run(bridge(f"http://{host}:{c['port']}{c['path']}", token_for(cfg, cfg.data_dir)))
        return 0
    if args.install_sentire:
        from .sentire.install import build as build_sentire

        load_dotenv(os.environ.get("VECTIQ_ENV", ".env"))
        data_dir = os.environ.get("VECTIQ_DATA_DIR", "data")
        try:
            path = build_sentire(data_dir, tee=args.tee)
        except Exception as exc:  # noqa: BLE001
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        print(f"Sentire is ready: {path}\nSwitch it on with `!module on sentire` (or in the dashboard), then "
              "`!sentire invite` in each community. If the bot is running with it on: `!sentire restart`.")
        return 0
    if args.check_module or args.import_module or args.export_module:
        return json_module_cli(args)
    if args.install_module or args.uninstall_module:
        from .plugin_install import InstallError, install, uninstall

        load_dotenv(os.environ.get("VECTIQ_ENV", ".env"))
        try:
            if args.install_module:
                install(args.install_module)
                Config.load(args.config) if os.path.exists(args.config or "config.yaml") else None
                from . import modules

                print("installed. plugins now available:",
                      ", ".join(m.name for m in modules.plugins()) or "(none found: is it a Vectiq plugin?)")
                print("switch one on with `!module on <name>` (or `!module scan` first if the bot is running)")
            else:
                Config.load(args.config)
                uninstall(args.uninstall_module)
                print(f"uninstalled {args.uninstall_module}")
        except (InstallError, ConfigError) as exc:
            print(f"❌ {exc}", file=sys.stderr)
            return 2
        return 0
    load_dotenv(os.environ.get("VECTIQ_ENV", ".env"))
    if args.setup:
        from .wizard import run as setup

        try:
            return setup(args.config)
        except (KeyboardInterrupt, EOFError):
            print("\nStopped. config.yaml wasn't changed.")
            return 1
    try:
        config = Config.load(args.config)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2
    if args.modules:
        from . import modules

        for g in modules.GROUPS:
            ms = [m for m in modules.REGISTRY if m.group == g]
            if ms:
                print(g)
            for m in ms:
                state = "on " if config.enabled(m.name) else "off"
                extra = "" if m.builtin else f"  [plugin: {m.source}]"
                swap = f"  (does {m.slot})" if m.slot != m.name else ""
                need = f"  needs: {m.install_hint()}" if m.missing() else ""
                print(f"  {state} {m.name:<16} {m.label}{swap}{extra}{need}")
        for where, why in modules.PROBLEMS.items():
            print(f"  ⚠ {where}: {why}")
        return 0
    if args.check:
        print(f"config ok: {config.path} ({sum(config.enabled(m) for m in config['modules'])} modules on, "
              f"{len(config.hooks)} webhooks)")
        return 0
    if args.export_config or args.import_config:
        return asyncio.run(_config_files(config, args))
    if args.backup or args.list_backups or args.restore:
        from .backup import cli as backup_cli

        return asyncio.run(backup_cli(config, args))
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


async def _config_files(config: Config, args) -> int:
    from pathlib import Path

    from .config_io import ImportError_, export_yaml, parse, plan
    from .db import Database
    from .stores.dashboard import DashboardStore
    from .wizard import set_value

    db = await Database(config.db_path).connect()
    try:
        overrides = await DashboardStore(db).overrides()
    finally:
        await db.close()
    if args.export_config:
        if overrides:
            config.apply_overrides(overrides)
        text = export_yaml(config)
        if args.export_config == "-":
            print(text, end="")
        else:
            Path(args.export_config).write_text(text)
            print(f"Exported every setting to {args.export_config}"
                  + (f", including {len(overrides)} changed on the dashboard." if overrides else "."))
        return 0

    try:
        data = parse(Path(args.import_config).read_text())
    except (OSError, ImportError_) as exc:
        print(f"Can't import {args.import_config}: {exc}", file=sys.stderr)
        return 2
    p = plan(config, data)
    for line in p.skipped:
        print(f"  skipped  {line}")
    if not p.changes:
        print(f"Nothing to change: {p.unchanged} setting(s) already match.")
        return 0
    print(f"Importing {args.import_config} would change {len(p.changes)} setting(s) in {config.path}:")
    for k, v in p.changes.items():
        print(f"  {k}: {config.get(k)!r} -> {v!r}")
    shadowed = sorted(k for k in p.changes if k in overrides)
    if shadowed:
        print("Note: the dashboard has its own value for " + ", ".join(shadowed)
              + ", which still wins. Reset it on the Settings page to use the imported one.")
    if not args.yes and input("Apply? [y/N] ").strip().lower() not in ("y", "yes"):
        print("Nothing changed.")
        return 0
    from .backup import RestorePoints

    await RestorePoints(config).create(f"Before importing {Path(args.import_config).name}", "automatic")
    path = Path(config.path or "config.yaml")
    old = path.read_text()
    text = old
    for k, v in p.changes.items():
        text = set_value(text, k, v)
    path.with_name(path.name + ".bak").write_text(old)
    path.write_text(text)
    try:
        Config.load(path)
    except ConfigError as exc:
        path.write_text(old)
        print(f"Those settings aren't valid together, so nothing changed: {exc}", file=sys.stderr)
        return 2
    print(f"Imported. The old file is in {path.name}.bak. Restart the bot to use the new settings.")
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
