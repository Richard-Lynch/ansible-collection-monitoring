# service_prometheus

Deploy **Prometheus** as a docker-compose service on the shared `monitoring` network, alongside the
other service roles in this collection.

## What it does

- Templates the compose + config into `/opt/prometheus`, ensures the shared external docker network
  (`monitoring`) exists, and brings the container up.
- **Retention-capped** (`--storage.tsdb.retention.time` + `.size`) — bounds the TSDB by both time and
  size so it can never fill the disk (unbounded TSDB growth is the classic way a monitoring host dies).
- Enables the **remote-write receiver** (`--web.enable-remote-write-receiver`) — an HA seam so another
  Prometheus / Alloy can remote-write into this instance later.
- Scrapes via **file-SD** (`/etc/prometheus/file_sd/*.yml`, 30s refresh) so targets are dynamic,
  plus per-owner scrape jobs from `/etc/prometheus/scrape_jobs/*.yml` (both written by
  `config_metrics`).
- Wires **Alertmanager** and loads rule files from `/etc/prometheus/rules/*.yml` (written by
  `config_alerts`) while `prometheus_alertmanager_enabled` is true (the default).

## Wiring (shared network)

Prometheus joins the external `monitoring` network; other services reach it by container name
(`http://prometheus:9090`). Grafana's datasource, Alertmanager, etc. use that name — no host IPs.

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml):
- `prometheus_image_version` (default `latest`), `prometheus_host_port` (default `9090`)
- `prometheus_retention_time` (default `30d`), `prometheus_retention_size` (default `20GB`)
- `prometheus_network` (default `monitoring`)
- `prometheus_alertmanager_enabled` (default `true`), `prometheus_alertmanager_target` (default
  `alertmanager:9093`)

## Usage

```yaml
- hosts: monitoring
  roles:
    - role: richard_lynch.monitoring.service_prometheus
      vars:
        prometheus_retention_size: 20GB
```

## Testing

`molecule/default/` renders the compose from sample vars and asserts the retention caps + remote-write
receiver + shared-network wiring are present (offline; no live Prometheus).
