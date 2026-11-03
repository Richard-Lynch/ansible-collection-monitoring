# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description=(
                "Prometheus textfile exporters: GPU, Docker, WAN IP, WireGuard, HA recorder"
            ),
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                # Every exporter is opt-in per host: the GPU one is meaningless without an Intel
                # GPU and the docker one without docker, so none defaults to true. The role
                # asserts that at least one is selected rather than installing nothing quietly.
                "txe_gpu": OptionSpec(type="bool", required=False, default=False),
                "txe_docker": OptionSpec(type="bool", required=False, default=False),
                "txe_wireguard": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Export WireGuard tunnel state. For the MONITORED end of a site link: when",
                        "the far end has no other monitoring, 'is the tunnel up' must not itself",
                        "depend on the tunnel.",
                    ],
                ),
                "txe_wireguard_interface": OptionSpec(
                    type="str",
                    required=False,
                    default="wg0",
                    description=["Which interface to report on."],
                ),
                "txe_wan_ip": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Export the site's public egress IP. Intended for ONE host behind the",
                        "uplink — the address is a property of the uplink, not of the host, so",
                        "running it everywhere would emit N identical series.",
                    ],
                ),
                "txe_wan_ip_expected": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "The address something else pins (e.g. a source-IP allow or bypass",
                        "policy). When set, the exporter also emits whether reality still matches it.",
                        "Empty means 'export the address but assert nothing about it'.",
                    ],
                ),
                "txe_ha_recorder": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Export how stale Home Assistant's recorder is. Intended for ONE host, and",
                        "deliberately NOT the HAOS box: an exporter must not depend on the thing it",
                        "watches, or a dead HA produces no metric and absence is indistinguishable",
                        "from a dead exporter. Run it from a monitoring host.",
                        "Exists because HA's own prometheus integration exports entity states and",
                        "NOTHING about whether history is being persisted, so no Prometheus-only",
                        "rule can see a recorder that has stopped writing.",
                    ],
                ),
                "txe_ha_recorder_base_url": OptionSpec(
                    type="str",
                    required=False,
                    default="",
                    description=[
                        "Home Assistant's base URL, e.g. http://ha.example.test:8123. Installation",
                        "config, so it is passed in rather than defaulted to any one address.",
                        "Required when txe_ha_recorder is true.",
                    ],
                ),
                "txe_ha_recorder_token_file": OptionSpec(
                    type="str",
                    required=False,
                    default="/etc/ha-recorder-exporter/token",
                    description=[
                        "Path on the TARGET holding HA's long-lived token, mode 0600. A path, not",
                        "the token itself: argv is world-readable via /proc, so the value must never",
                        "reach a command line.",
                    ],
                ),
                "txe_ha_recorder_window_seconds": OptionSpec(
                    type="int",
                    required=False,
                    default=3600,
                    description=[
                        "How far back to ask the logbook. Deliberately SHORT. /api/logbook/<since>",
                        "silently caps a response at ~24h from `since`, so the newest row returned",
                        "tracks the START of the window -- a long value here reports a healthy",
                        "recorder as days stale.",
                    ],
                ),
                # Must match the SCRAPER's configured path, and the scraper differs by host class:
                # PVE hosts run a standalone node_exporter, guests run Alloy. A mismatch means the
                # .prom files are written every interval and read by nobody.
                "txe_collector_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="/var/lib/node_exporter/textfile_collector",
                ),
                # Deliberately shorter than the scrape interval, so a scrape always finds a file
                # at most one interval stale.
                "txe_interval": OptionSpec(type="str", required=False, default="30s"),
                # Generate, don't apply: report what would be installed by default, write only
                # when explicitly asked.
                "txe_apply": OptionSpec(type="bool", required=False, default=False),
            },
        ),
    }
)
