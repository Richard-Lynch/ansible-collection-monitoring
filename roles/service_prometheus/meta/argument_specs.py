# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Deploys Prometheus (retention-capped) on the shared monitoring network",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "prometheus_image_version": OptionSpec(
                    type="str",
                    required=False,
                    default="latest",
                    description=["prom/prometheus image tag."],
                ),
                "prometheus_host_port": OptionSpec(
                    type="int",
                    required=False,
                    default="9090",
                    description=["Host port mapped to Prometheus 9090."],
                ),
                "prometheus_retention_time": OptionSpec(
                    type="str",
                    required=False,
                    default="30d",
                    description=["TSDB retention by time (e.g. 30d)."],
                ),
                "prometheus_retention_size": OptionSpec(
                    type="str",
                    required=False,
                    default="20GB",
                    description=[
                        "TSDB retention by size — hard ceiling so it can't fill the disk."
                    ],
                ),
                "prometheus_network": OptionSpec(
                    type="str",
                    required=False,
                    default="monitoring",
                    description=["Shared external docker network the stack joins."],
                ),
                # Declared here, never hand-added to the GENERATED defaults file: regeneration
                # deletes anything not in this spec, and prometheus_alertmanager_enabled falling back
                # to absent would silently disarm alerting.
                "prometheus_alertmanager_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "DEFAULT TRUE, deliberately. The template wraps BOTH `alerting:` and "
                        "`rule_files:` in this flag, so a false/absent value re-renders "
                        "prometheus.yml with alerting REMOVED: Prometheus then loads zero alert "
                        "rules, and a host looks monitored while it cannot alert. A default of "
                        "false would mean 'does nothing', which for a monitoring stack is the "
                        "opposite of safe.",
                    ],
                ),
                "prometheus_alertmanager_target": OptionSpec(
                    type="str",
                    required=False,
                    default="alertmanager:9093",
                    description=["Alertmanager endpoint Prometheus sends alerts to."],
                ),
            },
        ),
    }
)
