"""Optional JSON persistence of limiter state, keyed by (collar name, event index)."""

import datetime
import json
import logging
import os
import pathlib

from fi_notifications import limiter

log = logging.getLogger(__name__)

type StateKey = tuple[str, int]


def load_state(path: pathlib.Path | None, valid_keys: set[StateKey]) -> dict[StateKey, limiter.LimiterState]:
    """Loads saved limiter state, ignoring an unreadable file.

    Args:
        path: State file, or None when persistence is disabled.
        valid_keys: Keys still present in the config; others are dropped.

    Returns:
        Saved state for valid keys; empty if the file is missing or unreadable.
    """
    if path is None or not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text())
        state: dict[StateKey, limiter.LimiterState] = {}
        for key, value in raw.items():
            name, _, index = key.rpartition("/")
            if (name, int(index)) not in valid_keys:
                continue
            window_date, next_allowed = value["window_date"], value["next_allowed"]
            state[name, int(index)] = limiter.LimiterState(
                window_date=datetime.date.fromisoformat(window_date) if window_date else None,
                sent=int(value["sent"]),
                next_allowed=datetime.datetime.fromisoformat(next_allowed) if next_allowed else None,
            )
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        log.warning("ignoring unreadable state file %s: %r", path, exc)
        return {}
    return state


def save_state(path: pathlib.Path | None, state: dict[StateKey, limiter.LimiterState]) -> None:
    """Atomically writes limiter state.

    Args:
        path: State file, or None when persistence is disabled (no-op).
        state: State to save.

    Raises:
        OSError: The file cannot be written.
    """
    if path is None:
        return
    raw = {
        f"{name}/{index}": {
            "window_date": s.window_date.isoformat() if s.window_date else None,
            "sent": s.sent,
            "next_allowed": s.next_allowed.isoformat() if s.next_allowed else None,
        }
        for (name, index), s in state.items()
    }
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(raw, indent=2))
    os.replace(tmp, path)
