from __future__ import annotations

import random

import vector
from vector.ext import commands

from ..stores import InsufficientFunds
from ..utils.durations import format_duration
from ..utils.embeds import embed, fail, name_of, ok


class Economy(commands.Cog, name="Economy"):
    """A per-community currency: daily and work rewards, a bank, a shop and a rich list."""

    def __init__(self, bot):
        self.bot = bot
        self.cfg = bot.config
        self.store = bot.stores.economy

    async def cog_check(self, ctx):
        if ctx.guild is None:
            raise commands.CheckFailure("The economy works inside a community.")
        return True

    @property
    def sym(self) -> str:
        return self.cfg.get("economy.currency_symbol", "🪙")

    @property
    def start(self) -> int:
        return self.cfg.get("economy.start_balance", 0)

    def fmt(self, n: int) -> str:
        return f"{self.sym} {n:,}"

    @commands.Cog.listener()
    async def on_message(self, message):
        reward = self.cfg.get("economy.message_reward", 0)
        if reward and not message.author.bot and message.guild and self.bot.serves(message.guild) \
                and not (message.content or "").startswith(self.cfg.prefix):
            await self.store.adjust(str(message.guild.id), str(message.author.id), reward, "chat", start=self.start)

    @commands.command(aliases=["bal", "wallet"])
    async def balance(self, ctx, member: vector.Member = None):
        """Cash and bank."""
        member = member or ctx.author
        w = await self.store.wallet(str(ctx.guild.id), str(member.id), start=self.start)
        await ctx.send(embed=embed(f"{name_of(member)}'s wallet", fields=[
            ("Cash", self.fmt(w.balance), True), ("Bank", self.fmt(w.bank), True),
            ("Net worth", self.fmt(w.total), True)]))

    @commands.command()
    async def daily(self, ctx):
        """Claim your daily reward; consecutive days pay more."""
        e = self.cfg["economy"]
        paid, extra = await self.store.claim_daily(
            str(ctx.guild.id), str(ctx.author.id), amount=e["daily_amount"], bonus=e["daily_streak_bonus"],
            cap=e["daily_streak_cap"], start=self.start)
        if paid is None:
            return await ctx.send(f"⏳ Come back in {format_duration(extra)}.")
        await ctx.send(ok(f"You claimed {self.fmt(paid)}. Streak: **{extra}** day(s)."))

    @commands.command()
    async def work(self, ctx):
        """Earn some coins (has a cooldown)."""
        e = self.cfg["economy"]
        paid, wait = await self.store.claim_work(
            str(ctx.guild.id), str(ctx.author.id), low=e["work_min"], high=e["work_max"],
            cooldown=e["work_cooldown_minutes"] * 60, start=self.start)
        if paid is None:
            return await ctx.send(f"⏳ You're tired. Try again in {format_duration(wait)}.")
        job = random.choice(["fixed a relay", "reviewed a pull request", "debugged a mini app",
                             "moderated a busy channel", "delivered a pizza by sled"])
        await ctx.send(ok(f"You {job} and earned {self.fmt(paid)}."))

    @commands.command(aliases=["give"])
    async def pay(self, ctx, member: vector.Member, amount: int):
        """Send coins to someone."""
        if member.bot or str(member.id) == str(ctx.author.id) or amount <= 0:
            return await ctx.send(fail("Pick another member and a positive amount."))
        try:
            await self.store.transfer(str(ctx.guild.id), str(ctx.author.id), str(member.id), amount, start=self.start)
        except InsufficientFunds as exc:
            return await ctx.send(fail(f"You only have {self.fmt(exc.have)}."))
        await ctx.send(ok(f"Sent {self.fmt(amount)} to {name_of(member)}."))

    @commands.command(aliases=["dep"])
    async def deposit(self, ctx, amount: int):
        """Move cash into the bank."""
        try:
            await self.store.deposit(str(ctx.guild.id), str(ctx.author.id), amount)
        except (InsufficientFunds, ValueError):
            return await ctx.send(fail("Not enough cash for that."))
        await ctx.send(ok(f"Deposited {self.fmt(amount)}."))

    @commands.command()
    async def withdraw(self, ctx, amount: int):
        """Take cash out of the bank."""
        try:
            await self.store.withdraw(str(ctx.guild.id), str(ctx.author.id), amount)
        except (InsufficientFunds, ValueError):
            return await ctx.send(fail("Not enough in the bank for that."))
        await ctx.send(ok(f"Withdrew {self.fmt(amount)}."))

    @commands.command(aliases=["rich"])
    async def richest(self, ctx):
        """The wealthiest members."""
        rows = await self.store.leaderboard(str(ctx.guild.id))
        if not rows:
            return await ctx.send("Nobody has any coins yet. Try `daily`!")
        lines = []
        for i, w in enumerate(rows, 1):
            m = ctx.guild.get_member(w.user_id)
            lines.append(f"`{i:>2}.` {name_of(m) if m else w.user_id[:10]}: {self.fmt(w.total)}")
        await ctx.send(embed=embed("Richest members", "\n".join(lines)))

    @commands.command(aliases=["txs"])
    async def transactions(self, ctx):
        """Your last few transactions."""
        rows = await self.store.history(str(ctx.guild.id), str(ctx.author.id))
        await ctx.send(embed=embed("Your transactions", "\n".join(
            f"`{r['amount']:+}` {r['reason']}" for r in rows) or "Nothing yet."))

    @commands.command()
    @commands.has_permissions(administrator=True)
    async def addmoney(self, ctx, member: vector.Member, amount: int):
        """Admin: give (or take, negative) coins."""
        try:
            now = await self.store.adjust(str(ctx.guild.id), str(member.id), amount, f"admin {ctx.author.id}",
                                          start=self.start)
        except InsufficientFunds:
            return await ctx.send(fail("They don't have that much."))
        await ctx.send(ok(f"{name_of(member)} now has {self.fmt(now)} in cash."))

    # -- shop -------------------------------------------------------------------------

    @commands.group(invoke_without_command=True)
    async def shop(self, ctx):
        """See what is for sale. Buy with `buy <item>`."""
        items = await self.store.shop(str(ctx.guild.id))
        if not items:
            return await ctx.send("The shop is empty. Admins: `shop add <price> <name> | <description>`")
        await ctx.send(embed=embed("Shop", "\n".join(
            f"**{i.name}** · {self.fmt(i.price)}" + (f" · {i.stock} left" if i.stock is not None else "")
            + (f"\n  {i.description}" if i.description else "") for i in items)))

    @shop.command(name="add")
    @commands.has_permissions(administrator=True)
    async def shop_add(self, ctx, price: int, *, spec: str):
        """`shop add 500 VIP | Gold name colour` (add `role:<name>` to grant a role)."""
        name, _, desc = (p.strip() for p in spec.partition("|"))
        role_id = None
        if "role:" in desc:
            desc, _, role_name = desc.partition("role:")
            role_id = str((await self.bot.ensure_role(ctx.guild, role_name.strip())).id)
        if price <= 0 or not name:
            return await ctx.send(fail("Give a positive price and a name."))
        try:
            await self.store.add_item(str(ctx.guild.id), name, price, desc.strip(), role_id)
        except Exception:  # noqa: BLE001 - UNIQUE (guild, name)
            return await ctx.send(fail("An item with that name already exists."))
        await ctx.send(ok(f"Added **{name}** for {self.fmt(price)}."))

    @shop.command(name="remove")
    @commands.has_permissions(administrator=True)
    async def shop_remove(self, ctx, *, name: str):
        await ctx.send(ok("Removed.") if await self.store.remove_item(str(ctx.guild.id), name)
                       else fail("No such item."))

    @commands.command()
    async def buy(self, ctx, *, item: str):
        """Buy something from the shop."""
        try:
            bought = await self.store.buy(str(ctx.guild.id), str(ctx.author.id), item, start=self.start)
        except KeyError:
            return await ctx.send(fail("No such item."))
        except LookupError:
            return await ctx.send(fail("That is sold out."))
        except InsufficientFunds as exc:
            return await ctx.send(fail(f"You need {self.fmt(exc.needed)} but have {self.fmt(exc.have)}."))
        if bought.role_id:
            role = ctx.guild.get_role(bought.role_id)
            if role:
                await ctx.author.add_roles(role, reason="shop purchase")
        await ctx.send(ok(f"You bought **{bought.name}** for {self.fmt(bought.price)}."))

    @commands.command(aliases=["inv"])
    async def inventory(self, ctx):
        """What you own."""
        rows = await self.store.inventory(str(ctx.guild.id), str(ctx.author.id))
        await ctx.send(embed=embed("Inventory", "\n".join(f"{r['quantity']}× {r['name']}" for r in rows)
                                   or "Empty."))


async def setup(bot):
    await bot.add_cog(Economy(bot))
