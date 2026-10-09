import base64

import httpx
import pytest

from fi_notifications import config
from fi_notifications import events
from fi_notifications import notify

MSG = events.Message(title="Zoë: battery 37%", body="low", priority="default", tags="battery")


def target(**kw: str) -> config.NtfyTarget:
    return config.NtfyTarget.model_validate({"type": "ntfy", "url": "https://ntfy.example.com/fi"} | kw)


async def send(t: config.NtfyTarget, response: httpx.Response | Exception) -> httpx.Request:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if isinstance(response, Exception):
            raise response
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        await notify.send_ntfy(http, t, MSG)
    return seen[0]


async def test_ntfy_bearer() -> None:
    req = await send(target(token="t"), httpx.Response(200))
    assert req.method == "POST"
    assert req.url.host == "ntfy.example.com"
    assert req.url.path == "/fi"
    assert req.headers["authorization"] == "Bearer t"
    assert req.url.params["title"] == "Zoë: battery 37%"  # Non-ASCII survives via the query string
    assert req.url.params["priority"] == "default"
    assert req.url.params["tags"] == "battery"
    assert req.content == b"low"


async def test_ntfy_basic() -> None:
    req = await send(target(username="u", password="p"), httpx.Response(200))
    assert req.headers["authorization"] == "Basic " + base64.b64encode(b"u:p").decode()


async def test_ntfy_no_auth() -> None:
    req = await send(target(), httpx.Response(200))
    assert "authorization" not in req.headers


async def test_ntfy_non_2xx_raises() -> None:
    with pytest.raises(notify.NotifyError, match="403"):
        await send(target(token="t"), httpx.Response(403))


async def test_ntfy_timeout_raises_notify_error() -> None:
    with pytest.raises(notify.NotifyError):
        await send(target(token="t"), httpx.ReadTimeout("slow"))
