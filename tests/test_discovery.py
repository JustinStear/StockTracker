from __future__ import annotations

import requests

from stockcheck.discovery import ProductCandidate, ProductDiscoveryService


def test_discovery_continues_when_one_retailer_errors(monkeypatch) -> None:
    svc = ProductDiscoveryService()

    def fake_target(keyword: str, limit: int):
        del keyword, limit
        return [
            ProductCandidate(
                retailer="target",
                label="Target Result",
                identifier_type="url",
                identifier_value="https://www.target.com/p/example",
                url="https://www.target.com/p/example",
            )
        ]

    def fake_bestbuy(keyword: str, limit: int):
        del keyword, limit
        raise requests.RequestException("timeout")

    monkeypatch.setattr(svc, "_discover_target", fake_target)
    monkeypatch.setattr(svc, "_discover_bestbuy", fake_bestbuy)

    result = svc.discover("elite trainer box", ["target", "bestbuy"], limit=3)

    assert len(result.candidates) == 1
    assert result.candidates[0].retailer == "target"
    assert len(result.errors) == 1
    assert "bestbuy" in result.errors[0]
