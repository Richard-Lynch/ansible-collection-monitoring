<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to this collection are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the collection
uses [Semantic Versioning](https://semver.org/).

## [1.0.1] — 2026-11-03

The first release published to Galaxy; 1.0.0 exists only as the git tag `v1.0.0`.

### Added

- `service_node_exporter` has a README, which Galaxy's importer requires of every role.
- `meta/main.yml` with `galaxy_info` (author, description, license, minimum Ansible version) for
  every role that lacked one, so each role carries a description on Galaxy.

## [1.0.0] — 2026-11-03

### Added

- Service roles, each a Docker Compose project deployed with `richard_lynch.common.deployment_config`: `service_prometheus`, `service_alert_manager`, `service_loki`, `service_grafana`, `service_alloy`, `service_node_exporter`, `service_uptime_kuma`, `service_apprise` and `service_homepage`.
- Cross-cutting roles that any play calls for its own host or service: `config_metrics` (scrape targets), `config_logs` (Alloy log shipping), `config_alerts` (Prometheus rules, promtool-checked and read back from the ruler), `config_log_alerts` (Loki ruler rules), `config_log_backfill`, `textfile_exporters` and `apprise_notify_config`.
- Every installation-specific value is an option the caller sets: hosts, addresses, URLs, dashboard cards and credentials.
