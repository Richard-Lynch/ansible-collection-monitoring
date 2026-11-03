# config_metrics

Register **one owner's** Prometheus scrape targets via file-based service discovery.

This role is a **mechanism**. It owns no scrape target. Targets belong to the play that deploys the
thing being scraped, so an application's exporters are registered by that application's play and
stop being scraped when that play retires them.

Sibling of [`config_alerts`](../config_alerts/README.md) (alert rules) and
[`config_logs`](../config_logs/README.md) (log shipping). Same shape, three different destinations.

## Why it exists

A central scrape-target list kept in two places — a role's `vars/` and a play's vars — has to be
kept in sync by hand, and role `vars/` outranks play vars in Ansible's precedence, so a target
added only to the play is silently discarded the next time the file_sd is re-rendered, with no
error anywhere. One file per owner removes the second list instead.

## Usage

Called from the play that deploys the entity:

```yaml
- name: Metrics — arr exporters
  hosts: monitoring
  tasks:
    - ansible.builtin.include_role:
        name: richard_lynch.monitoring.config_metrics
      vars:
        config_metrics_owner: app-exporters
        config_metrics_targets:
          - targets: ["192.0.2.6:9707"]
            labels: { role: service-exporter, component: sonarr, service_host: arr }
          - targets: ["192.0.2.6:9708"]
            labels: { role: service-exporter, component: radarr, service_host: arr }
```

Retiring the entity:

```yaml
      vars:
        config_metrics_owner: app-exporters
        config_metrics_state: absent
```

## Labels are load-bearing — do not "tidy" them

Alert rules and dashboards select on these labels. An alert such as `HostDown` firing on
`up{role="proxmox-node"}` depends on a label that exists **only** on the file_sd scrape, so
renaming or dropping it silently disarms that down-detection. A host scraped twice (here, and by
its own Alloy as `job=integrations/unix`) may need **both** `node` and `hostname` so either label
scheme finds it. Check what selects on a label before changing it.

## What it guarantees

- **No reload needed** — Prometheus polls `file_sd_configs` on a 30s `refresh_interval`. That is
  also what makes the failure mode silent, which is why the read-back below is not optional.
- **Reads back from the API.** After writing, the role asks `/api/v1/targets` and asserts every
  address it just registered is actually discovered. file_sd fails silently: a malformed or
  misplaced file is logged once and the targets simply never appear — a file_sd file that still
  holds raw Jinja, say, leaves the stack looking healthy while discovery finds nothing.
- **The `until:` loop is followed by an explicit assert**, recomputed from the last response. A
  retry loop that exhausts its retries otherwise reports green on its own.
- **Rejects an entry with no `targets`.** Valid YAML, valid file_sd, scrapes nothing — the symptom
  is a missing exporter, indistinguishable from one that is down.
- **Rejects `state=present` with no targets**, which would write an empty file and silently stop
  this owner being scraped.

## Options

See `meta/argument_specs.py` — the source of truth. `defaults/main.yml`, `meta/argument_specs.yml`
and `tasks/_argspec_guards.yml` are generated from it.

| option | default | notes |
|---|---|---|
| `config_metrics_owner` | *required* | Becomes `<owner>.yml`; unique per Prometheus, `[a-z0-9-]` only. |
| `config_metrics_targets` | `[]` | file_sd entries verbatim: `[{targets: [...], labels: {...}}]`. Required when `state=present`. |
| `config_metrics_state` | `present` | `absent` removes this owner's file. |
| `config_metrics_dir` | `/opt/prometheus/config/file_sd` | Host path; `/etc/prometheus/file_sd` in the container. |
| `config_metrics_verify` | `true` | Read back from the API and assert the targets are live. |
| `config_metrics_verify_retries` | `12` | × 5s. Must outlast one 30s refresh interval. |

## Testing

```bash
cd roles/config_metrics && molecule test -s default
```

The scenario includes the role's own `_resolve_defaults.yml` rather than restating its defaults — a
scenario that hand-copies a role's resolution is a second source of truth and drifts.
