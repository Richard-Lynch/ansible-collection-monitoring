# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Deploy Grafana (Postgres backend, provisioned datasources) on a shared net",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "grafana_container_name": OptionSpec(
                    type="str", required=False, description=["Container name."]
                ),
                "grafana_image_version": OptionSpec(
                    type="str",
                    required=False,
                    default="12.1.1",
                    description=["grafana-oss image tag."],
                ),
                "grafana_host_port": OptionSpec(
                    type="int", required=False, description=["Host port → 3000 (0 = none)."]
                ),
                "grafana_admin_user": OptionSpec(
                    type="str", required=False, description=["Admin username."]
                ),
                "grafana_admin_password": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=["Admin password (from a secret store; placeholder rejected)."],
                ),
                "grafana_server_root_url": OptionSpec(
                    type="str", required=False, description=["GF_SERVER_ROOT_URL."]
                ),
                "grafana_network": OptionSpec(
                    type="str",
                    required=False,
                    default="monitoring",
                    description=["Shared external docker network."],
                ),
                "grafana_db_host": OptionSpec(
                    type="str", required=False, description=["Postgres host (container name)."]
                ),
                "grafana_db_port": OptionSpec(
                    type="int", required=False, description=["Postgres port."]
                ),
                "grafana_db_name": OptionSpec(
                    type="str", required=False, description=["Grafana database name."]
                ),
                "grafana_db_user": OptionSpec(
                    type="str", required=False, description=["Grafana DB role."]
                ),
                "grafana_db_password": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "Grafana DB role password (from a secret store; placeholder rejected)."
                    ],
                ),
                "grafana_dashboards_src": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Controller directory of dashboard JSON files to provision (copied into the",
                        "provisioner's directory). Empty ships none: dashboards are installation data.",
                    ],
                ),
                "grafana_dashboards_folder": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Grafana folder for the provisioned dashboards. Never 'General', which Grafana",
                        "already owns: provisioning into it fails and loads no dashboard at all.",
                    ],
                ),
            },
        )
    }
)
