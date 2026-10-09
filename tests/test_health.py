import asyncio

from fi_notifications import health


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_healthy_initially() -> None:
    assert health.Health(60, Clock()).healthy() is True


def test_unhealthy_after_3x() -> None:
    clock = Clock()
    monitor = health.Health(60, clock)
    clock.now += 180
    assert monitor.healthy() is True
    clock.now += 1
    assert monitor.healthy() is False


def test_mark_ok_recovers() -> None:
    clock = Clock()
    monitor = health.Health(60, clock)
    clock.now += 500
    monitor.mark_ok()
    assert monitor.healthy() is True


async def get(port: int, path: str) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(f"GET {path} HTTP/1.1\r\nHost: x\r\n\r\n".encode())
    await writer.drain()
    data = await reader.read()
    writer.close()
    return data.split(b"\r\n", 1)[0]


async def test_http_200_503_404() -> None:
    clock = Clock()
    monitor = health.Health(60, clock)
    server = await health.serve_health(monitor, 0, host="127.0.0.1")
    port = server.sockets[0].getsockname()[1]
    try:
        assert await get(port, "/healthz") == b"HTTP/1.1 200 OK"
        clock.now += 1000
        assert await get(port, "/healthz") == b"HTTP/1.1 503 Service Unavailable"
        assert await get(port, "/x") == b"HTTP/1.1 404 Not Found"
    finally:
        server.close()
        await server.wait_closed()
