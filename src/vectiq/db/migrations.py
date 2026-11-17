"""Schema, as an ordered list. Index + 1 is the ``user_version`` it brings the database to.

Never edit an applied migration: append a new one. All ids are TEXT because Vector ids
are npub / hex strings. ``guild_id`` is the Community id.
"""

MIGRATIONS: list[str] = [
    # 1 - settings, moderation, leveling, economy
    """
    CREATE TABLE guild_settings (
        guild_id TEXT NOT NULL,
        key      TEXT NOT NULL,
        value    TEXT NOT NULL,
        PRIMARY KEY (guild_id, key)
    );

    CREATE TABLE mod_cases (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   TEXT NOT NULL,
        user_id    TEXT NOT NULL,
        moderator  TEXT NOT NULL,
        action     TEXT NOT NULL,
        reason     TEXT NOT NULL DEFAULT '',
        created_at INTEGER NOT NULL,
        expires_at INTEGER,
        active     INTEGER NOT NULL DEFAULT 1
    );
    CREATE INDEX idx_cases_user ON mod_cases (guild_id, user_id, action);

    CREATE TABLE levels (
        guild_id    TEXT NOT NULL,
        user_id     TEXT NOT NULL,
        xp          INTEGER NOT NULL DEFAULT 0,
        level       INTEGER NOT NULL DEFAULT 0,
        messages    INTEGER NOT NULL DEFAULT 0,
        last_xp_at  REAL NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    );
    CREATE INDEX idx_levels_rank ON levels (guild_id, xp DESC);

    CREATE TABLE level_rewards (
        guild_id TEXT NOT NULL,
        level    INTEGER NOT NULL,
        role_id  TEXT NOT NULL,
        PRIMARY KEY (guild_id, level)
    );

    CREATE TABLE wallets (
        guild_id     TEXT NOT NULL,
        user_id      TEXT NOT NULL,
        balance      INTEGER NOT NULL DEFAULT 0,
        bank         INTEGER NOT NULL DEFAULT 0,
        daily_at     INTEGER NOT NULL DEFAULT 0,
        daily_streak INTEGER NOT NULL DEFAULT 0,
        work_at      INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id),
        CHECK (balance >= 0 AND bank >= 0)
    );

    CREATE TABLE shop_items (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id    TEXT NOT NULL,
        name        TEXT NOT NULL,
        price       INTEGER NOT NULL CHECK (price > 0),
        description TEXT NOT NULL DEFAULT '',
        role_id     TEXT,
        stock       INTEGER,
        UNIQUE (guild_id, name)
    );

    CREATE TABLE inventory (
        guild_id TEXT NOT NULL,
        user_id  TEXT NOT NULL,
        item_id  INTEGER NOT NULL REFERENCES shop_items (id) ON DELETE CASCADE,
        quantity INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (guild_id, user_id, item_id)
    );

    CREATE TABLE transactions (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   TEXT NOT NULL,
        user_id    TEXT NOT NULL,
        amount     INTEGER NOT NULL,
        reason     TEXT NOT NULL,
        created_at INTEGER NOT NULL
    );
    CREATE INDEX idx_tx_user ON transactions (guild_id, user_id, id DESC);
    """,
    # 2 - tickets, verification, role menus, giveaways, game stats, activity
    """
    CREATE TABLE tickets (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   TEXT NOT NULL,
        channel_id TEXT,
        user_id    TEXT NOT NULL,
        subject    TEXT NOT NULL DEFAULT '',
        status     TEXT NOT NULL DEFAULT 'open',
        claimed_by TEXT,
        created_at INTEGER NOT NULL,
        closed_at  INTEGER,
        closed_by  TEXT
    );
    CREATE INDEX idx_tickets_user ON tickets (guild_id, user_id, status);

    CREATE TABLE ticket_messages (
        id        INTEGER PRIMARY KEY AUTOINCREMENT,
        ticket_id INTEGER NOT NULL REFERENCES tickets (id) ON DELETE CASCADE,
        author_id TEXT NOT NULL,
        content   TEXT NOT NULL,
        sent_at   INTEGER NOT NULL
    );

    CREATE TABLE verifications (
        guild_id   TEXT NOT NULL,
        user_id    TEXT NOT NULL,
        question   TEXT NOT NULL,
        answer     TEXT NOT NULL,
        attempts   INTEGER NOT NULL DEFAULT 0,
        created_at INTEGER NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    );

    CREATE TABLE role_menus (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        message_id TEXT NOT NULL,
        title      TEXT NOT NULL,
        UNIQUE (message_id)
    );

    CREATE TABLE role_menu_options (
        menu_id INTEGER NOT NULL REFERENCES role_menus (id) ON DELETE CASCADE,
        emoji   TEXT NOT NULL,
        role_id TEXT NOT NULL,
        label   TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (menu_id, emoji)
    );

    CREATE TABLE giveaways (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        message_id TEXT,
        host_id    TEXT NOT NULL,
        prize      TEXT NOT NULL,
        winners    INTEGER NOT NULL DEFAULT 1,
        ends_at    INTEGER NOT NULL,
        ended      INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_giveaways_open ON giveaways (ended, ends_at);

    CREATE TABLE giveaway_entries (
        giveaway_id INTEGER NOT NULL REFERENCES giveaways (id) ON DELETE CASCADE,
        user_id     TEXT NOT NULL,
        PRIMARY KEY (giveaway_id, user_id)
    );

    CREATE TABLE game_stats (
        guild_id TEXT NOT NULL,
        user_id  TEXT NOT NULL,
        game     TEXT NOT NULL,
        played   INTEGER NOT NULL DEFAULT 0,
        won      INTEGER NOT NULL DEFAULT 0,
        drawn    INTEGER NOT NULL DEFAULT 0,
        score    INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, user_id, game)
    );

    CREATE TABLE activity (
        guild_id   TEXT NOT NULL,
        day        TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        messages   INTEGER NOT NULL DEFAULT 0,
        joins      INTEGER NOT NULL DEFAULT 0,
        leaves     INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (guild_id, day, channel_id)
    );
    """,
    # 3 - onboarding progress
    """
    CREATE TABLE onboarding (
        guild_id     TEXT NOT NULL,
        user_id      TEXT NOT NULL,
        started_at   INTEGER NOT NULL,
        verified_at  INTEGER,
        picked_at    INTEGER,
        completed_at INTEGER,
        PRIMARY KEY (guild_id, user_id)
    );
    """,
    # 4 - web dashboard: sign-in codes, sessions, audit log, settings edited in the dashboard
    """
    CREATE TABLE dash_logins (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        npub       TEXT NOT NULL,
        code_hash  TEXT NOT NULL,
        link_hash  TEXT NOT NULL UNIQUE,
        expires_at INTEGER NOT NULL,
        attempts   INTEGER NOT NULL DEFAULT 0,
        used       INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_dash_logins_npub ON dash_logins (npub);

    CREATE TABLE dash_sessions (
        token_hash TEXT PRIMARY KEY,
        npub       TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        last_seen  INTEGER NOT NULL,
        user_agent TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE dash_audit (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        at       INTEGER NOT NULL,
        npub     TEXT NOT NULL,
        guild_id TEXT NOT NULL DEFAULT '',
        action   TEXT NOT NULL,
        detail   TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX idx_dash_audit_guild ON dash_audit (guild_id, id);

    CREATE TABLE config_overrides (
        path       TEXT PRIMARY KEY,
        value      TEXT NOT NULL,
        updated_by TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    );
    """,
    # 5 - dashboard accounts (username + password, each tied to a Vector npub for permissions)
    """
    CREATE TABLE dash_users (
        username     TEXT PRIMARY KEY COLLATE NOCASE,
        npub         TEXT NOT NULL,
        pw_hash      TEXT NOT NULL,
        created_at   INTEGER NOT NULL,
        updated_at   INTEGER NOT NULL,
        created_by   TEXT NOT NULL DEFAULT '',
        failed       INTEGER NOT NULL DEFAULT 0,
        locked_until INTEGER NOT NULL DEFAULT 0,
        last_login   INTEGER
    );
    CREATE INDEX idx_dash_users_npub ON dash_users (npub);
    """,
    # 6 - event calendar
    """
    CREATE TABLE events (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id    TEXT NOT NULL,
        channel_id  TEXT NOT NULL,
        message_id  TEXT,
        image_message_id TEXT,
        footer_message_id TEXT,
        creator_id  TEXT NOT NULL,
        title       TEXT NOT NULL,
        description TEXT NOT NULL DEFAULT '',
        location    TEXT NOT NULL DEFAULT '',
        image_path  TEXT NOT NULL DEFAULT '',
        starts_at   INTEGER NOT NULL,
        ends_at     INTEGER NOT NULL,
        tz          TEXT NOT NULL DEFAULT 'UTC',
        repeat      TEXT NOT NULL DEFAULT 'none',
        remind      TEXT NOT NULL DEFAULT '[]',
        capacity    INTEGER NOT NULL DEFAULT 0,
        role_id     TEXT NOT NULL DEFAULT '',
        status      TEXT NOT NULL DEFAULT 'scheduled',
        created_at  INTEGER NOT NULL
    );
    CREATE INDEX idx_events_guild ON events (guild_id, starts_at);
    CREATE INDEX idx_events_status ON events (status, starts_at);
    CREATE INDEX idx_events_message ON events (message_id);
    CREATE INDEX idx_events_footer ON events (footer_message_id);

    CREATE TABLE event_rsvps (
        event_id INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        user_id  TEXT NOT NULL,
        status   TEXT NOT NULL,
        at       REAL NOT NULL,
        PRIMARY KEY (event_id, user_id)
    );

    CREATE TABLE event_reminders (
        event_id  INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
        starts_at INTEGER NOT NULL,
        minutes   INTEGER NOT NULL,
        PRIMARY KEY (event_id, starts_at, minutes)
    );
    """,
    # 7 - verification ported from GateBot: lasting verified records, one-time web links,
    #     hashed device marks (one verification per device), and softbans (kick on sight)
    """
    CREATE TABLE verified_members (
        guild_id    TEXT NOT NULL,
        user_id     TEXT NOT NULL,
        verified_at INTEGER NOT NULL,
        is_adult    INTEGER NOT NULL DEFAULT 0,
        method      TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (guild_id, user_id)
    );

    CREATE TABLE verify_links (
        token      TEXT PRIMARY KEY,
        guild_id   TEXT NOT NULL,
        user_id    TEXT NOT NULL,
        channel_id TEXT NOT NULL DEFAULT '',
        age        INTEGER,
        created_at INTEGER NOT NULL,
        used       INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX idx_verify_links_user ON verify_links (guild_id, user_id);

    CREATE TABLE verify_marks (
        guild_id TEXT NOT NULL,
        hash     TEXT NOT NULL,
        at       INTEGER NOT NULL,
        PRIMARY KEY (guild_id, hash)
    );

    CREATE TABLE softbans (
        guild_id  TEXT NOT NULL,
        user_id   TEXT NOT NULL,
        reason    TEXT NOT NULL DEFAULT '',
        by_id     TEXT NOT NULL DEFAULT '',
        kicks     INTEGER NOT NULL DEFAULT 0,
        banned_at INTEGER NOT NULL,
        PRIMARY KEY (guild_id, user_id)
    );
    """,
    # 8: image guard blocklist and stream/video alerts
    """
    CREATE TABLE image_blocks (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id TEXT NOT NULL,
        hash     TEXT NOT NULL,
        note     TEXT NOT NULL DEFAULT '',
        by_id    TEXT NOT NULL DEFAULT '',
        at       INTEGER NOT NULL,
        UNIQUE (guild_id, hash)
    );

    CREATE TABLE notify_feeds (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id   TEXT NOT NULL,
        kind       TEXT NOT NULL,
        source     TEXT NOT NULL,
        channel_id TEXT NOT NULL,
        message    TEXT NOT NULL DEFAULT '',
        role       TEXT NOT NULL DEFAULT '',
        by_id      TEXT NOT NULL DEFAULT '',
        at         INTEGER NOT NULL,
        UNIQUE (guild_id, kind, source, channel_id)
    );

    CREATE TABLE notify_seen (
        feed_key TEXT NOT NULL,
        item_id  TEXT NOT NULL,
        at       INTEGER NOT NULL,
        PRIMARY KEY (feed_key, item_id)
    );
    """,
]
