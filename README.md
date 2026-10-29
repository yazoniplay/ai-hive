# AI Hive

AI Hive coordinates multi-round collaboration between your existing logged-in ChatGPT, Claude, and Gemini tabs without model API keys.

## Current workflow
1. Submit a goal and choose participating models and 1–5 rounds.
2. Round 1 asks each model for an independent proposal.
3. The backend waits for each selected model's response.
4. Round 2 and later include the model's previous answer plus the other models' previous-round answers, asking for critique and improvement.
5. The final round's responses are saved on the task and displayed in the dashboard.

## Important limits
- Website automation is experimental. AI chat UIs change often and selectors may break.
- This uses browser sessions, not official APIs. You must keep a supported desktop Chromium browser running with the extension installed and the relevant AI tabs open.
- Android Chrome and many managed school Chromebooks do not allow unpacked extensions. You may need an unrestricted desktop computer for the connector.
- This is a coordination prototype, not a guarantee of correctness. Review the final responses.
- The free Render service can sleep/restart. The current backend stores tasks and history in memory, so a restart clears active work.
- Do not share passwords, cookies, or session tokens with this repository.

## Deploy
1. In Render, create a Blueprint using this repository and deploy `render.yaml`.
2. Copy the actual Render service URL.
3. Open the extension's options page and replace the default relay URL with the real service URL.
4. Load the `extension` folder as an unpacked extension in desktop Chromium.
5. Keep ChatGPT, Claude, and Gemini tabs open and signed in.
6. Open the dashboard, submit a small goal, and watch round and response events.

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

## License
MIT
