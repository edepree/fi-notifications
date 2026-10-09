"""Entry point: poll Fi, evaluate subscriptions, notify."""

import argparse
import asyncio
import contextlib
import datetime
import logging
import os
import pathlib
import signal

import httpx
import pydantic

from fi_notifications import config
from fi_notifications import events
from fi_notifications import fi
from fi_notifications import health
from fi_notifications import limiter
from fi_notifications import notify
from fi_notifications import state as state_store

log = logging.getLogger("fi_notifications")

type States = dict[state_store.StateKey, limiter.LimiterState]


def check_collars(cfg: config.Config, names: set[str]) -> None:
    """Verifies every configured collar exists on the Fi account.

    Args:
        cfg: Service config.
        names: Names of all collared pets on the account.

    Raises:
        SystemExit: A configured collar is missing; the message lists available names.
    """
    missing = [c.name for c in cfg.collars if c.name not in names]
    if missing:
        available = ", ".join(sorted(names)) or "(none)"
        raise SystemExit(f"collars not found on Fi account: {', '.join(missing)}; available: {available}")


async def poll_once(
    cfg: config.Config,
    pets: list[fi.PetStatus],
    http: httpx.AsyncClient,
    states: States,
    now: datetime.datetime,
) -> States:
    """Evaluates every subscription against fetched pets and sends allowed notifications.

    Missing collars and failed sends are logged, not raised. State is saved after
    each successful send.

    Args:
        cfg: Service config.
        pets: Pet statuses from this poll.
        http: HTTP client for ntfy.
        states: Limiter state from the previous poll; not mutated.
        now: Current time in the configured timezone.

    Returns:
        Updated limiter state.
    """
    by_name = {p.name: p for p in pets}
    states = dict(states)
    for collar in cfg.collars:
        pet = by_name.get(collar.name)
        if pet is None:
            log.warning("collar %r not returned by Fi this poll", collar.name)
            continue
        for index, event in enumerate(collar.events):
            msg = events.evaluate(pet, event, now, cfg.timezone)
            if msg is None:
                continue
            key = (collar.name, index)
            target = cfg.targets[event.target]
            current = states.get(key, limiter.LimiterState())
            if not limiter.allowed(current, now, target.window, event.max_per_window):
                log.debug("%s/%s matched but limited", collar.name, event.type)
                continue
            try:
                await notify.send_ntfy(http, target, msg)
            except notify.NotifyError as exc:
                log.error("notify %s for %s failed: %s", event.target, collar.name, exc)
                continue
            log.info("sent %s for %s to %s", event.type, collar.name, event.target)
            states[key] = limiter.record(current, now, target.window, event.max_per_window)
            try:
                state_store.save_state(cfg.state_file, states)
            except OSError as exc:  # keep running on in-memory state rather than crash-loop
                log.error("cannot write state file %s: %s", cfg.state_file, exc)
    return states


async def run(cfg: config.Config) -> None:
    """Runs the poll loop until SIGTERM or SIGINT.

    Args:
        cfg: Service config.

    Raises:
        SystemExit: A configured collar is not on the Fi account.
    """
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    keys = {(c.name, i) for c in cfg.collars for i in range(len(c.events))}
    states = state_store.load_state(cfg.state_file, keys)
    monitor = health.Health(cfg.poll_interval)
    server = await health.serve_health(monitor, cfg.health_port)
    checked = False
    async with httpx.AsyncClient(timeout=30) as http:
        client = fi.FiClient(cfg.fi.email, cfg.fi.password.get_secret_value(), http)
        try:
            while not stop.is_set():
                try:
                    pets = await client.fetch_pets()
                except (fi.FiError, httpx.HTTPError, ValueError) as exc:
                    log.error("Fi poll failed: %s", exc)
                else:
                    if not checked:
                        check_collars(cfg, client.pet_names)
                        checked = True
                    states = await poll_once(cfg, pets, http, states, datetime.datetime.now(cfg.timezone))
                    monitor.mark_ok()
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(stop.wait(), cfg.poll_interval)
        finally:
            server.close()
            await server.wait_closed()
    log.info("stopped")


def main(argv: list[str] | None = None) -> None:
    """Parses arguments, loads the config, and runs the service.

    Args:
        argv: Command-line arguments; defaults to sys.argv.

    Raises:
        SystemExit: The config is missing or invalid.
    """
    parser = argparse.ArgumentParser(prog="fi_notifications", description=__doc__)
    parser.add_argument("--config", type=pathlib.Path, required=True)
    parser.add_argument("--log-level", default=os.environ.get("LOG_LEVEL", "INFO"))
    args = parser.parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        cfg = config.load_config(args.config)
    except (OSError, ValueError, pydantic.ValidationError) as exc:
        raise SystemExit(f"invalid config {args.config}: {exc}") from None
    asyncio.run(run(cfg))


if __name__ == "__main__":
    main()
