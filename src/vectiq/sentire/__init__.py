"""Run Sentire (https://github.com/VectorPrivacy/Sentire), the Vector moderation bot, as a Vectiq module.

Sentire is a separate program written in Rust, with its own Vector identity. Vectiq builds or finds its binary,
writes its ``sentinel.toml`` from Vectiq's settings, starts and supervises it while the module is on, invites it
into communities and gives it a role, and shows its status and log in chat.
"""
