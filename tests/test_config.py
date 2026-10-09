import pathlib
import zoneinfo

import pydantic
import pytest

from fi_notifications import config

EXAMPLE = """
fi:
  email: me@example.com
  password_file: {secrets}/fi-password
poll_interval: 300
timezone: America/New_York
state_file: /data/state.json
targets:
  phone:
    type: ntfy
    url: https://ntfy.example.com/fi-alerts
    token_file: {secrets}/ntfy-token
    window: {{ start: "08:00", end: "20:00" }}
collars:
  - name: Rex
    events:
      - type: battery_low
        threshold: 40
        suppress_when_charging: true
        target: phone
        max_per_window: 2
      - type: collar_offline
        minutes: 60
        target: phone
      - type: lost_mode
        target: phone
"""


@pytest.fixture
def write(tmp_path: pathlib.Path):
    (tmp_path / "fi-password").write_text("pw\n")
    (tmp_path / "ntfy-token").write_text("tok\n")

    def _write(text: str = EXAMPLE, **replace: str) -> pathlib.Path:
        text = text.format(secrets=tmp_path)
        for old, new in replace.items():
            assert old in text, old
            text = text.replace(old, new)
        path = tmp_path / "config.yaml"
        path.write_text(text)
        return path

    return _write


def test_load_valid(write) -> None:
    cfg = config.load_config(write())
    event = cfg.collars[0].events[0]
    assert isinstance(event, config.BatteryLow)
    assert event.threshold == 40
    assert event.max_per_window == 2
    assert cfg.fi.password.get_secret_value() == "pw"
    token = cfg.targets["phone"].token
    assert token is not None
    assert token.get_secret_value() == "tok"
    assert cfg.timezone == zoneinfo.ZoneInfo("America/New_York")
    assert cfg.health_port == 8080
    assert cfg.targets["phone"].window is not None


def test_unknown_target(write) -> None:
    with pytest.raises(ValueError, match="unknown target 'phone'"):
        config.load_config(write(**{"  phone:\n    type: ntfy": "  pager:\n    type: ntfy"}))


def test_unknown_event_type(write) -> None:
    with pytest.raises(pydantic.ValidationError):
        config.load_config(write(**{"type: lost_mode": "type: geofence"}))


def test_secret_both_inline_and_file(write) -> None:
    with pytest.raises(ValueError, match="password"):
        config.load_config(write(**{"  password_file:": "  password: x\n  password_file:"}))


def test_secret_neither(write, tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="password"):
        config.load_config(write(**{f"  password_file: {tmp_path}/fi-password\n": ""}))


def test_secret_file_missing(write, tmp_path: pathlib.Path) -> None:
    with pytest.raises(ValueError, match="nope"):
        config.load_config(write(**{f"{tmp_path}/fi-password": f"{tmp_path}/nope"}))


def test_window_crossing_midnight_rejected(write) -> None:
    with pytest.raises(ValueError, match="start"):
        config.load_config(write(**{'start: "08:00", end: "20:00"': 'start: "22:00", end: "06:00"'}))


def test_ntfy_token_and_basic_both_rejected(write) -> None:
    with pytest.raises(ValueError):
        config.load_config(write(**{"    token_file:": "    username: u\n    password: p\n    token_file:"}))


def test_poll_interval_below_60_rejected(write) -> None:
    with pytest.raises(ValueError):
        config.load_config(write(**{"poll_interval: 300": "poll_interval: 30"}))


def test_bad_timezone_rejected(write) -> None:
    with pytest.raises(ValueError):
        config.load_config(write(**{"America/New_York": "Mars/Olympus"}))


def test_secrets_hidden(write) -> None:
    cfg = config.load_config(write())
    assert "pw" not in repr(cfg.fi)
    with pytest.raises(pydantic.ValidationError) as exc:
        config.load_config(write(**{"    token_file:": "    username: u\n    password: hunter2\n    token_file:"}))
    assert "hunter2" not in str(exc.value)


def test_bad_health_port_rejected(write) -> None:
    with pytest.raises(ValueError):
        config.load_config(write(**{"poll_interval: 300": "poll_interval: 300\nhealth_port: 0"}))


def test_example_config_is_valid(tmp_path: pathlib.Path) -> None:
    text = (pathlib.Path(__file__).parent.parent / "config.example.yaml").read_text()
    (tmp_path / "fi-password").write_text("pw")
    (tmp_path / "ntfy-token").write_text("tok")
    path = tmp_path / "config.yaml"
    path.write_text(text.replace("/run/secrets/fi-notifications", str(tmp_path)))
    assert config.load_config(path).collars[0].name == "Rex"
