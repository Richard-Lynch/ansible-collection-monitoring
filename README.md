<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# richard_lynch.monitoring

Observability roles: Prometheus, Alertmanager, Loki, Grafana, Alloy, node_exporter, Uptime Kuma, Apprise and a Homepage dashboard as Docker Compose services; plus the cross-cutting roles that give any host or service its metrics, logs, alert rules, log alert rules, textfile exporters and notification targets.

## Modules

| Module | Description |
| ------ | ----------- |
| `alertmanager_silence` | One Alertmanager silence as desired state (identity = comment + matchers; honest `changed`, `--check`, `--diff`) |
| `alertmanager_silence_info` | List Alertmanager silences, normalized, filtered by state and comment |

Both take `richard_lynch.common`'s connection options (`url`, optional `token`, `validate_certs`,
`ca_path`, `timeout`); the resource model is `docs/resources/alertmanager_silence.md`.

## Roles

| Role | Description |
| ---- | ----------- |
| `apprise_notify_config` | Configure an Apprise config-id with HA / email / Slack targets |
| `config_alerts` | Install one owner's Prometheus alert rules into the shared rules directory |
| `config_log_alerts` | Install one owner's Loki LogQL alert rules into the ruler's tenant directory |
| `config_log_backfill` | Backfill historical log files into Loki at their original timestamps |
| `config_logs` | Register one owner's custom log sources as an Alloy drop-in config file |
| `config_metrics` | Register one owner's Prometheus scrape targets via file-based service discovery |
| `service_alert_manager` | Deploy Prometheus Alertmanager routing to Apprise, with an external heartbeat |
| `service_alloy` | Installs Grafana Alloy |
| `service_apprise` | Deploy the Apprise notification API, optionally behind Traefik |
| `service_grafana` | Deploy Grafana (Postgres backend, provisioned datasources) on a shared net |
| `service_homepage` | Deploy gethomepage/homepage as a validated links-and-widgets dashboard |
| `service_loki` | Deploys Loki (tsdb, retention-compacted) on the shared monitoring network |
| `service_node_exporter` | Install Prometheus node_exporter as a Docker Compose service or as a pinned release binary under systemd, optionally with the textfile collector; binary mode confirms the exporter serves metrics. |
| `service_prometheus` | Deploys Prometheus (retention-capped) on the shared monitoring network |
| `service_uptime_kuma` | Deploy Uptime Kuma, loopback-bound by default (dead-man heartbeat receiver) |
| `textfile_exporters` | Prometheus textfile exporters: GPU, Docker, WAN IP, WireGuard, HA recorder |

## Install

```sh
ansible-galaxy collection install richard_lynch.monitoring
```

or pin it in `requirements.yml`:

```yaml
collections:
  - name: richard_lynch.monitoring
    version: "1.0.5"
```

Requires ansible-core >=2.19.0.

## Development

```sh
# from a checkout at ansible_collections/richard_lynch/monitoring
ansible-test sanity --docker
ansible-test units --docker
ansible-galaxy collection build
devkit conform                  # the repository standard (ansible-devkit)
devkit check all                # the static checks, configured by devkit.toml
```

CI, the disclosure gate and releases are the shared workflows of
[ansible-devkit](https://github.com/Richard-Lynch/ansible-devkit), called from
`.github/workflows/` at tag `v0.4.1`. A release is a merged pull
request that bumps `version` in `galaxy.yml` and adds the matching
`CHANGELOG.md` section. `export.manifest` lists every tracked path; update it in
the same commit as any file added or removed.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).
