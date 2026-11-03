# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

# Baseline options — shared by the default entrypoint. Declared once so the two entrypoints cannot
# drift apart in what they accept.
_BASELINE = {
    "config_logs_journal": OptionSpec(
        type="bool",
        required=False,
        default=True,
        description=[
            "Ship the systemd journal. On by default: it is the only log source that exists on",
            "every host, and the one that carries unit failures.",
        ],
    ),
    "config_logs_journal_max_age": OptionSpec(
        type="str",
        required=False,
        default="12h",
        description=["How far back to read on start, so a restart does not re-ship history."],
    ),
    "config_logs_system": OptionSpec(
        type="bool",
        required=False,
        default=True,
        description=["Ship /var/log/{syslog,messages,*.log}."],
    ),
    "config_logs_docker": OptionSpec(
        type="bool",
        required=False,
        default=False,
        description=[
            "Ship container logs via the docker socket. OFF by default — a host without docker",
            "has no socket, and the component then fails rather than being skipped.",
        ],
    ),
    "config_logs_hostname_override": OptionSpec(
        type="str",
        required=False,
        default="",
        description=[
            "Override the `instance` label on docker logs. Empty means use constants.hostname.",
            "Needed where the container's view of its hostname is not the name it is known by.",
        ],
    ),
    "config_logs_dir": OptionSpec(
        type="str",
        required=False,
        default="/etc/alloy/config.alloy.d",
        description=[
            "Alloy's config directory on the shipping host — the value of CONFIG_FILE in",
            "/etc/default/alloy. Every *.alloy file here is loaded.",
        ],
    ),
    "config_logs_restart": OptionSpec(
        type="bool",
        required=False,
        default=True,
        description=[
            "Restart Alloy when the config changes. Set false to batch several calls on one host",
            "into a single restart. Restart, not reload, is deliberate: Alloy's SIGHUP does not",
            "re-apply external_labels on loki.write, so a reload reports success while the agent",
            "keeps the old config. Disabling this also disables the read-back, because an",
            "unrestarted agent has not read the file and the role will not assert what it did not",
            "cause.",
        ],
    ),
    "config_logs_validate": OptionSpec(
        type="bool",
        required=False,
        default=True,
        description=[
            "Run `alloy fmt` before installing. A syntax error in ANY file in the directory fails",
            "the whole agent's config load, so a bad file takes down this host's metrics and logs",
            "together — not just this one concern.",
        ],
    ),
}


argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description=(
                "Register one owner's custom log sources as an Alloy drop-in config file"
            ),
            description=[
                "MECHANISM ONLY — this role owns no log source. Sources are owned by the play that",
                "deploys the thing producing the logs, so an application's log files are shipped",
                "because its own play says so, and stop being shipped when that play retires it.",
                "",
                "Sibling of config_alerts (alert rules) and config_metrics (scrape targets). Same",
                "shape, three destinations.",
                "",
                "DIFFERENT FROM ITS SIBLINGS IN TWO WAYS:",
                "",
                "1. The config lives on the SHIPPING host, not centrally. Alerts and targets are",
                "   written once on the monitoring host; log shipping is configured on every host",
                "   that has logs. So this role targets the owner's own host.",
                "",
                "2. It needs a RESTART, not a poll. Prometheus re-reads rules on reload and file_sd",
                "   on a timer; Alloy does neither for this. Its SIGHUP reload re-evaluates the",
                "   component graph but does NOT re-apply external_labels on loki.write, so a",
                "   reload exits 0 while the agent keeps writing the OLD labels. This role",
                "   therefore restarts Alloy.",
                "",
                "Alloy's CONFIG_FILE is a DIRECTORY (/etc/alloy/config.alloy.d/) and it loads every",
                "*.alloy file in it. service_alloy already runs the agent from drop-ins, so one",
                "file per owner needs no new mechanism.",
                "",
                "COMPONENT NAMES ARE ONE GLOBAL NAMESPACE across all those files — they reference",
                "each other freely (logs_system.alloy forwards to loki.write.default, defined in",
                "another file). Two owners declaring the same component id is a config-load failure",
                "for the WHOLE agent, not just for one file, so the owner name is required to",
                "prefix every component this role writes.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "config_logs_owner": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Short identifier for the play/entity that owns this log shipping — becomes",
                        "the filename (logs_<owner>.alloy) and the required prefix for every",
                        "component id in it. Must be unique per host and is restricted to",
                        "[a-z0-9-] so it cannot escape the config directory.",
                        "",
                        "REQUIRED BY THE `main` ENTRYPOINT, AND ONLY THAT ONE — which is why it is",
                        "declared required=False here and asserted in tasks/main.yml instead.",
                        "",
                        "Ansible validates EVERY task entrypoint against this one ArgumentSpec (the",
                        "baseline options are declared here for the defaults-loading reason noted",
                        "at the end of this block). So `required=True` would make",
                        "`tasks_from: default` — the per-host BASELINE, which owns no sources and",
                        "needs no owner — fail argspec validation before running a single task:",
                        "  'missing required arguments: config_logs_owner'",
                        "",
                        "Nothing is weakened: tasks/main.yml asserts the value is present, non-empty",
                        "and [a-z0-9-], with a sharper message than the argspec gives.",
                    ],
                ),
                "config_logs_sources": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[],
                    description=[
                        "Log sources to ship. Each entry is:",
                        "  name:    short id, unique within this owner (becomes part of the",
                        "           component id, after the owner prefix)",
                        "  paths:   list of glob paths to tail, e.g. ['/var/log/foo/*.log']",
                        "  labels:  optional map of Loki labels attached to every line",
                        "  exclude: optional glob of paths NOT to tail even if `paths` matches",
                        "           them (Alloy's __path_exclude__), e.g. an app's rotated",
                        "           '*.previous.txt' copies, which would re-ship old lines",
                        "  tail_from_end: optional bool — a file with no stored position starts",
                        "           at its END instead of its beginning. Lines carry ingestion",
                        "           time, so back-filling an existing file re-dates its whole",
                        "           history to 'now'; set this when adding sources to a live host.",
                        "",
                        "Kept deliberately narrow. Alloy's config language can express far more",
                        "than this, and a role that accepted arbitrary config would be a templating",
                        "engine with no way to validate what it emitted. File tailing is the case",
                        "every application play actually needs; anything more belongs in",
                        "service_alloy, which owns the agent itself.",
                        "Required when state=present.",
                    ],
                ),
                "config_logs_state": OptionSpec(
                    type="str",
                    required=False,
                    default="present",
                    choices=["present", "absent"],
                    description=[
                        "'present' installs this owner's drop-in; 'absent' removes it. Cleanup is",
                        "the OWNER's job, matching config_alerts and config_metrics. The role never",
                        "deletes a file it was not asked about, so one owner cannot remove",
                        "another's log shipping. With 'absent', config_logs_sources is not",
                        "required.",
                    ],
                ),
                "config_logs_forward_to": OptionSpec(
                    type="str",
                    required=False,
                    default="loki.write.default.receiver",
                    description=[
                        "The Loki sink to forward to. Defaults to the default writer declared in",
                        "service_alloy's own drop-in — reusing it rather than",
                        "declaring a second writer per owner, which would duplicate the connection",
                        "and the external_labels that go with it.",
                    ],
                ),
                # Baseline options, consumed by the `default` task entrypoint. Declared in
                # the SAME ArgumentSpec on purpose: Ansible only auto-loads defaults/main.yml, so a
                # second ArgumentSpec generates a second defaults file that never loads and the role
                # fails at run time with "<opt>__default is undefined". Several task entrypoints
                # behind one declared interface is the intended pattern.
                **_BASELINE,
            },
        ),
    }
)
