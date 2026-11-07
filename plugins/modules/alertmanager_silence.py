#!/usr/bin/python
# -*- coding: utf-8 -*-
# Copyright: (c) 2026, Richard Lynch
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
---
module: alertmanager_silence
short_description: Manage one Alertmanager silence as desired state
version_added: "1.1.0"
description:
  - Create, refresh or expire one Alertmanager silence, found by its identity (O(comment) plus the
    matcher set), never by its server-generated id.
  - Idempotent, with honest C(changed), C(--check) and C(--diff). Replaces the C(uri) loops that
    expired and re-created silences on every run.
  - Built on C(richard_lynch.common) (C(DesiredState), C(FetchUrlTransport)) - read, compare the
    normalized state, write once, read back, report drift.
extends_documentation_fragment:
  - richard_lynch.common.http_connection
options:
  token:
    description:
      - Optional bearer token, for an Alertmanager behind an authenticating proxy. Alertmanager
        itself has no authentication.
    type: str
    required: false
  matchers:
    description:
      - The matchers of the silence. Alertmanager ANDs them, so "any of these" is one silence per
        matcher (one task per matcher via C(loop)).
    type: list
    elements: dict
    required: true
    suboptions:
      name:
        description: Label name.
        type: str
        required: true
      value:
        description: Label value, or a regular expression when O(matchers[].is_regex=true).
        type: str
        required: true
      is_regex:
        description: Match the value as a regular expression.
        type: bool
        default: false
      is_equal:
        description: Equality match (V(true)) or negation (V(false)).
        type: bool
        default: true
  comment:
    description:
      - The silence's comment, and half of its identity. Use a stable tag the play owns, for
        example C(app-build-silence); a later run finds the silence by it.
    type: str
    required: true
  ends_at:
    description:
      - When the silence ends, RFC 3339 (for example C(2026-11-07T23:59:00Z)). Compared to the
        minute, so a re-run computing "end of today" is not a change.
      - Required for O(state=present).
    type: str
  starts_at:
    description:
      - When the silence starts, RFC 3339. Defaults to now. Not part of the compared state, since
        an active silence's start time is when it was made.
    type: str
  created_by:
    description: Alertmanager's C(createdBy) field.
    type: str
    default: ansible
  state:
    description:
      - V(present) ensures an active silence with this identity ends at O(ends_at) (refreshing it
        in one write when it does not); V(absent) expires every active silence with this identity.
    type: str
    choices: [present, absent]
    default: present
notes:
  - Identity is O(comment) plus the normalized matcher set. Two active silences with the same
    identity are duplicates; the newest is the resource and the others are listed in
    RV(duplicates) and expired by O(state=absent).
  - A refresh posts the existing id, which Alertmanager handles as "expire the old, create the
    new" in one call, so the record's id changes while the state converges.
attributes:
  check_mode:
    support: full
  diff_mode:
    support: full
author:
  - Richard Lynch (@Richard-Lynch)
"""

EXAMPLES = r"""
- name: Silence every alert of one application until the end of today
  richard_lynch.monitoring.alertmanager_silence:
    url: http://127.0.0.1:9093
    comment: "app-build-silence: alerts muted while the application's build runs its proofs"
    matchers:
      - { name: "{{ item.name }}", value: "{{ item.value }}", is_regex: true }
    ends_at: "{{ '%Y-%m-%dT%H:%M:%SZ' | strftime(_ends_epoch | int, utc=true) }}"
    created_by: ansible/app_alert_silence
  loop:
    - { name: alertname, value: "App.*|AppEdge.*" }
    - { name: service_name, value: "app.*" }

- name: Lift a lab's silence
  richard_lynch.monitoring.alertmanager_silence:
    url: http://127.0.0.1:9093
    comment: "dns-lab"
    matchers:
      - { name: lab, value: dns }
    state: absent
"""

RETURN = r"""
changed:
  description: Whether a write was made (or, in check mode, would be).
  type: bool
  returned: always
action:
  description: "What was done: C(create), C(update), C(delete) or C(none)."
  type: str
  returned: always
resource:
  description: The normalized silence after the write (the read-back), or the prediction in check mode.
  type: dict
  returned: always
diff:
  description: Normalized C(before) and C(after).
  type: dict
  returned: always
applied:
  description: Whether a write reached Alertmanager (C(false) in check mode and when nothing was to do).
  type: bool
  returned: always
duplicates:
  description: Ids of other active silences with the same identity, beyond the one taken as the resource.
  type: list
  returned: always
"""

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.richard_lynch.common.plugins.module_utils import (
    require_common,
)
from ansible_collections.richard_lynch.common.plugins.module_utils.args import (
    http_argument_spec,
)
from ansible_collections.richard_lynch.common.plugins.module_utils.desired_state import (
    DesiredState,
)
from ansible_collections.richard_lynch.common.plugins.module_utils.transport import (
    FetchUrlTransport,
)
from ansible_collections.richard_lynch.monitoring.plugins.module_utils.alertmanager.client import (
    AlertmanagerClient,
    SilenceResource,
    normalize_matchers,
    parse_time,
    round_to_minute,
)

EXTRA = {
    "matchers": {
        "type": "list",
        "elements": "dict",
        "required": True,
        "options": {
            "name": {"type": "str", "required": True},
            "value": {"type": "str", "required": True},
            "is_regex": {"type": "bool", "default": False},
            "is_equal": {"type": "bool", "default": True},
        },
    },
    "comment": {"type": "str", "required": True},
    "ends_at": {"type": "str"},
    "starts_at": {"type": "str"},
    "created_by": {"type": "str", "default": "ansible"},
    "state": {"type": "str", "choices": ["present", "absent"], "default": "present"},
}


def _check_time(module, name, value):
    if value is None:
        return
    try:
        parse_time(value)
    except (ValueError, TypeError):
        module.fail_json(msg="%s is not an RFC 3339 timestamp: %r" % (name, value))


def main():
    module = AnsibleModule(
        argument_spec=http_argument_spec(token_required=False, extra=EXTRA),
        supports_check_mode=True,
        required_if=[("state", "present", ("ends_at",))],
    )
    require_common(">=1.0,<2")
    p = module.params
    _check_time(module, "ends_at", p["ends_at"])
    _check_time(module, "starts_at", p["starts_at"])

    client = AlertmanagerClient(
        FetchUrlTransport(module), p["url"], token=p["token"], timeout=p["timeout"]
    )
    resource = SilenceResource(
        client, comment=p["comment"], matchers=p["matchers"], starts_at=p["starts_at"]
    )
    desired = None
    if p["state"] == "present":
        desired = {
            "comment": p["comment"],
            "created_by": p["created_by"],
            "ends_at": round_to_minute(p["ends_at"]),
            "matchers": normalize_matchers(p["matchers"]),
        }

    # DesiredState exits the module itself; `duplicates` rides along through exit_json's kwargs.
    original_exit = module.exit_json

    def exit_json(**result):
        result.setdefault("duplicates", sorted(resource.duplicates_seen))
        original_exit(**result)

    module.exit_json = exit_json
    DesiredState(module, resource, p["state"], desired).run()


if __name__ == "__main__":
    main()
