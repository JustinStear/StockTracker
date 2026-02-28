from __future__ import annotations

import os
import re
from dataclasses import dataclass
from html import unescape
from urllib.parse import quote_plus

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
    def __init__(self, timeout_seconds: float = 15.0) -> None:
        self.timeout_seconds = timeout_seconds

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
                elif retailer == "bestbuy":
                    results.extend(self._discover_bestbuy(cleaned, limit))
            except requests.RequestException as exc:
                errors.append(f"{retailer}: {exc}")

        return DiscoveryResult(candidates=results, errors=errors)

    def _discover_target(self, keyword: str, limit: int) -> list[ProductCandidate]:
        url = f"https://www.target.com/s?searchTerm={quote_plus(keyword)}"
        html = self._get(url)
        links = self._extract_product_links(
            html,
            retailer="target",
            base_url="https://www.target.com",
            path_pattern=r'(/p/[^"]+)',
            title_pattern=r"<title>(.*?)</title>",
            limit=limit,
        )
        return [
            ProductCandidate(
                retailer="target",
                label=item["label"],
                identifier_type="url",
                identifier_value=item["url"],
                url=item["url"],
            )
            for item in links
        ]

    def _discover_walmart(self, keyword: str, limit: int) -> list[ProductCandidate]:
        url = f"https://www.walmart.com/search?q={quote_plus(keyword)}"
        html = self._get(url)
        links = self._extract_product_links(
            html,
            retailer="walmart",
            base_url="https://www.walmart.com",
            path_pattern=r'(/ip/[^"]+)',
            title_pattern=r"<title>(.*?)</title>",
            limit=limit,
        )
        return [
            ProductCandidate(
                retailer="walmart",
                label=item["label"],
                identifier_type="url",
                identifier_value=item["url"],
                url=item["url"],
            )
            for item in links
        ]

    def _discover_gamestop(self, keyword: str, limit: int) -> list[ProductCandidate]:
        url = f"https://www.gamestop.com/search/?q={quote_plus(keyword)}"
        html = self._get(url)
        links = self._extract_product_links(
            html,
            retailer="gamestop",
            base_url="https://www.gamestop.com",
            path_pattern=r'(/[^"\s]*?/products/[^"\s]*?)',
            title_pattern=r"<title>(.*?)</title>",
            limit=limit,
        )
        return [
            ProductCandidate(
                retailer="gamestop",
                label=item["label"],
                identifier_type="url",
                identifier_value=item["url"],
                url=item["url"],
            )
            for item in links
        ]

    def _discover_bestbuy(self, keyword: str, limit: int) -> list[ProductCandidate]:
        api_key = os.getenv("BESTBUY_API_KEY")
        if api_key:
            api_results = self._discover_bestbuy_api(keyword, limit, api_key)
            if api_results:
                return api_results

        url = f"https://www.bestbuy.com/site/searchpage.jsp?st={quote_plus(keyword)}"
        html = self._get(url)

        sku_pattern = re.compile(r"/site/[^\"]+/(\d+)\.p", flags=re.IGNORECASE)
        skus: list[str] = []
        for sku in sku_pattern.findall(html):
            if sku not in skus:
                skus.append(sku)
            if len(skus) >= limit:
                break

        return [
            ProductCandidate(
                retailer="bestbuy",
                label=f"Best Buy SKU {sku}",
                identifier_type="sku",
                identifier_value=sku,
                url=f"https://www.bestbuy.com/site/{sku}.p",
            )
            for sku in skus
        ]

    def _discover_bestbuy_api(self, keyword: str, limit: int, api_key: str) -> list[ProductCandidate]:
        endpoint = "https://api.bestbuy.com/v1/products((search={query}))"
        response = requests.get(
            endpoint.format(query=quote_plus(keyword)),
            params={
                "apiKey": api_key,
                "format": "json",
                "show": "name,sku,url",
                "pageSize": limit,
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code != 200:
            return []

        payload = response.json()
        products = payload.get("products", [])
        results: list[ProductCandidate] = []
        for p in products:
            sku = str(p.get("sku", "")).strip()
            name = str(p.get("name", "")).strip() or f"Best Buy SKU {sku}"
            if not sku:
                continue
            results.append(
                ProductCandidate(
                    retailer="bestbuy",
                    label=name,
                    identifier_type="sku",
                    identifier_value=sku,
                    url=str(p.get("url", "")).strip() or f"https://www.bestbuy.com/site/{sku}.p",
                )
            )
        return results

    def _extract_product_links(
        self,
        html: str,
        retailer: str,
        base_url: str,
        path_pattern: str,
        title_pattern: str,
        limit: int,
    ) -> list[dict[str, str]]:
        del retailer
        seen: set[str] = set()
        links: list[dict[str, str]] = []

        title_match = re.search(title_pattern, html, flags=re.IGNORECASE | re.DOTALL)
        fallback_title = "Search result"
        if title_match:
            fallback_title = self._clean_label(title_match.group(1))

        for match in re.finditer(path_pattern, html, flags=re.IGNORECASE):
            path = match.group(1).split("?")[0]
            full_url = f"{base_url}{path}"
            if full_url in seen:
                continue
            seen.add(full_url)
            links.append({"url": full_url, "label": fallback_title})
            if len(links) >= limit:
                break

        return links

    def _clean_label(self, raw: str) -> str:
        raw = unescape(raw)
        raw = re.sub(r"\s+", " ", raw).strip()
        return raw

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
