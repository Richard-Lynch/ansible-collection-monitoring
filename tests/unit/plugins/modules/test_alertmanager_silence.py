# Copyright: (c) 2026, Richard Lynch
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
"""alertmanager_silence / alertmanager_silence_info against the fake Alertmanager.

What the `uri`-loop plays this module replaces got wrong, each pinned here as a case that was RED
against that approach and is GREEN against the module: a re-run re-created every silence (not
idempotent: `test_rerun_is_not_a_change`); "refresh" was expire-then-create, two writes with a gap
(`test_refresh_is_one_write_that_replaces`); the silence was found by a comment SUBSTRING, so two
plays sharing a word collided (`test_identity_is_comment_and_matchers`); nothing was read back
(`test_read_back_drift_is_a_failure`); and a token in the URL's auth header could reach the log
(`test_token_never_in_output`).
"""

from __future__ import annotations

import datetime
import json

import pytest
from ansible_collections.richard_lynch.monitoring.plugins.module_utils.alertmanager import (
    client as c,
)
from ansible_collections.richard_lynch.monitoring.plugins.modules import (
    alertmanager_silence,
    alertmanager_silence_info,
)


def _in(minutes):
    when = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=minutes)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _args(am, **over):
    base = {
        "url": am.url,
        "comment": "app-build-silence: proofs running",
        "matchers": [{"name": "alertname", "value": "App.*", "is_regex": True}],
        "ends_at": _in(90),
        "created_by": "ansible/test",
    }
    base.update(over)
    return base


def _active(am):
    return [s for s in am.am.listing() if s["status"]["state"] != "expired"]


# -- the resource model --------------------------------------------------------------------------


def test_normalize_matchers_is_canonical_and_order_free():
    a = c.normalize_matchers(
        [{"name": "b", "value": "2"}, {"name": "a", "value": "1", "isRegex": True}]
    )
    b = c.normalize_matchers(
        [{"name": "a", "value": "1", "is_regex": True}, {"name": "b", "value": "2"}]
    )
    assert a == b
    assert a[0] == {"name": "a", "value": "1", "isRegex": True, "isEqual": True}


def test_time_parsing_accepts_alertmanager_shapes():
    assert c.round_to_minute("2026-11-07T23:59:40.123456789Z") == "2026-11-07T23:59:00Z"
    assert c.round_to_minute("2026-11-07T23:59:40+01:00") == "2026-11-07T22:59:00Z"
    with pytest.raises(ValueError):
        c.parse_time("tomorrow")


# -- the module ----------------------------------------------------------------------------------


def test_create_then_rerun_is_not_a_change(alertmanager, run_module):
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager))
    assert kind == "exit", r
    assert r["changed"] is True and r["action"] == "create" and r["applied"] is True
    assert len(_active(alertmanager)) == 1
    assert r["resource"]["matchers"][0]["isRegex"] is True

    kind, r2 = run_module(alertmanager_silence.main, _args(alertmanager))
    assert kind == "exit", r2
    assert r2["changed"] is False and r2["action"] == "none"
    assert len(_active(alertmanager)) == 1, "a re-run must not create a duplicate"
    assert alertmanager.am.posts == 1


def test_rerun_with_a_new_start_time_is_not_a_change(alertmanager, run_module):
    run_module(alertmanager_silence.main, _args(alertmanager, starts_at=_in(-5)))
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, starts_at=_in(0)))
    assert kind == "exit" and r["changed"] is False, r


def test_refresh_is_one_write_that_replaces(alertmanager, run_module):
    run_module(alertmanager_silence.main, _args(alertmanager, ends_at=_in(30)))
    before = _active(alertmanager)[0]["id"]
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, ends_at=_in(120)))
    assert kind == "exit", r
    assert r["changed"] is True and r["action"] == "update"
    assert r["diff"]["before"]["ends_at"] != r["diff"]["after"]["ends_at"]
    active = _active(alertmanager)
    assert len(active) == 1 and active[0]["id"] != before, "the old record is expired, one new one"
    assert (
        alertmanager.am.posts == 2
    ), "a refresh is ONE POST carrying the old id, not expire+create"


def test_absent_expires_the_silence_and_every_duplicate(alertmanager, run_module):
    am = alertmanager.am
    for _copy in range(2):  # two duplicates with the same identity, as the old plays left behind
        am.post(
            {
                "matchers": [{"name": "alertname", "value": "App.*", "isRegex": True}],
                "startsAt": _in(-1),
                "endsAt": _in(60),
                "createdBy": "x",
                "comment": "app-build-silence: proofs running",
            }
        )
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, state="absent"))
    assert kind == "exit", r
    assert r["changed"] is True and r["action"] == "delete"
    assert r["duplicates"] and len(r["duplicates"]) == 1
    assert _active(alertmanager) == []
    kind, r2 = run_module(alertmanager_silence.main, _args(alertmanager, state="absent"))
    assert kind == "exit" and r2["changed"] is False


def test_identity_is_comment_and_matchers(alertmanager, run_module):
    run_module(alertmanager_silence.main, _args(alertmanager))
    # same comment, a different matcher set: a DIFFERENT silence (one task per matcher set)
    kind, r = run_module(
        alertmanager_silence.main,
        _args(
            alertmanager,
            matchers=[{"name": "hostname", "value": "app.*", "is_regex": True}],
        ),
    )
    assert kind == "exit" and r["action"] == "create"
    # a comment that merely CONTAINS the tag is not ours (the old substring match collided here)
    kind, r = run_module(
        alertmanager_silence.main, _args(alertmanager, comment="app-build-silence")
    )
    assert kind == "exit" and r["action"] == "create"
    assert len(_active(alertmanager)) == 3


def test_check_mode_writes_nothing_and_predicts(alertmanager, run_module):
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager), check_mode=True)
    assert kind == "exit", r
    assert r["changed"] is True and r["applied"] is False and r.get("predicted") is True
    assert _active(alertmanager) == [] and alertmanager.am.posts == 0


def test_read_back_drift_is_a_failure(alertmanager, run_module, monkeypatch):
    # The server "accepts" the write but stores a different end time: the module must not report
    # the desired state as applied.
    am = alertmanager.am
    real_post = am.post

    def lying_post(body):
        body = dict(body)
        body["endsAt"] = _in(5)
        return real_post(body)

    monkeypatch.setattr(am, "post", lying_post)
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, ends_at=_in(90)))
    assert kind == "fail", r
    assert r["applied"] is True and "remaining" in r and "ends_at" in r["remaining"]


def test_api_rejection_is_a_clear_failure(alertmanager, run_module):
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, ends_at=_in(-10)))
    assert kind == "fail", r
    assert "400" in json.dumps(r) or "rejected" in r["msg"]
    assert _active(alertmanager) == []


def test_bad_timestamp_is_refused_before_any_request(alertmanager, run_module):
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, ends_at="tomorrow"))
    assert kind == "fail" and "RFC 3339" in r["msg"]
    assert alertmanager.am.requests == []


def test_token_never_in_output(alertmanager, run_module, good_token):
    GOOD_TOKEN = good_token
    am = alertmanager.am
    am.require_token = True
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, token=GOOD_TOKEN))
    assert kind == "exit" and r["changed"] is True
    assert GOOD_TOKEN not in json.dumps(r)
    # the wrong token: the server echoes it in its error body, the module must not
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager, token="tok-wrong-value"))
    assert kind == "fail", r
    assert "tok-wrong-value" not in json.dumps(r)


def test_unparseable_listing_is_a_failure_not_absent(alertmanager, run_module):
    alertmanager.am.fail_next = (200, "plain text, not json")
    kind, r = run_module(alertmanager_silence.main, _args(alertmanager))
    assert kind == "fail", r
    assert r["applied"] is False and alertmanager.am.posts == 0


# -- the info module ------------------------------------------------------------------------------


def test_info_lists_and_filters(alertmanager, run_module):
    run_module(alertmanager_silence.main, _args(alertmanager))
    run_module(
        alertmanager_silence.main,
        _args(
            alertmanager,
            comment="dns-lab",
            matchers=[{"name": "lab", "value": "dns"}],
        ),
    )
    kind, r = run_module(alertmanager_silence_info.main, {"url": alertmanager.url})
    assert kind == "exit" and r["changed"] is False
    assert r["summary"] == {"active": 2}
    kind, r = run_module(
        alertmanager_silence_info.main,
        {"url": alertmanager.url, "comment_contains": "dns-lab", "state": ["active"]},
    )
    assert [s["comment"] for s in r["silences"]] == ["dns-lab"]
    assert r["silences"][0]["matchers"] == [
        {"name": "lab", "value": "dns", "isRegex": False, "isEqual": True}
    ]
