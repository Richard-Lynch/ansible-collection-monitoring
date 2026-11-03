# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Deploy Uptime Kuma, loopback-bound by default (dead-man heartbeat receiver)",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "uptime_kuma_container_name": OptionSpec(
                    type="str",
                    required=False,
                    default="uptime-kuma",
                    description=["Container name."],
                ),
                "uptime_kuma_image": OptionSpec(
                    type="str",
                    required=False,
                    default="louislam/uptime-kuma:2.5.3",
                    description=[
                        "Image, PINNED to a specific tag — never 'latest' (and not the floating '2',",
                        "which moves to whatever 2.x is newest). Bump deliberately.",
                    ],
                ),
                "uptime_kuma_deploy_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="/opt/uptime-kuma",
                    description=["Directory holding the compose file on the target host."],
                ),
                "uptime_kuma_data_dir": OptionSpec(
                    type="str",
                    required=False,
                    default="/opt/uptime-kuma/data",
                    description=[
                        "Bind mount for Kuma's SQLite DB + uploads. A named Docker volume would be",
                        "equally valid; a bind mount is used so the data is visible/backuppable from",
                        "the host without reaching into the volume store.",
                    ],
                ),
                "uptime_kuma_host_port": OptionSpec(
                    type="int",
                    required=False,
                    default=3001,
                    description=["Host port the web UI (+ push-monitor HTTP endpoint) listens on."],
                ),
                "uptime_kuma_bind_address": OptionSpec(
                    type="str",
                    required=False,
                    default="127.0.0.1",
                    description=[
                        "Interface the host port is published on. Defaults to loopback ONLY — a fresh",
                        "install has NO admin account until first-run setup completes, so an",
                        "unclaimed Kuma on a reachable interface (worst case a public host with no",
                        "host firewall) can be claimed by whoever finds it first. Takes effect only",
                        "together with the explicit uptime_kuma_publish_publicly flag below, so the",
                        "publish decision stays a single, auditable switch. See the role README for",
                        "the tunnel alternative.",
                    ],
                ),
                "uptime_kuma_publish_publicly": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Explicit opt-in to bind the UI to 0.0.0.0 instead of 127.0.0.1. Leave false",
                        "and front Kuma with a tunnel/reverse proxy instead unless you have a",
                        "specific reason to expose it directly and have completed first-run admin",
                        "setup immediately after deploy.",
                    ],
                ),
                "uptime_kuma_network_mode": OptionSpec(
                    type="str",
                    required=False,
                    default="bridge",
                    description=[
                        "Docker network mode. 'bridge' (default) keeps the container isolated from",
                        "the host's other ports, so it cannot collide with another service that uses",
                        "'host' networking on the same box.",
                    ],
                ),
            },
        )
    }
)
