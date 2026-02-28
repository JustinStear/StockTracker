from __future__ import annotations

import logging
from contextlib import AbstractContextManager
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from playwright.sync_api import BrowserContext, Page, sync_playwright

from stockcheck.adapters.base import RetailerAdapter
from stockcheck.models import StockStatus, Store, WatchItem

LOG = logging.getLogger(__name__)


class PlaywrightRetailerAdapter(RetailerAdapter, AbstractContextManager["PlaywrightRetailerAdapter"]):
    blocked_resource_types = {"image", "media", "font"}

    def __init__(
        self,
        headless: bool = True,
        zip_code: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
    ) -> None:
        self.headless = headless
        self.zip_code = zip_code
        self.lat = lat
        self.lon = lon
        self._playwright = None
        self._browser = None
        self._context: BrowserContext | None = None

    def __enter__(self) -> "PlaywrightRetailerAdapter":
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        context_kwargs: dict[str, object] = {}
        if self.lat is not None and self.lon is not None:
            context_kwargs["geolocation"] = {"latitude": self.lat, "longitude": self.lon}
            context_kwargs["permissions"] = ["geolocation"]
        if self.zip_code:
            context_kwargs["extra_http_headers"] = {
                "x-zip-code": self.zip_code,
                "x-postal-code": self.zip_code,
            }
        self._context = self._browser.new_context(**context_kwargs)
        if self.zip_code:
            self._context.add_init_script(
                script=(
                    "(() => {"
                    f"const z = {self.zip_code!r};"
                    "try {"
                    "localStorage.setItem('zipCode', z);"
                    "localStorage.setItem('zipcode', z);"
                    "localStorage.setItem('postalCode', z);"
                    "sessionStorage.setItem('zipCode', z);"
                    "} catch (_) {}"
                    "})();"
                )
            )
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
                store_id=f"local-context-{self.zip_code or 'unknown'}",
                name=f"{self.name} local area ({self.zip_code or 'zip-unknown'})",
                lat=lat,
                lon=lon,
                address=f"within {radius_miles:.1f} miles of ZIP {self.zip_code or 'unknown'}",
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

    def _append_query_params(self, url: str, params: dict[str, str]) -> str:
        parsed = urlparse(url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query.update(params)
        updated = parsed._replace(query=urlencode(query))
        return urlunparse(updated)
