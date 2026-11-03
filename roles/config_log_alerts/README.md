# config_log_alerts

Install **one owner's** Loki LogQL alert rules into the ruler's tenant directory.

This role is a **mechanism**. It owns no alert rule and never will. Rules are owned by the play that
deploys the thing being alerted on — a rule about a service's error rate belongs to the play that
deploys that service, not to a central alerting play and not to `service_loki`. This role's whole
job is to get one owner's LogQL rules into the Loki ruler safely, and to prove they took effect.

It is `config_alerts`' counterpart for **logs**. Same split, same reasoning, different store.

## Why it exists

A Loki deployed with **no `ruler:` stanza at all** answers `/loki/api/v1/rules` with:

```
HTTP 400  unable to read rule dir /loki/rules/fake: open /loki/rules/fake: no such file or directory
```

Nothing can page anyone on a log signal — while every log stream keeps arriving and Grafana renders
them perfectly, so the logs look fully monitored. That is a silent guard: alerting coverage that
reads as real and is structurally incapable of firing.

`service_loki` provides the ruler (the mechanism); this role installs the content.

## Where the files go, and why that is not a host path

`config_alerts` writes Prometheus rules with a plain `ansible.builtin.copy` to a host directory,
because Prometheus's rules directory is **bind-mounted**. Loki's is not: the ruler reads from
`<rule_path>/<tenant>/` on a **docker volume inside the container**. So this role stages the file on
the host and copies it in with `docker cp`.

Two consequences worth knowing:

- **The ruler needs the rule file to be WRITABLE, not merely readable.** This is the most
  counter-intuitive thing here. A read-only file logs:

  ```
  caller=mapper.go:163  msg="updating rule file"   file=/loki/rules/fake/roundtrip-probe.yml
  caller=manager.go:139 msg="unable to map rule files" user=fake
      err="open /loki/rules/fake/roundtrip-probe.yml: permission denied"
  ```

  Loki **maps** rule files — it rewrites them into its own working layout on every sync — so a
  `0644 root:root` file it can read but not write is **rejected once a minute, forever**. The
  rejection is **per file**: every other owner's rules keep evaluating perfectly, so the symptom
  is *"my rule is missing from `/prometheus/api/v1/rules`"* with the explanation only in the
  container log.

  So the role **chowns the staged file to `10001:10001` on the host** and copies it with
  **`docker cp --archive`**, which preserves ownership. Doing it afterwards is impossible:
  `docker exec <c> chown ...` fails with `Operation not permitted`, because `docker exec` runs as
  the image's own unprivileged user. The gate asserts **`test -w`**.

  `test -r` would be the wrong gate: `docker cp` preserves the `0644` mode, so the ruler can read
  the file — true and irrelevant, since that gate passes on a file the ruler rejects every minute.
  A guard that checks the wrong permission is a silent guard.
- **`fake` is the tenant, and it is not a placeholder.** Loki hardcodes that tenant id under
  `auth_enabled: false` (single-tenant mode). Renaming it points the ruler at a directory nothing
  writes to.

## Usage

Called from the play that deploys the entity, hopping to the monitoring host — the same shape
`config_alerts` uses:

```yaml
- name: Log alerts for the arr stack
  hosts: monitoring
  tags: [arr, log-alerts]
  tasks:
    - ansible.builtin.include_role:
        name: richard_lynch.monitoring.config_log_alerts
      vars:
        config_log_alerts_owner: app-stack
        config_log_alerts_groups:
          - name: app-stack
            interval: 1m
            rules:
              - alert: SonarrErrorBurst
                expr: 'sum(count_over_time({service_name="sonarr"} |~ `(?i)(error|fail)`[5m])) > 50'
                for: 10m
                labels: {severity: warning, alert_source: loki}
                annotations:
                  summary: "{% raw %}{{ $labels.service_name }}{% endraw %} error burst"
```

Removing them when the entity is retired — cleanup is the **owner's** job:

```yaml
      vars:
        config_log_alerts_owner: app-stack
        config_log_alerts_state: absent
        # Required to actually STOP the alerts — see "Removal needs a restart" below.
        config_log_alerts_restart_on_remove: true
```

The role never deletes a file it was not asked about, so one owner can never remove another's rules.

## Removal needs a restart, and that is not a shortcut being taken

**Deleting the rule file does not stop the rule.** Each obvious alternative fails:

1. after the file is removed, the ruler goes on **evaluating** the group — `lastEvaluation`
   **advancing**, not frozen.
2. **no copy of the file exists anywhere** under the rule path: the group lives purely in the
   ruler's in-memory rule manager, which does not drop a group when its file disappears.
3. the documented fix, `DELETE /loki/api/v1/rules/<namespace>/<group>`, answers **HTTP 500**:

   ```
   {"status":"error","errorType":"server_error",
    "error":"DeleteRuleGroup unsupported in rule local store"}
   ```

   The write half of the ruler API is **not implemented for `storage.type: local`**. (So
   `enable_api` is read-only with local rule storage as a property of Loki, not a choice.)

That leaves restarting Loki, which re-reads the tenant directory from scratch.
`config_log_alerts_restart_on_remove` is **off by default** because the cost is real and
fleet-wide — a restart briefly interrupts log **ingest** for every host, not just alerting — so
the caller decides. With it off the role says plainly that the group is still live rather than
reporting a clean removal.

The restart goes through **compose**, not `community.docker.docker_container`. A `docker_container`
restart recreates the container outside compose's knowledge and detaches it from the project, and
the ruler can come back answering HTTP 400 for a missing tenant directory, needing a full
`service_loki` re-converge to recover.

## `expr` is LogQL, and it must be metric-producing

A bare log selector returns **streams**, which the ruler cannot compare to a threshold — the rule
loads and never evaluates to anything. Wrap it in an aggregation:

```
# WRONG — returns streams, can never fire
{service_name="traefik"} |~ `error`

# RIGHT — returns a vector
sum(count_over_time({service_name="traefik"} |~ `error`[5m])) > 50
```

The role refuses the first form rather than installing it.

## Two label schemes, and the rule that matches nothing

A Loki fed by both journal and container sources (as `config_logs` ships them) carries **two label
schemes that share no host key**:

```
journal    {hostname="host1", transport="journal", unit="...", job="loki.source.journal.journallogs"}
container  {instance="host1", parenthostname="host1", platform="docker", service_name="bind9"}
```

A `{hostname="X"}` selector **returns zero against a container stream** — which reads exactly like
*"this service ships no logs"*.

So the role, by default, **probes every rule's selector against live Loki over a 24h window and
refuses to install a rule whose selector matched nothing**. That is what
`config_log_alerts_verify_matches` controls.

## Writing Go template annotations

Loki annotations use **Go** templating (`{{ $labels.service_name }}`), which shares Jinja's
delimiters. Wrap them in `{% raw %}` at the call site:

```yaml
summary: "{% raw %}{{ $labels.service_name }}{% endraw %} is logging errors"
```

Inside the role the rules are serialised with `to_nice_yaml` and written with `copy: content=`, so
rule text is **never** rendered as a template and Go expressions arrive verbatim. `template:` would
fail with `unexpected char '$'`.

## What it guarantees

- **Validates before installing.** Each expression goes through **Loki's own query API** — the
  authoritative parser, rather than a second implementation that could disagree (Loki ships no
  `promtool` equivalent). Three separate properties: the LogQL parses, the query is
  metric-producing, and the selector can match real data.
- **Refuses a rule that can never fire.** See the label-scheme section above.
- **Verifies inline, not via a handler.** A handler runs at play end, so anything later in the same
  run reads the pre-change state — and a guard that reads stale state produces false alerts.
- **Reads back from the ruler API** on **every** run, not only when something changed. The rule file
  lives on a docker volume inside a container that anything else on the host can recreate or roll
  back, so *"nothing changed this run"* does not imply *"the ruler still has these rules"*.
  (`config_alerts` gates its equivalent on `changed`, which is right for a bind-mounted file.)
- **Safe to run twice.** The `docker cp` compares the bytes already in the container against the
  rendered content, so a converged run reports `changed=0`, and a second run of the same owner
  reports `changed=0` too.

## Options

See `meta/argument_specs.py` — the source of truth. `defaults/main.yml` and
`meta/argument_specs.yml` are generated from it.

| option | default | notes |
|---|---|---|
| `config_log_alerts_owner` | *required* | Becomes `<owner>.yml`. Unique across callers; `[a-z0-9-]` only, so it cannot escape the tenant directory. |
| `config_log_alerts_groups` | `[]` | Loki rule groups verbatim: `[{name, interval?, rules[]}]`. Required when `state=present`. |
| `config_log_alerts_state` | `present` | `absent` removes this owner's file. |
| `config_log_alerts_container` | `loki` | For the `docker cp` and the directory write. |
| `config_log_alerts_tenant` | `fake` | Must match `service_loki`'s `loki_ruler_tenant`. |
| `config_log_alerts_rule_path` | `/loki/rules` | Must match `service_loki`'s `loki__rule_path`. |
| `config_log_alerts_url` | `http://127.0.0.1:3100` | For validation and the read-back. |
| `config_log_alerts_validate` | `true` | LogQL parses + is metric-producing, via Loki itself. |
| `config_log_alerts_verify_matches` | `true` | Selector must match live data. Turn off only with a recorded reason. |

## Testing

```bash
cd roles/config_log_alerts && molecule test -s default
```

**Honest scope.** The scenario covers the guards and the rendering — everything that needs nothing
external. It does **not** cover the `docker cp` install path, the LogQL validation queries or the
ruler read-back, because all three need a live Loki and a docker daemon. A round-trip run against a
live Loki proves those: install a rule, watch it go firing in the ruler, confirm it reaches
Alertmanager, and remove it again. Honest partial coverage beats none, and beats a scenario that
stubs the thing under test and asserts the stub.

## Related

- `config_alerts` — the same mechanism for Prometheus metric rules.
- `service_loki` — provides the ruler this role writes into.
- Before writing a rule, query the candidate selector against live Loki (`/loki/api/v1/query_range`)
  and read the lines it matches.
