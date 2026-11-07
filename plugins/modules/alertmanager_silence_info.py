#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Richard Lynch
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: alertmanager_silence_info
short_description: List Alertmanager silences
version_added: "1.1.0"
description:
  - Read Alertmanager's silences, optionally filtered by state and by a substring of the comment.
  - Read-only; a play asserts on RV(silences) instead of parsing C(uri) output.
extends_documentation_fragment:
  - richard_lynch.common.http_connection
options:
  token:
    description: Optional bearer token, for an Alertmanager behind an authenticating proxy.
    type: str
    required: false
  state:
    description: Keep only silences in these states (Alertmanager's C(status.state)).
    type: list
    elements: str
    choices: [active, pending, expired]
  comment_contains:
    description: Keep only silences whose comment contains this text.
    type: str
attributes:
  check_mode:
    support: full
author:
  - Richard Lynch (@Richard-Lynch)
"""

EXAMPLES = r"""
- name: Which of the application's silences are active
  richard_lynch.monitoring.alertmanager_silence_info:
    url: http://127.0.0.1:9093
    state: [active, pending]
    comment_contains: app-build-silence
  register: _hub_silences
"""

RETURN = r"""
silences:
  description: The matching silences, normalized (comment, created_by, ends_at to the minute, sorted matchers) plus id, state, starts_at.
  type: list
  elements: dict
  returned: always
summary:
  description: Counts per state over the matching silences.
  type: dict
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.richard_lynch.common.plugins.module_utils import (
    require_common,
)
from ansible_collections.richard_lynch.common.plugins.module_utils.args import (
    http_argument_spec,
)
from ansible_collections.richard_lynch.common.plugins.module_utils.errors import (
    CommonError,
)
from ansible_collections.richard_lynch.common.plugins.module_utils.transport import (
    FetchUrlTransport,
)
from ansible_collections.richard_lynch.monitoring.plugins.module_utils.alertmanager.client import (
    AlertmanagerClient,
    normalize_matchers,
    round_to_minute,
)

EXTRA = {
    "state": {
        "type": "list",
        "elements": "str",
        "choices": ["active", "pending", "expired"],
    },
    "comment_contains": {"type": "str"},
}


def main():
    module = AnsibleModule(
        argument_spec=http_argument_spec(token_required=False, extra=EXTRA),
        supports_check_mode=True,
    )
    require_common(">=1.0,<2")
    p = module.params
    client = AlertmanagerClient(
        FetchUrlTransport(module), p["url"], token=p["token"], timeout=p["timeout"]
    )
    try:
        raw = client.list_silences()
    except CommonError as e:
        module.fail_json(msg="could not list silences: %s" % e, error=e.to_dict())
        return
    out = []
    for s in raw:
        state = str((s.get("status") or {}).get("state") or "")
        if p["state"] and state not in p["state"]:
            continue
        if p["comment_contains"] and p["comment_contains"] not in str(s.get("comment") or ""):
            continue
        out.append(
            {
                "id": str(s.get("id") or ""),
                "state": state,
                "comment": str(s.get("comment") or ""),
                "created_by": str(s.get("createdBy") or ""),
                "starts_at": str(s.get("startsAt") or ""),
                "ends_at": round_to_minute(str(s["endsAt"])) if s.get("endsAt") else "",
                "matchers": normalize_matchers(s.get("matchers") or []),
            }
        )
    summary = {}
    for s in out:
        summary[s["state"]] = summary.get(s["state"], 0) + 1
    module.exit_json(changed=False, silences=out, summary=summary)


if __name__ == "__main__":
    main()
