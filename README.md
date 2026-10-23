# CHINNU Free Fire API — Render starter

This project adapts the uploaded Flask/Protobuf files for Render. It provides player info and a read-only current likes count. It does not automate sending likes.

## Render settings
- Runtime: Python
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --bind 0.0.0.0:$PORT`
- Environment variable: `API_KEY` = a long random private key
- Environment variable: `OWNER_NAME` = your branding, e.g. `CHINNU TEAM`

## Required token files
For player lookups, add your own authorized token files to the project as private files:
- `token_ind.json` for IND
- `token_bd.json` for BD
- `token_br.json` for BR/US/SAC/NA (not included because it was not uploaded)

Each file should be a JSON list whose objects contain `jwt_token` or `token`. Do not commit real tokens to a public repository. Prefer a private repository and rotate any credentials that were shared publicly. Tokens may expire; this starter does not generate or refresh them.

## Endpoints
- `GET /health`
- `GET /player-info?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY`
- `GET /like?uid=PLAYER_UID&server_name=IND&key=YOUR_API_KEY` — read-only current likes count

You can also send the key as the `X-API-Key` request header. API key must be configured in Render as `API_KEY`.
