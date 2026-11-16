#!/usr/bin/env python3
"""Build the documentation site into ./site (served by GitHub Pages).

    pip install markdown pygments pyyaml
    python tools/build_docs.py            # build, check every internal link, exit 1 if one is broken
    python tools/build_docs.py --serve    # build, then serve http://localhost:8000

Pages are ``docs/*.md`` with a small front matter block (title, group, order, summary). The command and
configuration references are generated from the source and config.yaml by ``docsgen`` (no SDK needed).
"""

from __future__ import annotations

import argparse
import html
import http.server
import json
import re
import shutil
import socketserver
import sys
from dataclasses import dataclass, field
from pathlib import Path

import markdown
from pygments.formatters import HtmlFormatter
from pygments.style import Style
from pygments.token import Comment, Generic, Keyword, Name, Number, Operator, String, Token

sys.path.insert(0, str(Path(__file__).resolve().parent))
import docsgen  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DOCS, TPL, OUT = ROOT / "docs", ROOT / "tools" / "site", ROOT / "site"
REPO = "https://github.com/lucky-edgelord/aio-vector-bot"
SITE_URL = "https://lucky-edgelord.github.io/aio-vector-bot/"

GROUPS = ["Start here", "Community", "Events and play", "Connect", "Reference", "Project"]


class VectorStyle(Style):
    """Code colours drawn from the site palette."""
    background_color = "#121214"
    styles = {
        Token: "#e4e4e7", Comment: "italic #6f737b", Keyword: "#59fcb3", Keyword.Constant: "#59fcb3",
        Operator: "#8d9097", String: "#e8c28a", Number: "#9ecbff", Name.Builtin: "#9ecbff",
        Name.Function: "#ececee bold", Name.Class: "#ececee bold", Name.Decorator: "#9ecbff",
        Name.Tag: "#59fcb3", Name.Attribute: "#9ecbff", Generic.Prompt: "#6f737b", Generic.Output: "#8d9097",
        Generic.Heading: "bold", Generic.Deleted: "#ff8a8a", Generic.Inserted: "#59fcb3",
    }


@dataclass
class Page:
    slug: str
    title: str
    group: str
    order: float
    summary: str
    body_md: str
    source: str = ""                       # path of the .md for "edit this page" ("" for generated pages)
    html: str = ""
    toc: list[tuple[int, str, str]] = field(default_factory=list)       # (level, id, text)
    sections: list[dict] = field(default_factory=list)                  # for search

    @property
    def url(self) -> str:
        return f"{self.slug}.html"


# -- reading pages ---------------------------------------------------------------------------------------


CUR = ' aria-current="page"'


def front_matter(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        meta[k.strip()] = v.strip().strip('"')
    return meta, text[m.end():]


def expand(md: str) -> str:
    """{{commands}}, {{commands:Events}}, {{config:events}}, {{changelog}} -> generated content."""
    def sub(m: re.Match) -> str:
        kind, _, arg = m.group(1).partition(":")
        if kind == "commands":
            return docsgen.commands_markdown(arg or None)
        if kind == "config":
            return docsgen.config_markdown(arg)
        if kind == "changelog":
            text = (ROOT / "CHANGELOG.md").read_text()
            return re.sub(r"^# .*\n+", "", text).replace("\n## ", "\n\n## ").replace("## ", "## ", 1)
        raise SystemExit(f"unknown placeholder {{{{{m.group(1)}}}}}")
    return re.sub(r"\{\{([a-z]+(?::[A-Za-z_ ]+)?)\}\}", sub, md)


def load_pages() -> list[Page]:
    pages = []
    for path in sorted(DOCS.glob("*.md")):
        meta, body = front_matter(path.read_text())
        pages.append(Page(slug=path.stem, title=meta.get("title", path.stem.replace("-", " ").title()),
                          group=meta.get("group", "Project"), order=float(meta.get("order", 50)),
                          summary=meta.get("summary", ""), body_md=body,
                          source="" if meta.get("generated") == "yes" else f"docs/{path.name}"))
    for group in {p.group for p in pages}:
        if group not in GROUPS:
            raise SystemExit(f"unknown group {group!r}; use one of {GROUPS}")
    return sorted(pages, key=lambda p: (GROUPS.index(p.group), p.order, p.title))


# -- markdown -> html ------------------------------------------------------------------------------------


def render(page: Page) -> None:
    md = markdown.Markdown(extensions=["extra", "admonition", "toc", "sane_lists", "codehilite"],
                           extension_configs={"codehilite": {"css_class": "hl", "guess_lang": False},
                                              "toc": {"toc_depth": "2-3", "permalink": False}})
    body = md.convert(expand(page.body_md))
    body = re.sub(r'href="([^"#:]+)\.md(#[^"]*)?"', lambda m: f'href="{m.group(1)}.html{m.group(2) or ""}"', body)
    body = re.sub(r"<table>", '<div class="table"><table>', body)
    body = re.sub(r"</table>", "</table></div>", body)
    body = body.replace('<div class="table"><div class="table">', '<div class="table">')
    body = re.sub(r'<div class="hl">', '<div class="code"><button class="copy" type="button" aria-label="Copy code">Copy</button>'
                  '<div class="hl">', body)
    body = re.sub(r"(</pre></div>)", r"\1</div>", body)
    # clickable headings
    body = re.sub(r'<h([23]) id="([^"]+)">(.*?)</h\1>',
                  r'<h\1 id="\2"><a class="anchor" href="#\2" aria-label="Link to this section">\3</a></h\1>', body, flags=re.S)
    page.html = body

    def walk(tokens):
        for t in tokens:
            yield t
            yield from walk(t.get("children", []))
    page.toc = [(t["level"], t["id"], re.sub(r"<[^>]+>", "", html.unescape(t["name"]))) for t in walk(md.toc_tokens)]

    # search sections: split at h2/h3
    parts = re.split(r'(<h[23] id="[^"]+">.*?</h[23]>)', body, flags=re.S)
    page.sections = [{"h": page.title, "id": "", "t": _text(parts[0])}]
    for i in range(1, len(parts), 2):
        m = re.match(r'<h[23] id="([^"]+)">(.*?)</h', parts[i], re.S)
        page.sections.append({"h": _text(m.group(2)), "id": m.group(1), "t": _text(parts[i + 1] if i + 1 < len(parts) else "")})


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())[:1200]


# -- templates -------------------------------------------------------------------------------------------


def fill(template: str, **values: str) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{{" + k + "}}", v)
    return out


def nav_html(pages: list[Page], current: str | None) -> str:
    out = []
    for group in GROUPS:
        items = [p for p in pages if p.group == group]
        if not items:
            continue
        links = "".join(f'<li><a href="{p.url}"{CUR if p.slug == current else ""}>'
                        f"{html.escape(p.title)}</a></li>" for p in items)
        out.append(f"<section><h2>{html.escape(group)}</h2><ul>{links}</ul></section>")
    return "".join(out)


def toc_html(page: Page) -> str:
    if len(page.toc) < 2:
        return ""
    items = "".join(f'<li class="l{lvl}"><a href="#{i}">{html.escape(t)}</a></li>' for lvl, i, t in page.toc)
    return f'<nav class="toc" aria-label="On this page"><h2>On this page</h2><ul>{items}</ul></nav>'


def prevnext(pages: list[Page], page: Page) -> str:
    i = pages.index(page)
    prev = pages[i - 1] if i > 0 else None
    nxt = pages[i + 1] if i + 1 < len(pages) else None
    cell = lambda p, label, cls: (f'<a class="{cls}" href="{p.url}"><small>{label}</small><span>{html.escape(p.title)}</span></a>'  # noqa: E731
                                  if p else "<span></span>")
    return f'<nav class="prevnext" aria-label="Pages">{cell(prev, "Previous", "prev")}{cell(nxt, "Next", "next")}</nav>'


def header(pages: list[Page], active: str = "") -> str:
    return fill((TPL / "header.html").read_text(), active=active)


def build_page(pages: list[Page], page: Page) -> str:
    edit = (f'<a class="edit" href="{REPO}/edit/main/{page.source}">Edit this page on GitHub</a>' if page.source else "")
    return fill((TPL / "page.html").read_text(), title=html.escape(page.title),
                description=html.escape(page.summary or f"{page.title}, in the Vectiq documentation"),
                header=header(pages), nav=nav_html(pages, page.slug), toc=toc_html(page),
                content=page.html, prevnext=prevnext(pages, page), edit=edit,
                canonical=SITE_URL + page.url, footer=(TPL / "footer.html").read_text())


# -- landing page ----------------------------------------------------------------------------------------

FEATURES = [
    ("moderation", "Moderation", "Warnings that escalate, timeouts, bans that lift themselves, purge, lock, automod, a mod log."),
    ("leveling", "Leveling", "XP for chatting on the familiar MEE6 curve, role rewards, and rank and leaderboard cards as images."),
    ("economy", "Economy", "Coins, daily streaks, work, a bank and a shop that sells roles."),
    ("tickets", "Tickets", "A private channel per request. Staff claim it; anyone closes it with a 🔒 reaction. Transcripts are kept."),
    ("onboarding", "Welcome and onboarding", "Greet, verify with a question, then let people pick roles from a reaction menu."),
    ("role-menus", "Role menus", "Reaction roles that add and remove, built from chat or from the dashboard."),
    ("giveaways", "Giveaways", "Timed, multiple winners, reroll. Entering is a 🎉 reaction."),
    ("events", "Event calendar", "RSVPs, waitlists, repeats, reminders by DM, a month picture and .ics files."),
    ("games", "Mini games", "Tic-Tac-Toe, Connect Four, trivia and slots as WebXDC apps, refereed by the bot."),
    ("security-cam", "Security cam", "Echo every message from every channel into one staff channel."),
    ("webhooks", "Webhooks", "Declare them in YAML. Vectiq creates them, DMs you each URL once and mirrors events into the channel."),
    ("dashboard", "Web dashboard", "Manage members, settings, tickets and more in a browser, behind real logins."),
]


def landing(pages: list[Page]) -> str:
    rows = "".join(f'<li><a href="{slug}.html"><b>{html.escape(name)}</b><span>{html.escape(text)}</span></a></li>'
                   for slug, name, text in FEATURES)
    return fill((TPL / "index.html").read_text(), header=header(pages, "home"), features=rows,
                footer=(TPL / "footer.html").read_text(), canonical=SITE_URL)


# -- link check ------------------------------------------------------------------------------------------


def check_links() -> list[str]:
    ids: dict[str, set[str]] = {}
    for f in OUT.glob("*.html"):
        ids[f.name] = set(re.findall(r'\bid="([^"]+)"', f.read_text()))
    bad = []
    for f in OUT.glob("*.html"):
        text = f.read_text()
        for attr, target in re.findall(r'\b(href|src)="([^"]+)"', text):
            if re.match(r"^(https?:|mailto:|data:|javascript:)", target):
                continue
            if f.name == "404.html":
                target = target.removeprefix("/aio-vector-bot/")   # the 404 page uses absolute project paths
            path, _, frag = target.partition("#")
            name = path or f.name
            if path and not (OUT / path).exists():
                bad.append(f"{f.name}: {attr}={target!r} does not exist")
            elif frag and name.endswith(".html") and frag not in ids.get(name, set()):
                bad.append(f"{f.name}: #{frag} is not on {name}")
    return bad


# -- build -----------------------------------------------------------------------------------------------


def build() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    pages = load_pages()
    for p in pages:
        render(p)
    for p in pages:
        (OUT / p.url).write_text(build_page(pages, p))
    (OUT / "index.html").write_text(landing(pages))
    (OUT / "404.html").write_text(fill((TPL / "404.html").read_text(), header=header(pages), footer=(TPL / "footer.html").read_text()))
    (OUT / "style.css").write_text((TPL / "style.css").read_text() + "\n/* code */\n" +
                                   HtmlFormatter(style=VectorStyle).get_style_defs(".hl"))
    shutil.copy(TPL / "site.js", OUT / "site.js")
    shutil.copy(TPL / "favicon.svg", OUT / "favicon.svg")
    shutil.copytree(DOCS / "images", OUT / "images")
    shutil.copytree(ROOT / "src" / "vectiq" / "assets" / "fonts", OUT / "fonts", ignore=shutil.ignore_patterns("*.txt"))
    shutil.copy(ROOT / "src" / "vectiq" / "assets" / "fonts" / "Inter-OFL.txt", OUT / "fonts" / "LICENSE.txt")
    (OUT / ".nojekyll").write_text("")
    index = [{"t": p.title, "u": p.url, "g": p.group, "s": p.sections} for p in pages]
    (OUT / "search.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    (OUT / "sitemap.xml").write_text('<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                     + "".join(f"<url><loc>{SITE_URL}{u}</loc></url>" for u in ["", *(p.url for p in pages)])
                                     + "</urlset>")
    bad = check_links()
    for line in bad:
        print("broken:", line, file=sys.stderr)
    print(f"built {len(pages)} pages into {OUT.relative_to(ROOT)}/" + (f" ({len(bad)} broken links)" if bad else ""))
    return 1 if bad else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serve", action="store_true")
    args = ap.parse_args()
    code = build()
    if args.serve:
        handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(OUT), **k)  # noqa: E731
        with socketserver.TCPServer(("", 8000), handler) as srv:
            print("http://localhost:8000")
            srv.serve_forever()
    sys.exit(code)


if __name__ == "__main__":
    main()
