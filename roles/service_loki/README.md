# service_loki

Deploy **Loki** (log store) as a docker-compose service on the shared `monitoring` network,
alongside the other service roles in this collection.

## What it does

- Templates the compose + Loki config into `/opt/loki`, ensures the shared external `monitoring`
  network + the data volume (with `chunks/index/wal/compactor/rules` subdirs), and brings Loki up.
- **tsdb** index store (schema v13), filesystem storage.
- **Bounded retention**: `retention_period` (default `768h`/32d) enforced by the **compactor**
  (`retention_enabled: true`) — so the log store actually deletes old chunks and can't fill the disk.
- Reachable by container name on the shared network (`http://loki:3100`), e.g. from Alloy / Grafana.

## Log-based alerting (the ruler)

This role provisions Loki's **ruler**, which is what makes LogQL alert rules possible. It is the
**mechanism only** — it ships no alert rule, exactly as `service_prometheus` ships none. Rules are
owned by the play that deploys the thing being alerted on and installed per-owner by
[`config_log_alerts`](../config_log_alerts/README.md).

### Why it is enabled by default

With no `ruler:` stanza, `/loki/api/v1/rules` answers:

```
HTTP 400  unable to read rule dir /loki/rules/fake: open /loki/rules/fake: no such file or directory
```

Nothing can alert on a log signal, while every log stream keeps arriving and Grafana renders them
perfectly — so the logs *look* fully monitored. Off is therefore not a safe default; it is a silent
guard.

### What the role guarantees

- **The tenant rule directory exists before Loki starts**, owned by **uid 10001** (the uid
  `grafana/loki` runs as). Both halves matter: with the directory absent the ruler answers HTTP 400
  forever, and a root-owned directory the ruler cannot list presents as *"no rules loaded"* rather
  than as a permissions error.
- **A hard gate on the directory** before the stack comes up, and **a hard gate on the ruler
  actually serving** after it. A `200`/`404` from the rules API is the pass (404 = "serving, no
  rules installed yet", which is correct after this role runs alone); `400` is the failure.
- **A hard gate that the ruler's scratch path (`rule_path`) is not its rules source**: Loki cleans
  `rule_path` on startup, so conflating the two deletes the installed rules at every restart.

### Two traps the volume handling avoids

1. **Compose prefixes an unnamed volume.** `docker-compose.yml` declares `volumes: {loki: }` with no
   `name:`, so compose creates **`loki_loki`**. A `docker_volume: name=loki` task would create an
   unprefixed **`loki`** the container never mounts, and every "ensure the directories exist" run
   would go into that orphan. The role derives the real name (`loki__compose_volume`) and reads the
   rule directory back from it.
2. **No brace expansion.** `mkdir -p /loki/{chunks,index,...}` runs in `alpine`'s BusyBox `sh`,
   which does not perform brace expansion, and would create one directory named literally
   `{chunks,index,...}`. The directory list is built as data and joined, needing no shell feature.

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml):
- `loki_image_version` (default `3.5.5`), `loki_host_port` (default `3100`)
- `loki__index_store` (default `tsdb`), `loki__retention_period` (default `768h`)
- `loki_network` (default `monitoring`)
- `loki_ruler_enabled` (default `true`), `loki_ruler_alertmanager_url`
  (default `http://alertmanager:9093` — the container name, resolved on the shared network),
  `loki_ruler_tenant` (default `fake` — Loki's hardcoded single-tenant id, **not** a placeholder),
  `loki_ruler_evaluation_interval` (default `1m`), `loki_ruler_enable_api` (default `true`)

## Usage

```yaml
- hosts: monitoring
  roles:
    - role: richard_lynch.monitoring.service_loki
```

## Testing

`molecule/default/` renders the compose + config from sample vars and asserts the `grafana/loki` image,
tsdb store, retention period, compactor-with-retention, and shared-network wiring (offline).
