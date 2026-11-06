<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to this collection are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the collection
uses [Semantic Versioning](https://semver.org/).

## [1.0.4] — 2026-11-06

### Changed

- The CI, release and disclose callers use ansible-devkit `v0.4.1`.

### Fixed

- `service_grafana` no longer prints the admin and database passwords under `--diff`: the include of `richard_lynch.common.deployment_config` that renders `grafana.env` passes `apply: {no_log: true, diff: false}`, which reaches the included template task.
- `service_homepage` renders the caller's dashboard config the same way, so widget API keys are not printed under `--diff`. Its config validation reduces each service card to its name and href before the gates read it, so a card's widget block (and its key) no longer leaves the no_log fact it was rendered into.
- `service_alert_manager` writes the mTLS client certificate and key with `no_log` and `diff: false`, renders `alertmanager.yml` (which carries the heartbeat push URL and its token) with `apply: {no_log: true, diff: false}`, and its HTTPS check on the heartbeat URL reports only the URL's scheme. `alertmanager_heartbeat_url` and `alertmanager_heartbeat_mtls_key` are `no_log` in the argument spec.

## [1.0.3] — 2026-11-04

### Changed

- The CI, release and disclose callers use ansible-devkit `v0.3.2`, whose CI selects molecule scenarios with `ci/affected-scenarios.sh` (shipped in the repository, not in the built collection; the sanity ignores cover its two intended shellcheck notes).

### Fixed

- `config_alerts` runs to the end under `--check`. The promtool validation read the staged candidate's path from the staging task's result, which a check-mode run does not produce, so every dry run of a play that registers rules failed at the copy into the container. The validation now runs under `--check` too (it stages, checks and removes scratch files only); when the container does not exist yet, the run reports that the rules were not validated instead of failing. The reload and the loaded-rules read-back are skipped, since nothing was installed. The molecule scenario runs the role under a real `--check` with validation and reload on.

## [1.0.2] — 2026-11-03

### Fixed

- Argument spec descriptions no longer contain template delimiters that break
  `validate_argument_spec`. `service_alert_manager`'s spec carried a literal unbalanced double
  brace in one option's description, so every play using the role failed validation before its
  first task ("Syntax error in template"); `config_alerts` and `config_log_alerts` carried
  balanced ones in their entrypoint descriptions. All three now describe the delimiters in words.

### Changed

- The CI, release and disclose callers use ansible-devkit `v0.2.2`.

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
