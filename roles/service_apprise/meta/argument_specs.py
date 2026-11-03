# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Deploy the Apprise notification API, optionally behind Traefik",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "apprise_container_name": OptionSpec(
                    type="str", required=False, description=["Container name."]
                ),
                "apprise_image": OptionSpec(
                    type="str", required=False, description=["caronc/apprise image tag."]
                ),
                "apprise_stateful_mode": OptionSpec(
                    type="str",
                    required=False,
                    description=["APPRISE_STATEFUL_MODE (simple/hash/disabled)."],
                ),
                "apprise_network": OptionSpec(
                    type="str", required=False, description=["Shared monitoring docker network."]
                ),
                "apprise_traefik_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=["Expose via Traefik (only on a host running Traefik)."],
                ),
                "apprise_host_port": OptionSpec(
                    type="int",
                    required=False,
                    description=["Host port for the API when not behind Traefik."],
                ),
                "apprise_bind_address": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Interface the host port is published on; empty means every interface.",
                        "apprise-api is unauthenticated, so bind a private address on a public host.",
                    ],
                ),
                "apprise_traefik_network": OptionSpec(
                    type="str", required=False, description=["Traefik external network."]
                ),
                "apprise_traefik_host": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Traefik Host() rule (FQDN). Required when apprise_traefik_enabled."
                    ],
                ),
                "apprise_config_dir": OptionSpec(
                    type="str", required=False, description=["Host config dir."]
                ),
                "apprise_puid": OptionSpec(
                    type="int", required=False, description=["Container PUID."]
                ),
                "apprise_pgid": OptionSpec(
                    type="int", required=False, description=["Container PGID."]
                ),
                "apprise_tz": OptionSpec(
                    type="str", required=False, description=["Container timezone."]
                ),
            },
        )
    }
)
