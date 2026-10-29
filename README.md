# AI Hive

AI Hive exposes a remote Model Context Protocol (MCP) server for coordinating ChatGPT, Claude, and Gemini through one integration.

## Remote MCP endpoint

After deployment, the MCP endpoint is:

`https://ai-hive.onrender.com/mcp`

Connect an MCP-capable client to that URL using **Streamable HTTP**. The MCP tools are:

- `list_models` — report whether each AI session connector has checked in recently.
- `start_collaboration` — send one request to selected models and optionally run cross-review rounds.
- `get_collaboration` — retrieve status and responses using the returned task ID.
- `list_recent_collaborations` — list recent tasks.

## Critical connection limitation

MCP is the integration protocol, not a way to log into consumer AI subscriptions. These tools create and manage AI Hive jobs, but ChatGPT, Claude, and Gemini must still have an actual supported way to process those jobs. The current no-API-key prototype relies on the existing experimental browser connector running in a supported desktop Chromium browser with all selected AI tabs signed in. **This MCP endpoint alone does not make all three models work from an Android phone.** A phone-only, no-API-key setup cannot be promised using MCP alone. Official provider APIs require provider credentials and may incur charges.

## Current web interface

Open the deployed root URL for the mobile-friendly AI Hive web interface. The site can be added to your Android home screen from the browser menu, but the current session connector requirement still applies.

## Deploy

Render deploys from the repository using `render.yaml`. The start command runs `mcp_server:app`, which mounts the MCP endpoint at `/mcp` and keeps the existing web app and API routes available.

## Security and reliability

- This is an early prototype; do not send sensitive personal information.
- Task state is held in memory and is lost when the free service restarts.
- The public API currently has no user authentication. Do not treat it as private or production-safe.
- Website automation is experimental and can break when provider interfaces change.
- Review model output rather than assuming it is correct.

## API

- `GET /health`
- `GET /api/state`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks`
- `POST /api/register`
- `POST /api/message`
- `GET /api/jobs/{agent}`
- `POST /api/jobs/{job_id}/result`
- `WS /ws`
- `POST/GET via MCP Streamable HTTP: /mcp`

## License

MIT
