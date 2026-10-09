import datetime
import json
import pathlib
from typing import Any
import zoneinfo

import httpx
import pytest

from fi_notifications import __main__ as app
from fi_notifications import config
from fi_notifications import fi
from fi_notifications import limiter

NY = zoneinfo.ZoneInfo("America/New_York")
REX = fi.PetStatus("p", "Rex", "m", 37, None, "ConnectedToUser", datetime.datetime.now(datetime.UTC), "NORMAL")


def make_config(tmp_path: pathlib.Path, collars: tuple[str, ...] = ("Rex",), limit: int | None = 2) -> config.Config:
    return config.Config.model_validate(
        {
            "fi": {"email": "e", "password": "p"},
            "poll_interval": 300,
            "timezone": "America/New_York",
            "state_file": str(tmp_path / "state.json"),
            "targets": {
                "phone": {
                    "type": "ntfy",
                    "url": "https://ntfy.example.com/fi",
                    "token": "t",
                    "window": {"start": "08:00", "end": "20:00"},
                }
            },
            "collars": [
                {
                    "name": name,
                    "events": [{"type": "battery_low", "target": "phone", "max_per_window": limit}],
                }
                for name in collars
            ],
        }
    )


def at(hh: int, mm: int = 0) -> datetime.datetime:
    return datetime.datetime(2026, 10, 9, hh, mm, tzinfo=NY)


class Ntfy:
    def __init__(self, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []

    def client(self) -> httpx.AsyncClient:
        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(self.status)

        return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def run_polls(cfg: config.Config, ntfy: Ntfy, *times: datetime.datetime) -> dict[Any, limiter.LimiterState]:
    states: dict[Any, limiter.LimiterState] = {}
    async with ntfy.client() as http:
        for t in times:
            states = await app.poll_once(cfg, [REX], http, states, t)
    return states


async def test_sends_battery_low_in_window(tmp_path: pathlib.Path) -> None:
    ntfy = Ntfy()
    states = await run_polls(make_config(tmp_path), ntfy, at(9))
    assert len(ntfy.requests) == 1
    assert ntfy.requests[0].url.params["title"] == "Rex: battery 37%"
    assert states[("Rex", 0)].sent == 1


async def test_respects_limit_across_polls(tmp_path: pathlib.Path) -> None:
    ntfy = Ntfy()
    await run_polls(make_config(tmp_path), ntfy, at(8), at(8, 5), at(14))
    assert len(ntfy.requests) == 2


async def test_no_limit_sends_every_poll(tmp_path: pathlib.Path) -> None:
    ntfy = Ntfy()
    await run_polls(make_config(tmp_path, limit=None), ntfy, at(8), at(8, 5), at(8, 10))
    assert len(ntfy.requests) == 3


async def test_outside_window_no_send(tmp_path: pathlib.Path) -> None:
    ntfy = Ntfy()
    await run_polls(make_config(tmp_path), ntfy, at(21))
    assert ntfy.requests == []


async def test_failed_send_not_recorded(tmp_path: pathlib.Path) -> None:
    ntfy = Ntfy(status=500)
    states = await run_polls(make_config(tmp_path), ntfy, at(9))
    assert len(ntfy.requests) == 1
    assert states.get(("Rex", 0), limiter.LimiterState()).sent == 0


async def test_missing_collar_warns_and_continues(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    ntfy = Ntfy()
    await run_polls(make_config(tmp_path, collars=("Ghost", "Rex")), ntfy, at(9))
    assert len(ntfy.requests) == 1
    assert "Ghost" in caplog.text


async def test_state_saved_after_send(tmp_path: pathlib.Path) -> None:
    await run_polls(make_config(tmp_path), Ntfy(), at(9))
    saved = json.loads((tmp_path / "state.json").read_text())
    assert saved["Rex/0"]["sent"] == 1


def test_check_collars_lists_available(tmp_path: pathlib.Path) -> None:
    with pytest.raises(SystemExit, match=r"Ghost.*available: Broken, Rex"):
        app.check_collars(make_config(tmp_path, collars=("Ghost",)), {"Rex", "Broken"})
    app.check_collars(make_config(tmp_path, collars=("Rex", "Broken")), {"Rex", "Broken"})


async def test_unwritable_state_file_keeps_running(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    cfg = make_config(tmp_path).model_copy(update={"state_file": tmp_path / "missing-dir" / "s.json"})
    ntfy = Ntfy()
    states = await run_polls(cfg, ntfy, at(8), at(8, 5))
    assert len(ntfy.requests) == 1  # In-memory budget still enforced
    assert states[("Rex", 0)].sent == 1
    assert "state" in caplog.text
