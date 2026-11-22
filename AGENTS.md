# AGENTS.md

Instructions for AI agents (Claude, Codex, Cursor and others) that install, run, configure or change **Vectiq**, the all-in-one bot for [Vector](https://vectorapp.io) communities. People should read the [README](README.md) and the [docs](https://lucky-edgelord.github.io/aio-vector-bot/).

## Ground rules

- **Keys are secrets.** The bot's key (`VECTOR_NSEC`, an `nsec1…`) is its Vector account. It goes only in `.env` (mode 600), never in `config.yaml`, a commit, a log, a chat message or a command line that others can see. Never ask for, or use, the person's *personal* nsec: the bot gets its own account (the installer makes one if no key is given).
- Ask before anything you can't undo, or that changes what the bot does in someone's community: deleting data, restoring a backup, turning on `marketplace.allow_code` or `plugins.allow_install`, banning, mass messages.
- Prefer the bot's own tools over editing files: the setup wizard, the dashboard, the MCP server, and the CLI flags below. They check what they write.

## Installing for someone

One line, the same way Ollama installs. It gets git if needed, puts Vectiq in `~/vectiq` (`VECTIQ_DIR` to change), installs Python, Rust and the rest, and starts the bot at login.

| System | Command |
|---|---|
| macOS, Linux | `curl -fsSL https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.sh \| sh` |
| Windows (PowerShell) | `irm https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.ps1 \| iex` |
| Docker | see [docs/docker.md](docs/docker.md) |

An agent has no terminal to answer questions on, so run it without prompts:

```sh
# macOS / Linux. Leave VECTOR_NSEC unset to create a new bot account.
curl -fsSL https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.sh \
  | VECTIQ_INVITE_URLS="https://vectorapp.io/invite/..." sh -s -- --yes
```

```powershell
# Windows
$env:VECTIQ_YES = "1"; $env:VECTIQ_INVITE_URLS = "https://vectorapp.io/invite/..."
irm https://raw.githubusercontent.com/lucky-edgelord/aio-vector-bot/main/get.ps1 | iex
```

Add `--no-service` (`$env:VECTIQ_NO_SERVICE = "1"` on Windows) to install without starting it at login. The first install compiles the Vector SDK from Rust and takes several minutes; don't cut it short. Running the same line again updates Vectiq and keeps the config and data.

Then check it:

| | macOS | Linux | Windows |
|---|---|---|---|
| Config is valid | `~/vectiq/run.sh --check` | same | `~\vectiq\run.ps1 --check` |
| Logs | `~/vectiq/data/vectiq.log` | `journalctl --user -u vectiq -f` | `~\vectiq\data\vectiq.log` |
| Service | `launchctl kickstart -k gui/$(id -u)/com.vectiq.bot` | `systemctl --user restart vectiq` | `Start-ScheduledTask Vectiq` |

The log says `logged in as npub1…` when the bot is up. Tell the person that npub: it's the account they invite to their community.

**What the person has to do themselves** (say so plainly; you can't do these for them):

1. Invite the bot's account to their Vector community, or give you an invite link for `VECTIQ_INVITE_URLS`.
2. In Vector, give the bot a role with Manage Roles, Manage Channels, Manage Messages, Moderate Members, Kick and Ban. Without them it still runs and says which permission is missing.
3. Back up `~/vectiq/.env`: it holds the bot's account.

## Configuring

Below, `vectiq …` means `~/vectiq/run.sh …` (`~\vectiq\run.ps1 …` on Windows) for a one-line install, or `vectiq` itself for a pip install.

| Way | When |
|---|---|
| `vectiq --setup` (or **Setup wizard** on the dashboard) | First setup: features, channels, verification. Asks one question at a time. |
| Dashboard, `http://localhost:8090` | Everything, for people. Turn on `modules.dashboard`. Sign-in: `vectiq --add-user NAME --npub NPUB`. |
| MCP server (`vectiq --mcp`, [docs/mcp.md](docs/mcp.md)) | You, managing communities: members, roles, channels, settings, modules. Token in `VECTIQ_MCP_TOKEN`. Set `mcp.read_only: true` if you only need to look. |
| `config.yaml` | By hand. Run `vectiq --check` after every edit; [docs/config-reference.md](docs/config-reference.md) lists every key. |
| `vectiq --export-config FILE` / `--import-config FILE` | Copy settings between bots; import shows the changes first. |

Make a restore point before big changes: `vectiq --backup "before X"`, list with `--list-backups`, undo with `--restore N` (stop the bot first).

### Modules

Every feature is a module that switches on and off live (`!module on music`, the dashboard, or `modules.<name>` in `config.yaml`).

- **From the marketplace** ([lucky-edgelord/aio-marketplace](https://github.com/lucky-edgelord/aio-marketplace)): dashboard **Marketplace → Browse**, or `!module get <id>` in chat, or the MCP tool `add_module_from_marketplace`.
- **Write one** as a single JSON file: read the format with the MCP tool `module_format_guide` (or [docs/json-modules.md](docs/json-modules.md)), check it with `vectiq --check-module FILE` or `check_module_json`, then add it with `vectiq --import-module FILE` or `add_module_json`. Modules without `code` can only reply, react and post on timers, so they are safe to add.
- **Modules with code** run Python with the bot's access. They need `marketplace.allow_code: true` and they install switched off. Read the code and ask the owner first.

## Changing the code

```sh
git clone https://github.com/lucky-edgelord/aio-vector-bot && cd aio-vector-bot
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/pytest -q && .venv/bin/ruff check .
```

- Layout: `src/vectiq/cogs/` talk to Vector (one file per feature), `stores/` hold all SQL, `db/migrations.py` has numbered migrations, `dashboard/` is FastAPI plus a no-build single-page app (`static/app.js`), `jsonmods/` is JSON modules and the marketplace client. More in [docs/development.md](docs/development.md).
- Tests run without Vector. Add one for every fix and feature; keep the suite green and `ruff check` clean.
- A new database table or column is a new migration, never an edit to an old one.
- Docs are in `docs/*.md` and are built into the website by `tools/build_docs.py`. Write them for the person using the bot: plain words, what to do, what happens.
- Use a throwaway bot account for live testing, never a real community's key.
