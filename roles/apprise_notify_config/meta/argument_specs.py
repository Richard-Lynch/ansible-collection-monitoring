# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Configure an Apprise config-id with HA / email / Slack targets",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "apprise_notify_base_url": OptionSpec(
                    type="str", required=False, description=["Apprise API base URL."]
                ),
                "apprise_notify_config_id": OptionSpec(
                    type="str",
                    required=False,
                    description=["Stateful config-id (Alertmanager notify target)."],
                ),
                "apprise_notify_ha_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=["Enable the Home Assistant target."],
                ),
                "apprise_notify_ha_host": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "HA host (installation config, no default). Empty skips the HA target."
                    ],
                ),
                "apprise_notify_ha_port": OptionSpec(
                    type="int", required=False, description=["HA port."]
                ),
                "apprise_notify_ha_token": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "HA long-lived token, resolved by the caller from its secret store. Empty "
                        "skips the HA target."
                    ],
                ),
                "apprise_notify_email_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=True,
                    description=["Enable the email target."],
                ),
                "apprise_notify_email_user": OptionSpec(
                    type="str", required=False, description=["SMTP/Gmail sender address."]
                ),
                "apprise_notify_email_password": OptionSpec(
                    type="str", required=False, no_log=True, description=["Email app password."]
                ),
                "apprise_notify_email_to": OptionSpec(
                    type="str", required=False, description=["Destination address."]
                ),
                "apprise_notify_slack_enabled": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=["Enable the Slack target."],
                ),
                "apprise_notify_slack_url": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=["Apprise slack:// URL / webhook path."],
                ),
            },
        )
    }
)
