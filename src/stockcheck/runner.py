from __future__ import annotations

import json
import logging
import random
import time
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from stockcheck.adapters import BestBuyAdapter, GameStopAdapter, TargetAdapter, WalmartAdapter
from stockcheck.alerts import AlertSink, DiscordWebhookAlertSink, DryRunAlertSink
from stockcheck.config import load_config
from stockcheck.geo import ZipGeocoder
from stockcheck.models import AppConfig, StockStatus, Store, WatchItem
from stockcheck.state import StateStore

LOG = logging.getLogger(__name__)

AdapterFactory = Callable[[], object]


@dataclass(slots=True)
class CheckRecord:
    retailer: str
    label: str
    item_key: str
    store_id: str
    store_name: str
    status: StockStatus


class StockCheckerService:
    def __init__(self, config: AppConfig, dry_run: bool = False, headless: bool = True) -> None:
        self.config = config
        self.dry_run = dry_run
        self.headless = headless
        self.state = StateStore(config.state_db)
        self.alert_sink = self._build_alert_sink()

    def _build_alert_sink(self) -> AlertSink:
        if self.dry_run:
            return DryRunAlertSink()
        webhook = self.config.alerts.discord_webhook
        if webhook:
            return DiscordWebhookAlertSink(str(webhook))
        return DryRunAlertSink()

    def _resolve_lat_lon(self) -> tuple[float, float]:
        lat, lon = self.config.resolved_lat_lon()
        if lat is not None and lon is not None:
            return lat, lon

        if self.config.location.zip:
            return ZipGeocoder().geocode_zip(self.config.location.zip)

        raise ValueError("location must include zip or lat/lon")

    def _adapter_factories(self) -> dict[str, AdapterFactory]:
        return {
            "bestbuy": lambda: BestBuyAdapter(),
            "target": lambda: TargetAdapter(headless=self.headless),
            "walmart": lambda: WalmartAdapter(headless=self.headless),
            "gamestop": lambda: GameStopAdapter(headless=self.headless),
        }

    def run_once(self) -> list[CheckRecord]:
        lat, lon = self._resolve_lat_lon()
        records: list[CheckRecord] = []
        factories = self._adapter_factories()

        by_retailer: dict[str, list[WatchItem]] = {}
        for item in self.config.watchlist:
            by_retailer.setdefault(item.retailer, []).append(item)

        with ExitStack() as stack:
            adapters: dict[str, object] = {}
            for retailer in by_retailer:
                adapter = factories[retailer]()
                if hasattr(adapter, "__enter__") and hasattr(adapter, "__exit__"):
                    adapter = stack.enter_context(adapter)
                adapters[retailer] = adapter

            for retailer, items in by_retailer.items():
                adapter = adapters[retailer]
                stores = adapter.find_stores_near(lat, lon, self.config.radius_miles)
                for item in items:
                    self._process_item(item, stores, adapter, records)

        self._write_status(records)
        return records

    def _process_item(
        self,
        item: WatchItem,
        stores: list[Store],
        adapter,
        records: list[CheckRecord],
    ) -> None:
        for store in stores:
            try:
                status = adapter.check_item_in_store(item, store)
            except Exception as exc:  # noqa: BLE001
                LOG.exception(
                    "check failed retailer=%s label=%s store=%s error=%s",
                    item.retailer,
                    item.label,
                    store.store_id,
                    exc,
                )
                status = StockStatus.UNKNOWN

            transition = self.state.update_status(
                retailer=item.retailer,
                item_key=item.item_key,
                store_id=store.store_id,
                status=status,
            )
            LOG.info(
                "retailer=%s item=%s store=%s status=%s changed=%s",
                item.retailer,
                item.label,
                store.store_id,
                status.value,
                transition.changed,
            )
            if transition.should_alert:
                message = (
                    f"Pokemon stock alert: {item.label} is IN STOCK at {store.name} "
                    f"({item.retailer}, store={store.store_id})"
                )
                try:
                    self.alert_sink.send(message)
                except Exception as exc:  # noqa: BLE001
                    LOG.exception("alert delivery failed: %s", exc)

            records.append(
                CheckRecord(
                    retailer=item.retailer,
                    label=item.label,
                    item_key=item.item_key,
                    store_id=store.store_id,
                    store_name=store.name,
                    status=status,
                )
            )

    def run_forever(self) -> None:
        schedule: dict[tuple[str, str], float] = {}
        base = self.config.poll_seconds

        while True:
            now = time.time()
            triggered = False
            for item in self.config.watchlist:
                key = (item.retailer, item.item_key)
                due = schedule.get(key, 0)
                if now < due:
                    continue

                self.run_once_for_item(item)
                jitter_factor = random.uniform(0.8, 1.2)
                schedule[key] = now + (base * jitter_factor)
                triggered = True
            if not triggered:
                time.sleep(2)

    def run_once_for_item(self, item: WatchItem) -> list[CheckRecord]:
        partial_config = self.config.model_copy(update={"watchlist": [item]})
        return StockCheckerService(
            config=partial_config,
            dry_run=self.dry_run,
            headless=self.headless,
        ).run_once()

    def _write_status(self, records: list[CheckRecord]) -> None:
        payload = [
            {
                "retailer": r.retailer,
                "label": r.label,
                "item_key": r.item_key,
                "store_id": r.store_id,
                "store_name": r.store_name,
                "status": r.status.value,
            }
            for r in records
        ]
        path = Path(self.config.status_json)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def build_service(config_path: str, dry_run: bool = False, headless: bool = True) -> StockCheckerService:
    config = load_config(config_path)
    return StockCheckerService(config=config, dry_run=dry_run, headless=headless)
