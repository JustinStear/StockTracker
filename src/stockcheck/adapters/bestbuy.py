from __future__ import annotations

import logging
import os
from typing import Any

import requests

from stockcheck.adapters.base import RetailerAdapter
from stockcheck.models import StockStatus, Store, WatchItem

LOG = logging.getLogger(__name__)


class BestBuyAdapter(RetailerAdapter):
    name = "bestbuy"
    base_url = "https://api.bestbuy.com/v1"

    def __init__(self, api_key: str | None = None, timeout_seconds: float = 12.0) -> None:
        self.api_key = api_key or os.getenv("BESTBUY_API_KEY")
        self.timeout_seconds = timeout_seconds
        if not self.api_key:
            raise ValueError("BESTBUY_API_KEY is required for Best Buy adapter")

    def find_stores_near(self, lat: float, lon: float, radius_miles: float) -> list[Store]:
        endpoint = f"{self.base_url}/stores(area({lat},{lon},{radius_miles}))"
        params = {
            "apiKey": self.api_key,
            "format": "json",
            "show": "storeId,name,lat,lng,address,city,region,postalCode",
            "pageSize": 100,
        }
        response = requests.get(endpoint, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        payload = response.json()
        stores = []
        for entry in payload.get("stores", []):
            store_id = str(entry.get("storeId"))
            if not store_id:
                continue
            address = ", ".join(
                x
                for x in [
                    entry.get("address"),
                    entry.get("city"),
                    entry.get("region"),
                    entry.get("postalCode"),
                ]
                if x
            )
            stores.append(
                Store(
                    retailer=self.name,
                    store_id=store_id,
                    name=entry.get("name", f"Best Buy {store_id}"),
                    lat=float(entry.get("lat", 0.0)),
                    lon=float(entry.get("lng", 0.0)),
                    address=address,
                )
            )
        return stores

    def check_item_in_store(self, watch_item: WatchItem, store: Store) -> StockStatus:
        if watch_item.identifier.type != "sku":
            raise ValueError("bestbuy adapter requires sku identifier")

        sku = watch_item.identifier.value
        payload = self._fetch_product_store_payload(sku, store.store_id)
        normalized = self._flatten_text(payload).lower()

        negative = ["sold out", "unavailable", "out of stock", "not available"]
        positive = ["available", "in stock", "pickup", "ready"]

        if any(term in normalized for term in negative):
            return StockStatus.OUT_OF_STOCK
        if any(term in normalized for term in positive):
            return StockStatus.IN_STOCK
        return StockStatus.UNKNOWN

    def _fetch_product_store_payload(self, sku: str, store_id: str) -> dict[str, Any]:
        endpoint = f"{self.base_url}/products(sku={sku})+stores(storeId={store_id})"
        params = {
            "apiKey": self.api_key,
            "format": "json",
            "show": "sku,name,inStoreAvailability,onlineAvailability,storePickup,storePickupSla",
            "pageSize": 1,
        }
        response = requests.get(endpoint, params=params, timeout=self.timeout_seconds)
        response.raise_for_status()
        return response.json()

    def _flatten_text(self, payload: Any) -> str:
        if payload is None:
            return ""
        if isinstance(payload, (str, int, float, bool)):
            return str(payload)
        if isinstance(payload, list):
            return " ".join(self._flatten_text(item) for item in payload)
        if isinstance(payload, dict):
            return " ".join(self._flatten_text(v) for v in payload.values())
        return ""
