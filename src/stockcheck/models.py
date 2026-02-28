from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl


class StockStatus(str, Enum):
    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class Store(BaseModel):
    model_config = ConfigDict(extra="ignore")

    retailer: str
    store_id: str
    name: str
    lat: float
    lon: float
    address: str


class Identifier(BaseModel):
    type: Literal["sku", "url"]
    value: str


class WatchItem(BaseModel):
    retailer: Literal["target", "walmart", "gamestop"]
    label: str
    identifier: Identifier

    @property
    def item_key(self) -> str:
        return f"{self.identifier.type}:{self.identifier.value}"


class LocationConfig(BaseModel):
    zip: str | None = None
    lat: float | None = None
    lon: float | None = None


class AlertsConfig(BaseModel):
    discord_webhook: HttpUrl | None = None


class AppConfig(BaseModel):
    location: LocationConfig
    radius_miles: float = Field(default=20.0, gt=0)
    poll_seconds: int = Field(default=180, ge=120)
    state_db: str = "state.sqlite3"
    status_json: str = "status.json"
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)
    watchlist: list[WatchItem]

    def resolved_lat_lon(self) -> tuple[float | None, float | None]:
        return self.location.lat, self.location.lon
