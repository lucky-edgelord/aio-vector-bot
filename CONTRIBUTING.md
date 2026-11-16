# Contributing

Thanks for helping make this bot useful for more Vector communities.

## Setup

```sh
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # needs rustc/cargo and cmake for the SDK
.venv/bin/pytest -q && .venv/bin/ruff check .
```

## Ground rules

- **Never commit keys.** `.env`, `*.nsec` and `data/` are git-ignored; keep it that way. Test with a throwaway bot account.
- **Layout:** SQL lives only in `src/vectiq/stores/`, Vector I/O only in `src/vectiq/cogs/`, game rules in `src/vectiq/games/` stay pure (no network).
- **Schema changes:** append a migration in `db/migrations.py`; never edit one that has shipped.
- **New settings:** add a default in `config.py` `DEFAULTS`, a commented entry in `config.yaml`, and validation if a wrong value would break things.
- **New games:** see "Mini games" in the README.
- Add or update tests for behaviour you change, and a line in `CHANGELOG.md`.

## Pull requests

Keep them focused. Say what you tested live (which community features, which client) and what you couldn't test.
