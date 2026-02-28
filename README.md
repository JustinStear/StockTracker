# Pokemon Stock Checker + Ticket Search

Local Pokemon TCG stock checker plus a concert ticket metasearch page.

## Safety guardrails

- No checkout or purchase automation.
- No CAPTCHA solving, anti-bot bypass, proxy rotation, or fingerprint spoofing.
- Polling defaults to 180 seconds and enforces minimum 120 seconds with jitter.

## Features

- CLI modes: one-shot and daemon (`stockcheck once`, `stockcheck run`)
- Web UI (`stockcheck web`) with:
  - `/pokemon` for product stock checks
  - `/tickets` for concert ticket metasearch (artist/event, Ticketmaster event ID, section and price filters)
- Keyword-based product discovery in web UI (select products instead of writing JSON)
- Transition-based alerts: only alerts on `OUT_OF_STOCK/UNKNOWN -> IN_STOCK`
- Persistent SQLite state cache
- ZIP geocoding via pluggable geocoder (default: Zippopotam)

## Capability matrix

- `target`: Playwright page-based availability signal checks
- `walmart`: Playwright page-based availability signal checks
- `gamestop`: Playwright page-based availability signal checks
- `ticketmaster`: API-based ticket/event data (`TICKETMASTER_API_KEY`)
- `seatgeek`: API-based ticket/event data (`SEATGEEK_CLIENT_ID`)
- `stubhub` / `vividseats` / `tickpick`: search-link providers (no checkout automation)

## Quick start

```bash
cd /home/justin/Git/pokemon-stock-checker
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
playwright install chromium
cp config.example.yaml config.yaml
```

Set provider keys in environment for richer ticket results:

- `TICKETMASTER_API_KEY`
- `SEATGEEK_CLIENT_ID`

## CLI usage

```bash
# one check pass
stockcheck once --config config.yaml --dry-run

# continuous loop with per-item jittered schedule
stockcheck run --config config.yaml

# launch web frontend
stockcheck web --host 0.0.0.0 --port 8000
```

## Web frontend

1. Start server: `stockcheck web`
2. Open `http://localhost:8000`
3. Fill ZIP, radius, poll interval, and webhook.
4. Use product keyword search, select items, then click `Save Config`.
5. Click `Check Now (Dry Run)` to run and view live results on the page.

## Docker

```bash
cd /home/justin/Git/pokemon-stock-checker
cp config.example.yaml config.yaml
docker compose up --build
```

## Config format

See `config.example.yaml` for complete schema.

## Testing

```bash
pytest
```
