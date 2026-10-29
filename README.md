# AI Hive MCP

A remote MCP server that sends one request to OpenAI, Anthropic, and Google Gemini through their official APIs and returns all responses in one tool result. Supports cross-review rounds.

## MCP connection

- **Endpoint:** `https://ai-hive.onrender.com/mcp`
- **Transport:** MCP Streamable HTTP
- **Health:** `https://ai-hive.onrender.com/health`

Connect an MCP-capable client to the endpoint above.

## Authenticate the providers

The server uses **provider API keys**, not passwords, cookies, or consumer subscription logins. Add the keys in the Render dashboard under your service's **Environment** settings. Never commit keys to GitHub or paste them into a chat.

Required environment secrets:
- `OPENAI_API_KEY` — OpenAI API key for the ChatGPT/OpenAI model.
- `ANTHROPIC_API_KEY` — Anthropic API key for Claude.
- `GEMINI_API_KEY` — Google AI Studio API key for Gemini.

Optional model settings:
- `OPENAI_MODEL` (default `gpt-4.1-mini`)
- `ANTHROPIC_MODEL` (default `claude-sonnet-4-5`)
- `GEMINI_MODEL` (default `gemini-2.5-flash`)

After adding or changing environment variables, redeploy/restart the service. Use the `list_models` MCP tool or `/health` endpoint to check whether each key is configured. That check only confirms a key exists; the first real request validates whether it works.

**Billing:** provider API usage is separate from ChatGPT, Claude, or Gemini consumer subscriptions. Each provider may require separate API account setup and billing. Do not assume the APIs are free.

## MCP tools

- `list_models` — show which provider credentials are configured and each model name. It never reveals key values.
- `start_collaboration` — query multiple models in parallel and optionally run 2–5 rounds of cross-review.
- `get_collaboration` — retrieve a collaboration by task ID while it remains in server memory.
- `list_recent_collaborations` — list recent tasks.

## Notes

- Each provider is called directly over HTTPS; no browser extension or open consumer-account browser session is required.
- Provider/model names and availability can change; model names can be overridden with environment variables.
- The Render free service may sleep/restart. Collaboration history is currently in memory and is lost after a restart.
- The endpoint is a prototype and does not yet have user-level authentication. Avoid sending sensitive personal information.

## License

MIT
