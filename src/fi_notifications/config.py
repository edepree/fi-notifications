"""YAML configuration models.

Secrets may be given inline (`x`) or read from a file (`x_file`), which is how
Kubernetes Secrets are mounted.
"""

import datetime
import pathlib
from typing import Annotated, Any, Literal, Self
import zoneinfo

import pydantic
import yaml

Priority = Literal["min", "low", "default", "high", "urgent"]


def _resolve_secret(data: Any, key: str, *, required: bool) -> Any:
    """Replaces `<key>_file` in raw model input with the file's stripped contents under `key`.

    Args:
        data: Raw model input; returned unchanged if it is not a dict.
        key: Secret field name.
        required: Whether one of `key` or `<key>_file` must be present.

    Returns:
        The input with any `<key>_file` entry replaced by `key`.

    Raises:
        ValueError: Both or (if required) neither form is set, or the file is unreadable.
    """
    if not isinstance(data, dict):
        return data
    file_key = f"{key}_file"
    if key in data and file_key in data:
        raise ValueError(f"set only one of {key!r} or {file_key!r}")
    if file_key in data:
        path = pathlib.Path(data[file_key])
        try:
            secret = path.read_text().strip()
        except OSError as exc:
            raise ValueError(f"cannot read {file_key} {path}: {exc.strerror}") from None
        data = {k: v for k, v in data.items() if k != file_key} | {key: secret}
    if required and key not in data:
        raise ValueError(f"{key!r} or {file_key!r} is required")
    return data


class _Model(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class Window(_Model):
    """Daily delivery window, in the configured timezone.

    Attributes:
        start: First time of day notifications may be sent.
        end: Exclusive end; must be after `start` (midnight-crossing is not supported).
    """

    start: datetime.time
    end: datetime.time

    @pydantic.model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.start >= self.end:
            raise ValueError("window start must be before end (midnight-crossing not supported)")
        return self


class NtfyTarget(_Model):
    """An ntfy topic to publish to.

    Attributes:
        type: Always "ntfy".
        url: Full topic URL.
        window: Optional delivery window; None means all day.
        token: Bearer token, exclusive with username/password.
        username: Basic-auth user.
        password: Basic-auth password.
    """

    type: Literal["ntfy"]
    url: pydantic.HttpUrl
    window: Window | None = None
    token: pydantic.SecretStr | None = None
    username: str | None = None
    password: pydantic.SecretStr | None = None

    @pydantic.model_validator(mode="before")
    @classmethod
    def _secrets(cls, data: Any) -> Any:
        data = _resolve_secret(data, "token", required=False)
        return _resolve_secret(data, "password", required=False)

    @pydantic.model_validator(mode="after")
    def _auth(self) -> Self:
        basic = self.username is not None or self.password is not None
        if self.token is not None and basic:
            raise ValueError("use either token or username/password, not both")
        if basic and (self.username is None or self.password is None):
            raise ValueError("basic auth needs both username and password")
        return self


class _Event(_Model):
    target: str
    max_per_window: int | None = pydantic.Field(default=None, ge=1)
    priority: Priority | None = None


class BatteryLow(_Event):
    """Fires while battery is below `threshold` percent.

    Attributes:
        type: Always "battery_low".
        threshold: Percent; fires when battery is strictly below it.
        suppress_when_charging: Skip while the collar is charging or on its base.
        target: Name of the target to notify.
        max_per_window: Optional cap on sends per window day.
        priority: Optional ntfy priority override.
    """

    type: Literal["battery_low"]
    threshold: int = pydantic.Field(default=40, ge=1, le=100)
    suppress_when_charging: bool = False


class CollarOffline(_Event):
    """Fires when the collar has not connected for more than `minutes`.

    Attributes:
        type: Always "collar_offline".
        minutes: Allowed silence before firing.
        target: Name of the target to notify.
        max_per_window: Optional cap on sends per window day.
        priority: Optional ntfy priority override.
    """

    type: Literal["collar_offline"]
    minutes: int = pydantic.Field(default=60, ge=1)


class LostMode(_Event):
    """Fires while the collar is in lost dog mode.

    Attributes:
        type: Always "lost_mode".
        target: Name of the target to notify.
        max_per_window: Optional cap on sends per window day.
        priority: Optional ntfy priority override.
    """

    type: Literal["lost_mode"]


EventConfig = Annotated[BatteryLow | CollarOffline | LostMode, pydantic.Field(discriminator="type")]


class Collar(_Model):
    """A pet's collar and its event subscriptions.

    Attributes:
        name: Pet name exactly as shown in the Fi app.
        events: Subscriptions evaluated on every poll.
    """

    name: str
    events: list[EventConfig]


class FiCreds(_Model):
    """Fi account login.

    Attributes:
        email: Account email.
        password: Account password.
    """

    email: str
    password: pydantic.SecretStr

    @pydantic.model_validator(mode="before")
    @classmethod
    def _secrets(cls, data: Any) -> Any:
        return _resolve_secret(data, "password", required=True)


class Config(_Model):
    """Top-level service configuration.

    Attributes:
        fi: Fi account login.
        poll_interval: Seconds between polls (>= 60).
        timezone: Zone for windows and displayed times.
        state_file: Optional path to persist limiter state.
        health_port: Port for the /healthz endpoint.
        targets: Notification targets by name.
        collars: Collars to monitor.
    """

    fi: FiCreds
    poll_interval: int = pydantic.Field(ge=60)
    timezone: zoneinfo.ZoneInfo
    state_file: pathlib.Path | None = None
    health_port: int = pydantic.Field(default=8080, ge=1, le=65535)
    targets: dict[str, NtfyTarget]
    collars: list[Collar]

    @pydantic.model_validator(mode="after")
    def _targets_exist(self) -> Self:
        for collar in self.collars:
            for event in collar.events:
                if event.target not in self.targets:
                    raise ValueError(f"collar {collar.name!r}: unknown target {event.target!r}")
        return self


def load_config(path: pathlib.Path) -> Config:
    """Loads and validates a YAML config file.

    Args:
        path: YAML file to read.

    Returns:
        The validated config, with secrets resolved.

    Raises:
        OSError: The file cannot be read.
        pydantic.ValidationError: The config is invalid.
    """
    return Config.model_validate(yaml.safe_load(path.read_text()))
