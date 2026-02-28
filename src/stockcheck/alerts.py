from __future__ import annotations

import logging

import requests

LOG = logging.getLogger(__name__)


class AlertSink:
    def send(self, message: str) -> None:
        raise NotImplementedError


class DryRunAlertSink(AlertSink):
    def send(self, message: str) -> None:
        LOG.info("[DRY RUN] alert: %s", message)


class DiscordWebhookAlertSink(AlertSink):
    def __init__(self, webhook_url: str, timeout_seconds: float = 10.0) -> None:
        self.webhook_url = webhook_url
        self.timeout_seconds = timeout_seconds

    def send(self, message: str) -> None:
        response = requests.post(
            self.webhook_url,
            json={"content": message},
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 300:
            raise RuntimeError(
                f"discord webhook failed ({response.status_code}): {response.text}"
            )
