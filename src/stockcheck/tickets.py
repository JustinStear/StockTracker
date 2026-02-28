from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, unquote, urlparse

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
        radius_miles: int | None,
        date_from: str | None,
        date_to: str | None,
        event_id: str | None,
        venue_query: str | None,
        section_query: str | None,
        max_price: float | None,
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
        cleaned_event_id = (event_id or "").strip()
        if not cleaned_query and not cleaned_event_id:
            return TicketSearchResponse(results=[], errors=["query is required"])

        results: list[TicketResult] = []
        errors: list[str] = []
        venue_term = (venue_query or "").strip().lower()
        section_term = (section_query or "").strip().lower()
        effective_query = " ".join(x for x in [cleaned_query, venue_term, section_term] if x).strip()
        event_id_only_mode = bool(cleaned_event_id and not cleaned_query)

        if include_ticketmaster:
            if cleaned_event_id:
                results.append(
                    TicketResult(
                        source="ticketmaster",
                        event_name=f"Ticketmaster event {cleaned_event_id}",
                        venue="",
                        event_date=date_from or "",
                        city=zip_code,
                        min_price=None,
                        max_price=None,
                        currency=None,
                        url=f"https://www.ticketmaster.com/event/{cleaned_event_id}",
                        availability="search_link",
                    )
                )
            else:
                results.extend(
                    self._search_public_provider(
                        "ticketmaster",
                        effective_query or cleaned_query,
                        zip_code,
                        radius_miles,
                        date_from,
                        date_to,
                        limit_per_source=max(2, min(8, limit // 3)),
                    )
                )

        if include_seatgeek and not event_id_only_mode:
            results.extend(
                self._search_public_provider(
                    "seatgeek",
                    effective_query or cleaned_query,
                    zip_code,
                    radius_miles,
                    date_from,
                    date_to,
                    limit_per_source=max(2, min(8, limit // 3)),
                )
            )

        public_sources = [
            (include_stubhub, "stubhub"),
            (include_vividseats, "vividseats"),
            (include_tickpick, "tickpick"),
            (include_livenation, "livenation"),
            (include_axs, "axs"),
            (include_gametime, "gametime"),
        ]
        for enabled, source in public_sources:
            if event_id_only_mode:
                continue
            if not enabled:
                continue
            results.extend(
                self._search_public_provider(
                    source=source,
                    query=effective_query or cleaned_query,
                    zip_code=zip_code,
                    radius_miles=radius_miles,
                    date_from=date_from,
                    date_to=date_to,
                    limit_per_source=max(2, min(8, limit // 3)),
                )
            )

        deduped = self._dedupe_results(results)
        if venue_term:
            deduped = [r for r in deduped if self._matches_venue(r, venue_term)]
        if section_term:
            deduped = [r for r in deduped if self._matches_section(r, section_term)]
        if max_price is not None:
            deduped = [r for r in deduped if r.min_price is None or r.min_price <= max_price]
        deduped.sort(key=lambda r: (r.min_price is None, r.min_price or float("inf"), r.event_date, r.source))
        return TicketSearchResponse(results=deduped[:limit], errors=errors)

    def _search_public_provider(
        self,
        source: str,
        query: str,
        zip_code: str,
        radius_miles: int | None,
        date_from: str | None,
        date_to: str | None,
        limit_per_source: int,
        fallback_only: bool = False,
    ) -> list[TicketResult]:
        url = self._provider_search_url(source, query, zip_code, radius_miles, date_from, date_to)
        if fallback_only:
            return [self._search_link_result(source, query, zip_code, radius_miles, date_from, date_to)]

        try:
            html = self._get_html(url)
            extracted = self._extract_events_from_jsonld(html, source=source, default_city=zip_code)
            if extracted:
                return extracted[:limit_per_source]
        except requests.RequestException:
            pass

        return [self._search_link_result(source, query, zip_code, radius_miles, date_from, date_to)]

    def _provider_search_url(
        self,
        source: str,
        query: str,
        zip_code: str,
        radius_miles: int | None,
        date_from: str | None,
        date_to: str | None,
    ) -> str:
        terms: list[str] = [query]
        if zip_code:
            terms.append(zip_code)
        if date_from:
            terms.append(date_from)
        if date_to:
            terms.append(date_to)
        # Public search URLs are more reliable with the core artist/event query only.
        del zip_code, radius_miles
        q = quote_plus(" ".join(t for t in terms if t).strip())

        if source == "stubhub":
            return f"https://www.stubhub.com/search?search={q}"
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
        radius_miles: int | None,
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
        primary_url = self._provider_search_url(source, query, zip_code, radius_miles, date_from, date_to)
        # Never fail the whole request due to provider link discovery issues.
        try:
            url = self._choose_best_link(source=source, query=query, primary_url=primary_url)
        except requests.RequestException:
            url = primary_url
        return TicketResult(
            source=source,
            event_name=label,
            venue="",
            event_date=date_from or "",
            city=zip_code or "",
            min_price=None,
            max_price=None,
            currency=None,
            url=url,
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

    def _choose_best_link(self, source: str, query: str, primary_url: str) -> str:
        if self._link_looks_usable(primary_url):
            return primary_url

        domain_map = {
            "stubhub": "stubhub.com",
            "vividseats": "vividseats.com",
            "tickpick": "tickpick.com",
            "livenation": "livenation.com",
            "axs": "axs.com",
            "gametime": "gametime.co",
            "ticketmaster": "ticketmaster.com",
            "seatgeek": "seatgeek.com",
        }
        domain = domain_map.get(source)
        if domain:
            try:
                discovered = self._duckduckgo_domain_result(query=query, domain=domain)
            except requests.RequestException:
                discovered = None
            if discovered and self._link_looks_usable(discovered):
                return discovered

        return primary_url

    def _duckduckgo_domain_result(self, query: str, domain: str) -> str | None:
        search_url = f"https://duckduckgo.com/html/?q={quote_plus(f'site:{domain} {query} tickets')}"
        html = self._get_html(search_url)
        links = re.findall(r'class=\"result__a\" href=\"([^\"]+)\"', html, flags=re.IGNORECASE)
        for raw in links:
            decoded = unquote(raw)
            if "uddg=" in decoded:
                match = re.search(r"uddg=([^&]+)", decoded)
                if match:
                    decoded = unquote(match.group(1))
            parsed = urlparse(decoded)
            if parsed.scheme not in {"http", "https"}:
                continue
            if domain not in parsed.netloc:
                continue
            return decoded
        return None

    def _link_looks_usable(self, url: str) -> bool:
        try:
            response = requests.get(
                url,
                timeout=self.timeout_seconds,
                allow_redirects=True,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (X11; Linux x86_64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0 Safari/537.36"
                    )
                },
            )
        except requests.RequestException:
            return False

        if response.status_code >= 400:
            return False

        text = response.text.lower()
        bad_markers = [
            "no results found",
            "0 results",
            "we couldn't find",
            "try a different search",
            "access denied",
        ]
        return not any(marker in text for marker in bad_markers)

    def _matches_section(self, row: TicketResult, section_term: str) -> bool:
        blob = " ".join([row.event_name, row.venue, row.url]).lower()
        return section_term in blob

    def _matches_venue(self, row: TicketResult, venue_term: str) -> bool:
        blob = " ".join([row.venue, row.city, row.event_name, row.url]).lower()
        norm_blob = re.sub(r"[^a-z0-9]+", " ", blob)
        norm_term = re.sub(r"[^a-z0-9]+", " ", venue_term.lower()).strip()
        if not norm_term:
            return True
        tokens = [t for t in norm_term.split() if len(t) >= 3]
        if not tokens:
            return norm_term in norm_blob
        return all(t in norm_blob for t in tokens)
