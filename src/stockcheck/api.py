from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse

from stockcheck.models import AppConfig
from stockcheck.runner import StockCheckerService
from stockcheck.state import StateStore

LOG = logging.getLogger(__name__)

app = FastAPI(title="Pokemon Stock Checker")

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / "config.yaml"


def _load_form_html() -> str:
    return (Path(__file__).parent / "templates" / "index.html").read_text(encoding="utf-8")


def _build_config_from_form(
    zip_code: str,
    lat: str,
    lon: str,
    radius_miles: float,
    poll_seconds: int,
    discord_webhook: str,
    watchlist_json: str,
) -> AppConfig:
    try:
        watchlist = json.loads(watchlist_json)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid watchlist JSON: {exc}") from exc

    location: dict[str, object] = {}
    if zip_code.strip():
        location["zip"] = zip_code.strip()
    else:
        try:
            location["lat"] = float(lat)
            location["lon"] = float(lon)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Provide ZIP or numeric lat/lon") from exc

    payload = {
        "location": location,
        "radius_miles": radius_miles,
        "poll_seconds": poll_seconds,
        "alerts": {"discord_webhook": discord_webhook.strip() or None},
        "watchlist": watchlist,
    }
    return AppConfig.model_validate(payload)


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return _load_form_html()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/status")
def status(config_path: str = str(CONFIG_PATH)) -> JSONResponse:
    if not Path(config_path).exists():
        return JSONResponse({"status": []})

    db_path = "state.sqlite3"
    if Path(config_path).exists():
        import yaml

        parsed = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        db_path = parsed.get("state_db", db_path)

    store = StateStore(db_path)
    return JSONResponse({"status": store.dump_status()})


@app.post("/save-config")
def save_config(
    zip_code: str = Form(default=""),
    lat: str = Form(default=""),
    lon: str = Form(default=""),
    radius_miles: float = Form(default=20.0),
    poll_seconds: int = Form(default=180),
    discord_webhook: str = Form(default=""),
    watchlist_json: str = Form(default="[]"),
) -> dict[str, str]:
    config = _build_config_from_form(
        zip_code=zip_code,
        lat=lat,
        lon=lon,
        radius_miles=radius_miles,
        poll_seconds=poll_seconds,
        discord_webhook=discord_webhook,
        watchlist_json=watchlist_json,
    )

    import yaml

    CONFIG_PATH.write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )
    return {"saved": str(CONFIG_PATH)}


@app.post("/check-now")
def check_now(dry_run: bool = Form(default=True)) -> JSONResponse:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=400, detail="Save config first")

    import yaml

    raw = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8"))
    config = AppConfig.model_validate(raw)
    service = StockCheckerService(config=config, dry_run=dry_run, headless=True)
    records = service.run_once()

    return JSONResponse(
        {
            "checks": [
                {
                    "retailer": r.retailer,
                    "label": r.label,
                    "store_id": r.store_id,
                    "status": r.status.value,
                }
                for r in records
            ]
        }
    )
