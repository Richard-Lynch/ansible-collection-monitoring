# Copyright: (c) 2026, Richard Lynch
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
"""Alertmanager v2 silences as a desired-state Resource (richard_lynch.common ADR-C9/C11).

Pure Python: the only dependency is a ``Transport`` injected by the caller, so the same client runs
inside a module (``FetchUrlTransport``), from a script (``UrllibTransport``) and under the unit
tests' fake server. Nothing here imports Ansible.

THE RESOURCE MODEL (docs/resources/alertmanager_silence.md in this collection):

  identity   ``comment`` + the normalized matcher set. Alertmanager generates silence ids, so a
             caller that only knew an id would create a duplicate on every run; the two plays this
             module replaces already found their silences by a comment tag and ``status.state !=
             expired`` (the two plays this module replaces).
  state      the non-expired silence with that identity; several such silences are duplicates and
             the newest one (by ``updatedAt``) is the resource, the rest are reported.
  normalize  matchers sorted by (name, value, isRegex, isEqual); ``endsAt`` rounded to the minute;
             ``comment``; ``createdBy``. Server-managed ``id``, ``status`` and ``updatedAt`` are
             dropped. ``startsAt`` is dropped too: an ACTIVE silence's start time is when it was
             made, and a desired state of "silenced until endsAt" is the same state whenever it was
             asked for -- comparing it would make every re-run ``changed``.
  create     POST /api/v2/silences (sent once: a creating POST is not idempotent).
  update     POST /api/v2/silences with the existing ``id``: Alertmanager expires the old silence
             and stores the replacement in ONE call, so "expire then recreate" is one write.
  delete     DELETE /api/v2/silence/{id} (an expire; the record stays, state ``expired``).
"""

from __future__ import annotations

import datetime
import typing as t

from ansible_collections.richard_lynch.common.plugins.module_utils.errors import (
    ApiError,
    DecodeError,
)
from ansible_collections.richard_lynch.common.plugins.module_utils.transport import (
    bearer,
    call_api,
    join_url,
)

SILENCES = "/api/v2/silences"
SILENCE = "/api/v2/silence/"
# What Alertmanager's own validation says per status, for the error message a play reads.
HINTS = {
    400: "Alertmanager rejected the silence (a matcher must have name and value; endsAt must be "
    "after startsAt and in the future)",
    404: "no silence with that id (it may have been garbage-collected after expiring)",
}
RFC3339 = "%Y-%m-%dT%H:%M:%SZ"


def to_rfc3339(when: datetime.datetime) -> str:
    """Alertmanager's accepted shape: seconds, UTC, trailing Z."""
    return when.astimezone(datetime.timezone.utc).strftime(RFC3339)


def parse_time(text: str) -> datetime.datetime:
    """Parse the RFC3339 forms Alertmanager emits and accepts (nanoseconds and offsets included)."""
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    # Python accepts at most 6 fractional digits.
    if "." in s:
        head, _dot, tail = s.partition(".")
        digits = ""
        i = 0
        while i < len(tail) and tail[i].isdigit():
            digits += tail[i]
            i += 1
        s = head + "." + (digits[:6] or "0") + tail[i:]
    when = datetime.datetime.fromisoformat(s)
    if when.tzinfo is None:
        when = when.replace(tzinfo=datetime.timezone.utc)
    return when


def round_to_minute(text: str) -> str:
    when = parse_time(text).astimezone(datetime.timezone.utc).replace(second=0, microsecond=0)
    return when.strftime(RFC3339)


def normalize_matchers(matchers: t.Iterable[dict]) -> list:
    """Alertmanager's matcher objects as a canonical, order-free list of plain dicts."""
    out = []
    for m in matchers:
        out.append(
            {
                "name": str(m["name"]),
                "value": str(m["value"]),
                "isRegex": bool(m.get("isRegex", m.get("is_regex", False))),
                "isEqual": bool(m.get("isEqual", m.get("is_equal", True))),
            }
        )
    out.sort(key=lambda m: (m["name"], m["value"], m["isRegex"], m["isEqual"]))
    return out


class AlertmanagerClient:
    """GET/POST silences, DELETE one. ``token`` is optional: Alertmanager has no auth of its own,
    and a reverse proxy in front of it may want a bearer."""

    def __init__(self, transport, url: str, *, token: str | None = None, timeout: float = 30.0):
        self.transport = transport
        self.url = url
        self.headers = bearer(token) if token else {}
        self.timeout = timeout

    def _call(self, method: str, path: str, **kw):
        resp = call_api(
            self.transport,
            method,
            join_url(self.url, path),
            headers=self.headers,
            timeout=self.timeout,
            hints=HINTS,
            **kw,
        )
        return resp

    def list_silences(self) -> list:
        resp = self._call("GET", SILENCES)
        data = resp.json()
        if not isinstance(data, list):
            raise DecodeError(
                "GET %s did not return a JSON list" % SILENCES,
                url=join_url(self.url, SILENCES),
                body=resp.text,
            )
        return data

    def post_silence(self, body: dict) -> str:
        resp = self._call("POST", SILENCES, json_body=body)
        data = resp.json()
        sid = data.get("silenceID") if isinstance(data, dict) else None
        if not sid:
            raise DecodeError(
                "POST %s returned no silenceID" % SILENCES,
                url=join_url(self.url, SILENCES),
                body=resp.text,
            )
        return str(sid)

    def expire_silence(self, silence_id: str) -> None:
        self._call("DELETE", SILENCE + silence_id)


def _state(s: dict) -> str:
    status = s.get("status") or {}
    return str(status.get("state") or "")


class SilenceResource:
    """One silence by identity (comment + matchers), for richard_lynch.common.DesiredState."""

    secret_keys = ("token",)

    def __init__(
        self,
        client: AlertmanagerClient,
        *,
        comment: str,
        matchers: t.Iterable[dict],
        starts_at: str | None = None,
    ):
        self.client = client
        self.comment = comment
        self.matchers = normalize_matchers(matchers)
        # Not part of the compared state (see the module docstring): kept on the resource, so a
        # caller's explicit start time reaches the write without making every re-run `changed`.
        self.starts_at = starts_at
        self.duplicates: list = []  # non-expired silences with this identity beyond the newest
        self.current_id: str | None = None
        self.duplicates_seen: set = set()  # every duplicate id any read of this run returned

    # -- Resource protocol ---------------------------------------------------------------------

    def _mine(self, silences: list) -> list:
        out = []
        for s in silences:
            if _state(s) == "expired":
                continue
            if str(s.get("comment") or "") != self.comment:
                continue
            if normalize_matchers(s.get("matchers") or []) != self.matchers:
                continue
            out.append(s)
        out.sort(key=lambda s: str(s.get("updatedAt") or ""), reverse=True)
        return out

    def read(self) -> dict | None:
        mine = self._mine(self.client.list_silences())
        if not mine:
            self.current_id = None
            self.duplicates = []
            return None
        self.current_id = str(mine[0].get("id") or "")
        self.duplicates = [str(s.get("id") or "") for s in mine[1:]]
        self.duplicates_seen.update(self.duplicates)
        return mine[0]

    def normalize(self, raw: dict) -> dict:
        """Alertmanager's record (``endsAt``/``createdBy``) OR an already-normalized desired state
        (``ends_at``/``created_by``, what DesiredState hands back) to the compared shape.
        """
        ends = raw.get("endsAt", raw.get("ends_at"))
        return {
            "comment": str(raw.get("comment") or ""),
            "created_by": str(raw.get("createdBy", raw.get("created_by")) or ""),
            "ends_at": round_to_minute(str(ends)),
            "matchers": normalize_matchers(raw.get("matchers") or []),
        }

    def _body(self, desired: dict, *, silence_id: str | None = None) -> dict:
        body = {
            "matchers": desired["matchers"],
            "startsAt": self.starts_at or to_rfc3339(datetime.datetime.now(datetime.timezone.utc)),
            "endsAt": desired["ends_at"],
            "createdBy": desired["created_by"],
            "comment": desired["comment"],
        }
        if silence_id:
            body["id"] = silence_id
        return body

    def create(self, desired: dict) -> None:
        self.client.post_silence(self._body(desired))

    def update(self, current: dict, desired: dict) -> None:
        # One write: Alertmanager replaces the silence carrying this id (expires the old record).
        self.client.post_silence(self._body(desired, silence_id=self.current_id))

    def delete(self, current: dict) -> None:
        for sid in [self.current_id] + list(self.duplicates):
            if sid:
                try:
                    self.client.expire_silence(sid)
                except ApiError as e:
                    if e.status != 404:  # already gone is the desired state
                        raise
