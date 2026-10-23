# CHINNU FF API — Anime dashboard + job monitoring

## Render web service
- Build: `pip install -r requirements.txt`
- Start: `gunicorn app:app --bind 0.0.0.0:$PORT`
- Environment variables: `API_KEY` (private), `DASHBOARD_PASSWORD` (private), `FLASK_SECRET_KEY` (long random secret), optional `OWNER_NAME=CHINNU TEAM`.

Open `/dashboard` and log in with `DASHBOARD_PASSWORD`. Dashboard includes today's API request count, reported successful/failed jobs, confirmed likes gained, unique limit-hit accounts, region breakdown, UID history, token-file status, and recent requests/jobs. Anime-inspired background and Dark/Light/Neon/Ocean themes are included.

## IDs list
Edit `ids.json` to list UIDs to track. Example:
```json
{
  "ids": [
    {"uid": "1234567890", "region": "IND", "nickname": "Optional nickname"},
    {"uid": "2345678901", "region": "BD", "nickname": "Optional nickname"}
  ]
}
```
The example UID is a placeholder; replace it. IDs in this file appear as `waiting` until job results are recorded.

## Token files
`token_ind.json`, `token_bd.json`, and `token_br.json` are empty templates. Add only your own authorized tokens privately. Expected format is a JSON list with objects containing `jwt_token` or `token`. **Never commit real tokens to a public GitHub repo.** Do not share token values or put them in screenshots. The dashboard only reports whether a token file has entries; it never displays tokens. A valid token is required for player lookups. Region support depends on the upstream service and valid authorized tokens.

## Recording actual job outcomes
This project does **not** send or automate likes. The current `/like` endpoint is read-only and reports the player's current likes count. To populate job-specific metrics, an existing authorized upstream integration must POST each real result to `/monitor/event` using header `X-API-Key: YOUR_API_KEY` and JSON like:
```json
{
  "job_id": "job-001",
  "uid": "1234567890",
  "nickname": "Example",
  "region": "IND",
  "status": "success",
  "likes_before": 100,
  "likes_after": 105,
  "likes_given": 5,
  "message": "Confirmed by upstream service"
}
```
Allowed statuses: `success`, `fail`, `limit_reached`. Likes gained are only counted for success events and are capped at the observed `likes_after - likes_before` delta. Never send fake results; dashboard values reflect reported events. Requests to `/monitor/event` require the API key and must be made over HTTPS.

## Persistence note
SQLite database `monitor.db` is local to the service. Depending on Render disk configuration, data may be lost on restart/redeploy. Use a persistent disk or managed database if long-term history is required.
