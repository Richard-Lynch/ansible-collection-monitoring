# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description=(
                "Register one owner's Prometheus scrape targets via file-based service discovery"
            ),
            description=[
                "MECHANISM ONLY — this role owns no scrape target. Targets are owned by the play",
                "that deploys the thing being scraped, so an application's exporters are",
                "registered by its own play and disappear when it is retired. Each caller passes",
                "its own targets and a unique owner name, and gets exactly one file in the",
                "file_sd directory.",
                "",
                "WHY IT EXISTS. A central target list kept in TWO places — a role's vars/ and a",
                "play's vars — must be kept in sync by hand. Role vars outrank play vars, so a",
                "target added only to the play is silently discarded the next time the file_sd is",
                "re-rendered, with no error anywhere. One file per owner removes the second list.",
                "",
                "Prometheus globs `file_sd_configs: /etc/prometheus/file_sd/*.yml` and re-reads it",
                "every 30s, so N files are the native shape and no reload is needed — unlike alert",
                "rules (see roles/config_alerts).",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "config_metrics_owner": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "Short identifier for the play/entity that owns these targets — becomes the",
                        "filename (<owner>.yml) and so must be unique per Prometheus. Name the",
                        "thing being scraped, not the metric: 'app-exporters', 'proxmox-nodes'.",
                        "Restricted to [a-z0-9-] so it cannot escape the file_sd directory.",
                    ],
                ),
                "config_metrics_targets": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[],
                    description=[
                        "Prometheus file_sd entries, exactly as Prometheus models them: a list of",
                        "{targets: [host:port], labels: {k: v}}. Passed through structurally rather",
                        "than reshaped, so the upstream documentation applies unchanged and no",
                        "translation layer can silently drop a label it does not know about.",
                        "Required when state=present.",
                        "",
                        "Label with care: alert rules select on these labels. An alert on",
                        'up{role="proxmox-node"} depends on a label that exists only on the file_sd',
                        "scrape, so changing or dropping it silently disarms that alert.",
                    ],
                ),
                "config_metrics_state": OptionSpec(
                    type="str",
                    required=False,
                    default="present",
                    choices=["present", "absent"],
                    description=[
                        "'present' installs this owner's targets; 'absent' removes its file.",
                        "Cleanup is the OWNER's job, matching config_alerts and config_logs: the",
                        "play that retires an entity also stops it being scraped. The role never",
                        "deletes a file it was not asked about, so one owner cannot remove",
                        "another's targets. With 'absent', config_metrics_targets is not required.",
                    ],
                ),
                "config_metrics_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="/opt/prometheus/config/file_sd",
                    description=[
                        "Host path of the file_sd directory. This is the bind-mount source; inside",
                        "the container it appears as /etc/prometheus/file_sd, which is what the",
                        "prometheus.yml file_sd_configs glob refers to.",
                    ],
                ),
                "config_metrics_verify": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "After writing, read the targets back from Prometheus's own API and assert",
                        "this owner's targets are actually being scraped. A file on disk that",
                        "Prometheus never picked up is worth nothing, and file_sd fails SILENTLY:",
                        "a malformed file is logged once and the targets simply never appear,",
                        "while the stack looks healthy.",
                    ],
                ),
                # --- scrape_job entrypoint -----------------------------------------------------
                # A file_sd entry is only {targets, labels}: no per-target auth, no per-target
                # interval, no metric_relabel_configs. Targets needing any of those ship as a full
                # scrape JOB instead, pulled in by prometheus.yml's scrape_config_files. Same
                # ownership model, different destination directory.
                "config_metrics_job": OptionSpec(
                    type="dict",
                    required=False,
                    default={},
                    description=[
                        "A complete Prometheus scrape_config, passed through verbatim: job_name,",
                        "scheme, metrics_path, scrape_interval, authorization, static_configs,",
                        "metric_relabel_configs, and anything else Prometheus accepts. Not",
                        "reshaped, so the upstream documentation applies and no translation layer",
                        "can silently drop a key it does not know about.",
                        "",
                        "Required by the `scrape_job` entrypoint. The file is written as a mapping",
                        "with a `scrape_configs:` key — a bare list is rejected by Prometheus with",
                        "'cannot unmarshal !!seq into config.ScrapeConfigs'.",
                    ],
                ),
                "config_metrics_job_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="/opt/prometheus/config/scrape_jobs",
                    description=[
                        "Host path for per-owner scrape-job files. Separate from the file_sd",
                        "directory because Prometheus reads the two differently: file_sd is polled",
                        "on a refresh_interval, scrape_config_files are read at config load and",
                        "need a reload.",
                    ],
                ),
                "config_metrics_job_group": OptionSpec(
                    type="str",
                    required=False,
                    default="65534",
                    description=[
                        "Group owning the scrape-job file, so the Prometheus container can read it.",
                        "The official image runs as nobody(65534). A job may carry a bearer token,",
                        "so the file is 0640 rather than the 0644 the other config files use —",
                        "which means the container's own group must own it.",
                        "",
                        "The NUMERIC gid, deliberately. 65534 is `nobody` inside the container but",
                        "`nogroup` on a Debian host, so the name does not survive the namespace",
                        "boundary — `chgrp nobody` fails with 'failed to look up group nobody'.",
                        "The number means the same thing on both sides.",
                        "",
                        "Getting this wrong is not subtle but it IS total: Prometheus rejects the",
                        "ENTIRE config on an unreadable scrape_config_files entry, so one bad file",
                        "stops every other job reloading too.",
                    ],
                ),
                "config_metrics_job_secret": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    no_log=True,
                    description=[
                        "Credential for the job, injected per config_metrics_job_auth (bearer token",
                        "or basic-auth password) so it is not written into config_metrics_job",
                        "itself. no_log, so a",
                        "validation failure cannot echo it into a task result or CI log. Empty",
                        "means the job carries no authorization block.",
                    ],
                ),
                "config_metrics_job_auth": OptionSpec(
                    type="str",
                    required=False,
                    default="bearer",
                    choices=["bearer", "basic"],
                    description=[
                        "How config_metrics_job_secret is presented. bearer -> authorization:",
                        "{type: Bearer, credentials: <secret>} (Home Assistant). basic ->",
                        "basic_auth: {username: config_metrics_job_username, password: <secret>}",
                        "(Uptime Kuma's /metrics takes an API key as the Basic password).",
                    ],
                ),
                "config_metrics_job_username": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "Basic-auth username for config_metrics_job_auth=basic. Empty is valid:",
                        "Uptime Kuma ignores it and reads only the password (the API key).",
                    ],
                ),
                "config_metrics_verify_retries": OptionSpec(
                    type="int",
                    required=False,
                    default=12,
                    min_value=1,
                    description=[
                        "How many times to re-ask the API before failing. file_sd is re-read on a",
                        "30s refresh_interval, so the read-back must outlast one full interval;",
                        "12 x 5s covers it with margin.",
                    ],
                ),
            },
        )
    }
)
