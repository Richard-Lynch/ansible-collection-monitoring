# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Deploys Loki (tsdb, retention-compacted) on the shared monitoring network",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "loki_image_version": OptionSpec(
                    type="str",
                    required=False,
                    default="3.5.5",
                    description=["grafana/loki image tag."],
                ),
                "loki_host_port": OptionSpec(
                    type="int",
                    required=False,
                    default="3100",
                    description=["Host port mapped to Loki 3100."],
                ),
                "loki__index_store": OptionSpec(
                    type="str",
                    required=False,
                    default="tsdb",
                    description=["Index store (tsdb for schema v13)."],
                ),
                "loki__retention_period": OptionSpec(
                    type="str",
                    required=False,
                    default="768h",
                    description=[
                        "Log retention; the compactor deletes past this so the store stays bounded."
                    ],
                ),
                "loki_network": OptionSpec(
                    type="str",
                    required=False,
                    default="monitoring",
                    description=["Shared external docker network the stack joins."],
                ),
                # --- ruler: log-based alerting ----------------------------------------------
                # MECHANISM ONLY. These options enable the ruler and give it somewhere to read
                # from; they do NOT carry any alert rule. Rules are owned by the play that
                # deploys the thing being alerted on, installed via config_log_alerts — the
                # same split as Prometheus/config_alerts. See README.md "Log-based alerting".
                "loki_ruler_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Provision the ruler so LogQL alert rules can be evaluated and sent to",
                        "Alertmanager. Defaults ON: with no ruler stanza Loki answers HTTP 400",
                        "on /loki/api/v1/rules and NO log-based alert can fire anywhere, which",
                        "reads as alerting coverage while being incapable of it.",
                        "Off is for a Loki deployed purely as a log store with its own reason.",
                    ],
                ),
                "loki_ruler_alertmanager_url": OptionSpec(
                    type="str",
                    required=False,
                    default="http://alertmanager:9093",
                    description=[
                        "Alertmanager the ruler notifies. Resolved on the shared docker network,",
                        "so the container NAME is correct here and a host address is not — the",
                        "ruler resolves this from inside the Loki container.",
                        "Plain HTTP is deliberate: this is an internal service-to-service",
                        "telemetry hop carrying no credential.",
                    ],
                ),
                "loki_ruler_tenant": OptionSpec(
                    type="str",
                    required=False,
                    default="fake",
                    description=[
                        "Tenant id whose rule directory is created under the rule path.",
                        "'fake' is NOT a placeholder — it is the tenant id Loki hardcodes when",
                        "auth_enabled is false (single-tenant mode), and the ruler reads rules",
                        "from <rule_path>/<tenant>/. Renaming it makes the ruler look in a",
                        "directory nothing writes to, which presents as 'no rules loaded'.",
                        "Change this only alongside enabling multi-tenancy.",
                    ],
                ),
                "loki_ruler_evaluation_interval": OptionSpec(
                    type="str",
                    required=False,
                    default="1m",
                    description=[
                        "How often the ruler evaluates its rule groups. The floor on how fast a",
                        "log alert can go pending, so a rule's `for:` is this plus the delay.",
                    ],
                ),
                "loki_ruler_enable_api": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=[
                        "Serve the ruler's HTTP API (/loki/api/v1/rules). ON deliberately: it is",
                        "the ONLY authoritative read-back of what the ruler actually loaded, and",
                        "a rule file on disk that the ruler never read is worth nothing. With it",
                        "off, 'the rules are live' can only ever be inferred from the write.",
                        "The API is READ-ONLY in this configuration, and that is a property of",
                        "Loki: with `storage.type: local` the write half is not implemented —",
                        "DELETE on a rule group answers HTTP 500 'DeleteRuleGroup unsupported in",
                        "rule local store'. So enabling this cannot expose rule mutation over HTTP; it",
                        "exposes exactly the read-back that proves what the ruler loaded.",
                        "One consequence worth knowing: because deletes are unsupported, removing",
                        "an owner's rules needs a Loki RESTART to clear the group from the running",
                        "ruler — see config_log_alerts_restart_on_remove.",
                    ],
                ),
            },
        ),
    }
)
