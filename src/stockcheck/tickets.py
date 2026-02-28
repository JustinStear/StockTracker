from __future__ import annotations

import os
from dataclasses import dataclass
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
        limit: int = 20,
    ) -> TicketSearchResponse:
        cleaned_query = query.strip()
        if not cleaned_query:
            return TicketSearchResponse(results=[], errors=["query is required"])

        results: list[TicketResult] = []
        errors: list[str] = []

        if include_ticketmaster:
            api_key = os.getenv("TICKETMASTER_API_KEY")
            if not api_key:
                errors.append("ticketmaster: set TICKETMASTER_API_KEY for live event/price data")
            else:
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

        if include_seatgeek:
            client_id = os.getenv("SEATGEEK_CLIENT_ID")
            if not client_id:
                errors.append("seatgeek: set SEATGEEK_CLIENT_ID for live event/price data")
            else:
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

        if include_stubhub:
            results.append(self._search_link_result("stubhub", cleaned_query, zip_code, date_from, date_to))
        if include_vividseats:
            results.append(self._search_link_result("vividseats", cleaned_query, zip_code, date_from, date_to))
        if include_tickpick:
            results.append(self._search_link_result("tickpick", cleaned_query, zip_code, date_from, date_to))

        # Known prices first, then sort ascending.
        results.sort(key=lambda r: (r.min_price is None, r.min_price or float("inf"), r.event_date))
        return TicketSearchResponse(results=results[:limit], errors=errors)

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

    def _search_link_result(
        self,
        source: str,
        query: str,
        zip_code: str,
        date_from: str | None,
        date_to: str | None,
    ) -> TicketResult:
        date_suffix = ""
        if date_from or date_to:
            date_suffix = f" {date_from or ''} {date_to or ''}".strip()

        if source == "stubhub":
            url = f"https://www.stubhub.com/find/s/?q={quote_plus(query + ' ' + zip_code + ' ' + date_suffix)}"
            label = "StubHub search"
        elif source == "vividseats":
            url = f"https://www.vividseats.com/search?searchTerm={quote_plus(query + ' ' + zip_code + ' ' + date_suffix)}"
            label = "Vivid Seats search"
        else:
            url = f"https://www.tickpick.com/search?q={quote_plus(query + ' ' + zip_code + ' ' + date_suffix)}"
            label = "TickPick search"

        return TicketResult(
            source=source,
            event_name=label,
            venue="",
            event_date=date_from or "",
            city=zip_code,
            min_price=None,
            max_price=None,
            currency=None,
            url=url,
            availability="search_link",
        )
