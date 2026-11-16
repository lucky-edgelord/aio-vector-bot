---
title: Development
group: Reference
order: 4
summary: Set up a development copy, understand how the code is laid out and add a command, a game or a setting.
---

Vectiq is a Python package in `src/vectiq/`. This page is for people who want to change it. For ground rules and pull requests, read [CONTRIBUTING](https://github.com/lucky-edgelord/aio-vector-bot/blob/main/CONTRIBUTING.md).

## Set up

```sh
git clone https://github.com/lucky-edgelord/aio-vector-bot
cd aio-vector-bot
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q && .venv/bin/ruff check .
```

The Vector SDK is built from source, so you need `rustc`, `cargo` and `cmake`. The first install takes several minutes.

Use a throwaway bot account for testing. Never commit a key: `.env`, `*.nsec` and `data/` are ignored by git.

## How the code is laid out

| Folder | What lives there |
|---|---|
| `cogs/` | Everything that talks to Vector: commands, listeners and background loops. One file per feature. |
| `stores/` | All SQL. A cog never writes a query; it calls a store. |
| `db/` | The SQLite connection and the numbered migrations. |
| `games/` | Game rules as pure Python with no network, plus their WebXDC front ends. |
| `render/` | Pillow pictures: rank cards, leaderboards, event banners and the month calendar. |
| `dashboard/` | The FastAPI server and the single-page front end. |
| `utils/` | Small helpers such as time parsing and `.ics` export. |

Keeping SQL in stores and Vector I/O in cogs lets the tests run without Vector.

## Adding a command

Commands are methods on a cog, with a decorator that declares who can use them. The command reference on this site is built by reading the cog files, so the help text and the docs come from the same place: write a clear one-line description and an example in the docstring.

## Adding a setting

1. Add the default to `DEFAULTS` in `config.py`.
2. Add a commented entry to `config.yaml`. The comment becomes the description in the [configuration reference](config-reference.md).
3. Validate it in `config.py` if a wrong value would break something.
4. Add a line to `CHANGELOG.md`.

## Changing the database

Add a new migration at the end of `db/migrations.py`. Never edit one that has shipped, because existing databases have already run it. Update the migration count in `tests/test_stores.py`.

## Adding a game

1. Write `games/<name>.py` with a `Game` subclass. It receives moves, returns updates and owns all state. It must not touch the network.
2. Write the front end in `games/apps/<name>/`: `index.html`, `manifest.toml` with `id = "vectiq-<name>"`, and `icon.png`.
3. Register it in `games/registry.py`.
4. Add tests for the rules in `tests/`.

## Tests and checks

```sh
.venv/bin/pytest -q          # tests
.venv/bin/ruff check .       # lint
```

CI also builds the SDK from source and runs both on every pull request.

## Building these docs

```sh
pip install markdown pygments pyyaml
python tools/build_docs.py          # writes the site to site/
python -m http.server -d site 8000  # preview at http://localhost:8000
```

The pages are Markdown files in `docs/`. The command and configuration references are generated from the code and `config.yaml`, so they can't drift. The build fails if a link or anchor points nowhere. When the change reaches `main`, GitHub Actions publishes the site.

Screenshots are rebuilt from a made-up demo community with `python tools/screenshots.py --chrome /path/to/chrome`, and the event pictures with `python tools/card_samples.py`.
