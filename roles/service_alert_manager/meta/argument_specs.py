# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

DEFAULT_AUTHOR = "Collection maintainers"
from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Deploy Prometheus Alertmanager routing to Apprise, with an external heartbeat",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "alertmanager_container_name": OptionSpec(
                    type="str", required=False, description=["Container name."]
                ),
                "alertmanager_image": OptionSpec(
                    type="str",
                    required=False,
                    description=["prom/alertmanager image tag."],
                ),
                "alertmanager_host_port": OptionSpec(
                    type="int", required=False, description=["Host port → 9093."]
                ),
                "alertmanager_bind_address": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Interface the host port is published on; empty means every interface.",
                        "Alertmanager is unauthenticated, so bind a private address on a public host.",
                    ],
                ),
                "alertmanager_inhibit_rules": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    description=[
                        "Alertmanager inhibit_rules (source_matchers / target_matchers / equal),",
                        "rendered verbatim. Empty means no inhibition.",
                    ],
                ),
                "alertmanager_discard_routes": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    description=[
                        "Child routes whose alerts reach Alertmanager but notify NOBODY, each a dict",
                        "of `matchers` (Alertmanager matcher strings, ANDed) and `reason`. For",
                        "alerts that exist to prove delivery (firing proofs). Empty means none.",
                    ],
                ),
                "alertmanager_network": OptionSpec(
                    type="str",
                    required=False,
                    description=["Shared monitoring network."],
                ),
                "alertmanager_config_dir": OptionSpec(
                    type="str", required=False, description=["Host config dir."]
                ),
                "alertmanager_resolve_timeout": OptionSpec(
                    type="str", required=False, description=["global.resolve_timeout."]
                ),
                "alertmanager_apprise_url": OptionSpec(
                    type="str", required=False, description=["Apprise base URL."]
                ),
                "alertmanager_apprise_config_id": OptionSpec(
                    type="str",
                    required=False,
                    description=["Apprise stateful config-id (notify target)."],
                ),
                "alertmanager_apprise_format": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Apprise notify format for the rendered payload (text|markdown|html)."
                    ],
                ),
                "alertmanager_group_wait": OptionSpec(
                    type="str", required=False, description=["route.group_wait."]
                ),
                "alertmanager_group_interval": OptionSpec(
                    type="str", required=False, description=["route.group_interval."]
                ),
                "alertmanager_repeat_interval": OptionSpec(
                    type="str", required=False, description=["route.repeat_interval."]
                ),
                "alertmanager_notification_footer": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Last line of every notification body (e.g. where to start investigating).",
                        "Plain text inside a Go template, so it must not contain Go template delimiters",
                        "(double braces). Empty = none.",
                    ],
                ),
                # --- dead-man heartbeat (external watchdog) ---
                "alertmanager_heartbeat_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    description=[
                        "Route the always-firing Watchdog alert to an EXTERNAL heartbeat receiver.",
                        "When false the Watchdog still fires but goes only to Apprise, which shares a",
                        "failure domain with the stack it is meant to be watching.",
                    ],
                ),
                "alertmanager_heartbeat_url": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Push URL of the external heartbeat monitor (e.g. an Uptime Kuma push check",
                        "hosted OFF the monitored site). Alertmanager POSTs here every repeat_interval",
                        "while the Watchdog fires; if the pushes stop, that service alerts.",
                        "MUST NOT resolve to anything inside the monitored site, or it cannot report",
                        "the site's own death.",
                    ],
                ),
                "alertmanager_heartbeat_interval": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "How often the Watchdog re-notifies the heartbeat (route.repeat_interval for that branch)."
                    ],
                ),
                # --- Cloudflare Access mTLS for the heartbeat webhook ---
                # See this role's README "Heartbeat transport" for why mTLS (not a service-token
                # header pair): two Cloudflare Access service-token headers cannot be carried by
                # either single-value auth option of the webhook http_config, while mTLS maps
                # directly onto tls_config.cert_file/key_file.
                "alertmanager_heartbeat_mtls_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    description=[
                        "Present a client certificate (Cloudflare Access mTLS) on the heartbeat POST.",
                        "Required if the heartbeat URL is a Cloudflare Access-protected hostname (the",
                        "same tunnel+hostname the Kuma UI uses) rather than an unprotected path or a",
                        "static-IP-allowlisted one. Off by default — choose a transport explicitly",
                        '(this role\'s README, "Heartbeat transport").',
                    ],
                ),
                "alertmanager_heartbeat_mtls_cert": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "PEM client certificate content for Cloudflare Access mTLS, from a secret store.",
                        "Written to a file under alertmanager_config_dir and referenced via tls_config",
                        "in the rendered alertmanager.yml. Never logged (no_log on the writing task).",
                    ],
                ),
                "alertmanager_heartbeat_mtls_key": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "PEM client private key content matching alertmanager_heartbeat_mtls_cert.",
                        "Same handling as the cert: written to a 0600 file, never logged.",
                    ],
                ),
            },
        )
    }
)
