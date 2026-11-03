# service_uptime_kuma

Deploy **Uptime Kuma**: a docker-compose project, loopback-bound by default. The
same role can be used for several instances (different host, deploy directory
and data directory per instance) — for example two instances in different
failure domains that watch each other.

## Why two instances can matter

A common dead-man's switch has two halves:

- **Internal half**: a `Watchdog` alert in Prometheus/Alertmanager that fires
  **continuously**, routed to the normal notification path. Catches component
  failure while the site is alive.
- **External half**: Alertmanager also POSTs to an Uptime Kuma **push monitor**
  hosted **off** the monitored site (`service_alert_manager`'s
  `alertmanager_heartbeat_*` options). Kuma expects a push on a fixed interval;
  if the pushes **stop**, Kuma alerts. Because it lives off-site, it is the one
  thing that can report the site's own death.

That opens a symmetrical gap: **nothing reports the external host itself
dying.** Its silence looks identical to "nothing to report". A second Kuma
instance on the monitored site, with a monitor on the external instance, closes
it: either instance going dark is then visible **from the other side**.

| Instance     | Runs on                           | Watches                                          | Typical ingress                    |
| ------------ | --------------------------------- | ------------------------------------------------ | ---------------------------------- |
| **External** | a host outside the monitored site | the site (receives Alertmanager's Watchdog push) | Cloudflare Tunnel + Access         |
| **Site**     | a host inside the site            | the external instance                            | the site's reverse proxy, LAN-only |

Place the site instance in a different failure domain from the rest of the
monitoring stack where you can: if it shares one, it goes dark together with
Prometheus/Alertmanager. The mutual property still holds (the external instance
keeps watching the site), but you lose a second, independent detector of that
failure domain.

## What it does

- Renders a docker-compose file and converges Uptime Kuma
  (`community.docker.docker_compose_v2`).
- Image is **pinned** (`uptime_kuma_image`); tag `2` floats to the latest 2.x
  and is deliberately avoided. Never `latest`.
- Persists data to a **bind mount** (`uptime_kuma_data_dir`), visible and
  backuppable from the host.
- Runs on the Docker **bridge** network, publishing exactly one host port, so it
  cannot collide with a host-networked service on the same box.

It does **not** configure any monitor inside Kuma (Kuma manages its own state in
its database) and does **not** set Alertmanager's `alertmanager_heartbeat_url`.

## Security posture — READ THIS BEFORE CHANGING THE DEFAULTS

A freshly deployed Uptime Kuma has **no admin account** until a human completes
first-run setup in the browser. Between "container starts" and "someone claims
it," anyone who can reach the port can claim the instance as admin. On a public
host — especially one with no active host firewall, and remember a
Docker-published port bypasses the host firewall anyway — exposing a new port is
a real decision, not a default.

**Default posture: `uptime_kuma_bind_address: 127.0.0.1`,
`uptime_kuma_publish_publicly: false`.** The UI is reachable only from the host
itself. `uptime_kuma_bind_address` alone cannot publish the port —
`tasks/setup_vars.yml` forces loopback unless
`uptime_kuma_publish_publicly: true` is also set, so publishing is always one
explicit, auditable switch, never an accidental override.

Reaching a loopback-bound Kuma:

- **SSH tunnel** (no exposure): `ssh -L 3001:127.0.0.1:3001 <user>@<host>`, then
  browse `http://127.0.0.1:3001` locally. Best for the first-run claim and
  occasional dashboard checks.
- **A Cloudflare Tunnel on the same host** (`cloudflared` reaching Kuma over the
  host's own loopback, plain HTTP — that hop never leaves the host). Cloudflare
  terminates TLS at its edge, so the boundary-crossing hop is HTTPS, and an
  Access policy gates the UI. The bind stays loopback and no inbound port is
  opened. The tunnel, public hostname and Access policy are created in the
  Cloudflare dashboard, not by this role — and **confirm the Access policy is
  applied**: an unprotected tunnel is reachable from anywhere.
- **A reverse proxy** on the host or in front of it, with TLS and auth, then
  `uptime_kuma_publish_publicly: true` bound to a private address.

For Alertmanager's heartbeat POST through that same Access-protected hostname,
see `service_alert_manager`'s README, "Heartbeat transport" (Cloudflare Access
mTLS).

An instance inside a private network uses the same gate. A reverse proxy that
reaches backends over the host's own address (not loopback) has nothing to route
to until `uptime_kuma_publish_publicly: true` is set deliberately; complete the
first-run claim immediately after flipping it.

## What it does NOT do

- Does not create an admin account or any credential — first-run claim is a
  manual, one-time browser step on EACH instance.
- Does not configure any monitor inside Kuma — see the checklist below.
- Does not manage a cloud firewall in front of the host.

## Mutual monitoring setup — what a human configures, on each instance

**On the site instance:** an HTTP(s) monitor on the external instance's public
hostname. That hostname sits behind a Cloudflare Access policy, so a plain
monitor hits the Access login redirect, not Kuma — give the monitor the same
Access mTLS client cert/key the Alertmanager heartbeat uses (Kuma's HTTP(s)
monitor accepts a client certificate), or a narrower Service Auth policy on a
health path.

**On the external instance:** the push monitor Alertmanager posts its Watchdog
to, and a monitor on the site instance. The site instance is usually LAN-only,
so the external host needs a path in (a VPN, or a second tunnel exposing the
site instance) before that monitor can work.

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml) (generated from
`meta/argument_specs.py`). Key:

- `uptime_kuma_image` (str) — pinned tag.
- `uptime_kuma_host_port` (int, default `3001`).
- `uptime_kuma_bind_address` / `uptime_kuma_publish_publicly` — see Security
  posture above.
- `uptime_kuma_deploy_dir` / `uptime_kuma_data_dir` — set per instance when one
  host runs more than one.

## Usage

```yaml
# External instance
- hosts: external_watchdog
  roles:
    - role: richard_lynch.monitoring.service_uptime_kuma

# Site instance — same role, different directories
- hosts: monitoring
  roles:
    - role: richard_lynch.monitoring.service_uptime_kuma
      vars:
        uptime_kuma_deploy_dir: /opt/uptime-kuma-site
        uptime_kuma_data_dir: /opt/uptime-kuma-site/data
```

## Testing

`molecule/default/` runs in **check/parse mode**: it renders the compose file
from the role's own defaults and resolver and asserts the image tag is pinned,
the loopback bind is the default, the bridge network mode, and the data bind
mount. It does not converge against a real host.
