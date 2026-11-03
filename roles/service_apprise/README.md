# service_apprise

Deploy the **Apprise notification API** (`caronc/apprise`) — the notification hub the monitoring
stack (Alertmanager, via `service_alert_manager`) fans out through.

## What it does

- Templates the compose into `/opt/apprise` and brings the Apprise API up.
- Joins the shared `monitoring` network, so Alertmanager reaches
  `http://apprise-api:8000/notify/<config-id>` by name.
- Optionally joins the `traefik` network and carries Traefik labels for HTTPS exposure at
  `apprise_traefik_host` (`apprise_traefik_enabled`, off by default; only on a host running Traefik).
- **Stateful `simple` mode** — notification configs are stored on disk keyed by a config-id (URL slug),
  so clients POST to `/notify/<config-id>`.

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml). Key ones:
- `apprise_image` (pinned), `apprise_stateful_mode` (default `simple`).
- `apprise_network` (default `monitoring`), `apprise_traefik_enabled` (default `false`),
  `apprise_traefik_network` (default `traefik`), `apprise_traefik_host` (no default; required when
  Traefik exposure is enabled).
- `apprise_bind_address` (default empty = every interface). apprise-api is unauthenticated and can
  send mail as the configured account, so on an internet-facing host set it to a private/tunnel
  address; a Docker-published port bypasses the host firewall.

## Configuring notification targets

After deploy, add a config (email, Home Assistant, chat, ...) under a config-id — via the Apprise UI,
`POST /add/<config-id>`, or the `apprise_notify_config` role. Alertmanager then posts to
`/notify/<config-id>`.

## Usage

```yaml
- hosts: monitoring
  roles:
    - role: richard_lynch.monitoring.service_apprise
```

## Testing

`molecule/default/` renders the compose and asserts the pinned image, the monitoring network,
stateful mode and the published port, and that `apprise_bind_address` publishes on that address
only (offline).
