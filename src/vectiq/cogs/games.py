"""WebXDC mini games.

``play <game>`` shares a small web app into the chat. People open it, and Vectiq joins the app's realtime
channel as the referee: it owns every rule, the clock and the coins, so a modified client can't cheat.
"""

from __future__ import annotations

import asyncio
import logging
import time

import vector
from vector.ext import commands

from ..games import GAMES, Player, create_game, packager
from ..games.base import Update
from ..utils.embeds import embed, fail, name_of, table

log = logging.getLogger("vectiq.games")

BLURB = {
    "tictactoe": "two players · classic",
    "connect4": "two players · four in a row",
    "trivia": "everyone · 8 timed questions, earns coins",
    "slots": "solo · bet your coins, bot-run reels",
}


class GameBank:
    """The economy as a game sees it: one community, addressed by npub."""

    def __init__(self, store, guild_id: str, start: int):
        self.store, self.guild_id, self.start = store, guild_id, start

    async def balance(self, npub: str) -> int:
        return (await self.store.wallet(self.guild_id, npub, start=self.start)).balance

    async def adjust(self, npub: str, amount: int, reason: str) -> int:
        return await self.store.adjust(self.guild_id, npub, amount, reason, start=self.start)


class Games(commands.Cog, name="Games"):
    """Mini games you play in a Mini App, refereed by the bot."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.instances: dict[str, tuple[object, str]] = {}   # app message id -> (game, guild id)
        self.hosting: set[str] = set()                        # app message ids a session is already refereeing
        self._tasks: set[asyncio.Task] = set()
        self.out_dir = f"{bot.config.data_dir}/xdc"

    # -- commands ---------------------------------------------------------------------

    @commands.command(name="games")
    async def games_(self, ctx):
        """List the mini games."""
        lines = [f"**{g.title}** (`play {name}`): {BLURB.get(name, '')}" for name, g in GAMES.items()]
        await ctx.send(embed=embed("Mini games", "\n".join(lines), footer="They open as Mini Apps in the chat"))

    @commands.command()
    async def play(self, ctx, game: str = ""):
        """Share a game: `play tictactoe`, `connect4`, `trivia` or `slots`."""
        game = game.lower().replace("-", "").replace(" ", "")
        if game not in GAMES:
            return await ctx.send(fail(f"Pick one of: {', '.join(GAMES)}."))
        path = packager.build(game, self.out_dir)
        app = await ctx.channel.send_xdc(str(path))
        # The SDK never auto-joins an app the bot posted itself, so the referee joins its own game right away.
        # (If its session later times out, the "opened" handler below starts a new one with the same game state.)
        try:
            session = await app.join()
            await session.set_idle_timeout(float(self.cfg.get("games.idle_timeout_seconds", 300)))
            task = asyncio.ensure_future(self._host(session, game))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        except Exception:  # noqa: BLE001 - the app is posted either way; the opened-handler can still take over
            log.exception("could not join my own %s app", game)
        await ctx.send(f"🎮 **{GAMES[game].title}** is ready. Tap the app above to play.")

    @commands.command()
    @commands.guild_only()
    async def gamestats(self, ctx, member: vector.Member = None):
        """Your record in every game."""
        member = member or ctx.author
        rows = await self.bot.stores.games.for_user(str(ctx.guild.id), str(member.id))
        if not rows:
            return await ctx.send(f"{name_of(member)} hasn't played yet. Try `games`.")
        await ctx.send(embed=embed(f"{name_of(member)}'s games", table(
            [(r["game"], str(r["played"]), str(r["won"]), str(r["drawn"])) for r in rows],
            ("game", "played", "won", "drawn"))))

    @commands.command()
    @commands.guild_only()
    async def gameboard(self, ctx, game: str = "tictactoe"):
        """Top players of one game."""
        if game not in GAMES:
            return await ctx.send(fail(f"Pick one of: {', '.join(GAMES)}."))
        rows = await self.bot.stores.games.leaderboard(str(ctx.guild.id), game)
        if not rows:
            return await ctx.send("Nobody has played that yet.")
        lines = []
        for i, r in enumerate(rows, 1):
            m = ctx.guild.get_member(r["user_id"])
            lines.append(f"`{i}.` {name_of(m) if m else r['user_id'][:10]}: {r['won']} won / {r['played']} played")
        await ctx.send(embed=embed(f"{GAMES[game].title} leaderboard", "\n".join(lines)))

    # -- the referee ------------------------------------------------------------------

    async def cog_load(self):
        """Register the referee. ``games.join_when``: ``opened`` (the bot joins when a player opens the app, the
        default) or ``shared`` (it joins as soon as the app is posted, and stays until idle)."""
        g = self.cfg["games"]
        self.bot.xdc_app("*", join_when=g.get("join_when", "opened"), idle_timeout=float(g["idle_timeout_seconds"]),
                         quiet_timeout=1800.0, max_per_chat=8)(self.referee)

    async def referee(self, session: vector.XdcSession):
        """Router handler: someone opened a Mini App. Referee it if it is one of ours."""
        manifest = await session.app.manifest()
        app_id = manifest.id or ""
        name = app_id.removeprefix("vectiq-") if app_id.startswith("vectiq-") else None
        if name in GAMES:
            await self._host(session, name)

    async def _host(self, session: vector.XdcSession, name: str):
        """Run one game session until everyone leaves. Only one session referees a given app message."""
        key = session.app.message_id
        if key in self.hosting:
            return                                    # the join-on-play session already has it
        self.hosting.add(key)
        guild_id = self._guild_id(session)
        entry = self.instances.get(key)
        if entry is None:
            bank = GameBank(self.bot.stores.economy, guild_id, self.cfg.get("economy.start_balance", 0))
            entry = (create_game(name, bank, self.cfg["games"]), guild_id)
            self.instances[key] = entry
            while len(self.instances) > 100:              # forget the oldest unfinished games
                self.instances.pop(next(iter(self.instances)))
        game = entry[0]
        ticker = asyncio.ensure_future(self._ticker(session, game, guild_id))
        try:
            log.info("refereeing %s in app message %s", name, key[:10])
            await session.send_json(game.state())
            async for event in session:
                log.debug("xdc event %s", event.type)
                if event.type == "peer_join":
                    await session.send_json(game.state())
                elif event.type == "data":
                    await self._on_data(session, game, guild_id, event)
        finally:
            ticker.cancel()
            self.hosting.discard(key)
            if getattr(game, "finished", False):
                self.instances.pop(key, None)

    def _guild_id(self, session) -> str:
        channel = session.channel
        community = getattr(channel, "community", None) or getattr(channel, "guild", None)
        return str(community.id) if community is not None else "dm"

    async def _on_data(self, session, game, guild_id: str, event) -> None:
        try:
            msg = event.json()
            if not isinstance(msg, dict):
                raise ValueError
        except ValueError:
            return
        addr = str(msg.get("addr", ""))[:200]
        log.debug("data %r from %s verified=%s direct=%s", msg.get("t"), event.peer, event.verified_sender, event.direct)
        sender = event.verified_sender
        if sender is None and self.cfg.get("games.allow_unverified", False) and event.peer and event.peer.npub:
            sender = event.peer.npub              # testing only: the peer's own claim, relayed so unprovable
        if sender is None:
            if msg.get("t") == "hello":
                await session.send_json(game.state())
            else:                                 # the client retries: a device is verified once its announcement lands
                await session.send_json({"t": "error", "msg": "Verifying your identity… try again.", "retry": True,
                                         "for": addr})
            return
        user = event.author or (self.bot.get_user(sender) if sender else None)
        who = Player(npub=str(sender), name=name_of(user) if user else "", addr=addr)
        try:
            update = await game.handle(who, msg)
        except Exception:
            log.exception("game %s failed on %r", game.name, msg.get("t"))
            update = Update(error="Something went wrong in that game.")
        await self._publish(session, game, guild_id, who, update)

    async def _publish(self, session, game, guild_id: str, who: Player, update: Update) -> None:
        if update.error:
            await session.send_json({"t": "error", "msg": update.error, "for": who.addr})
        if update.state is not None:
            await session.send_json(update.state)
        for outcome in update.outcomes:
            await self._settle(game, guild_id, outcome)

    async def _settle(self, game, guild_id: str, outcome) -> None:
        eco, stats = self.bot.stores.economy, self.bot.stores.games
        start = self.cfg.get("economy.start_balance", 0)
        try:
            if outcome.coins:
                await eco.adjust(guild_id, outcome.player.npub, outcome.coins, f"{game.name}: {outcome.note}", start=start)
            await stats.record(guild_id, outcome.player.npub, game.name, won=outcome.won, drawn=outcome.drawn,
                               score=outcome.score)
        except Exception:
            log.exception("could not record a %s result", game.name)
            return
        guild = self.bot.get_guild(guild_id)
        if guild is not None and game.name != "slots":
            self.bot.emit(guild, "games", f"{game.title}: {outcome.note}",
                          f"{outcome.player.label}" + (f" (+{outcome.coins})" if outcome.coins else ""))

    async def _ticker(self, session, game, guild_id: str) -> None:
        """Time-based games (trivia) advance on a clock, not on messages."""
        try:
            while True:
                await asyncio.sleep(1)
                update = await game.tick(time.time())
                if update is not None:
                    await self._publish(session, game, guild_id, Player(""), update)
        except asyncio.CancelledError:
            pass


async def setup(bot):
    await bot.add_cog(Games(bot))
