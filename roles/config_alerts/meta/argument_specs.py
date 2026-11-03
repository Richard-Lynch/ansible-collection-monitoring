# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description=(
                "Install one owner's Prometheus alert rules into the shared rules directory"
            ),
            description=[
                "MECHANISM ONLY — this role does not own any alert rule. Rules are owned by the",
                "play that deploys the thing being alerted on: a rule about a VM's disk belongs to",
                "the play that deploys that VM, not to a central alerting play. Each caller passes",
                "its own rules and a unique owner name, and gets exactly one file in the rules",
                "directory.",
                "",
                "WHY ONE FILE PER OWNER. When several roles ship one shared alert-rules file to the",
                "same path, whichever runs last defines all alerting, and a run silently deletes",
                "every other owner's rules while Prometheus reloads clean. One file per owner",
                "removes the shared write entirely: two owners cannot collide because they cannot",
                "address the same file.",
                "",
                "Prometheus globs `rule_files: /etc/prometheus/rules/*.yml`, so N files are the",
                "native shape, not a workaround, and separate files may even reuse a group name",
                "without colliding (promtool accepts it).",
                "",
                "GO TEMPLATING IS SAFE HERE. Prometheus annotations use Go template syntax",
                "(double-brace $labels.node), which shares Jinja's delimiters and is a Jinja syntax error.",
                "This role builds the file with the `to_nice_yaml` filter from plain Ansible data",
                "and writes it with `copy: content=`, so rule text is never rendered as a template.",
                "Callers write Go expressions as ordinary strings and they arrive verbatim. Naming",
                "the destination *.yml (never *.j2) also keeps deployment_config's template pass",
                "off it.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "config_alerts_owner": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "Short identifier for the play/entity that owns these rules — becomes the",
                        "filename (<owner>.yml) and so must be unique across every caller. Use the",
                        "thing being alerted on, not the alert topic: 'app-stack', 'vpn-link',",
                        "'gpu-host'. Restricted to [a-z0-9-] so it cannot escape the rules dir.",
                    ],
                ),
                "config_alerts_groups": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[],
                    description=[
                        "Prometheus rule groups, exactly as Prometheus models them: a list of",
                        "{name, rules[]} where each rule is {alert, expr, for?, labels?,",
                        "annotations?}. Passed through structurally rather than reshaped, so the",
                        "upstream documentation applies unchanged and no translation layer can",
                        "silently drop a field it does not know about.",
                    ],
                ),
                "config_alerts_state": OptionSpec(
                    type="str",
                    required=False,
                    default="present",
                    choices=["present", "absent"],
                    description=[
                        "'present' installs this owner's rules; 'absent' removes its file. Cleanup",
                        "is the OWNER's job: a play that retires the thing it deploys removes its",
                        "alerts in the same pass. The role",
                        "never deletes a file it was not asked about, so one owner can never remove",
                        "another's rules.",
                        "With 'absent', config_alerts_groups is not required.",
                    ],
                ),
                "config_alerts_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="/opt/prometheus/config/rules",
                    description=[
                        "Host path of the rules directory. This is the bind-mount source; inside",
                        "the container it appears as /etc/prometheus/rules, which is what the",
                        "prometheus.yml glob refers to.",
                    ],
                ),
                "config_alerts_validate": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Validate with promtool before installing. A rule file with a bad",
                        "expression makes Prometheus refuse the whole file, so an unvalidated",
                        "write can silently disable this owner's entire alert coverage.",
                    ],
                ),
                "config_alerts_reload": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "POST /-/reload after a change. A rules file on disk that Prometheus has",
                        "not re-read is worth nothing; without this the new rules take effect at",
                        "the next unrelated restart, whenever that happens to be.",
                    ],
                ),
                "config_alerts_container": OptionSpec(
                    type="str",
                    required=False,
                    default="prometheus",
                    description=["Prometheus container name, for promtool and the reload."],
                ),
            },
        )
    }
)
