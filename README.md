# fi-notifications

fi-notifications is a small service. It checks your Fi collars at a fixed interval and sends an ntfy notification when something needs your attention, for example when a collar battery is below 40%.

## Quick Start

You need [uv](https://docs.astral.sh/uv/) (it installs Python 3.13 if needed), a Fi account, and an ntfy topic.

```bash
git clone https://github.com/edepree/fi-notifications.git && cd fi-notifications
cp config.example.yaml config.yaml   # then edit it
uv sync
uv run python -m fi_notifications --config config.yaml
```

Use `--log-level DEBUG` (or the `LOG_LEVEL` environment variable) to see more detail.

> [!TIP]
> To see what your collars report before you write a config, run the [probe script](#probing-the-fi-api).

## Configuration

[`config.example.yaml`](config.example.yaml) is a full, commented example. For every key, its default and its limits, see the models in [`config.py`](src/fi_notifications/config.py).

Any secret can be given inline (`password:`) or as a file (`password_file:`).

> [!NOTE]
> At startup, the service checks that every configured collar exists on your Fi account.
> If a name is wrong, it stops and lists the available names.

### Events

| Type | Fires when |
|---|---|
| `battery_low` | battery < `threshold` |
| `collar_offline` | no connection for more than `minutes` |
| `lost_mode` | lost dog mode is on |

With `suppress_when_charging`, `battery_low` stays quiet while the collar charges. "Charging" means the collar is on its base. On V1 collars, it means the collar reports `isCharging`.

### Windows and Rate Limits

The service drops notifications outside a target's `window`.

Without `max_per_window`, every matching poll sends a notification. With `max_per_window: N`, each
send splits the *remaining* window evenly between the remaining sends. Example with a
08:00–20:00 window and `N = 2`:

- Battery low from 08:00: notified at 08:00 and 14:00.
- Battery low first at 18:00: notified at 18:00 and 19:00.

The budget is per day. It is shared, even if the condition clears and then comes back.

> [!IMPORTANT]
> Windows cannot cross midnight. For example, `22:00`–`06:00` is not supported.

## Deployment

### Docker

A GitHub Actions workflow publishes the image to `ghcr.io/edepree/fi-notifications`. Each `v*` git tag builds a new image, tagged with the version (for example `1.2.0`) and `latest`.

```bash
docker run -v $PWD/config.yaml:/config/config.yaml:ro -p 8080:8080 ghcr.io/edepree/fi-notifications:latest
```

To build the image yourself, run `docker build -t fi-notifications .`.

The image runs as user `10001` and reads `/config/config.yaml` by default.

### Kubernetes

Example manifests are in [`deploy/k8s/`](deploy/k8s/): a ConfigMap, a Secret, a PVC for state, and a Deployment.

1. Put your Fi password and ntfy token in `deploy/k8s/secret.yaml`.
2. Edit the config in `deploy/k8s/configmap.yaml`.
3. Apply the manifests. The Deployment uses `ghcr.io/edepree/fi-notifications:latest`.


```bash
kubectl apply -f deploy/k8s/
```

> [!WARNING]
> Run exactly one replica. A second replica sends every notification twice.

### Health Check

`GET /healthz` returns `200` if a poll succeeded in the last 3 × `poll_interval`. Otherwise it returns `503`.

## Probing the Fi API

`scripts/probe.py` makes one login and one read-only query, then prints the response with secrets
removed. Use it to see what your collars report:

```bash
# creds file: line 1 is the email, line 2 is the password
uv run scripts/probe.py ~/.config/fi-notifications/creds
```

> [!NOTE]
> Fi has no public API. This project uses the same API as the Fi app, which can change without notice.

## Development

The code follows the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html). See [`pyproject.toml`](pyproject.toml) for the lint rules.

```bash
uv sync
uv run pytest && uv run ruff check && uv run ruff format --check && uv run ty check
```
