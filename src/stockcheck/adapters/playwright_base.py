from __future__ import annotations

import logging
from contextlib import AbstractContextManager

from playwright.sync_api import BrowserContext, Page, sync_playwright

from stockcheck.adapters.base import RetailerAdapter
from stockcheck.models import StockStatus, Store, WatchItem

LOG = logging.getLogger(__name__)


class PlaywrightRetailerAdapter(RetailerAdapter, AbstractContextManager["PlaywrightRetailerAdapter"]):
    blocked_resource_types = {"image", "media", "font"}

    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> "PlaywrightRetailerAdapter":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._context.route("**/*", self._route_filter)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()

    def _route_filter(self, route) -> None:  # type: ignore[no-untyped-def]
        if route.request.resource_type in self.blocked_resource_types:
            route.abort()
            return
        route.continue_()

    def _new_page(self) -> Page:
        if not self._context:
            raise RuntimeError("adapter context is not initialized")
        return self._context.new_page()

    def find_stores_near(self, lat: float, lon: float, radius_miles: float) -> list[Store]:
        # Page-based adapters do item checks by location context and usually do not expose
        # store search APIs. Return an abstract local context store.
        return [
            Store(
                retailer=self.name,
                store_id="local-context",
                name=f"{self.name} local area",
                lat=lat,
                lon=lon,
                address=f"within {radius_miles:.1f} miles",
            )
        ]

    def check_item_in_store(self, watch_item: WatchItem, store: Store) -> StockStatus:
        page = self._new_page()
        try:
            return self._check_item_with_page(page, watch_item)
        finally:
            page.close()

    def _check_item_with_page(self, page: Page, watch_item: WatchItem) -> StockStatus:
        raise NotImplementedError
