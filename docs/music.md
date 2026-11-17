---
title: Music
group: Events and play
order: 3
summary: Music in voice channels with a queue, loops, shuffle, filters, vote-skips, a DJ role and 24/7 mode.
---

Vectiq plays music in Vector voice channels, with the commands people know from the big Discord music bots.

## Setup

Music needs [yt-dlp](https://github.com/yt-dlp/yt-dlp) and [ffmpeg](https://ffmpeg.org):

```sh
pip install "vectiq[music]"          # or .venv/bin/pip install -e ".[music]" in the bot's folder
brew install ffmpeg                  # macOS; apt install ffmpeg on Debian/Ubuntu; winget install ffmpeg on Windows
```

The Docker image includes ffmpeg; build it with `EXTRAS=dashboard,webhooks,music`. Then run `!module on music`.

## Playing

Join a voice channel, then:

```text
!play never gonna give you up
!play https://www.youtube.com/watch?v=...
!play https://soundcloud.com/...
!play https://www.youtube.com/playlist?list=...
```

`play` takes search words, or a link to YouTube, YouTube Music, SoundCloud, Bandcamp, a direct audio file, or anything else yt-dlp knows, including playlists. `search` shows the top five results to pick from. `playnext` puts a song at the front.

`play` is shared with [mini games](games.md): `!play tictactoe` still starts a game, and anything else is music.

## The queue

`queue` shows ten songs per page, and `nowplaying` shows a progress bar. You can `skip`, `skipto 4`, `back`, `remove 3`, `move 5 1`, `shuffle`, `clearqueue`, `removedupes`, and `leavecleanup` (drops songs from people who left). `loop` cycles through off, track and queue.

`seek 1:30` (or `seek +30`) jumps within a song, and `replay` starts it again. `volume 60` changes the volume straight away. `filter` adds an effect: bassboost, nightcore, vaporwave, slowed, speed, 8d, karaoke, treble, soft, loud or mono. `filter off` removes it.

## Who's in charge

People with the **DJ** role (`dj_role`), staff with Manage Channels, and anyone alone with the bot control everything. Everyone else can add songs, remove their own, and **vote to skip**: once `vote_skip_ratio` of the listeners have voted, the song is skipped. Whoever added a song can always skip it. Leave `dj_role` empty to let everyone control the player.

The bot leaves when it's been alone for `leave_when_alone_seconds`, or has had nothing to play for `leave_when_idle_seconds`. `247` keeps it in the channel regardless.

!!! note "Audio streams"
    Songs stream through ffmpeg a few seconds ahead instead of being downloaded whole, so long mixes and live streams use little memory. Play only what you have the right to play in your community.

## Commands

{{commands:Music}}

## Settings

{{config:music}}
