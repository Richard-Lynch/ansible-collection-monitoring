<!--
Copyright: (c) 2026, Richard Lynch
SPDX-License-Identifier: GPL-3.0-or-later
-->

# Changelog

All notable changes to this collection are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the collection
uses [Semantic Versioning](https://semver.org/).

## [1.1.0] — 2026-11-07

### Added

- **`alertmanager_silence`** — one Alertmanager silence as desired state, found by its identity
  (comment + normalized matcher set), never by its server-generated id. Honest `changed`,
  `--check` and `--diff`; a refresh is ONE write (a POST carrying the existing id, which
  Alertmanager handles as expire-and-replace); `state: absent` expires the silence and every
  duplicate; a read-back that does not show the desired state is a failure, never a pass. Built on
  `richard_lynch.common` (`DesiredState`, `FetchUrlTransport`, `http_argument_spec`), so the
  connection options and the redaction are the shared ones. Replaces the `uri` loops that expired
  and re-created silences on every run.
- **`alertmanager_silence_info`** — list silences, filtered by state and comment substring,
  normalized the same way.
- `plugins/module_utils/alertmanager/client.py`: the pure-Python client and `SilenceResource`
  (no Ansible imports; a script or a test drives it through `UrllibTransport`), and
  `docs/resources/alertmanager_silence.md`, the resource model a provider in another language would
  implement from.
- Unit tests against a fake Alertmanager that enforces the v2 silences API (server-generated ids,
  id-carrying POST = replace, state from the clock, DELETE = expire, Alertmanager's own 400s), with
  the five defects of the `uri` approach pinned as cases, and a token-never-in-output case.

## [1.0.5] — 2026-11-07

### Fixed

- `service_homepage` retries its post-deploy HTTP check: a container that has just been restarted resets its first connections, so a single attempt can fail the first converge of a healthy deploy. The check makes up to `homepage_health_retries` + 1 attempts (new option, default 12), `homepage_health_delay` seconds apart (new option, default 5), and an assert after the loop fails the run if the endpoint never answers 200.

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
