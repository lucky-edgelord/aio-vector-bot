---
title: Link safety
group: Community
order: 3
summary: Removes links to scam, malware, phishing, tracking and (optionally) adult sites, using oisd.nl blocklists and Google Safe Browsing.
---

Link safety checks every link in a message against big public blocklists. By default it uses [oisd big](https://oisd.nl), a list of around 230,000 domains that serve scams, phishing, malware, ads and tracking. It catches links with or without `https://`, and subdomains of a listed site too.

Turn it on with `!module on linksafety`. The first start downloads the lists into `data/linksafety`, which takes a few seconds, and they're downloaded again every `refresh_hours`. A cached copy is used when the internet is down.

## Lists

`lists` takes any domain list: one domain per line, hosts-file lines (`0.0.0.0 example.com`), or adblock `||example.com^` rules. `nsfw: true` adds oisd's adult-site list.

```yaml
linksafety:
  lists:
    - https://big.oisd.nl/domainswild2
    - https://example.org/my-list.txt
  nsfw: true
  allow: [example-shortener.com]     # never blocked
  block: [annoying.example]          # always blocked
```

`allow` beats everything, and `block` beats the lists.

## Google Safe Browsing

To also ask Google about each link, get a free [Safe Browsing API key](https://developers.google.com/safe-browsing/v4/get-started), put it in `.env` (for example `SAFE_BROWSING_KEY=...`), and set `safe_browsing_key_env: SAFE_BROWSING_KEY`. Only full links (with `https://`) are sent to Google.

## What happens

`action` works as in [Automod](automod.md): `delete`, `warn`, `timeout` or `log`. Staff with Manage Messages and `exempt_roles` / `exempt_channels` are skipped. `!linksafety check <link>` tells you whether a link would be removed, without posting it.

## Commands

{{commands:Link safety}}

## Settings

{{config:linksafety}}
