from __future__ import annotations

from pathlib import Path

import yaml

from stockcheck.models import AppConfig


def load_config(config_path: str | Path) -> AppConfig:
    path = Path(config_path)
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AppConfig.model_validate(payload)
