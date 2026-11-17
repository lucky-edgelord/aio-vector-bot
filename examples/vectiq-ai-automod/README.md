# vectiq-ai-automod

An example [Vectiq](https://github.com/lucky-edgelord/aio-vector-bot) module, installable with pip. An AI model reads each message against your community's rules and removes what breaks them. It **does automod's job instead of Sentire** (`provides="automod"`), so switching it on switches Sentire off, and back.

```sh
vectiq --install-module "git+https://github.com/lucky-edgelord/aio-vector-bot#subdirectory=examples/vectiq-ai-automod"
```

Then in chat: `!module scan`, `!module on ai_automod`. Settings appear on the dashboard and in the setup wizard, or in config.yaml:

```yaml
ai_automod:
  base_url: http://localhost:11434/v1   # Ollama on this computer; or https://api.openai.com/v1, OpenRouter...
  model: llama3.2
  api_key_env: ""                       # e.g. OPENAI_API_KEY, with the key in .env
  rules: "No harassment or hate. No spam or scams."
```

`!aicheck <text>` asks the model without removing anything. Read the code: it's about 120 lines, and a good starting point for your own module.
