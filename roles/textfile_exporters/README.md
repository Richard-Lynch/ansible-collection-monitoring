# textfile_exporters

Installs Prometheus **textfile-collector** exporters and their systemd timers.

Several exporters share this role because they share all the plumbing —
collector directory, timer pattern, atomic-write contract — and differ only in
the script and which hosts want them.

| Variable            | Default                                     | What it installs                       | Where it belongs                                           |
| ------------------- | ------------------------------------------- | -------------------------------------- | ---------------------------------------------------------- |
| `txe_gpu`           | `false`                                     | Intel GPU telemetry from sysfs         | the host physically holding the GPU                        |
| `txe_docker`        | `false`                                     | Container health from `docker inspect` | any docker host                                            |
| `txe_wan_ip`        | `false`                                     | The site's public egress IP            | ONE host behind the uplink; it is a property of the uplink |
| `txe_wireguard`     | `false`                                     | WireGuard tunnel state                 | the MONITORED end of a site link, never the far end        |
| `txe_ha_recorder`   | `false`                                     | How stale Home Assistant's recorder is | a monitoring host — **never** the HAOS box (see below)     |
| `txe_collector_dir` | `/var/lib/node_exporter/textfile_collector` | —                                      | must match the scraper's configured path                   |
| `txe_interval`      | `30s`                                       | timer period                           | shorter than the scrape interval                           |
| `txe_apply`         | `false`                                     | report-only unless `true`              | generate, don't apply                                      |

Per-exporter options: `txe_wan_ip_expected`, `txe_wireguard_interface`,
`txe_ha_recorder_base_url` (required with `txe_ha_recorder`),
`txe_ha_recorder_token_file`, `txe_ha_recorder_window_seconds`. See
`meta/argument_specs.py` — edit the Python, then regenerate; the `.yml` and
`defaults/` are generated and hand edits are overwritten.

```yaml
- hosts: docker_hosts
  become: true
  roles:
    - role: richard_lynch.monitoring.textfile_exporters
      vars:
        txe_docker: true
        txe_apply: true
```

## Why the docker health exporter exists at all

Alloy's vendored cAdvisor **already** exports `container_health_state`, so this
looks redundant. It is not.

Inside a Proxmox LXC guest, cAdvisor cannot resolve a cgroup to a container
(EPERM reading Docker's `layerdb`), so it **discards every real container** and
emits only LXC-level cgroups. The result is worse than missing data: the metric
_exists_, carries no `name` label, and reads `0` for everything — including for
a container that has been unhealthy for hours:

```
max_over_time(container_health_state{name="<container>"}[24h])  =  0
```

An alert built on that metric would look correct, pass review, and **never fire
once**: a silent guard. `docker inspect` reads the same state cAdvisor cannot
reach and works fine in the guest, so this reads it directly and exports it
under a **distinct** metric name — two metrics with the same name and different
semantics would be its own trap.

## Metrics

| Metric                                                                                                            | Meaning                                                                                            |
| ----------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| `docker_container_health`                                                                                         | `1` healthy, `0` unhealthy, `2` starting. **Absent = no healthcheck defined, NOT healthy.**        |
| `docker_container_health_failing_streak`                                                                          | consecutive failed checks                                                                          |
| `docker_container_running`                                                                                        | `1` if running                                                                                     |
| `docker_health_exporter_up`                                                                                       | `0` if `docker ps` failed — distinguishes "docker down" from "never ran"                           |
| `intel_gpu_info`                                                                                                  | one per GPU, labelled `pci` / `driver` / `device_id`                                               |
| `intel_gpu_freq_mhz`                                                                                              | `kind=act` is the **load signal**; `kind=cur` is **not** (see the script header)                   |
| `intel_gpu_fan_rpm`, `intel_gpu_power_limit_watts`                                                                | as sysfs reports them                                                                              |
| `intel_gpu_temp_celsius`, `intel_gpu_vram_bytes`                                                                  | emitted **only where the driver exposes them** — `xe` does not, for some cards                     |
| `estate_wan_egress_ip_info`, `_lookup_success`, `_matches_expected`                                               | the egress IP as a label, whether it could be learned, and whether it equals `txe_wan_ip_expected` |
| `wireguard_up`, `wireguard_peers`, `wireguard_latest_handshake_seconds`, `wireguard_transfer_{rx,tx}_bytes_total` | tunnel liveness by handshake age, with RX and TX apart                                             |
| `ha_recorder_probe_success`                                                                                       | `1` if HA's logbook API could be read and parsed this run                                          |
| `ha_recorder_staleness_seconds`                                                                                   | age of the newest persisted row — **the alertable number.** Absent on a failed probe, deliberately |
| `ha_recorder_newest_row_timestamp_seconds`                                                                        | unix ts of that row. Absent rather than `0`, which would read as epoch 1970                        |
| `ha_recorder_rows_in_window`                                                                                      | rows returned — distinguishes a quiet home from a dead recorder                                    |

Health is tristate and most containers have no healthcheck. Exporting those as
`0` would make "not monitored" indistinguishable from "healthy", so they get no
health series at all — only `_running`.

## Two traps worth knowing

**One `HELP` line per metric.** The Prometheus text format permits exactly one;
a second is a hard parse error that makes node_exporter reject the **entire
file** — valid samples on disk, every series gone, `node_textfile_scrape_error`
quietly at 1. The role gates on duplicate HELP/TYPE _and_ on node_exporter's own
verdict.

**Two different scrapers.** A standalone `node_exporter` (e.g. on a hypervisor)
and Alloy (on guests) each need their textfile collector switched on, and the
switch is different in each:

- Alloy → `richard_lynch.monitoring.service_alloy`
  (`enable_collectors = ["…", "textfile"]`)
- node_exporter → `richard_lynch.monitoring.service_node_exporter`
  (`node_exporter_textfile: true`)

Installing this role without the matching switch means metrics are written every
30s and read by nobody.

## Rollback

```bash
systemctl disable --now intel-gpu-metrics.timer      # or docker-health-metrics.timer
rm /etc/systemd/system/intel-gpu-metrics.{service,timer}
rm /usr/local/bin/intel-gpu-metrics.sh /var/lib/node_exporter/textfile_collector/intel_gpu.prom
systemctl daemon-reload
```

## Why the HA recorder exporter exists, and why it does not run on Home Assistant

Home Assistant's recorder can stop persisting history while HA itself stays
completely healthy, and nothing else reports it:

- HA's prometheus integration exports entity states, and there is no recorder
  metric among them, so a Prometheus target can be up and scraped cleanly
  throughout.
- Writes are accepted and dropped: `logbook.log` returns **HTTP 200** either
  way.
- A history **read** of a dead recorder returns a well-formed 200 carrying _old_
  rows — not an error, not an empty list. So a caller sees "nothing recorded
  yet", never "the database is not accepting writes".
- Disk gives no hint.

So the question has to be **asked of the history API** and turned into a metric.

**It runs on a monitoring host, not on the HAOS box.** Same reasoning as the
WireGuard exporter living on the monitored end of a site link: an exporter must
not depend on the thing it watches. On HA, a dead HA would emit no metric at all
and absence is indistinguishable from a dead exporter. From a monitoring host it
reports a **failed probe** instead, which is a different and more useful alert.

### The window is short on purpose

`/api/logbook/<since>` returns only **~24 hours from `since`** and caps the
response silently — so the newest row returned tracks the **start** of the
window, not now. With a 10-day window the newest row returned is about nine days
old however healthy the recorder is. A long `txe_ha_recorder_window_seconds`
therefore reports a perfectly healthy recorder as days stale, so the default is
**3600** and raising it is almost certainly a mistake.

### Four series, not one

`probe_success` is separate from `staleness_seconds` deliberately. If a failed
probe reported "stale", an unreachable HA and a dead recorder would look
identical and the alert would fire for the wrong reason. On a failed probe the
exporter emits **no** staleness value at all, because a stale `0` reads as
"perfectly fresh" for as long as Prometheus retains it.

Alert rules belong with the thing being watched (`config_alerts`, from the play
that deploys Home Assistant), not in this role.

## Tests

`molecule/default` runs the real exporter scripts against sysfs-shaped fixtures
and stubbed `docker`, `curl`/`wget` and `wg`, and asserts each script's output
contract: one HELP/TYPE per metric, the tristate health mapping, the WAN lookup
and mismatch cases, and handshake ages.
