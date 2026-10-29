# AI Hive

A prototype for relaying goals and activity between your existing logged-in ChatGPT, Claude, and Gemini browser tabs without model API keys.

## Included
- FastAPI relay and task queue
- Live dashboard with WebSocket activity
- Chromium Manifest V3 connector that attempts to submit goals into AI chat tabs
- Render Blueprint for free hosting

## Important limitations
- This is experimental. Chat websites frequently change their UI, so automation may break.
- The connector submits the initial goal to each selected AI and relays its response. Automatic multi-round critique, response sharing between models, and autonomous iteration are not implemented yet.
- The connector requires desktop Chromium with unpacked extensions allowed. Android Chrome and many managed school Chromebooks do not support loading it.
- Free services may sleep/restart. Tasks and events are currently held in memory and reset when the service restarts.
- Use your own logged-in sessions and review what is sent. Never paste passwords, cookies, or session tokens into this project.

## Deploy
1. In Render, create a new Blueprint from this repository and deploy the service defined in render.yaml.
2. Copy the actual Render URL from the dashboard.
3. Open the extension options page and set that URL.
4. Open the dashboard URL to view activity.

## Load the connector (desktop Chromium)
1. Download this repository to a computer.
2. Open chrome://extensions and enable Developer mode.
3. Select Load unpacked and choose the extension folder.
4. Configure the actual Render URL in the extension options.
5. Open ChatGPT, Claude, and/or Gemini tabs and sign in normally.
6. Submit a small test goal from the AI Hive dashboard.

If your current device blocks extensions, the dashboard can still run, but website automation cannot run on that device.

## API
- GET /health
- GET /api/state
- POST /api/tasks
- POST /api/register
- POST /api/message
- GET /api/next/{agent}
- WS /ws

## License
MIT
