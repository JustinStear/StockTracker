from __future__ import annotations

from abc import ABC, abstractmethod

from stockcheck.models import StockStatus, Store, WatchItem


class RetailerAdapter(ABC):
    name: str

    @abstractmethod
    def find_stores_near(self, lat: float, lon: float, radius_miles: float) -> list[Store]:
        raise NotImplementedError

    @abstractmethod
    def check_item_in_store(self, watch_item: WatchItem, store: Store) -> StockStatus:
        raise NotImplementedError
