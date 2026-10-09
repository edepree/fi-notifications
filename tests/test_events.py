import dataclasses
import datetime
from typing import Any
import zoneinfo

from fi_notifications import config
from fi_notifications import events
from fi_notifications import fi

NY = zoneinfo.ZoneInfo("America/New_York")
LAST = datetime.datetime(2026, 10, 9, 14, 2, tzinfo=datetime.UTC)
NOW = LAST + datetime.timedelta(minutes=72)


BASE = fi.PetStatus(
    pet_id="p",
    name="Rex",
    module_id="m",
    battery_percent=37,
    is_charging=None,
    connection_type="ConnectedToUser",
    last_connection=LAST,
    mode="NORMAL",
)


def pet(**kw: Any) -> fi.PetStatus:
    return dataclasses.replace(BASE, **kw)


def battery(**kw: Any) -> config.BatteryLow:
    return config.BatteryLow.model_validate({"type": "battery_low", "target": "t"} | kw)


def test_battery_low_matches() -> None:
    assert events.evaluate(pet(), battery(), NOW, NY) == events.Message(
        title="Rex: battery 37%",
        body="Rex's collar battery is 37% (threshold 40%).",
        priority="default",
        tags="battery",
    )


def test_battery_at_threshold_no_match() -> None:
    assert events.evaluate(pet(battery_percent=40), battery(), NOW, NY) is None


def test_battery_suppressed_when_charging_v2() -> None:
    p = pet(connection_type="ConnectedToBase")
    assert events.evaluate(p, battery(suppress_when_charging=True), NOW, NY) is None


def test_battery_suppressed_v1_is_charging() -> None:
    assert events.evaluate(pet(is_charging=True), battery(suppress_when_charging=True), NOW, NY) is None


def test_battery_not_suppressed_without_flag() -> None:
    assert events.evaluate(pet(connection_type="ConnectedToBase"), battery(), NOW, NY) is not None


def test_offline_matches() -> None:
    event = config.CollarOffline(type="collar_offline", target="t", minutes=60)
    msg = events.evaluate(pet(), event, NOW, NY)
    assert msg == events.Message(
        title="Rex: collar offline",
        body="No connection for 72 minutes (last seen 10:02).",
        priority="high",
        tags="warning",
    )


def test_offline_within_limit_none() -> None:
    event = config.CollarOffline(type="collar_offline", target="t", minutes=90)
    assert events.evaluate(pet(), event, NOW, NY) is None


def test_lost_mode() -> None:
    event = config.LostMode(type="lost_mode", target="t")
    assert events.evaluate(pet(), event, NOW, NY) is None
    assert events.evaluate(pet(mode="LOST_DOG"), event, NOW, NY) == events.Message(
        title="Rex: LOST MODE",
        body="Lost dog mode is active.",
        priority="urgent",
        tags="rotating_light",
    )


def test_priority_override() -> None:
    msg = events.evaluate(pet(), battery(priority="high"), NOW, NY)
    assert msg is not None
    assert msg.priority == "high"
