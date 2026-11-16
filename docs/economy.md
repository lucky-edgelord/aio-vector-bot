---
title: Economy
group: Community
order: 3
summary: Coins, daily streaks, work, a bank and a shop that can sell roles.
---

Every member has a wallet. They earn coins from daily rewards, work and optionally from chatting, keep savings in a bank, pay each other, and spend coins in a shop that can sell roles.

## Earning

- `!daily` pays `daily_amount` coins and can be claimed every 24 hours. Claim again within 48 hours of the last time and your streak continues, and each streak day after the first adds `daily_streak_bonus`, up to `daily_streak_cap` days of bonus. Wait longer than 48 hours and the streak starts over.
- `!work` pays a random amount between `work_min` and `work_max`, then waits `work_cooldown_minutes`.
- Set `message_reward` above 0 to pay coins for chatting too.

New wallets start with `start_balance` coins.

```yaml
economy:
  currency_name: coins
  currency_symbol: "🪙"
  daily_amount: 200
  daily_streak_bonus: 25
  daily_streak_cap: 10
```

## Wallet and bank

`!balance` shows cash and bank. `!deposit 100` and `!withdraw 100` move coins between them, `!pay @sam 50` sends coins to someone, `!richest` lists the wealthiest members and `!transactions` shows your recent activity.

## The shop

Admins stock the shop from chat:

```
!shop add 500 VIP | Gold name colour
!shop add 1500 Supporter | Show your support role:Supporter
!shop remove VIP
```

The name comes first, then a description after the `|`. Add `role:<name>` to the description and buying the item gives that role, which Vectiq creates if it doesn't exist. Members use `!shop` to look, `!buy VIP` to buy and `!inventory` to see what they own. Every purchase is recorded in the transaction history.

`!addmoney @sam 1000` gives coins to a member, and a negative number takes them away. It needs Administrator.

## Games pay out here too

The [mini games](games.md) use the same wallet: winners are paid by the referee, and slots bets come out of real coins.

## Commands

{{commands:Economy}}

## Settings

{{config:economy}}
