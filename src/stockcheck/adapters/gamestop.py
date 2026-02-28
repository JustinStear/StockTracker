from __future__ import annotations

import logging

from playwright.sync_api import Page

from stockcheck.adapters.playwright_base import PlaywrightRetailerAdapter
from stockcheck.models import StockStatus, WatchItem

LOG = logging.getLogger(__name__)


class GameStopAdapter(PlaywrightRetailerAdapter):
    name = "gamestop"

    positive_signals = ["pick up", "available", "in stock"]
    negative_signals = ["out of stock", "not available", "unavailable"]

    def _check_item_with_page(self, page: Page, watch_item: WatchItem) -> StockStatus:
        if watch_item.identifier.type != "url":
            raise ValueError("gamestop adapter requires url identifier")

        url = watch_item.identifier.value
        if self.zip_code:
            url = self._append_query_params(url, {"zip": self.zip_code, "zipcode": self.zip_code})
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        content = page.inner_text("body").lower()

        if any(term in content for term in self.negative_signals):
            return StockStatus.OUT_OF_STOCK
        if any(term in content for term in self.positive_signals):
            return StockStatus.IN_STOCK

        LOG.warning("gamestop status unknown for %s", watch_item.label)
        return StockStatus.UNKNOWN
