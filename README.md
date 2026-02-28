# Pokemon Stock Checker

Local Pokemon TCG stock checker for Best Buy, Target, Walmart, and GameStop with alerting and a web frontend.

## Safety guardrails

- No checkout or purchase automation.
- No CAPTCHA solving, anti-bot bypass, proxy rotation, or fingerprint spoofing.
- Polling defaults to 180 seconds and enforces minimum 120 seconds with jitter.

## Features

- CLI modes: one-shot and daemon (`stockcheck once`, `stockcheck run`)
- Web UI (`stockcheck web`) to fill variables and trigger checks
- Keyword-based product discovery in web UI (select products instead of writing JSON)
- Transition-based alerts: only alerts on `OUT_OF_STOCK/UNKNOWN -> IN_STOCK`
- Persistent SQLite state cache
- ZIP geocoding via pluggable geocoder (default: Zippopotam)

## Capability matrix

- `bestbuy`: API-based (requires `BESTBUY_API_KEY`)
- `target`: Playwright page-based availability signal checks
- `walmart`: Playwright page-based availability signal checks
- `gamestop`: Playwright page-based availability signal checks

## Quick start

```bash
cd /home/justin/Git/pokemon-stock-checker
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
playwright install chromium
cp config.example.yaml config.yaml
```

Set `BESTBUY_API_KEY` in your environment if using Best Buy SKUs.

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
