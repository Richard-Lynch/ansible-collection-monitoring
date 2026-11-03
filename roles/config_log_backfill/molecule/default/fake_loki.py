# SPDX-License-Identifier: GPL-3.0-or-later
"""A minimal Loki for the config_log_backfill scenario: just enough API, and the RULES that matter.

    fake_loki.py <port> <state_dir>

Serves /config, /loki/api/v1/push, /loki/api/v1/query_range and /loki/api/v1/series from memory.
It is deliberately strict about the three behaviours the role is designed around, because a stub
that accepted anything would let the role's ordering and windowing be wrong and still pass:

  * reject_old_samples: an entry older than MAX_AGE is HTTP 400, like Loki's distributor.
  * the out-of-order window: an entry more than OOO_WINDOW behind its stream's NEWEST entry is
    HTTP 400 "entry too far behind" — what makes pushing history into a live stream fail.
  * dedupe: an identical (stream, timestamp, line) is stored once.

Control files in <state_dir> (written by the scenario between runs):
  seed.json      — streams to preload, as a push body: the "live" stream Alloy would have written.
  fail_push      — if present, every push answers HTTP 500 (proves the role fails loudly).
  hide_reads     — an integer N: the next N FORWARD reads (other than the live-edge lookup, which
                   selects backfill="") omit every entry older than 3h. This is the real Loki's
                   query_ingesters_within: an old-timestamped entry still in an ingester is
                   accepted but not queryable until its chunk flushes. It is what
                   the role's polling verify exists for.
Every accepted push is appended to <state_dir>/pushes.log as one line, so the scenario can count
HTTP requests as well as entries.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

NS = 1_000_000_000
MAX_AGE_S = 7 * 86400
OOO_WINDOW_S = 3600
STATE = sys.argv[2] if len(sys.argv) > 2 else "/tmp/fake-loki"
STREAMS: dict = {}  # frozenset(labels.items()) -> {ts_ns: set(lines)}
DELETES: list = []  # what GET /loki/api/v1/delete reports

CONFIG_YAML = """\
target: all
limits_config:
  reject_old_samples: true
  reject_old_samples_max_age: 1w
  unordered_writes: true
  max_line_size: 256KB
  ingestion_rate_mb: 4
  ingestion_burst_size_mb: 6
  per_stream_rate_limit: 3MB
  max_label_names_per_series: 15
ingester:
  max_chunk_age: 2h0m0s
"""


def store(labels: dict, values, enforce: bool):
    key = frozenset(labels.items())
    st = STREAMS.setdefault(key, {})
    now_ns = int(time.time() * NS)
    for ts, line in values:
        ts = int(ts)
        if enforce:
            if ts < now_ns - MAX_AGE_S * NS:
                return 400, f"entry for stream '{labels}' has timestamp too old: {ts}"
            newest = max(st) if st else None
            if newest is not None and ts < newest - OOO_WINDOW_S * NS:
                return (
                    400,
                    f"entry too far behind, oldest acceptable timestamp is: {newest - OOO_WINDOW_S * NS}",
                )
        st.setdefault(ts, set()).add(line)
    return 204, ""


_SEL = re.compile(r'(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"')


def parse_query(q: str):
    sel, _brace, rest = q.partition("}")
    want = {k: v.replace('\\"', '"').replace("\\\\", "\\") for k, v in _SEL.findall(sel + "}")}
    # One line filter at most: `|= "text"` (substring) or `|~ `regex`` (search), returned as a
    # predicate so callers need not know which.
    contains = None
    m = re.match(r'\s*\|=\s*(".*")\s*$', rest)
    if m:
        needle = json.loads(m.group(1))

        def contains(line):
            return needle in line

    m = re.match(r"\s*\|~\s*`(.*)`\s*$", rest)
    if m:
        rx = re.compile(m.group(1))

        def contains(line):
            return rx.search(line) is not None

    return want, contains


def matches(key, want) -> bool:
    labels = dict(key)
    for k, v in want.items():
        if v == "":
            if k in labels:
                return False
        elif labels.get(k) != v:
            return False
    return True


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def reply(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(u.query)
        if u.path == "/config":
            return self.reply(200, CONFIG_YAML, "text/plain; charset=utf-8")
        if u.path == "/loki/api/v1/query_range":
            want, contains = parse_query(qs["query"][0])
            start, end = int(qs["start"][0]), int(qs["end"][0])
            limit = int(qs.get("limit", ["100"])[0])
            backward = qs.get("direction", ["backward"])[0] == "backward"
            hide_before = None
            hide = os.path.join(STATE, "hide_reads")
            if not backward and 'backfill=""' not in qs["query"][0] and os.path.exists(hide):
                left = int(open(hide, encoding="utf-8").read().strip() or 0)
                if left > 0:
                    hide_before = int((time.time() - 3 * 3600) * NS)
                    with open(hide, "w", encoding="utf-8") as fh:
                        fh.write(str(left - 1))
            hits = []
            for key, st in STREAMS.items():
                if not matches(key, want):
                    continue
                for ts, lines in st.items():
                    if start <= ts < end and (hide_before is None or ts >= hide_before):
                        for line in sorted(lines):
                            if contains is None or contains(line):
                                hits.append((ts, line, key))
            hits.sort(key=lambda h: h[0], reverse=backward)
            hits = hits[:limit]
            out: dict = {}
            for ts, line, key in hits:
                out.setdefault(key, []).append([str(ts), line])
            result = [{"stream": dict(k), "values": v} for k, v in out.items()]
            return self.reply(
                200,
                json.dumps(
                    {
                        "status": "success",
                        "data": {"resultType": "streams", "result": result},
                    }
                ),
            )
        if u.path == "/loki/api/v1/delete":
            return self.reply(200, json.dumps(DELETES))
        if u.path == "/loki/api/v1/series":
            want, _contains = parse_query(qs["match[]"][0])
            data = [dict(k) for k in STREAMS if matches(k, want)]
            return self.reply(200, json.dumps({"status": "success", "data": data}))
        return self.reply(404, "not found", "text/plain")

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if urllib.parse.urlparse(self.path).path == "/loki/api/v1/delete":
            # Applied at once (real Loki filters, then purges after its cancel period). The range
            # is INCLUSIVE at millisecond precision, as in Loki, so an end of sec+1 would also
            # take an entry stamped on the next whole second — which the role must avoid.
            # Parameters from the URL QUERY STRING, like Loki: a form body is a 400.
            form = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if "query" not in form:
                return self.reply(400, "query not set", "text/plain")
            want, _contains = parse_query(form["query"][0])

            def to_ms(v):
                try:
                    return int(float(v) * 1000)
                except ValueError:
                    from datetime import datetime

                    return int(datetime.fromisoformat(v.replace("Z", "+00:00")).timestamp() * 1000)

            lo, hi = to_ms(form["start"][0]), to_ms(form["end"][0])
            # defer_deletes: queue the request and change NOTHING, like Loki during its
            # delete_request_cancel_period (24h here) — the state verify must report as pending.
            deferred = os.path.exists(os.path.join(STATE, "defer_deletes"))
            DELETES.append(
                {
                    "request_id": str(len(DELETES)),
                    "query": form["query"][0],
                    "start_time": lo,
                    "end_time": hi,
                    "created_at": int(time.time() * 1000),
                    "status": "received" if deferred else "processed",
                }
            )
            if not deferred:
                for key, st in STREAMS.items():
                    if matches(key, want):
                        for ts in [t for t in st if lo <= t // 1_000_000 <= hi]:
                            del st[ts]
            return self.reply(204, "")
        if self.path != "/loki/api/v1/push":
            return self.reply(404, "not found", "text/plain")
        if os.path.exists(os.path.join(STATE, "fail_push")):
            return self.reply(500, "injected failure", "text/plain")
        doc = json.loads(body)
        for s in doc["streams"]:
            code, msg = store(s["stream"], s["values"], enforce=True)
            if code != 204:
                return self.reply(code, msg, "text/plain")
        with open(os.path.join(STATE, "pushes.log"), "a", encoding="utf-8") as fh:
            fh.write(f"{sum(len(s['values']) for s in doc['streams'])}\n")
        return self.reply(204, "")


def main():
    port = int(sys.argv[1])
    os.makedirs(STATE, exist_ok=True)
    seed = os.path.join(STATE, "seed.json")
    if os.path.exists(seed):
        with open(seed, encoding="utf-8") as fh:
            for s in json.load(fh)["streams"]:
                store(s["stream"], s["values"], enforce=False)
    ThreadingHTTPServer(("127.0.0.1", port), H).serve_forever()


if __name__ == "__main__":
    main()
