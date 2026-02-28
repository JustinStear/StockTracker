from __future__ import annotations

import os
import re
from dataclasses import dataclass
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
        self._retailer_domains = {
            "bestbuy": "bestbuy.com",
            "target": "target.com",
            "walmart": "walmart.com",
            "gamestop": "gamestop.com",
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
                elif retailer == "bestbuy":
                    if not os.getenv("BESTBUY_API_KEY"):
                        errors.append("bestbuy: set BESTBUY_API_KEY to discover SKU-backed Best Buy products")
                        continue
                    results.extend(self._discover_bestbuy(cleaned, limit))
            except requests.RequestException as exc:
                errors.append(f"{retailer}: {exc}")

        return DiscoveryResult(candidates=results, errors=errors)

    def _discover_target(self, keyword: str, limit: int) -> list[ProductCandidate]:
        links = self._discover_via_duckduckgo("target", keyword, limit, r"/p/")
        if not links:
            links = [
                {
                    "url": f"https://www.target.com/s?searchTerm={quote_plus(keyword)}",
                    "label": f"Target search: {keyword}",
                }
            ]
        return [
            ProductCandidate(
                retailer="target",
                label=item.get("label", self._label_from_url(item["url"], "Target")),
                identifier_type="url",
                identifier_value=item["url"],
                url=item["url"],
            )
            for item in links
        ]

    def _discover_walmart(self, keyword: str, limit: int) -> list[ProductCandidate]:
        links = self._discover_via_duckduckgo("walmart", keyword, limit, r"/ip/")
        if not links:
            links = [
                {
                    "url": f"https://www.walmart.com/search?q={quote_plus(keyword)}",
                    "label": f"Walmart search: {keyword}",
                }
            ]
        return [
            ProductCandidate(
                retailer="walmart",
                label=item.get("label", self._label_from_url(item["url"], "Walmart")),
                identifier_type="url",
                identifier_value=item["url"],
                url=item["url"],
            )
            for item in links
        ]

    def _discover_gamestop(self, keyword: str, limit: int) -> list[ProductCandidate]:
        links = self._discover_via_duckduckgo("gamestop", keyword, limit, r"/products/")
        if not links:
            links = [
                {
                    "url": f"https://www.gamestop.com/search/?q={quote_plus(keyword)}",
                    "label": f"GameStop search: {keyword}",
                }
            ]
        return [
            ProductCandidate(
                retailer="gamestop",
                label=item.get("label", self._label_from_url(item["url"], "GameStop")),
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

        links = self._discover_via_duckduckgo("bestbuy", keyword, limit, r"/site/")
        sku_pattern = re.compile(r"/(\d+)\.p", flags=re.IGNORECASE)
        skus: list[str] = []
        for item in links:
            match = sku_pattern.search(item["url"])
            if not match:
                continue
            sku = match.group(1)
            if sku in skus:
                continue
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

    def _discover_via_duckduckgo(
        self, retailer: str, keyword: str, limit: int, path_hint_regex: str
    ) -> list[dict[str, str]]:
        domain = self._retailer_domains[retailer]
        query = f"{keyword} pokemon tcg {retailer}"
        url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        html = self._get(url)

        encoded_links = re.findall(r'class=\"result__a\" href=\"([^\"]+)\"', html, flags=re.IGNORECASE)
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
            deduped.append({"url": clean_url, "label": self._label_from_url(clean_url, retailer)})
            if len(deduped) >= limit:
                break

        if deduped:
            return deduped

        for clean_url in all_domain_links:
            if clean_url in seen:
                continue
            seen.add(clean_url)
            deduped.append({"url": clean_url, "label": self._label_from_url(clean_url, retailer)})
            if len(deduped) >= limit:
                break

        return deduped

    def _label_from_url(self, url: str, retailer_name: str) -> str:
        parsed = urlparse(url)
        tail = parsed.path.rsplit("/", 1)[-1]
        tail = tail.replace(".p", "")
        tail = tail.replace("-", " ").strip()
        tail = re.sub(r"\s+", " ", tail)
        if not tail:
            return f"{retailer_name} Product"
        return f"{retailer_name}: {tail[:80]}"

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
