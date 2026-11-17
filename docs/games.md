---
title: Mini games
group: Events and play
order: 2
summary: Tic-Tac-Toe, Connect Four, trivia and slots as WebXDC apps that the bot referees.
---

```
!game tictactoe
!game connect4
!game trivia
!game slots
```

`!game` posts a small web app into the chat. Members open it inside Vector, and the bot joins the app's realtime channel as the **referee**. The bot owns the board, the clock, the random numbers and the coins, so a modified app can't cheat.

## The games

- **Tic-Tac-Toe** and **Connect Four:** two seats, other people can watch, and either player can ask for a rematch.
- **Trivia:** a lobby, then eight timed questions. Faster correct answers score more, and every point pays coins.
- **Slots:** you bet from your real wallet. Wins and losses come out of and go into your [economy](economy.md) balance, up to `slots_max_bet`.

Winners are paid `winner_coins`, draws pay `draw_coins`, and every result is recorded. `!gamestats` shows your record in each game and `!gameboard trivia` shows the top players of one game.

## How cheating is prevented

The referee only acts on frames that arrive directly from a player's own device, which Vector marks as **verified**. A frame that was relayed through someone else is ignored, and the app asks the player to retry. Keep `games.allow_unverified` off. It exists for testing only, and it makes the bot trust senders it can't verify.

## Timing

```yaml
games:
  join_when: opened        # opened: the referee joins when a player opens the app | shared: as soon as it is posted
  idle_timeout_seconds: 300
```

With `opened`, the bot joins only when someone opens a game, which saves resources when many games sit in a channel. A game that nobody touches for `idle_timeout_seconds` is closed.

## Commands

{{commands:Games}}

## Settings

{{config:games}}

## Adding a game

A game is a rules class plus a small front end. See [Development](development.md#adding-a-game).
