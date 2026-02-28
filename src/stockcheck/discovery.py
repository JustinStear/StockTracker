from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote_plus, unquote, urlparse

import requests


@dataclass(slots=True)
class DiscoveryResult:
    candidates: list["ProductCandidate"]
    errors: list[str]


@dataclass(slots=True)
class ProductCandidate:
    retailer: str
    label: str
    identifier_type: str
    identifier_value: str
    url: str
    price: float | None = None
    currency: str | None = None
    monitorable: bool = True

    def to_watch_item(self) -> dict[str, object]:
        return {
            "retailer": self.retailer,
            "label": self.label,
            "identifier": {
                "type": self.identifier_type,
                "value": self.identifier_value,
            },
        }


class ProductDiscoveryService:
    def __init__(self, timeout_seconds: float = 12.0) -> None:
        self.timeout_seconds = timeout_seconds
        self._retailer_domains = {
            "target": "target.com",
            "walmart": "walmart.com",
            "gamestop": "gamestop.com",
            "amazon": "amazon.com",
            "pokemoncenter": "pokemoncenter.com",
        }
        self._retailer_display = {
            "target": "Target",
            "walmart": "Walmart",
            "gamestop": "GameStop",
            "amazon": "Amazon",
            "pokemoncenter": "Pokemon Center",
        }

    def discover(self, keyword: str, retailers: list[str], limit: int = 8) -> DiscoveryResult:
        cleaned = keyword.strip()
        if not cleaned:
            return DiscoveryResult(candidates=[], errors=[])

        results: list[ProductCandidate] = []
        errors: list[str] = []
        for retailer in retailers:
            try:
                if retailer == "target":
                    results.extend(self._discover_target(cleaned, limit))
                elif retailer == "walmart":
                    results.extend(self._discover_walmart(cleaned, limit))
                elif retailer == "gamestop":
                    results.extend(self._discover_gamestop(cleaned, limit))
                elif retailer == "amazon":
                    results.extend(self._discover_amazon(cleaned, limit))
                elif retailer == "pokemoncenter":
                    results.extend(self._discover_pokemoncenter(cleaned, limit))
            except requests.RequestException as exc:
                errors.append(f"{retailer}: {exc}")

        deduped = self._dedupe(results)
        return DiscoveryResult(candidates=deduped, errors=errors)

    def _discover_target(self, keyword: str, limit: int) -> list[ProductCandidate]:
        return self._discover_retailer(
            retailer="target",
            keyword=keyword,
            limit=limit,
            path_hint_regex=r"/p/",
            fallback_url=f"https://www.target.com/s?searchTerm={quote_plus(keyword)}",
            monitorable=True,
        )

    def _discover_walmart(self, keyword: str, limit: int) -> list[ProductCandidate]:
        return self._discover_retailer(
            retailer="walmart",
            keyword=keyword,
            limit=limit,
            path_hint_regex=r"/ip/",
            fallback_url=f"https://www.walmart.com/search?q={quote_plus(keyword)}",
            monitorable=True,
        )

    def _discover_gamestop(self, keyword: str, limit: int) -> list[ProductCandidate]:
        return self._discover_retailer(
            retailer="gamestop",
            keyword=keyword,
            limit=limit,
            path_hint_regex=r"/products/",
            fallback_url=f"https://www.gamestop.com/search/?q={quote_plus(keyword)}",
            monitorable=True,
        )

    def _discover_amazon(self, keyword: str, limit: int) -> list[ProductCandidate]:
        return self._discover_retailer(
            retailer="amazon",
            keyword=keyword,
            limit=limit,
            path_hint_regex=r"/dp/",
            fallback_url=f"https://www.amazon.com/s?k={quote_plus(keyword + ' pokemon tcg')}",
            monitorable=False,
        )

    def _discover_pokemoncenter(self, keyword: str, limit: int) -> list[ProductCandidate]:
        return self._discover_retailer(
            retailer="pokemoncenter",
            keyword=keyword,
            limit=limit,
            path_hint_regex=r"/product/",
            fallback_url=f"https://www.pokemoncenter.com/search/{quote_plus(keyword)}",
            monitorable=False,
        )

    def _discover_retailer(
        self,
        retailer: str,
        keyword: str,
        limit: int,
        path_hint_regex: str,
        fallback_url: str,
        monitorable: bool,
    ) -> list[ProductCandidate]:
        links = self._discover_via_duckduckgo(retailer, keyword, limit, path_hint_regex)
        display = self._retailer_display[retailer]
        if not links:
            return [
                ProductCandidate(
                    retailer=retailer,
                    label=f"{display} search: {keyword}",
                    identifier_type="url",
                    identifier_value=fallback_url,
                    url=fallback_url,
                    price=None,
                    currency=None,
                    monitorable=False,
                )
            ]

        candidates: list[ProductCandidate] = []
        for item in links[:limit]:
            price, currency, title = self._extract_price_and_title(item["url"])
            label = title or item.get("label") or self._label_from_url(item["url"], display)
            candidates.append(
                ProductCandidate(
                    retailer=retailer,
                    label=label,
                    identifier_type="url",
                    identifier_value=item["url"],
                    url=item["url"],
                    price=price,
                    currency=currency,
                    monitorable=monitorable,
                )
            )
        return candidates

    def _discover_via_duckduckgo(
        self, retailer: str, keyword: str, limit: int, path_hint_regex: str
    ) -> list[dict[str, str]]:
        domain = self._retailer_domains[retailer]
        query = f"{keyword} pokemon tcg {retailer}"
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        html = self._get(url)

        encoded_links = re.findall(r'class="result__a" href="([^"]+)"', html, flags=re.IGNORECASE)
        deduped: list[dict[str, str]] = []
        seen: set[str] = set()
        hint_re = re.compile(path_hint_regex, flags=re.IGNORECASE)
        all_domain_links: list[str] = []
        for encoded in encoded_links:
            decoded = unquote(encoded)
            if "uddg=" in decoded:
                uddg_match = re.search(r"uddg=([^&]+)", decoded)
                if uddg_match:
                    decoded = unquote(uddg_match.group(1))
            parsed = urlparse(decoded)
            if parsed.scheme not in {"http", "https"}:
                continue
            if domain not in parsed.netloc:
                continue
            clean_url = decoded.split("?")[0]
            all_domain_links.append(clean_url)
            if clean_url in seen:
                continue
            if not hint_re.search(clean_url):
                continue
            seen.add(clean_url)
            deduped.append({"url": clean_url, "label": self._label_from_url(clean_url, self._retailer_display[retailer])})
            if len(deduped) >= limit:
                break

        if deduped:
            return deduped

        for clean_url in all_domain_links:
            if clean_url in seen:
                continue
            seen.add(clean_url)
            deduped.append({"url": clean_url, "label": self._label_from_url(clean_url, self._retailer_display[retailer])})
            if len(deduped) >= limit:
                break

        return deduped

    def _extract_price_and_title(self, url: str) -> tuple[float | None, str | None, str | None]:
        try:
            html = self._get(url)
        except requests.RequestException:
            return None, None, None

        title_match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
        title = self._clean_text(title_match.group(1)) if title_match else None

        scripts = re.findall(
            r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
            html,
            flags=re.IGNORECASE | re.DOTALL,
        )
        for raw in scripts:
            try:
                payload = json.loads(raw.strip())
            except json.JSONDecodeError:
                continue
            price, currency, name = self._find_product_offer(payload)
            if price is not None or name:
                return price, currency, name or title

        # Fallback text extraction for simple "$123.45" patterns.
        price_match = re.search(r"\$\s?([0-9]{1,5}(?:\.[0-9]{2})?)", html)
        if price_match:
            try:
                return float(price_match.group(1)), "USD", title
            except ValueError:
                pass
        return None, None, title

    def _find_product_offer(self, node: Any) -> tuple[float | None, str | None, str | None]:
        if isinstance(node, list):
            for item in node:
                p, c, n = self._find_product_offer(item)
                if p is not None or n:
                    return p, c, n
            return None, None, None

        if not isinstance(node, dict):
            return None, None, None

        typ = node.get("@type")
        is_product = typ == "Product" or (isinstance(typ, list) and "Product" in typ)
        if is_product:
            name = self._clean_text(str(node.get("name", "")).strip()) or None
            offers = node.get("offers")
            price, currency = self._extract_offer_price(offers)
            return price, currency, name

        for value in node.values():
            p, c, n = self._find_product_offer(value)
            if p is not None or n:
                return p, c, n

        return None, None, None

    def _extract_offer_price(self, offers: Any) -> tuple[float | None, str | None]:
        if isinstance(offers, list):
            prices: list[float] = []
            currency: str | None = None
            for offer in offers:
                if not isinstance(offer, dict):
                    continue
                value = self._safe_float(offer.get("price"))
                if value is not None:
                    prices.append(value)
                if not currency and offer.get("priceCurrency"):
                    currency = str(offer.get("priceCurrency")).strip()
            if prices:
                return min(prices), currency
            return None, currency

        if isinstance(offers, dict):
            value = self._safe_float(offers.get("price"))
            if value is None:
                value = self._safe_float(offers.get("lowPrice"))
            currency = offers.get("priceCurrency")
            return value, (str(currency).strip() if currency else None)

        return None, None

    def _safe_float(self, value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _dedupe(self, rows: list[ProductCandidate]) -> list[ProductCandidate]:
        seen: set[tuple[str, str]] = set()
        out: list[ProductCandidate] = []
        for row in rows:
            key = (row.retailer, row.url)
            if key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    def _label_from_url(self, url: str, retailer_name: str) -> str:
        parsed = urlparse(url)
        tail = parsed.path.rsplit("/", 1)[-1]
        tail = tail.replace(".p", "")
        tail = tail.replace("-", " ").strip()
        tail = re.sub(r"\s+", " ", tail)
        if not tail:
            return f"{retailer_name} Product"
        return f"{retailer_name}: {tail[:90]}"

    def _clean_text(self, text: str) -> str:
        return re.sub(r"\s+", " ", text).strip()

    def _get(self, url: str) -> str:
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
