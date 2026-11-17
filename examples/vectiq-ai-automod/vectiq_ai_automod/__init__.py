"""The module's manifest. Keep this file light: Vectiq reads it to list the module even while it's off."""

from vectiq.plugin import ACTIONS, Module, field

MODULE = Module(
    name="ai_automod",
    label="AI automod",
    help="An AI model reads each message against your rules and removes what breaks them",
    group="Safety",
    provides="automod",                     # takes the built-in automod's place: one runs at a time
    cogs=("vectiq_ai_automod.cog",),
    defaults={
        "base_url": "http://localhost:11434/v1",   # any OpenAI-compatible API; this is a local Ollama
        "model": "llama3.2",
        "api_key_env": "",                          # name of the .env variable holding the key (blank for Ollama)
        "rules": "No harassment or hate. No spam or scams. No sexual content. No sharing personal information.",
        "action": "delete",
        "timeout_minutes": 10,
        "min_chars": 12,                            # shorter messages aren't sent to the model
        "also_rules": True,                         # run the built-in automod rules first (cheap, instant)
        "max_per_minute": 30,                       # most model calls per minute; beyond that messages pass
        "exempt_roles": [],
        "exempt_channels": [],
    },
    settings=(
        field("ai_automod.base_url", "API address", "text", "An OpenAI-compatible /v1 address (OpenAI, OpenRouter, "
              "Ollama, LM Studio...)"),
        field("ai_automod.model", "Model", "text"),
        field("ai_automod.api_key_env", "API key variable", "text", "Name of the .env variable with the key"),
        field("ai_automod.rules", "Your rules", "longtext", "Plain words; the model judges messages against them"),
        field("ai_automod.action", "What to do", "enum", options=ACTIONS),
        field("ai_automod.also_rules", "Also use the built-in rules", "bool", "Floods, invites, files... first"),
        field("ai_automod.min_chars", "Shortest message to check", "int", minimum=1, maximum=2000),
        field("ai_automod.max_per_minute", "Most checks per minute", "int", minimum=1, maximum=10000),
    ),
    wizard="An AI will read messages against your rules. Point me at a model: a local one (Ollama) keeps "
           "messages on your computer.",
    version="0.1.0",
    author="Vectiq",
)
