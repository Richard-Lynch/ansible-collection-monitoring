# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Installs Grafana Alloy",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "alloy_cli_args": OptionSpec(type="list", required=True, elements="str"),
                "alloy_config": OptionSpec(
                    type="dict",
                    required=True,
                    options={
                        "loki_url": OptionSpec(type="str", required=True),
                        "prometheus_url": OptionSpec(type="str", required=True),
                        "platform": OptionSpec(
                            type="str", required=True, choices=["real", "vm", "docker"]
                        ),
                        "parent_hostname": OptionSpec(type="str", required=False),
                        # Pins the `hostname` label instead of taking constants.hostname, which
                        # reads the TRANSIENT hostname -- the one DHCP/DNS sets at runtime, not
                        # /etc/hostname.
                        #
                        # A host whose static hostname is `mon` and whose DHCP-set transient name is
                        # `mon.lan.example.test` reports under whichever name was current when Alloy
                        # started, so a restart flips the label and the host appears under two
                        # identities. An identity label that changes with a DHCP lease is not an
                        # identity.
                        "hostname_override": OptionSpec(type="str", required=False),
                        "logs_journal": OptionSpec(
                            type="dict",
                            required=False,
                            options={
                                "max_age": OptionSpec(type="str", required=False, default="24h0m0s")
                            },
                        ),
                        "metrics_docker": OptionSpec(
                            type="dict",
                            required=False,
                            options={
                                # MUST live here, not hand-added to defaults/main.yml: that file
                                # is generated, and a regeneration drops the hand-edit, breaking
                                # every deploy with "object of type 'dict' has no attribute
                                # 'containerd_host'". See templates/metrics_docker.alloy.j2 for
                                # what it is for.
                                "containerd_host": OptionSpec(
                                    type="str",
                                    required=False,
                                    default="unix:///run/containerd/containerd.sock",
                                ),
                                "storage_duration": OptionSpec(
                                    type="str", required=False, default="5m"
                                ),
                                "scrape_interval": OptionSpec(
                                    type="str", required=False, default="10s"
                                ),
                            },
                        ),
                        "metrics_system": OptionSpec(
                            type="dict",
                            required=False,
                            options={
                                "scrape_interval": OptionSpec(
                                    type="str", required=False, default="15s"
                                ),
                                # Where the unix exporter's textfile collector looks for .prom
                                # files. Written by the textfile_exporters role; must match, or
                                # the metrics are produced and never scraped.
                                "enable_collectors": OptionSpec(
                                    type="list",
                                    elements="str",
                                    required=False,
                                ),
                                "disable_collectors": OptionSpec(
                                    type="list",
                                    elements="str",
                                    required=False,
                                ),
                                "textfile_directory": OptionSpec(
                                    type="str",
                                    required=False,
                                    default="/var/lib/node_exporter/textfile_collector",
                                ),
                            },
                        ),
                    },
                ),
            },
        ),
        "uninstall": ArgumentSpec(
            short_description="Uninstalls Grafana Alloy",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={},
        ),
    }
)
