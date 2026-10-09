"""ntfy publisher."""

import httpx

from fi_notifications import config
from fi_notifications import events


class NotifyError(Exception):
    """Publishing to ntfy failed."""


async def send_ntfy(client: httpx.AsyncClient, target: config.NtfyTarget, msg: events.Message) -> None:
    """Publishes a message to an ntfy topic.

    Args:
        client: HTTP client to use.
        target: Topic URL and credentials.
        msg: Message to publish.

    Raises:
        NotifyError: The request failed, timed out, or returned a non-2xx status.
    """
    headers = {"Authorization": f"Bearer {target.token.get_secret_value()}"} if target.token else {}
    basic = target.username is not None and target.password is not None
    auth = httpx.BasicAuth(target.username, target.password.get_secret_value()) if basic else None
    try:
        resp = await client.post(
            str(target.url),
            # query params rather than headers so non-ASCII titles survive
            params={"title": msg.title, "priority": msg.priority, "tags": msg.tags},
            content=msg.body.encode(),
            headers=headers,
            auth=auth or httpx.USE_CLIENT_DEFAULT,
            timeout=10,
        )
    except httpx.HTTPError as exc:
        raise NotifyError(f"ntfy request failed: {exc!r}") from exc
    if resp.is_error:
        raise NotifyError(f"ntfy returned HTTP {resp.status_code}")
