import datetime
import pathlib

import pytest

from fi_notifications import limiter
from fi_notifications import state as state_store

S = limiter.LimiterState(datetime.date(2026, 10, 9), 1, datetime.datetime(2026, 10, 9, 18, tzinfo=datetime.UTC))


def test_round_trip(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state.json"
    state = {("Rex", 0): S, ("Odd/Name", 2): limiter.LimiterState()}
    state_store.save_state(path, state)
    assert state_store.load_state(path, set(state)) == state


def test_missing_file_empty(tmp_path: pathlib.Path) -> None:
    assert state_store.load_state(tmp_path / "nope.json", {("Rex", 0)}) == {}


def test_none_path_noop() -> None:
    state_store.save_state(None, {("Rex", 0): S})
    assert state_store.load_state(None, {("Rex", 0)}) == {}


def test_corrupt_file_empty_and_logs(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "state.json"
    path.write_text("{not json")
    assert state_store.load_state(path, {("Rex", 0)}) == {}
    assert "state" in caplog.text


def test_unknown_keys_dropped(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state.json"
    state_store.save_state(path, {("Rex", 0): S, ("Gone", 0): S, ("Rex", 5): S})
    assert state_store.load_state(path, {("Rex", 0)}) == {("Rex", 0): S}


def test_atomic_write_no_tmp_left(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "state.json"
    state_store.save_state(path, {("Rex", 0): S})
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
