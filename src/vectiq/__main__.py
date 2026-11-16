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


if __name__ == "__main__":
    sys.exit(main())
