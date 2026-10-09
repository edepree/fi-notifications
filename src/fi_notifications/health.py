"""Minimal /healthz endpoint on stdlib asyncio."""

import asyncio
from collections.abc import Callable
import time


class Health:
    """Tracks whether polling is keeping up.

    Args:
        poll_interval: Seconds between polls; unhealthy after 3x without success.
        clock: Monotonic clock, injectable for tests.
    """

    def __init__(self, poll_interval: int, clock: Callable[[], float] = time.monotonic) -> None:
        self._limit = 3 * poll_interval
        self._clock = clock
        self._last_ok = clock()

    def mark_ok(self) -> None:
        """Records a successful poll."""
        self._last_ok = self._clock()

    def healthy(self) -> bool:
        """Returns whether a poll succeeded (or startup happened) within 3x the interval."""
        return self._clock() - self._last_ok <= self._limit


async def serve_health(
    health: Health,
    port: int,
    host: str = "0.0.0.0",  # noqa: S104 - must be reachable by Kubernetes probes
) -> asyncio.Server:
    """Starts the /healthz server: 200 when healthy, 503 when not, 404 for other paths.

    Args:
        health: Health tracker to report.
        port: TCP port; 0 picks a free one.
        host: Interface to bind.

    Returns:
        The running server; the caller closes it.
    """

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            parts = (await asyncio.wait_for(reader.readline(), 5)).split()
            if len(parts) >= 2 and parts[1] == b"/healthz":
                status = "200 OK" if health.healthy() else "503 Service Unavailable"
            else:
                status = "404 Not Found"
            body = status.encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: text/plain\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except (TimeoutError, ConnectionError):
            pass
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port)
