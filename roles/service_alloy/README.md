# service_alloy

Install **Grafana Alloy** as a host agent (Debian package + systemd) that ships this host's **metrics
and logs** to Prometheus (`remote_write`) and Loki (`loki.write`). On an image-based (ostree) host
it installs the verified upstream release binary instead of a package.

## What it does

- Installs Alloy via the Grafana apt repo (`install_apt.yml`) or, on ostree hosts, the
  checksum-verified release binary (`install_binary.yml`); templates a modular config into
  `/etc/alloy/config.alloy.d/` (`config.yml`), and manages the systemd unit (`systemd.yml`).
- Modular collectors: system (unix-exporter) + docker **metrics** and Alloy self-metrics — each a
  small `.alloy` fragment. Log SOURCES are owned by `config_logs`; this role owns the agent and
  the sinks.
- **Targets** (`targets.alloy.j2`): remote-writes to `{{ alloy_config.prometheus_url }}/api/v1/write`
  and pushes logs to `{{ alloy_config.loki_url }}/loki/api/v1/push`, stamping external labels
  (platform, hostname, os, arch, version; parent hostname for VMs).

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml). Required:
- `alloy_cli_args` — Alloy CLI flags (e.g. the HTTP listen addr).
- `alloy_config` — dict with `loki_url`, `prometheus_url`, `platform` (real/vm/docker), optional
  `parent_hostname`, and per-collector scrape/storage tunables.

On the monitoring host Alloy runs as a host binary, so the URLs point at the host-published ports
(`http://localhost:3100` / `:9090`). Other hosts use the monitoring host's address or a proxy URL.

`alloy_version` (optional, an apt version such as `1.19.2-1`, or `latest`) pins the package and
selects the release binary; a binary install needs its SHA-256 listed in `vars/main.yml`.

## Usage

```yaml
- hosts: all
  become: true
  roles:
    - role: richard_lynch.monitoring.service_alloy
      vars:
        alloy_cli_args: ["--server.http.listen-addr=0.0.0.0:12345"]
        alloy_config:
          loki_url: http://monitoring.example.test:3100
          prometheus_url: http://monitoring.example.test:9090
          platform: vm
```

## Testing

`molecule/default/` renders `targets.alloy.j2` from sample vars and asserts the Loki push + Prometheus
remote-write URLs and external labels are correct (offline; no Alloy install).
