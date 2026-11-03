# config_logs

Register **one owner's** log shipping as an Alloy drop-in config file.

This role is a **mechanism**. It owns no log source. Sources belong to the play that deploys the
thing producing the logs, so an application's logs are shipped because its own play says so, and
stop being shipped when that play retires it.

Sibling of [`config_alerts`](../config_alerts/README.md) (alert rules) and
[`config_metrics`](../config_metrics/README.md) (scrape targets). Same shape, three destinations.

## Two ways it differs from its siblings

**1. It runs on the shipping host, not the monitoring host.** Alerts and scrape targets are written
once, centrally. Log shipping is configured on every host that has logs, so this role targets the
owner's own host.

**2. It restarts Alloy; it does not reload it.** Prometheus re-reads rules on reload and file_sd on
a timer. Alloy does neither for this. Its SIGHUP reload re-evaluates the component graph but does
**not** re-apply `external_labels` on `loki.write`, so a reload exits 0 and the agent keeps writing
the **old** labels while the play reports success.

## Why drop-ins work here

Alloy's `CONFIG_FILE` is a **directory** (`/etc/alloy/config.alloy.d/`) and it loads every `*.alloy`
file in it. `service_alloy` already runs the agent from drop-ins, so one file per owner needs no new
mechanism.

**Component ids are one global namespace across all of those files.** They reference each other
freely — `logs_system.alloy` forwards to `loki.write.default`, which is declared in a different
file. Two owners declaring the same id fails the config load for the **whole agent**, not just one
file. Every component this role writes is therefore prefixed with the owner name, and hyphens are
translated to underscores because Alloy ids are identifiers (`app-stack` → `app_stack_*`).

## Usage

Called from the play that deploys the entity, on that entity's own host:

```yaml
- name: Logs — app stack
  hosts: app_hosts
  tasks:
    - ansible.builtin.include_role:
        name: richard_lynch.monitoring.config_logs
      vars:
        config_logs_owner: app-stack
        config_logs_sources:
          - name: webapp
            paths: ["/var/log/webapp/*.log"]
            labels: { component: webapp }
```

Retiring it:

```yaml
      vars:
        config_logs_owner: app-stack
        config_logs_state: absent
```

## Deliberately narrow

`config_logs_sources` expresses **file tailing** and nothing else. Alloy's config language can do
far more, and a role that accepted arbitrary config would be a templating engine with no way to
validate what it emitted. File tailing is what application plays actually need; anything beyond it
belongs in `service_alloy`, which owns the agent itself.

It also reuses the existing `loki.write.default` sink rather than declaring a writer per owner —
a second writer would duplicate the connection and the `external_labels` attached to it.

## What it guarantees

- **Validates before installing.** The drop-in is rendered to a scratch path outside the config
  directory and checked with `alloy fmt` first. This matters more than for the siblings: a syntax
  error in *any* file in that directory fails the whole agent's config load, so a bad drop-in takes
  down the host's **metrics and logs together**, not just this owner's. `alloy fmt` rejects as
  well as accepts — valid config rc=0, malformed rc=1.
- **Gates on `rc`, not on stdout emptiness** — `alloy fmt` writes the formatted config to stdout on
  *success*, so non-empty output is the good case here.
- **Flushes the restart handler and reads the component graph back.** A drop-in on disk that Alloy
  never loaded is worth nothing, and a restart exiting 0 says nothing about whether the config
  inside it was accepted. The role asks Alloy's own API which components are running and asserts
  this owner's are present and `healthy`.
- **The `until:` loop is followed by an explicit assert**, recomputed from the last response — a
  retry loop that exhausts its retries otherwise reports green on its own.
- **Rejects a source with no `paths`**, which renders as valid config that ships nothing: the
  symptom is missing logs, indistinguishable from a quiet application.
- **Rejects duplicate source names within an owner**, which would emit two components with the same
  id and fail the agent's config load.

## Options

See `meta/argument_specs.py` — the source of truth. `defaults/main.yml` and
`meta/argument_specs.yml` are generated from it.

| option | default | notes |
|---|---|---|
| `config_logs_owner` | *required* | Becomes `logs_<owner>.alloy` and the component prefix. `[a-z0-9-]` only. |
| `config_logs_sources` | `[]` | `[{name, paths[], labels{}}]`. Required when `state=present`. |
| `config_logs_state` | `present` | `absent` removes this owner's drop-in. |
| `config_logs_dir` | `/etc/alloy/config.alloy.d` | Alloy's `CONFIG_FILE` directory on the shipping host. |
| `config_logs_forward_to` | `loki.write.default.receiver` | The Loki sink `service_alloy` declares. |
| `config_logs_restart` | `true` | Restart Alloy on change. Set `false` to batch several owners into one restart — this also disables the read-back, since an unrestarted agent has not read the file. |
| `config_logs_validate` | `true` | `alloy fmt` before installing. |

## Testing

```bash
cd roles/config_logs && molecule test -s default
```

The scenario renders the role's **own** template and asserts on the output; it does not restart a
real agent (`config_logs_restart: false`). That flag is a real option, not a test hook — a play
registering several owners on one host uses it to take a single restart at the end. Overriding the
role's handler from the scenario does **not** work: a play-level handler of the same name does not
shadow a role handler, so the role needs a real switch. `alloy fmt` is not available in CI, so
syntax is asserted structurally there and the formatter check needs a host with Alloy installed. A
scenario that hand-copies a role's default resolution is a second source of truth and drifts, so it
includes the role's real `_resolve_defaults.yml`.
