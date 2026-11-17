"""``vectiq --setup``: a step-by-step setup wizard in the terminal.

It asks the same questions as the dashboard's Setup wizard (``dashboard/schema.py`` WIZARD)
and writes the answers into config.yaml, changing only the values: every comment and the
layout of the file stay as they are. A copy of the old file is kept as config.yaml.bak.
"""

from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from .config import Config, ConfigError
from .dashboard import schema

KEY = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_]+):(?P<rest>.*)$")


# -- editing config.yaml without losing comments ----------------------------------------------

def scalar(value: Any) -> str:
    """One value as YAML on a single line (lists and maps in flow style)."""
    out = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=10_000).strip()
    return out.removesuffix("...").strip()


def _split_comment(rest: str) -> tuple[str, str]:
    """Split ' value   # comment' into the value and the spacing+comment, minding quotes."""
    quote = None
    for i, ch in enumerate(rest):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or rest[i - 1] in " \t"):
            j = i
            while j > 0 and rest[j - 1] in " \t":
                j -= 1
            return rest[:j], rest[j:]
    return rest.rstrip(), ""


def _block_end(lines: list[str], start: int, indent: int) -> int:
    """The line after the block that starts at ``start`` (its children are indented deeper)."""
    i = start + 1
    while i < len(lines):
        line = lines[i]
        if line.strip() and not line.lstrip().startswith("#"):
            if len(line) - len(line.lstrip()) <= indent and not line.lstrip().startswith("- "):
                break
            if len(line) - len(line.lstrip()) < indent:
                break
        i += 1
    while i > start + 1 and not lines[i - 1].strip():
        i -= 1
    return i


def set_value(text: str, path: str, value: Any) -> str:
    """Set ``a.b.c`` in YAML text, keeping comments. Missing keys are added in their section."""
    lines = text.split("\n")
    parts = path.split(".")
    lo, hi, indent = 0, len(lines), -1
    for depth, part in enumerate(parts):
        last = depth == len(parts) - 1
        found = None
        child_indent = None
        for i in range(lo, hi):
            m = KEY.match(lines[i])
            if not m or lines[i].lstrip().startswith("#"):
                continue
            ind = len(m["indent"])
            if ind <= indent:
                continue
            if child_indent is None:
                child_indent = ind
            if ind == child_indent and m["key"] == part:
                found = (i, m)
                break
        if found is None:
            pad = " " * (child_indent if child_indent is not None else indent + 2 if indent >= 0 else 0)
            rest = parts[depth:]
            new = []
            for k, key in enumerate(rest):
                p = pad + "  " * k
                new.append(f"{p}{key}: {scalar(value)}" if k == len(rest) - 1 else f"{p}{key}:")
            at = hi
            while at > lo and not lines[at - 1].strip():
                at -= 1
            lines[at:at] = new
            return "\n".join(lines)
        i, m = found
        ind = len(m["indent"])
        if last:
            val, comment = _split_comment(m["rest"])
            end = _block_end(lines, i, ind)
            head = f"{m['indent']}{part}: {scalar(value)}"
            if comment:   # keep the comment in its column when there's room
                column = len(lines[i]) - len(comment.lstrip())
                comment = " " * max(column - len(head), 1) + comment.lstrip()
            lines[i] = head + comment
            if not val.strip():   # a block list or map under the key is replaced by the flow value
                del lines[i + 1:end]
            return "\n".join(lines)
        lo, hi, indent = i + 1, _block_end(lines, i, ind), ind
    return "\n".join(lines)


# -- the installer screens ----------------------------------------------------------------------
#
# Like a text-mode OS installer: one boxed screen per question, the bot asks, you answer.
# Enter keeps the value shown and moves on; < goes back; s skips the rest of a section; q quits.

class Screen:
    """Draws boxed screens. Clears the terminal and uses colour only on a real terminal."""

    def __init__(self, say: Callable[[str], None], tty: bool):
        self.say, self.tty = say, tty
        self.width = min(shutil.get_terminal_size((80, 24)).columns, 78) if tty else 72

    def b(self, t: str) -> str:
        return f"\033[1m{t}\033[0m" if self.tty else t

    def dim(self, t: str) -> str:
        return f"\033[2m{t}\033[0m" if self.tty else t

    def accent(self, t: str) -> str:
        return f"\033[1;32m{t}\033[0m" if self.tty else t

    def draw(self, stage: str, n: int, total: int, bot: list[str], body: list[str], keys: str) -> None:
        import textwrap

        w = self.width
        inner = w - 4
        if self.tty:
            self.say("\033[2J\033[H")
        bar_len = 20
        filled = round(bar_len * n / max(total, 1))
        title = f" Vectiq setup · {stage} "
        progress = f" {'■' * filled}{'□' * (bar_len - filled)} {n}/{total} "
        self.say("┌" + title + "─" * max(w - 2 - len(title) - len(progress), 1) + progress + "┐")
        self.say("│" + " " * (w - 2) + "│")
        for k, line in enumerate(x for x in bot if x):
            for j, part in enumerate(textwrap.wrap(line, inner - 9) or [""]):
                lead = "Vectiq › " if k == 0 and j == 0 else "         "
                self._row((self.accent(lead) if lead.strip() else lead) + part, len(lead) + len(part), inner)
            self.say("│" + " " * (w - 2) + "│")
        for line in body:
            plain = re.sub(r"\033\[[0-9;]*m", "", line)
            if len(plain) <= inner:
                self._row(line, len(plain), inner)
            else:
                for part in textwrap.wrap(plain, inner, subsequent_indent="     "):
                    self._row(part, len(part), inner)
        self.say("│" + " " * (w - 2) + "│")
        self.say("└" + "─" * (w - 2) + "┘")
        self.say(self.dim(keys))

    def _row(self, text: str, visible: int, inner: int) -> None:
        self.say("│ " + text + " " * max(inner - visible, 0) + " │")


def show(value: Any) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, list):
        return ", ".join(map(str, value)) or "none"
    return "default" if value in ("", None) else str(value)


def parse(f: dict, raw: str) -> Any:
    """Turn a typed answer into the setting's value. Raises FieldError with a friendly message."""
    if f["type"] == "bool":
        if raw.lower() in ("y", "yes", "on", "true", "1"):
            return True
        if raw.lower() in ("n", "no", "off", "false", "0"):
            return False
        raise schema.FieldError("Just y or n, please.")
    if f["type"] == "enum":
        if raw.isdigit() and 1 <= int(raw) <= len(f["options"]):
            return f["options"][int(raw) - 1]
        if raw in f["options"]:
            return raw
        raise schema.FieldError(f"Pick a number from 1 to {len(f['options'])}.")
    if raw == "-":
        raw = [] if f["type"] == "list" else ""
    elif f["type"] == "list":
        raw = [x.strip() for x in raw.split(",")]
    return schema.coerce(f["path"], raw)


def run(path: str | Path | None = None, *, ask: Callable[[str], str] = input,
        say: Callable[[str], None] = print, tty: bool | None = None) -> int:
    import sys

    scr = Screen(say, sys.stdout.isatty() if tty is None else tty)
    cfg_path = Path(path or "config.yaml")
    if not cfg_path.exists():
        from .scaffold import example

        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(example("config.example.yaml"), "utf-8")
        say(f"{cfg_path} didn't exist, so I made one from the example.")
    cfg = Config.load(cfg_path, env={})
    answers: dict[str, Any] = {}

    def value(p):
        return answers[p] if p in answers else cfg.get(p)

    def keep(p, v):
        if v == cfg.get(p):
            answers.pop(p, None)
        else:
            answers[p] = v

    def screens() -> list[dict]:
        out = [{"key": "hello", "stage": "Welcome"}]
        for st in schema.WIZARD:
            if not schema.applies(st, value):
                continue
            if st["id"] == "features":
                out.append({"key": "features", "stage": st["title"], "st": st})
                continue
            qs = [p for p in st["paths"] if schema.applies(p, value)]
            out += [{"key": f"q:{p}", "stage": st["title"], "st": st, "path": p, "first": i == 0} for i, p in enumerate(qs)]
        out.append({"key": "ready", "stage": "Ready"})
        return out

    current, note = "hello", ""
    keys_q = "Enter: keep and continue   <: back   s: skip section   q: quit"
    while True:
        lst = screens()
        idx = next((i for i, x in enumerate(lst) if x["key"] == current), 1)
        sc = lst[idx]
        total = len(lst)

        def move(step, idx=idx, lst=lst):
            nonlocal current
            current = lst[min(max(idx + step, 0), len(lst) - 1)]["key"]

        if sc["key"] == "hello":
            scr.draw("Welcome", 0, total, [schema.WIZARD_HELLO], [], "Press Enter to start, or q to quit.")
            raw = ask("> ").strip().lower()
            if raw == "q":
                say("No problem. Nothing was changed.")
                return 0
            move(1)
            continue

        if sc["key"] == "features":
            paths = [p for p in sc["st"]["paths"] if schema.applies(p, value)]
            body = [f"{n:>2}. [{'x' if value(p) else ' '}] {schema.FIELDS[p]['label']}  "
                    + scr.dim(schema.FIELDS[p]["help"]) for n, p in enumerate(paths, 1)]
            scr.draw(sc["stage"], idx, total, [sc["st"]["say"], note], body,
                     "Type numbers to tick or untick (e.g. 3 9). Enter: continue   <: back   q: quit")
            note = ""
            raw = ask("> ").strip()
            if raw == "q":
                say("Stopped. Nothing was changed.")
                return 0
            if raw == "<":
                move(-1)
            elif not raw:
                move(1)
            else:
                nums = raw.replace(",", " ").split()
                if all(x.isdigit() and 1 <= int(x) <= len(paths) for x in nums):
                    for x in nums:
                        p = paths[int(x) - 1]
                        keep(p, not value(p))
                else:
                    note = f"Hmm, I need numbers from 1 to {len(paths)}."
            continue

        if sc["key"] == "ready":
            if not answers:
                scr.draw("Ready", total, total, ["You didn't change anything, so there's nothing to save."], [],
                         "Enter: finish   <: back")
                if ask("> ").strip() == "<":
                    move(-1)
                    continue
                say("Nothing changed.")
                return 0
            body = []
            for st in schema.WIZARD:
                ks = [k for k in answers if k in st["paths"]]
                if ks:
                    body.append(scr.b(st["title"]))
                    body += [f"  {schema.FIELDS[k]['label']}: {show(cfg.get(k))} → {scr.b(show(answers[k]))}" for k in ks]
            if any(schema.FIELDS[k]["restart"] for k in answers):
                body += ["", scr.dim("A few of these need a restart to take effect.")]
            scr.draw("Ready", total, total, [schema.WIZARD_READY, note], body,
                     "y: save   <: back   q: quit without saving")
            note = ""
            raw = ask("Save? [y/<] ").strip().lower()
            if raw == "<":
                move(-1)
                continue
            if raw == "q" or raw in ("n", "no"):
                say("Left config.yaml as it was.")
                return 0
            if raw not in ("", "y", "yes"):
                continue
            break

        # one question
        f = schema.FIELDS[sc["path"]]
        cur = value(sc["path"])
        body = []
        if f["type"] == "enum":
            help_ = schema.OPTION_HELP.get(f["path"], {})
            for n, opt in enumerate(f["options"], 1):
                mark = "●" if opt == cur else "○"
                body.append(f"  {n}. {mark} {scr.b(opt) if opt == cur else opt}"
                            + (scr.dim(f" — {help_[opt]}") if opt in help_ else ""))
            body += ["", f"Now: {show(cur)}"]
        else:
            hint = {"bool": "y or n", "list": "separate with commas, - for none", "channel": "a channel name, - for default",
                    "text": "- to clear", "longtext": "- to clear"}.get(f["type"], "a number")
            body += [f"Now: {scr.b(show(cur))}", scr.dim(f"({hint})")]
        if f["help"]:
            body.append(scr.dim(f["help"]))
        if f["restart"]:
            body.append(scr.dim("Takes effect after a restart."))
        bot = [sc["st"]["say"] if sc["first"] else "", schema.WIZARD_ASK.get(f["path"], f["label"]), note]
        scr.draw(sc["stage"], idx, total, bot, body, keys_q)
        note = ""
        raw = ask("> ").strip()
        if raw == "q":
            say("Stopped. Nothing was changed.")
            return 0
        if raw == "<":
            move(-1)
            continue
        if raw.lower() == "s":
            last = max(i for i, x in enumerate(lst) if x["stage"] == sc["stage"])
            current = lst[min(last + 1, len(lst) - 1)]["key"]
            continue
        if raw:
            try:
                keep(f["path"], parse(f, raw))
            except schema.FieldError as exc:
                note = f"Sorry, that didn't work: {exc}"
                continue
        move(1)

    try:   # a restore point first, like an installer would
        import asyncio

        from .backup import RestorePoints
        asyncio.run(RestorePoints(cfg).create("Before the setup wizard", "automatic"))
    except Exception as exc:  # noqa: BLE001 - the .bak copy below still protects config.yaml
        say(f"(I couldn't make a restore point first: {exc})")
    old = cfg_path.read_text()
    text = old
    for p, v in answers.items():
        text = set_value(text, p, v)
    backup = cfg_path.with_name(cfg_path.name + ".bak")
    shutil.copyfile(cfg_path, backup)
    cfg_path.write_text(text)
    try:
        Config.load(cfg_path, env={})
    except ConfigError as exc:
        cfg_path.write_text(old)
        say(f"Hmm, that combination isn't valid, so I didn't change anything: {exc}")
        say("Run vectiq --setup again to fix it.")
        return 1
    after = ["Restart me to use the new settings."]
    if value("verification.mode") == "captcha" and value("modules.verification"):
        after.append(f"Put your CAPTCHA secret in .env as {value('verification.captcha.secret_key_env')}=...")
    after.append("Then type !verification in your community and I'll tell you if I'm missing any permissions.")
    scr.draw("Done", 1, 1, [schema.WIZARD_DONE, f"Saved. Your old config is in {backup.name}."], after, "")
    return 0
