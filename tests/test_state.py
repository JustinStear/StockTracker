from pathlib import Path

from stockcheck.models import StockStatus
from stockcheck.state import StateStore


def test_alert_only_on_transition_to_in_stock(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    store = StateStore(db)

    first = store.update_status("target", "url:https://x", "s1", StockStatus.OUT_OF_STOCK)
    assert first.changed is True
    assert first.should_alert is False

    second = store.update_status("target", "url:https://x", "s1", StockStatus.OUT_OF_STOCK)
    assert second.changed is False
    assert second.should_alert is False

    third = store.update_status("target", "url:https://x", "s1", StockStatus.IN_STOCK)
    assert third.changed is True
    assert third.should_alert is True


def test_unknown_to_in_stock_alerts(tmp_path: Path) -> None:
    db = tmp_path / "state.sqlite3"
    store = StateStore(db)

    store.update_status("walmart", "url:https://y", "s2", StockStatus.UNKNOWN)
    transition = store.update_status("walmart", "url:https://y", "s2", StockStatus.IN_STOCK)
    assert transition.should_alert is True
