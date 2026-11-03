# service_node_exporter

Install **Prometheus node_exporter** on a host, either as a **Docker Compose
service** or as a **release binary under systemd**, so Prometheus can scrape the
host's hardware and OS metrics.

## What it does

`node_exporter_mode` selects one of three variants:

- **`docker`** — templates a compose file into
  `/opt/<node_exporter_container_name>` with
  `richard_lynch.common.deployment_config` and brings the `prom/node-exporter`
  container up with host networking and the host's `/proc`, `/sys` and `/`
  mounted read-only. The stack restarts when its rendered config changes.
- **`binary`** — downloads the node_exporter release for the host's architecture
  (`amd64`, `arm64` or `armv7`) into `/usr/local/bin`, writes a
  `node_exporter.service` systemd unit and restarts it. It then **scrapes
  `/metrics` on loopback** and fails the play unless the exporter answers: a
  unit started with a bad flag restarts cleanly and then exits, so a successful
  restart proves nothing.
- **`disabled`** (the default) — installs nothing and says so.

### Pin the version

In `binary` mode, `node_exporter_pinned_version` names the release to install.
Leaving it empty (or setting `latest`) asks the GitHub API for the newest
release at run time, so hosts provisioned on different days run different
releases — and an alert built on a collector added in a later release then
covers only part of the fleet. Pin it.

### Textfile collector

`node_exporter_textfile: true` (binary mode) creates
`node_exporter_textfile_dir` and starts the exporter with
`--collector.textfile.directory`, so it serves the `.prom` files the
`textfile_exporters` role writes. The post-start check also requires
`node_textfile_scrape_error` in the scrape, which is emitted only when the
collector is active — proof the flag was accepted, not merely that the process
is alive. Enabling it with nothing writing to the directory is harmless; the
`textfile_exporters` role without it writes metrics that are never scraped.

## Inputs

Defaults are in [`defaults/main.yml`](defaults/main.yml):

| Variable                       | Default                                     | Meaning                                                                                                                           |
| ------------------------------ | ------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `node_exporter_mode`           | `disabled`                                  | `docker`, `binary` or `disabled`.                                                                                                 |
| `node_exporter_container_name` | `node_exporter`                             | Container name, and the `/opt/<name>` directory the compose project lives in.                                                     |
| `node_exporter_image`          | `prom/node-exporter:latest`                 | Image for `docker` mode.                                                                                                          |
| `node_exporter_host_port`      | `9100`                                      | Port the binary-mode read-back scrapes and the compose file maps. The exporter listens on 9100 in both modes, so keep it at 9100. |
| `node_exporter_pinned_version` | `""`                                        | Release for `binary` mode, without the leading `v`. Empty or `latest` = newest now.                                               |
| `node_exporter_textfile`       | `false`                                     | Enable the textfile collector (`binary` mode).                                                                                    |
| `node_exporter_textfile_dir`   | `/var/lib/node_exporter/textfile_collector` | Directory the textfile collector reads.                                                                                           |

## Usage

```yaml
- hosts: all
  become: true
  roles:
    - role: richard_lynch.monitoring.service_node_exporter
      vars:
        node_exporter_mode: binary
        node_exporter_pinned_version: "1.9.1"
        node_exporter_textfile: true
```

Register the host with Prometheus from the same play with `config_metrics`.

## Testing

The role has no molecule scenario: both variants need a real host (a Docker
daemon, or systemd and network access to the release download), and the `binary`
variant carries its own read-back — the loopback scrape and the
textfile-collector assertion above — on every run.
