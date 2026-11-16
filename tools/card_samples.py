#!/usr/bin/env python3
"""Draw the sample event banner and month calendar used in the docs (made-up demo data).

    python tools/card_samples.py        # writes docs/images/event-banner.png and docs/images/calendar.png
"""

import datetime as dt
from pathlib import Path

from vectiq.render import Slot, calendar_card, event_card

OUT = Path(__file__).resolve().parent.parent / "docs" / "images"
D = dt.date

(OUT / "event-banner.png").write_bytes(event_card(
    "Game night", "Nov 20 Fri", "8:00 PM – 10:00 PM EST", location="Voice lounge", host="Lucky",
    community="Vector Bot And Webxdc dev", tz_label="America/New_York"))

slots = [Slot(D(2026, 11, 16), "7:00 PM", "Game night", 4, True), Slot(D(2026, 11, 20), "8:00 PM", "Art show"),
         Slot(D(2026, 11, 20), "6:30 PM", "Office hours"), Slot(D(2026, 11, 23), "7:00 PM", "Game night"),
         Slot(D(2026, 11, 30), "7:00 PM", "Game night"), Slot(D(2026, 11, 9), "7:00 PM", "Game night"),
         Slot(D(2026, 11, 25), "6:00 PM", "Webxdc dev stream"), Slot(D(2026, 11, 3), "10:00 AM", "Release 0.2")]
(OUT / "calendar.png").write_bytes(calendar_card(
    2026, 11, slots, today=D(2026, 11, 16), community="Vector Bot And Webxdc dev", tz_label="Times in America/New_York"))
print("wrote", OUT / "event-banner.png", OUT / "calendar.png")
