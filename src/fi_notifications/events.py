"""Event evaluators: decide whether a pet's status matches a subscription."""

import dataclasses
import datetime
import zoneinfo

from fi_notifications import config
from fi_notifications import fi


@dataclasses.dataclass(frozen=True, slots=True)
class Message:
    """A notification to send.

    Attributes:
        title: Short headline.
        body: Message text.
        priority: ntfy priority name.
        tags: Comma-separated ntfy tags.
    """

    title: str
    body: str
    priority: str
    tags: str


def _battery_low(pet: fi.PetStatus, event: config.BatteryLow) -> Message | None:
    if pet.battery_percent >= event.threshold or (event.suppress_when_charging and pet.charging):
        return None
    pct = pet.battery_percent
    return Message(
        f"{pet.name}: battery {pct}%",
        f"{pet.name}'s collar battery is {pct}% (threshold {event.threshold}%).",
        "default",
        "battery",
    )


def _collar_offline(
    pet: fi.PetStatus, event: config.CollarOffline, now: datetime.datetime, tz: zoneinfo.ZoneInfo
) -> Message | None:
    minutes = int((now - pet.last_connection).total_seconds() // 60)
    if minutes <= event.minutes:
        return None
    seen = pet.last_connection.astimezone(tz).strftime("%H:%M")
    return Message(
        f"{pet.name}: collar offline",
        f"No connection for {minutes} minutes (last seen {seen}).",
        "high",
        "warning",
    )


def _lost_mode(pet: fi.PetStatus) -> Message | None:
    if pet.mode != "LOST_DOG":
        return None
    return Message(f"{pet.name}: LOST MODE", "Lost dog mode is active.", "urgent", "rotating_light")


def evaluate(
    pet: fi.PetStatus, event: config.EventConfig, now: datetime.datetime, tz: zoneinfo.ZoneInfo
) -> Message | None:
    """Evaluates one subscription against a pet's status.

    Args:
        pet: Current pet status.
        event: The subscription to check.
        now: Current time (aware).
        tz: Zone for times shown in messages.

    Returns:
        The message to send if the event matches, else None.
    """
    match event:
        case config.BatteryLow():
            msg = _battery_low(pet, event)
        case config.CollarOffline():
            msg = _collar_offline(pet, event, now, tz)
        case config.LostMode():
            msg = _lost_mode(pet)
    if msg is not None and event.priority is not None:
        msg = dataclasses.replace(msg, priority=event.priority)
    return msg
