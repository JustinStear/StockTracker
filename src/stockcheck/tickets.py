from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus

import requests


@dataclass(slots=True)
class TicketResult:
    source: str
    event_name: str
    venue: str
    event_date: str
    city: str
    min_price: float | None
    max_price: float | None
    currency: str | None
    url: str
    availability: str


@dataclass(slots=True)
class TicketSearchResponse:
    results: list[TicketResult]
    errors: list[str]


class TicketSearchService:
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

    def search(
        self,
        query: str,
        zip_code: str,
        date_from: str | None,
        date_to: str | None,
        include_ticketmaster: bool,
        include_seatgeek: bool,
        include_stubhub: bool,
        include_vividseats: bool,
        include_tickpick: bool,
        include_livenation: bool = False,
        include_axs: bool = False,
        include_gametime: bool = False,
        limit: int = 20,
    ) -> TicketSearchResponse:
        cleaned_query = query.strip()
        if not cleaned_query:
            return TicketSearchResponse(results=[], errors=["query is required"])

        results: list[TicketResult] = []
        errors: list[str] = []

        if include_ticketmaster:
            api_key = os.getenv("TICKETMASTER_API_KEY")
            if api_key:
                try:
                    results.extend(
                        self._search_ticketmaster(
                            api_key=api_key,
                            query=cleaned_query,
                            zip_code=zip_code,
                            date_from=date_from,
                            date_to=date_to,
                            limit=limit,
                        )
                    )
                except requests.RequestException as exc:
                    errors.append(f"ticketmaster: {exc}")
            else:
                # No key: still provide a search-link style result.
                results.extend(self._search_public_provider("ticketmaster", cleaned_query, zip_code, date_from, date_to, limit_per_source=3, fallback_only=True))
                errors.append("ticketmaster: API key not set; using public search fallback")

        if include_seatgeek:
            client_id = os.getenv("SEATGEEK_CLIENT_ID")
            if client_id:
                try:
                    results.extend(
                        self._search_seatgeek(
                            client_id=client_id,
                            query=cleaned_query,
                            zip_code=zip_code,
                            date_from=date_from,
                            date_to=date_to,
                            limit=limit,
                        )
                    )
                except requests.RequestException as exc:
                    errors.append(f"seatgeek: {exc}")
            else:
                results.extend(self._search_public_provider("seatgeek", cleaned_query, zip_code, date_from, date_to, limit_per_source=3, fallback_only=True))
                errors.append("seatgeek: client id not set; using public search fallback")

        public_sources = [
            (include_stubhub, "stubhub"),
            (include_vividseats, "vividseats"),
            (include_tickpick, "tickpick"),
            (include_livenation, "livenation"),
            (include_axs, "axs"),
            (include_gametime, "gametime"),
        ]
        for enabled, source in public_sources:
            if not enabled:
                continue
            try:
                results.extend(
                    self._search_public_provider(
                        source=source,
                        query=cleaned_query,
                        zip_code=zip_code,
                        date_from=date_from,
                        date_to=date_to,
                        limit_per_source=max(2, min(8, limit // 3)),
                    )
                )
            except requests.RequestException as exc:
                errors.append(f"{source}: {exc}")
                results.append(self._search_link_result(source, cleaned_query, zip_code, date_from, date_to))

        deduped = self._dedupe_results(results)
        deduped.sort(key=lambda r: (r.min_price is None, r.min_price or float("inf"), r.event_date, r.source))
        return TicketSearchResponse(results=deduped[:limit], errors=errors)

    def _search_ticketmaster(
        self,
        api_key: str,
        query: str,
        zip_code: str,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> list[TicketResult]:
        params = {
            "apikey": api_key,
            "keyword": query,
            "postalCode": zip_code,
            "countryCode": "US",
            "size": min(limit, 50),
            "sort": "date,asc",
        }
        if date_from:
            params["startDateTime"] = f"{date_from}T00:00:00Z"
        if date_to:
            params["endDateTime"] = f"{date_to}T23:59:59Z"

        response = requests.get(
            "https://app.ticketmaster.com/discovery/v2/events.json",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        events = payload.get("_embedded", {}).get("events", [])
        out: list[TicketResult] = []
        for event in events:
            price_ranges = event.get("priceRanges") or []
            min_price = price_ranges[0].get("min") if price_ranges else None
            max_price = price_ranges[0].get("max") if price_ranges else None
            currency = price_ranges[0].get("currency") if price_ranges else None
            venue = ""
            city = ""
            venues = event.get("_embedded", {}).get("venues", [])
            if venues:
                venue = venues[0].get("name", "")
                city = venues[0].get("city", {}).get("name", "")

            out.append(
                TicketResult(
                    source="ticketmaster",
                    event_name=event.get("name", "Unknown event"),
                    venue=venue,
                    event_date=event.get("dates", {}).get("start", {}).get("localDate", ""),
                    city=city,
                    min_price=float(min_price) if min_price is not None else None,
                    max_price=float(max_price) if max_price is not None else None,
                    currency=currency,
                    url=event.get("url", "https://www.ticketmaster.com"),
                    availability="available" if event.get("dates", {}).get("status", {}).get("code") != "offsale" else "sold_out",
                )
            )
        return out

    def _search_seatgeek(
        self,
        client_id: str,
        query: str,
        zip_code: str,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> list[TicketResult]:
        params = {
            "client_id": client_id,
            "q": query,
            "postal_code": zip_code,
            "per_page": min(limit, 50),
            "sort": "datetime_utc.asc",
        }
        if date_from:
            params["datetime_utc.gte"] = f"{date_from}T00:00:00"
        if date_to:
            params["datetime_utc.lte"] = f"{date_to}T23:59:59"

        response = requests.get(
            "https://api.seatgeek.com/2/events",
            params=params,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()

        out: list[TicketResult] = []
        for event in payload.get("events", []):
            venue = event.get("venue", {}).get("name", "")
            city = event.get("venue", {}).get("city", "")
            out.append(
                TicketResult(
                    source="seatgeek",
                    event_name=event.get("title", "Unknown event"),
                    venue=venue,
                    event_date=(event.get("datetime_local") or "")[:10],
                    city=city,
                    min_price=float(event.get("lowest_price")) if event.get("lowest_price") is not None else None,
                    max_price=float(event.get("highest_price")) if event.get("highest_price") is not None else None,
                    currency="USD",
                    url=event.get("url", "https://seatgeek.com"),
                    availability="available" if event.get("stats", {}).get("listing_count", 0) > 0 else "unknown",
                )
            )
        return out

    def _search_public_provider(
        self,
        source: str,
        query: str,
        zip_code: str,
        date_from: str | None,
        date_to: str | None,
        limit_per_source: int,
        fallback_only: bool = False,
    ) -> list[TicketResult]:
        url = self._provider_search_url(source, query, zip_code, date_from, date_to)
        if fallback_only:
            return [self._search_link_result(source, query, zip_code, date_from, date_to)]

        html = self._get_html(url)
        extracted = self._extract_events_from_jsonld(html, source=source, default_city=zip_code)
        if extracted:
            return extracted[:limit_per_source]

        return [self._search_link_result(source, query, zip_code, date_from, date_to)]

    def _provider_search_url(
        self,
        source: str,
        query: str,
        zip_code: str,
        date_from: str | None,
        date_to: str | None,
    ) -> str:
        date_hint = ""
        if date_from or date_to:
            date_hint = f" {date_from or ''} {date_to or ''}".strip()
        q = quote_plus(f"{query} {zip_code} {date_hint}".strip())

        if source == "stubhub":
            return f"https://www.stubhub.com/find/s/?q={q}"
        if source == "vividseats":
            return f"https://www.vividseats.com/search?searchTerm={q}"
        if source == "tickpick":
            return f"https://www.tickpick.com/search?q={q}"
        if source == "livenation":
            return f"https://www.livenation.com/search/{q}"
        if source == "axs":
            return f"https://www.axs.com/search?q={q}"
        if source == "gametime":
            return f"https://gametime.co/search?q={q}"
        if source == "ticketmaster":
            return f"https://www.ticketmaster.com/search?q={q}"
        if source == "seatgeek":
            return f"https://seatgeek.com/search?search={q}"
        return f"https://www.google.com/search?q={q}+tickets"

    def _search_link_result(
        self,
        source: str,
        query: str,
        zip_code: str,
        date_from: str | None,
        date_to: str | None,
    ) -> TicketResult:
        label = {
            "stubhub": "StubHub search",
            "vividseats": "Vivid Seats search",
            "tickpick": "TickPick search",
            "livenation": "Live Nation search",
            "axs": "AXS search",
            "gametime": "Gametime search",
            "ticketmaster": "Ticketmaster search",
            "seatgeek": "SeatGeek search",
        }.get(source, f"{source} search")
        return TicketResult(
            source=source,
            event_name=label,
            venue="",
            event_date=date_from or "",
            city=zip_code,
            min_price=None,
            max_price=None,
            currency=None,
            url=self._provider_search_url(source, query, zip_code, date_from, date_to),
            availability="search_link",
        )

    def _get_html(self, url: str) -> str:
        response = requests.get(
            url,
            timeout=self.timeout_seconds,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        )
        response.raise_for_status()
        return response.text

    def _extract_events_from_jsonld(self, html: str, source: str, default_city: str) -> list[TicketResult]:
        scripts = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        out: list[TicketResult] = []
        for script_body in scripts:
            script_body = script_body.strip()
            if not script_body:
                continue
            try:
                payload = json.loads(script_body)
            except json.JSONDecodeError:
                continue

            for event in self._walk_events(payload):
                url = self._as_str(event.get("url"))
                if not url:
                    continue
                offers = event.get("offers")
                min_price, max_price, currency = self._parse_offers(offers)
                location = event.get("location") or {}
                venue = self._as_str(location.get("name"))
                city = self._as_str((location.get("address") or {}).get("addressLocality")) or default_city
                start_date = self._as_str(event.get("startDate"))[:10]
                name = self._as_str(event.get("name")) or f"{source} event"
                availability = "available" if offers else "unknown"
                out.append(
                    TicketResult(
                        source=source,
                        event_name=name,
                        venue=venue,
                        event_date=start_date,
                        city=city,
                        min_price=min_price,
                        max_price=max_price,
                        currency=currency,
                        url=url,
                        availability=availability,
                    )
                )

        return self._dedupe_results(out)

    def _walk_events(self, payload: Any) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        def rec(node: Any) -> None:
            if isinstance(node, list):
                for item in node:
                    rec(item)
                return
            if not isinstance(node, dict):
                return

            typ = node.get("@type")
            if typ == "Event" or (isinstance(typ, list) and "Event" in typ):
                events.append(node)

            for value in node.values():
                rec(value)

        rec(payload)
        return events

    def _parse_offers(self, offers: Any) -> tuple[float | None, float | None, str | None]:
        if isinstance(offers, list):
            numeric_prices = [self._as_float(o.get("price")) for o in offers if isinstance(o, dict)]
            numeric_prices = [p for p in numeric_prices if p is not None]
            if not numeric_prices:
                return None, None, None
            currency = None
            for o in offers:
                if isinstance(o, dict) and o.get("priceCurrency"):
                    currency = self._as_str(o.get("priceCurrency"))
                    break
            return min(numeric_prices), max(numeric_prices), currency

        if isinstance(offers, dict):
            low = self._as_float(offers.get("lowPrice"))
            high = self._as_float(offers.get("highPrice"))
            price = self._as_float(offers.get("price"))
            if low is None and price is not None:
                low = price
            if high is None and price is not None:
                high = price
            return low, high, self._as_str(offers.get("priceCurrency"))

        return None, None, None

    def _as_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _as_str(self, value: Any) -> str:
        return str(value).strip() if value is not None else ""

    def _dedupe_results(self, rows: list[TicketResult]) -> list[TicketResult]:
        seen: set[tuple[str, str]] = set()
        out: list[TicketResult] = []
        for row in rows:
            key = (row.source, row.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out
