# CHINNU FF API + Monitor + Telegram client

## Render API Web Service
- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
- Environment variables:
  - `API_KEY`: long random private API key used by clients
  - `OWNER_NAME`: `CHINNU TEAM` (optional)
  - `DASHBOARD_PASSWORD`: a separate strong password for `/dashboard`
  - `FLASK_SECRET_KEY`: a long random secret for dashboard sessions
- Add your own authorized region token JSON files privately to the service/repository. Do not put token files in a public repository. Rotate tokens that were accidentally exposed.

## Monitoring
Open `https://YOUR-RENDER-SERVICE.onrender.com/dashboard` and log in with `DASHBOARD_PASSWORD`.
The dashboard records timestamp, HTTP method, endpoint path, status code and response time. It deliberately does not record query strings, API keys, request bodies, or Authorization headers.

SQLite monitoring data is local to the instance and can be lost on redeploy/restart depending on Render service/storage setup. For durable logs, configure a persistent disk or external database.

## Telegram bot client
`tg_bot_example.py` is a separate optional Telegram bot client. Run it as a separate Render Background Worker or another always-on Python service (not as the web service's Start Command). Set these environment variables on that separate service:
- `BOT_TOKEN`: Telegram bot token
- `API_BASE_URL`: full URL of the deployed API, e.g. `https://your-service.onrender.com`
- `API_KEY`: same private API key configured on API service
- `ALLOWED_TELEGRAM_IDS`: optional comma-separated Telegram numeric user IDs allowed to use it

For the worker, build command: `pip install -r requirements.txt`; start command: `python tg_bot_example.py`.

Commands: `/start`, `/player UID [REGION]`.

## Endpoints
- `GET /health` - health check
- `GET /player-info?uid=...&server_name=IND` - player info; API key can be sent as `X-API-Key` header
- `GET /like?uid=...&server_name=IND` - current likes count only; does not send likes
- `GET /dashboard` - password-protected monitoring dashboard

This project does not automate or send likes. Region availability depends on valid authorized tokens and the upstream service.
