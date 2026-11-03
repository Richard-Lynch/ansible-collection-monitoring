# service_grafana

Deploy **Grafana** (grafana-oss) on a shared Docker network, with a **Postgres backend**,
**provisioned datasources** (Prometheus + Loki, by container name) and **provisioned dashboards**
from a directory the caller supplies.

## What it does

- Templates the compose + env + provisioning (datasources, dashboard provider) into
  `/opt/<container>`, ensures the shared network, and brings Grafana up.
- **Postgres backend** (not SQLite) — Grafana state lives in a Postgres database (`grafana` by
  default), which survives container recreation.
- **Admin and DB passwords from the caller** (the placeholder default is refused).
- **Provisioned datasources** wired by container name: `http://prometheus:9090`, `http://loki:3100`.
- **Provisioned dashboards** — every file in `grafana_dashboards_src` (a controller directory),
  into the `grafana_dashboards_folder` folder. They are CODE: `overwriteExisting: true`, so a UI
  edit is discarded on the next reload and the source directory stays the source of truth. The role
  ships no dashboards of its own: which dashboards exist is installation data.

### Adding a dashboard

Drop a `<uid>.json` into `grafana_dashboards_src` and re-run. Two things are not optional:

1. **Verify every panel against live data before committing.** A panel whose metric does not exist
   renders "No data", which is indistinguishable from an idle system. Query every panel of every
   dashboard and name the empty ones.
2. **A panel that is legitimately empty is recorded WITH A REASON**, so "checked, empty is correct"
   stays distinguishable from "not yet looked at".

Three traps that produce a confident wrong answer rather than an error:

- **A Loki panel must not select on a label only some streams carry.** With Alloy's defaults,
  `hostname`, `job` and `level` exist only on JOURNAL streams; docker streams carry
  `instance`/`platform`/`service_name`. A selector on a journal-only label silently drops 100% of
  container logs and renders as "no errors".
- **A state-set metric's VALUE is not a level.** It is the `state` LABEL of the series equal to 1
  that names the current state, so reducing with `max()` can report a healthy thing as broken.
- **Mirror an alert RULE's expression rather than querying `ALERTS{}`.** `ALERTS` carries series
  only while an alert is pending or firing, so an `ALERTS`-based panel is empty when everything is
  fine AND empty when the query is wrong.

## Inputs

See [`meta/argument_specs.yml`](meta/argument_specs.yml). Key ones:

- `grafana_admin_password`, `grafana_db_password` — from your secret store (placeholders rejected).
- `grafana_db_host/port/name/user` — Postgres backend (defaults: `postgres:5432`, db/user `grafana`).
- `grafana_network` (default `monitoring`), `grafana_host_port` (default `3000`).
- `grafana_dashboards_src` (default empty: none), `grafana_dashboards_folder` (default `Dashboards`).

## Usage

```yaml
- hosts: monitoring
  roles:
    - role: richard_lynch.monitoring.service_grafana
      vars:
        grafana_admin_password: "{{ grafana_admin_secret }}"
        grafana_db_password: "{{ grafana_db_secret }}"
        grafana_dashboards_src: "{{ playbook_dir }}/files/dashboards"
```

## Testing

`molecule/default/` renders the compose + env + datasources + dashboard provider and asserts the
Postgres backend env, the shared-network wiring, the Prometheus/Loki datasource URLs and the
provider folder (offline).
