# Copyright: (c) 2026, Richard Lynch
# GNU General Public License v3.0+ (see https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later
"""A fake Alertmanager (v2 silences API) in a thread, and the module harness.

The fake ENFORCES Alertmanager's rules instead of replaying calls (richard_lynch.common ADR-C5):
ids are server-generated; a POST carrying an existing ``id`` expires that silence and stores the
replacement under a NEW id (what Alertmanager does for an active silence); ``status.state`` is
derived from the clock (pending / active / expired); DELETE expires; a matcher without name or
value, or an ``endsAt`` not after ``startsAt``, is a 400 with the message Alertmanager gives. The
fixture corpus that drives it is in tests/fixtures/alertmanager/ (ADR-C11: the same recordings a Go
provider's httptest handler would read).

``ansible-test units`` puts the collection root on sys.path itself; plain ``pytest`` gets it here.
"""

from __future__ import annotations

import datetime
import http.server
import json
import os
import sys
import threading
import uuid

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
# tests/unit -> monitoring -> richard_lynch -> ansible_collections -> <root>
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

_no_proxy = [p for p in os.environ.get("no_proxy", "").split(",") if p]
for _host in ("127.0.0.1", "localhost"):
    if _host not in _no_proxy:
        _no_proxy.append(_host)
os.environ["no_proxy"] = os.environ["NO_PROXY"] = ",".join(_no_proxy)

GOOD_TOKEN = "tok-fixture-credential-for-unit-tests"


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


def _parse(text):
    s = text.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.datetime.fromisoformat(s)


class FakeAlertmanager:
    def __init__(self):
        self.silences = {}  # id -> record (Alertmanager's shape)
        self.requests = []  # (method, path)
        self.require_token = False
        self.fail_next = None  # (status, body) for the next request
        self.posts = 0

    def state_of(self, rec):
        now = _now()
        if rec.get("_expired") or _parse(rec["endsAt"]) <= now:
            return "expired"
        if _parse(rec["startsAt"]) > now:
            return "pending"
        return "active"

    def listing(self):
        out = []
        for rec in self.silences.values():
            item = {k: v for k, v in rec.items() if not k.startswith("_")}
            item["status"] = {"state": self.state_of(rec)}
            out.append(item)
        out.sort(key=lambda r: r["id"])
        return out

    def post(self, body):
        self.posts += 1
        matchers = body.get("matchers")
        if not isinstance(matchers, list) or not matchers:
            return 400, "silence invalid: at least one matcher required"
        for m in matchers:
            if not m.get("name") or m.get("value") is None:
                return 400, "silence invalid: invalid label matcher"
        try:
            starts, ends = _parse(body["startsAt"]), _parse(body["endsAt"])
        except (KeyError, ValueError):
            return 400, "silence invalid: invalid time"
        if ends <= starts:
            return 400, "silence invalid: end time must not be before start time"
        if ends <= _now():
            return 400, "silence invalid: end time can't be in the past"
        old = body.get("id")
        if old:
            if old not in self.silences:
                return 404, "silence %s not found" % old
            self.silences[old]["_expired"] = True
        sid = str(uuid.uuid4())
        self.silences[sid] = {
            "id": sid,
            "matchers": [
                {
                    "name": m["name"],
                    "value": m["value"],
                    "isRegex": bool(m.get("isRegex", False)),
                    "isEqual": bool(m.get("isEqual", True)),
                }
                for m in matchers
            ],
            "startsAt": body["startsAt"],
            "endsAt": body["endsAt"],
            "createdBy": body.get("createdBy", ""),
            "comment": body.get("comment", ""),
            "updatedAt": _now().isoformat(),
        }
        return 200, {"silenceID": sid}

    def delete(self, sid):
        rec = self.silences.get(sid)
        if rec is None:
            return 404, "silence %s not found" % sid
        rec["_expired"] = True
        return 200, {}


class _Handler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    @property
    def am(self) -> FakeAlertmanager:
        return self.server.am  # type: ignore[attr-defined]

    def _send(self, status, payload):
        body = (json.dumps(payload) if not isinstance(payload, str) else payload).encode()
        self.send_response(status)
        self.send_header(
            "Content-Type",
            "application/json" if not isinstance(payload, str) else "text/plain",
        )
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle(self, method):
        am = self.am
        am.requests.append((method, self.path))
        if am.fail_next:
            status, payload = am.fail_next
            am.fail_next = None
            return self._send(status, payload)
        if am.require_token and self.headers.get("Authorization") != "Bearer " + GOOD_TOKEN:
            return self._send(
                401, {"error": "unauthorized: %s" % self.headers.get("Authorization")}
            )
        if self.path == "/api/v2/silences":
            if method == "GET":
                return self._send(200, am.listing())
            if method == "POST":
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                status, payload = am.post(body)
                return self._send(status, payload)
        if self.path.startswith("/api/v2/silence/") and method == "DELETE":
            status, payload = am.delete(self.path[len("/api/v2/silence/") :])
            return self._send(status, payload)
        return self._send(404, {"error": "no route"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_DELETE(self):
        self._handle("DELETE")


class _Server(http.server.ThreadingHTTPServer):
    daemon_threads = True


@pytest.fixture
def good_token():
    return GOOD_TOKEN


@pytest.fixture
def alertmanager():
    srv = _Server(("127.0.0.1", 0), _Handler)
    srv.am = FakeAlertmanager()  # type: ignore[attr-defined]
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    srv.url = "http://127.0.0.1:%d" % srv.server_address[1]  # type: ignore[attr-defined]
    yield srv
    srv.shutdown()
    srv.server_close()


class ExitJson(Exception):
    def __init__(self, result):
        super().__init__("exit_json")
        self.result = result


class FailJson(Exception):
    def __init__(self, result):
        super().__init__("fail_json")
        self.result = result


@pytest.fixture
def run_module(monkeypatch, tmp_path):
    """Run a module's main() against args; returns the exit_json / fail_json payload."""
    from ansible.module_utils import basic
    from ansible.module_utils.testing import patch_module_args

    def run(main, args, check_mode=False):
        full = dict(args)
        full["_ansible_check_mode"] = check_mode
        full["_ansible_tmpdir"] = str(tmp_path)
        full["_ansible_remote_tmp"] = str(tmp_path)

        def exit_json(self, **kw):
            raise ExitJson(kw)

        def fail_json(self, **kw):
            raise FailJson(kw)

        monkeypatch.setattr(basic.AnsibleModule, "exit_json", exit_json)
        monkeypatch.setattr(basic.AnsibleModule, "fail_json", fail_json)
        with patch_module_args(full):
            try:
                main()
            except ExitJson as e:
                return "exit", e.result
            except FailJson as e:
                return "fail", e.result
        raise AssertionError("module returned without exit_json/fail_json")

    return run
