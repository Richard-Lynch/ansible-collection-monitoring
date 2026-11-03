# config_alerts

Install **one owner's** Prometheus alert rules into the shared rules directory.

This role is a **mechanism**. It owns no alert rule and never will. Rules are owned by the play that
deploys the thing being alerted on — a rule about a VM's disk belongs to the play that deploys that
VM, not to a central alerting play. This role's whole job is to get one owner's rules onto the
monitoring host safely, and to prove they took effect.

## Why one file per owner

When several roles ship one shared `alert-rules.yml` to the same path, whichever runs last defines
all alerting: a run of one silently deletes every rule the others installed, and Prometheus reloads
clean afterwards, so nothing reports a problem.

One file per owner removes the shared write entirely: two owners cannot collide because they cannot
address the same file. It also bounds the blast radius — Prometheus rejects a rule file **as a
whole** on a single bad expression, so with one shared file one owner's typo silently disables
everyone's alerts.

Prometheus globs `rule_files: /etc/prometheus/rules/*.yml`, so N files are the native shape, not a
workaround. `promtool` accepts separate files that reuse a group name without colliding.

## Usage

Called from the play that deploys the entity, hopping to the monitoring host:

```yaml
- name: Alerts for the arr stack
  hosts: monitoring
  tags: [arr, alerts]
  tasks:
    - ansible.builtin.include_role:
        name: richard_lynch.monitoring.config_alerts
      vars:
        config_alerts_owner: app-stack
        config_alerts_groups:
          - name: app-stack
            rules:
              - alert: JellyfinDown
                expr: 'docker_container_running{name="jellyfin"} == 0'
                for: 5m
                labels: { severity: critical }
                annotations:
                  summary: "{% raw %}{{ or $labels.node $labels.instance }}{% endraw %}: jellyfin is not running"
```

Removing them when the entity is retired — cleanup is the **owner's** job:

```yaml
      vars:
        config_alerts_owner: app-stack
        config_alerts_state: absent
```

The role never deletes a file it was not asked about, so one owner can never remove another's rules.
There is no prune and no central registry.

## Writing Go template annotations

Prometheus annotations use **Go** templating (`{{ $labels.node }}`), which shares Jinja's delimiters.
Wrap them in `{% raw %}`:

```yaml
summary: "{% raw %}{{ or $labels.node $labels.component }}{% endraw %} is down"
```

Inside the role the rules are serialised with `to_nice_yaml` and written with `copy: content=`, so
rule text is **never** rendered as a template and Go expressions arrive verbatim. Rendering a rule
file as a `.j2` template fails with `unexpected char '$'` (and a deployer that renders every `.j2`
it copies hits exactly that), so files written here are always `.yml`.

Name hosts with `{{ or $labels.node $labels.component $labels.instance }}` rather than
`$labels.instance` alone — `instance` is the scrape address, so alerts arrive as bare `IP:port`.
Attach `node`, `component` and `role` labels to every scrape target (e.g. through `file_sd`) so
these resolve.

## What it guarantees

- **Validates before installing.** The rendered file goes to a scratch path and through `promtool`
  first, so an invalid file never reaches the rules directory even briefly. Gates on `rc`, not on
  stdout emptiness — promtool writes diagnostics to stdout, so non-empty output does not mean
  success.
- **Reloads inline, not via a handler.** A handler runs at play end, so anything later in the same
  run reads the pre-reload state — and a reload guard that reads stale state produces false
  alerts.
- **Reads back from the API.** A file on disk that Prometheus never read is worth nothing, and a
  reload returning 200 does not prove the rules are in effect. The role asks
  `/api/v1/rules` which groups are actually loaded and asserts this owner's file is among them.
  The `until:` loop is followed by an explicit assert, because a retry loop that exhausts its
  retries otherwise reports green.

## Options

See `meta/argument_specs.py` — the source of truth. `defaults/main.yml` and
`meta/argument_specs.yml` are generated from it.

| option | default | notes |
|---|---|---|
| `config_alerts_owner` | *required* | Becomes `<owner>.yml`. Must be unique across callers; `[a-z0-9-]` only, so it cannot escape the rules directory. |
| `config_alerts_groups` | `[]` | Prometheus rule groups verbatim: `[{name, rules[]}]`. Required when `state=present`. |
| `config_alerts_state` | `present` | `absent` removes this owner's file. |
| `config_alerts_dir` | `/opt/prometheus/config/rules` | Host path; appears as `/etc/prometheus/rules` in the container. |
| `config_alerts_validate` | `true` | promtool before install. |
| `config_alerts_reload` | `true` | POST `/-/reload` and read back. |
| `config_alerts_container` | `prometheus` | For promtool and the reload. |

## Testing

```bash
cd roles/config_alerts && molecule test -s default
```

The scenario includes the role's own `_resolve_defaults.yml` rather than restating its defaults —
a scenario that hand-copies a role's resolution is a second source of truth and drifts.
