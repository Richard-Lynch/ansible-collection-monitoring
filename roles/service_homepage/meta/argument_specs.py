# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations
from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec
DEFAULT_AUTHOR = "Collection maintainers"

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Deploy gethomepage/homepage as a validated links-and-widgets dashboard",
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "homepage_container_name": OptionSpec(
                    type="str", required=False, description=["Container name."]
                ),
                "homepage_image": OptionSpec(
                    type="str",
                    required=False,
                    description=["gethomepage/homepage image tag. Pinned — never :latest."],
                ),
                "homepage_config_dir": OptionSpec(
                    type="str", required=False, description=["Host config dir."]
                ),
                "homepage_network": OptionSpec(
                    type="str",
                    required=False,
                    description=["Shared external docker network the container joins."],
                ),
                "homepage_host_port": OptionSpec(
                    type="int",
                    required=False,
                    description=["Host port -> container's 3000, for a reverse proxy to front."],
                ),
                "homepage_puid": OptionSpec(
                    type="int", required=False, description=["Container PUID."]
                ),
                "homepage_pgid": OptionSpec(
                    type="int", required=False, description=["Container PGID."]
                ),
                "homepage_umask": OptionSpec(
                    type="str", required=False, description=["Container UMASK."]
                ),
                "homepage_tz": OptionSpec(
                    type="str", required=False, description=["Container timezone."]
                ),
                "homepage_allowed_hosts": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Comma-separated HOMEPAGE_ALLOWED_HOSTS value — homepage rejects requests whose",
                        "Host header isn't in this list. Set every name the page is reached by. Empty",
                        "leaves homepage's own default (localhost only).",
                    ],
                ),
                "homepage_title": OptionSpec(
                    type="str", required=False, description=["Dashboard title (settings.yaml)."]
                ),
                "homepage_description": OptionSpec(
                    type="str",
                    required=False,
                    description=["Dashboard description (settings.yaml)."],
                ),
                "homepage_instance_name": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Dashboard instanceName (settings.yaml, aids multi-instance auto-discovery)."
                    ],
                ),
                "homepage_sonarr_api_key": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "Sonarr API key for the Sonarr service-card widget, from a secret store.",
                        "Empty string omits the widget's key field entirely (renders a plain link card",
                        # NEVER put literal Jinja delimiters in a description. Ansible TEMPLATES the
                        # argspec, so a documentation mention of a Jinja tag is parsed as real Jinja and
                        # fails the whole role at validate_argument_spec time, before any task runs.
                        "instead of a broken widget) — see the conditional guards in services.yaml.j2.",
                    ],
                ),
                "homepage_radarr_api_key": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "Radarr API key, same empty-string-omits-the-widget handling as homepage_sonarr_api_key."
                    ],
                ),
                "homepage_prowlarr_api_key": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "Prowlarr API key, same empty-string-omits-the-widget handling as homepage_sonarr_api_key."
                    ],
                ),
                "homepage_sabnzbd_api_key": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "SABnzbd API key, same empty-string-omits-the-widget handling as homepage_sonarr_api_key."
                    ],
                ),
                "homepage_proxmox_token_id": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Proxmox API token ID, for a caller's services.yaml.j2 that renders Proxmox",
                        "node widgets. The role's own default page does not read it.",
                    ],
                ),
                "homepage_proxmox_token_secret": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "Matching Proxmox API token secret. Same not-yet-wired status as homepage_proxmox_token_id."
                    ],
                ),
                "homepage_homeassistant_token": OptionSpec(
                    type="str",
                    required=False,
                    no_log=True,
                    description=[
                        "Home Assistant long-lived access token for its widget, from a secret store.",
                        "Empty string omits the widget's key field, same handling as the keys above.",
                    ],
                ),
                "homepage_config_src": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "Controller directory of config templates (services, settings, bookmarks,",
                        "widgets, docker; .yaml or .yaml.j2) that REPLACES the role's default set.",
                        "Empty deploys the role's default: an empty page. The cards are installation",
                        "data, so they live with the caller.",
                    ],
                ),
                "homepage_forbidden_href_patterns": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    description=[
                        "Regexes no service card href may match — hosts known to be dead or retired,",
                        "which a later edit could plausibly re-add. Checked before every deploy.",
                    ],
                ),
                "homepage_bookmarks_forbidden_href_pattern": OptionSpec(
                    type="str",
                    required=False,
                    description=[
                        "One regex no bookmark href may match — typically your own domain, since a",
                        "link there belongs in services.yaml as a card with its siteMonitor. Empty",
                        "checks nothing.",
                    ],
                ),
            },
        )
    }
)
