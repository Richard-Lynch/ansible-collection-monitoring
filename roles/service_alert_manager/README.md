# service_alert_manager

Deploy **Prometheus Alertmanager** routing to **Apprise**. Prometheus (and the
Loki ruler) evaluate rules → fire to Alertmanager → Alertmanager renders the
notification → Apprise fans it out to its targets (email, Home Assistant, chat,
...).

## What it does

- Deploys Alertmanager (compose) on the shared `monitoring` network.
- Config routes all alerts to a single **webhook receiver** → Apprise
  `http://apprise-api:8000/notify/<config-id>`, which fans out to its targets.
- **Alertmanager renders the notification itself** (`webhook_config.payload`,
  Alertmanager >= 0.32) from
  [`files/config/notification.tmpl`](files/config/notification.tmpl):
  - subject: `🔴 FIRING · WARNING · <alertname> — <service> on <host>` /
    `✅ RESOLVED · ...`
  - body, per alert (firing first): severity, affected service/host, summary,
    started/resolved, source (Prometheus or Loki ruler), identifying labels, and
    the rule's description, then an optional footer line
    (`alertmanager_notification_footer`).
  - "affected" reads `service_name` > `service` > `job`, then `hostname` >
    `instance`. A rule with none of these still renders — its labels are listed
    — but give new rules `severity` and an identifying label, and put the
    specific detail (`$labels`, `$value`) in `summary`. Apprise's own payload
    remapper can copy only one field into each of title/body, so the subject
    would be the bare word "firing" and the body would never name the affected
    service.
- Pre-flight: before (re)starting, the target image runs `amtool check-config`
  and renders each template against amtool's sample alerts; after, a gate reads
  `/api/v2/status` and asserts the RUNNING version and the loaded payload.
- The config **directory** is bind-mounted (not the file), so `/-/reload` sees
  an edited config (`/-/reload`, needs `--web.enable-lifecycle`).
- Does **NOT** install Prometheus alert rules. Rules are owned by whatever
  deploys the thing being alerted on, via `config_alerts`; a second copy here
  would silently overwrite them.

## Heartbeat transport — Cloudflare Access mTLS (and why not a service-token header)

The optional external heartbeat target (for example an Uptime Kuma push monitor
in another failure domain) can be reached through a Cloudflare Tunnel with an
Access policy protecting it. A browser passes that policy with an identity
login; Alertmanager is not a browser and needs a different authentication
mechanism to get past the same policy.

**Options considered:**

1. **Cloudflare Access service token** (`CF-Access-Client-Id` /
   `CF-Access-Client-Secret` headers) — the mechanism Cloudflare documents first
   for automated clients. **Not used**: Alertmanager's webhook `http_config`
   carries `basic_auth`, `authorization` (a single bearer/custom-scheme token),
   `oauth2` and `tls_config`. A service token needs **two** simultaneous
   headers; neither `authorization` nor `basic_auth` alone can carry both.
   Wiring it would need a translating sidecar this role does not build.
2. **Cloudflare Access mTLS — used.** Cloudflare recommends mTLS for clients
   that cannot send custom headers. It maps directly onto `tls_config.cert_file`
   / `key_file`. Same tunnel, same hostname, same Access application as the UI —
   one path, not two, and HTTPS by construction. This is what
   `alertmanager_heartbeat_mtls_*` wires up below.
3. **A VPN tunnel to the heartbeat host**, with the monitor's port bound on the
   tunnel interface. A reasonable choice, but a second transport to build, run
   and patch to carry one POST a minute.
4. **A static-IP firewall allowlist** on the heartbeat host. Simplest (no
   changes to this role: leave `alertmanager_heartbeat_mtls_enabled: false`),
   but weakest: it authenticates a network path, not a credential, and breaks
   silently if the source IP changes.

**Cloudflare steps to enable mTLS (before setting
`alertmanager_heartbeat_mtls_enabled: true`):**

1. Generate a client certificate + key (a private CA is fine — Cloudflare
   validates against a CA you upload).
   `openssl req -x509 -newkey rsa:2048 -keyout client.key -out client.crt -days 825 -nodes -subj "/CN=alertmanager-heartbeat"`
   is enough for a self-signed pair.
2. Zero Trust dashboard → Settings → Service credentials → **Mutual TLS
   Authentication** → upload the CA that signed the client cert, and associate
   it with the monitor's public hostname (e.g. `uptime.example.com`).
3. Zero Trust → Access → Applications → the monitor's application → add a policy
   with Action = **Service Auth**, rule = **Valid Certificate** (or **Common
   Name** to pin this exact cert), scoped to the push path (e.g. `/api/push/*`)
   if the rest of the UI should still require a login.
4. Keep the cert AND key in your secret store and pass them as
   `alertmanager_heartbeat_mtls_cert` / `alertmanager_heartbeat_mtls_key`.
5. Set `alertmanager_heartbeat_mtls_enabled: true`,
   `alertmanager_heartbeat_enabled: true`, and `alertmanager_heartbeat_url` to
   the `https://` push URL. The role refuses to render anything if the URL isn't
   `https://` or if mTLS is enabled without both cert and key.

The client cert/key are written host-side to
`{{ alertmanager_config_dir }}/tls/` at mode `0600` and bind-mounted read-only
into the container; the writing task is `no_log`'d.

## Wiring Prometheus

Prometheus must be deployed with `prometheus_alertmanager_enabled: true` (role
`service_prometheus`) so its config gains the `alerting:` block and
`rule_files: /etc/prometheus/rules/*.yml`. Run `service_prometheus` before this
role in the same play.

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml) (generated from
`meta/argument_specs.py`). Key: `alertmanager_apprise_config_id` (the Apprise
stateful config-id holding your notification targets — create it in Apprise
first, e.g. with `apprise_notify_config`), `alertmanager_heartbeat_url` (must be
`https://` when the heartbeat is enabled), `alertmanager_heartbeat_mtls_enabled`
/ `_cert` / `_key` (see "Heartbeat transport" above),
`alertmanager_notification_footer`.

### Running it on an internet-facing host (`alertmanager_bind_address`, `alertmanager_inhibit_rules`)

Alertmanager has no authentication, and a Docker-published port bypasses the
host firewall. On a public host set `alertmanager_bind_address` to a
private/tunnel address so the port is published there and nowhere else (empty,
the default, publishes on every interface — fine on a firewalled private host).
`alertmanager_inhibit_rules` is rendered verbatim as `inhibit_rules`, e.g. to
hold back every per-service alert while a "whole site unreachable" alert is
firing. Inhibited alerts are deferred, not lost: they notify normally once the
source resolves if they are still firing. Both are covered by the molecule
scenario, including the near-miss (a bound render must not also publish the bare
port).

### Alerts that must arrive but never notify (`alertmanager_discard_routes`)

Each entry (`matchers`, ANDed, plus a `reason`) becomes a child route, ahead of
the catch-all, to a `discard` receiver with no integrations. A matching alert is
still held by Alertmanager and listed by `GET /api/v2/alerts`, so a play that
proves delivery by reading that endpoint keeps working; it just notifies nobody
— useful for alerts that exist only to prove a rule can fire. Alertmanager
anchors regex matchers, so `.+FiringProof` does not catch the real rule a proof
is named after; the molecule scenario asserts both directions.

## Usage

```yaml
- hosts: monitoring
  vars:
    prometheus_alertmanager_enabled: true
  roles:
    - role: richard_lynch.monitoring.service_prometheus
    - role: richard_lynch.monitoring.service_alert_manager
```

## Testing

`molecule/default/` renders the Alertmanager config and the footer template,
parses the config as YAML, and asserts the Apprise webhook carries the templated
payload (no remap query), that `notification.tmpl` defines every template it
calls, the inhibit/discard/bind-address shapes, and the heartbeat receiver's
HTTPS URL + mTLS `tls_config` (offline; no real cert/key or tunnel needed — the
scenario writes fixed in-container file paths only, it never provisions
credentials).
