# SPDX-License-Identifier: GPL-3.0-or-later
"""Backfill historical log FILES into Loki, at each line's ORIGINAL timestamp.

Shipped and run by roles/config_log_backfill on the host that holds the files. Standard library
only: a target may be an image-based OS (Fedora atomic and its derivatives) where nothing can be
pip-installed.

    loki_backfill.py <config.json>          # mode comes from the config: plan | push | verify

Prints ONE JSON report on stdout and exits:
    0  the mode completed and every check passed
    2  a check failed (a push was rejected, a verify found a mismatch, a label drift) — the report
       says which, and nothing is silently partial
    3  the configuration is unusable (bad regex, unknown timezone, unreadable Loki /config)

WHY EACH DESIGN CHOICE (the role README carries the measurements):

* A DISTINCT STREAM per campaign (`<backfill_label>=<campaign>`). Loki with unordered_writes rejects
  an entry more than max_chunk_age/2 (1h here) behind its stream's NEWEST entry, so a week-old line
  pushed into the stream Alloy is writing now is "entry too far behind". A separate stream has its
  own newest-entry clock. The value is a CAMPAIGN id fixed by the caller, never the run date: a
  run-dated label would make every re-run a new stream and duplicate everything.

* ASCENDING ORDER per stream, for the same reason: inside the backfill stream the first batch sets
  the clock, so a later batch older than it by more than the window would be rejected.

* IDEMPOTENT BY A LOKI-SIDE WATERMARK. Before pushing a stream the script asks Loki for that
  stream's newest entry and skips everything at or before it. The authority on "what is already
  there" is Loki itself, not a state file on the box that can disagree with it after a retention
  sweep or a half-failed run. Because pushes are ascending and stop at the first failure, the
  watermark is exactly "everything up to here landed".

* A UNIQUE NANOSECOND PER LINE. Lines that share a second get +0ns, +1ns, +2ns... in file order.
  Loki treats an identical (timestamp, line) pair as a duplicate and keeps one, so two genuinely
  repeated lines in the same second would otherwise collapse into one and the on-disk count could
  never match. It also keeps the file's own order inside a second. Deterministic, so a re-run
  produces byte-identical entries.

* CONTINUATION LINES (no timestamp of their own) are FOLDED into the preceding record with '\\n',
  or ATTACHED as their own entry at the preceding timestamp — per source. Lines before a file's
  first timestamp have no time to inherit and are REPORTED as unparsed, never dropped silently.
"""

from __future__ import annotations

import fnmatch
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - python < 3.9
    ZoneInfo = None  # type: ignore[assignment,misc]

NS = 1_000_000_000
SAMPLE_LEN = 200
SAMPLES = 3
TRUNC_MARK = " ...[truncated by config_log_backfill]"

# --------------------------------------------------------------------------------------------
# Loki config value parsing
# --------------------------------------------------------------------------------------------

_DUR_UNITS = {
    "ns": 1e-9,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1,
    "m": 60,
    "h": 3600,
    "d": 86400,
    "w": 604800,
    "y": 31536000,
}
_DUR_RE = re.compile(r"(\d+(?:\.\d+)?)(ns|us|ms|s|m|h|d|w|y)")


def parse_duration(value) -> float:
    """Prometheus/Go style duration ('1w', '2h0m0s', '30d1h') -> seconds."""
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if text in ("0", ""):
        return 0.0
    total, pos = 0.0, 0
    for m in _DUR_RE.finditer(text):
        if m.start() != pos:
            raise ValueError(f"unparseable duration {value!r}")
        total += float(m.group(1)) * _DUR_UNITS[m.group(2)]
        pos = m.end()
    if pos != len(text):
        raise ValueError(f"unparseable duration {value!r}")
    return total


_SIZE_RE = re.compile(r"\A(\d+(?:\.\d+)?)\s*([KMGT]?i?B?)\Z", re.IGNORECASE)
_SIZE_MULT = {"": 1, "b": 1, "k": 1024, "m": 1024**2, "g": 1024**3, "t": 1024**4}


def parse_size(value) -> int:
    """Loki flagext.ByteSize ('256KB', '3MB'), which uses 1024-based units."""
    if isinstance(value, (int, float)):
        return int(value)
    m = _SIZE_RE.match(str(value).strip())
    if not m:
        raise ValueError(f"unparseable size {value!r}")
    unit = m.group(2).lower()[:1]
    return int(float(m.group(1)) * _SIZE_MULT[unit])


def parse_yaml_subset(text: str) -> dict:
    """Read the two-level `section: {key: scalar}` shape of Loki's /config.

    The host has no PyYAML. /config is block-style YAML whose limits sit at two levels of
    indentation, which is all this needs; anything deeper is skipped rather than guessed at.
    """
    out: dict = {}
    section = None
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if ":" not in line:
            continue
        key, _sep, val = line.partition(":")
        val = val.strip()
        if indent == 0:
            section = key
            out.setdefault(section, {})
            if val:
                out[section] = val
        elif indent == 2 and section is not None and isinstance(out.get(section), dict):
            if val.startswith(("'", '"')) and val.endswith(val[0]) and len(val) >= 2:
                val = val[1:-1]
            out[section][key] = val
    return out


# --------------------------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------------------------


class LokiError(Exception):
    pass


def http(url: str, data: bytes | None = None, timeout: int = 30):
    req = urllib.request.Request(url, data=data, method="POST" if data is not None else "GET")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def selector(labels: dict, extra: dict | None = None) -> str:
    merged = dict(labels)
    merged.update(extra or {})
    parts = []
    for k in sorted(merged):
        v = str(merged[k]).replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'{k}="{v}"')
    return "{" + ",".join(parts) + "}"


def loki_query_range(base, query, start_ns, end_ns, limit, direction):
    qs = urllib.parse.urlencode(
        {
            "query": query,
            "start": str(start_ns),
            "end": str(end_ns),
            "limit": str(limit),
            "direction": direction,
        }
    )
    status, body = http(f"{base}/loki/api/v1/query_range?{qs}")
    if status != 200:
        raise LokiError(f"query_range {query} -> HTTP {status}: {body[:300]}")
    try:
        doc = json.loads(body)
    except ValueError as e:
        raise LokiError(f"query_range {query} -> unparseable reply: {body[:300]}") from e
    if doc.get("status") != "success":
        raise LokiError(f"query_range {query} -> status {doc.get('status')}: {body[:300]}")
    return doc["data"]["result"]


def loki_edge(base, query, start_ns, end_ns, direction):
    """(ts_ns, line) of the oldest (forward) or newest (backward) entry, or None."""
    best = None
    for stream in loki_query_range(base, query, start_ns, end_ns, 1, direction):
        for ts, line in stream["values"]:
            cand = (int(ts), line)
            if best is None or (cand[0] < best[0] if direction == "forward" else cand[0] > best[0]):
                best = cand
    return best


def loki_all(base, query, start_ns, end_ns, page=5000):
    """Every entry of `query` in [start_ns, end_ns), paged forward. Returns {ts_ns: [lines]}."""
    got: dict = {}
    cursor = start_ns
    while cursor < end_ns:
        result = loki_query_range(base, query, cursor, end_ns, page, "forward")
        batch = [(int(ts), line) for s in result for ts, line in s["values"]]
        if not batch:
            break
        batch.sort()
        for ts, line in batch:
            got.setdefault(ts, []).append(line)
        if len(batch) < page:
            break
        cursor = batch[-1][0] + 1
    return got


def loki_series(base, query, start_ns, end_ns):
    qs = urllib.parse.urlencode({"match[]": query, "start": str(start_ns), "end": str(end_ns)})
    status, body = http(f"{base}/loki/api/v1/series?{qs}")
    if status != 200:
        raise LokiError(f"series {query} -> HTTP {status}: {body[:300]}")
    return json.loads(body).get("data", [])


# --------------------------------------------------------------------------------------------
# Parsing files into records
# --------------------------------------------------------------------------------------------


def compile_source(src: dict, redact_defaults: list, audit_terms: list, now_s: float) -> dict:
    tz_name = src.get("timezone", "UTC")
    if ZoneInfo is None:
        raise ValueError("python lacks zoneinfo (needs 3.9+)")
    try:
        tz = ZoneInfo(tz_name)
    except Exception as e:  # noqa: BLE001 - any failure here is a config error
        raise ValueError(f"source {src['name']}: unknown timezone {tz_name!r}") from e
    formats = []
    for f in src.get("formats", []):
        rx = re.compile(f["regex"])
        if "ts" not in rx.groupindex:
            raise ValueError(
                f"source {src['name']}: format regex has no (?P<ts>...) group: {f['regex']}"
            )
        formats.append({"rx": rx, "strptime": f["strptime"]})
    if not formats:
        raise ValueError(f"source {src['name']}: no timestamp formats")
    redact = []
    for r in list(redact_defaults) + list(src.get("redact", [])):
        rx = re.compile(r["regex"])
        if "secret" not in rx.groupindex:
            raise ValueError(
                f"source {src['name']}: redact regex has no (?P<secret>...) group: {r['regex']}"
            )
        redact.append({"name": r.get("name", r["regex"][:30]), "rx": rx})
    rotated = [{"rx": re.compile(r["regex"]), "live": r["live"]} for r in src.get("rotated", [])]
    continuation = src.get("continuation", "fold")
    if continuation not in ("fold", "attach"):
        raise ValueError(f"source {src['name']}: continuation must be fold|attach")
    return {
        **src,
        "_tz": tz,
        "_formats": formats,
        "_redact": redact,
        "_rotated": rotated,
        "_continuation": continuation,
        "_audit": [t.lower() for t in audit_terms],
        "_now": now_s,
    }


def parse_ts(text: str, fmt: str, tz, ref_s: float) -> float:
    if fmt == "epoch":
        return float(text)
    if fmt == "epoch_ms":
        return float(text) / 1000.0
    if "%Y" not in fmt and "%y" not in fmt:
        # YEAR-LESS formats (Chromium's [MMDD/HHMMSS.us:...]). strptime would default to 1900
        # (outside every window, and 29 Feb unparseable). The year comes from `ref_s` — the
        # FILE'S MTIME, not now: no line can be newer than the last write to its file, so a stale
        # file last touched in October 2025 dates its "1016/..." lines to 2025 instead of
        # silently landing them in this week's window. Step back a year if the guess is more than
        # a day after the reference (a December line in a file last written in January).
        year = datetime.fromtimestamp(ref_s, tz).year
        dt = datetime.strptime(f"{year} {text}", "%Y " + fmt).replace(tzinfo=tz)
        if dt.timestamp() > ref_s + 86400:
            dt = datetime.strptime(f"{year - 1} {text}", "%Y " + fmt).replace(tzinfo=tz)
        return dt.timestamp()
    dt = datetime.strptime(text, fmt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.timestamp()


_TOKENISH = re.compile(r"[A-Za-z0-9+/=_.-]{16,}")


def mask(line: str, term: str | None = None) -> str:
    """For REPORT samples only: hide every long token-shaped run, keep the structure readable.

    With `term` (an audit hit), the sample is the context AROUND the term, and the run that
    contains it keeps its NAME and loses only its value: `--password-store=basic` reads as
    `--password-store=<5ch>`, which is enough to tell a flag from a credential without printing
    the credential into the run log.
    """
    if term:
        i = line.lower().find(term)
        if i >= 0:
            line = line[max(0, i - 60) : i + 100]

    def _m(m):
        run = m.group(0)
        if term and term in run.lower():
            at = run.lower().find(term)
            k = re.search(r"[=:]", run[at:])
            # no separator: keep up to the end of the term itself, mask whatever is glued on
            cut = at + (k.end() if k else len(term))
            if cut >= len(run):
                return run
            return run[:cut] + f"<{len(run) - cut}ch>"
        return f"<{len(run)}ch>"

    return _TOKENISH.sub(_m, line)[:SAMPLE_LEN]


def live_name(path: str, csrc: dict) -> tuple[str, bool]:
    """The filename a rotated file's lines were shipped under while it was live."""
    for r in csrc["_rotated"]:
        if r["rx"].search(path):
            return r["rx"].sub(r["live"], path), True
    return path, False


def redact_line(line: str, csrc: dict, hits: dict) -> str:
    for r in csrc["_redact"]:

        def _sub(m, _name=r["name"]):
            hits[_name] = hits.get(_name, 0) + 1
            s, e = m.span("secret")
            return m.group(0)[: s - m.start()] + "<redacted>" + m.group(0)[e - m.start() :]

        line = r["rx"].sub(_sub, line)
    return line


def read_file(path: str, csrc: dict, fstats: dict):
    """Yield (epoch_seconds_float, first_line, full_text, raw_line_count) records, in file order."""
    cur = None
    ref_s = min(csrc["_now"], os.path.getmtime(path))
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.rstrip("\r\n")
            fstats["raw_lines"] += 1
            if not line.strip():
                # Blank lines carry nothing (most Steam files OPEN with two). Counted, never pushed.
                fstats["blank_lines"] += 1
                continue
            low = line.lower()
            for term in csrc["_audit"]:
                if term in low:
                    a = fstats["audit"].setdefault(term, {"lines": 0, "samples": []})
                    a["lines"] += 1
                    if len(a["samples"]) < SAMPLES:
                        a["samples"].append(mask(line, term))
            ts, bad = None, False
            for f in csrc["_formats"]:
                m = f["rx"].search(line)
                if m:
                    try:
                        ts = parse_ts(m.group("ts"), f["strptime"], csrc["_tz"], ref_s)
                    except (ValueError, OverflowError):
                        bad = True
                    break
            if ts is not None:
                if cur is not None:
                    yield cur
                cur = [ts, line, line, 1]
                continue
            # no usable timestamp of its own: counted ONCE, as whichever kind of unparsed it is
            if bad:
                fstats["bad_timestamp"] += 1
                if len(fstats["bad_timestamp_samples"]) < SAMPLES:
                    fstats["bad_timestamp_samples"].append(mask(line))
            if cur is None:
                if not bad:
                    fstats["orphan_lines"] += 1
                    if len(fstats["orphan_samples"]) < SAMPLES:
                        fstats["orphan_samples"].append(mask(line))
                continue
            fstats["continuation_lines"] += 1
            if csrc["_continuation"] == "fold":
                cur[2] += "\n" + line
                cur[3] += 1
            else:
                yield cur
                cur = [cur[0], line, line, 1]
    if cur is not None:
        yield cur


def new_fstats(path):
    return {
        "path": path,
        "raw_lines": 0,
        "blank_lines": 0,
        "audit": {},
        "continuation_lines": 0,
        "orphan_lines": 0,
        "orphan_samples": [],
        "bad_timestamp": 0,
        "bad_timestamp_samples": [],
        "records": 0,
        "records_in_window": 0,
        "raw_lines_in_window": 0,
        "too_old": 0,
        "too_old_lines": 0,
        "after_cut": 0,
        "redactions": {},
        "truncated": 0,
    }


def build_streams(cfg, csrcs, window_start, max_line_bytes):
    """Group every matching file into streams keyed by their final label set."""
    streams: dict = {}
    for csrc in csrcs:
        files = set()
        for pat in csrc.get("paths", []):
            files.update(p for p in glob.glob(pat) if os.path.isfile(p))
        excl = csrc.get("exclude", [])
        files = sorted(f for f in files if not any(fnmatch.fnmatch(f, e) for e in excl))
        # oldest first, so a rotated file's lines precede the live file's when they share a second
        files.sort(key=lambda p: (os.path.getmtime(p), p))
        for path in files:
            lname, rotated = live_name(path, csrc)
            if rotated and not csrc.get("label_rotated_as_live", True):
                lname = path
            labels = dict(csrc.get("labels", {}))
            labels[csrc.get("filename_label", "filename")] = lname
            key = selector(labels)
            st = streams.setdefault(
                key,
                {
                    "source": csrc["name"],
                    "labels": labels,
                    "live_filename": lname,
                    "files": [],
                    "records": [],
                },
            )
            fstats = new_fstats(path)
            fstats["rotated"] = rotated
            st["files"].append(fstats)
            for ts, first, text, nraw in read_file(path, csrc, fstats):
                fstats["records"] += 1
                if ts < window_start:
                    fstats["too_old"] += 1
                    # RAW lines too: a record that swallowed hundreds of continuation lines is
                    # the tell of a format that does not match (in-window lines folded into an
                    # out-of-window parent), and a record count alone hides it.
                    fstats["too_old_lines"] += nraw
                    continue
                text = redact_line(text, csrc, fstats["redactions"])
                first = text.split("\n", 1)[0]
                if len(text.encode("utf-8")) > max_line_bytes:
                    keep = max_line_bytes - len(TRUNC_MARK.encode()) - 16
                    text = text.encode("utf-8")[:keep].decode("utf-8", "ignore") + TRUNC_MARK
                    fstats["truncated"] += 1
                st["records"].append(
                    {
                        "ts": ts,
                        "first": first,
                        "line": text,
                        "nraw": nraw,
                        "file": fstats,
                    }
                )
    # nanosecond sequence within a second, in file order (files already oldest-first)
    for st in streams.values():
        st["records"].sort(key=lambda r: int(r["ts"]))  # stable: keeps file order inside a second
        seq_sec, seq = None, 0
        for r in st["records"]:
            sec = int(r["ts"])
            frac_ns = int(round((r["ts"] - sec) * NS))
            seq = seq + 1 if sec == seq_sec else 0
            seq_sec = sec
            r["ts_ns"] = sec * NS + frac_ns + seq
        st["records"].sort(key=lambda r: r["ts_ns"])
    return streams


# --------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------


def iso(ns: int | None, tz) -> str | None:
    if ns is None:
        return None
    return datetime.fromtimestamp(ns / NS, tz).isoformat(timespec="seconds")


def read_limits(cfg) -> dict:
    if cfg.get("limits"):
        lim = cfg["limits"]
        src = "config"
    else:
        status, body = http(f"{cfg['loki_url']}/config")
        if status != 200:
            raise LokiError(f"GET /config -> HTTP {status}: {body[:300]}")
        doc = parse_yaml_subset(body)
        lc, ing = doc.get("limits_config", {}), doc.get("ingester", {})
        comp = doc.get("compactor", {}) if isinstance(doc.get("compactor"), dict) else {}
        if not isinstance(lc, dict) or "reject_old_samples" not in lc:
            raise LokiError(f"/config did not parse into limits_config: {body[:300]}")
        lim = {
            "reject_old_samples": str(lc.get("reject_old_samples")).lower() == "true",
            "reject_old_samples_max_age": lc.get("reject_old_samples_max_age", "1w"),
            "unordered_writes": str(lc.get("unordered_writes", "true")).lower() == "true",
            "max_chunk_age": ing.get("max_chunk_age", "2h"),
            "max_line_size": lc.get("max_line_size", "256KB"),
            "ingestion_rate_mb": lc.get("ingestion_rate_mb", "4"),
            "ingestion_burst_size_mb": lc.get("ingestion_burst_size_mb", "6"),
            "per_stream_rate_limit": lc.get("per_stream_rate_limit", "3MB"),
            "max_label_names_per_series": lc.get("max_label_names_per_series", "15"),
            "delete_request_cancel_period": comp.get("delete_request_cancel_period", "24h"),
        }
        src = "loki /config"
    out = {
        "source": src,
        "reject_old_samples": bool(lim.get("reject_old_samples", True)),
        "max_age_s": parse_duration(lim.get("reject_old_samples_max_age", "1w")),
        "unordered_writes": bool(lim.get("unordered_writes", True)),
        "ooo_window_s": parse_duration(lim.get("max_chunk_age", "2h")) / 2,
        "max_line_bytes": parse_size(lim.get("max_line_size", "256KB")),
        "rate_bytes_s": float(lim.get("ingestion_rate_mb", 4)) * 1024 * 1024,
        "burst_bytes": float(lim.get("ingestion_burst_size_mb", 6)) * 1024 * 1024,
        "per_stream_bytes_s": parse_size(lim.get("per_stream_rate_limit", "3MB")),
        "max_labels": int(lim.get("max_label_names_per_series", 15)),
        "delete_cancel_s": parse_duration(lim.get("delete_request_cancel_period", "24h")),
    }
    return out


def push_stream(cfg, st, todo, lim, report_st):
    """Push `todo` (ascending) in byte-bounded, rate-paced batches. Stops at the first failure."""
    budget = min(lim["rate_bytes_s"], lim["per_stream_bytes_s"]) * float(
        cfg.get("rate_fraction", 0.5)
    )
    max_batch = min(int(cfg.get("batch_bytes", 524288)), int(lim["burst_bytes"] * 0.5))
    url = f"{cfg['loki_url']}/loki/api/v1/push"
    i = 0
    while i < len(todo):
        batch, size = [], 0
        while i < len(todo) and (not batch or size + len(todo[i]["line"]) + 40 <= max_batch):
            batch.append(todo[i])
            size += len(todo[i]["line"]) + 40
            i += 1
        body = json.dumps(
            {
                "streams": [
                    {
                        "stream": st["labels_push"],
                        "values": [[str(r["ts_ns"]), r["line"]] for r in batch],
                    }
                ]
            }
        ).encode("utf-8")
        attempt = 0
        while True:
            t0 = time.monotonic()
            status, text = http(url, body, timeout=60)
            report_st["http_statuses"][str(status)] = (
                report_st["http_statuses"].get(str(status), 0) + 1
            )
            if 200 <= status < 300:
                break
            if status == 429 and attempt < int(cfg.get("max_retries", 6)):
                attempt += 1
                time.sleep(min(2**attempt, 30))
                continue
            report_st["push_error"] = {
                "status": status,
                "body": text[:500],
                "batch_first_ts": iso(batch[0]["ts_ns"], timezone.utc),
                "batch_entries": len(batch),
            }
            return False
        report_st["pushed"] += len(batch)
        report_st["batches"] += 1
        # pace: never exceed a fraction of the tenant's ingestion rate (Alloy shares it)
        wait = len(body) / budget - (time.monotonic() - t0)
        if wait > 0:
            time.sleep(wait)
    return True


def compare(cfg, rst, window, start_ns, cut_ns, tz):
    """Read one backfill stream's window back from Loki and diff it against the files."""
    got = loki_all(cfg["loki_url"], rst["stream"], start_ns, cut_ns)
    want: dict = {}
    for r in window:
        want.setdefault(r["ts_ns"], []).append(r["line"])
    missing = [(t, ln) for t, ls in want.items() for ln in ls if ln not in got.get(t, [])]
    extra = [(t, ln) for t, ls in got.items() for ln in ls if ln not in want.get(t, [])]
    rst["verify"] = {
        "disk_records": len(window),
        "loki_entries": sum(len(v) for v in got.values()),
        "missing_from_loki": len(missing),
        "extra_in_loki": len(extra),
        "missing_samples": [f"{iso(t, tz)} {ln[:SAMPLE_LEN]}" for t, ln in missing[:SAMPLES]],
        "extra_samples": [f"{iso(t, tz)} {ln[:SAMPLE_LEN]}" for t, ln in extra[:SAMPLES]],
    }
    return len(missing), len(extra)


def spot_check(cfg, sc, tz):
    at = datetime.fromisoformat(sc["at"]).timestamp()
    q = selector(sc["labels"]) + " |= " + json.dumps(sc["contains"])
    res = loki_query_range(cfg["loki_url"], q, int(at) * NS, (int(at) + 1) * NS, 10, "forward")
    hits = [(int(t), ln) for s in res for t, ln in s["values"]]
    ok = bool(hits) and all(int(t // NS) == int(at) for t, _line in hits)
    return {
        "query": q,
        "at": sc["at"],
        "found": [f"{iso(t, tz)} {ln[:SAMPLE_LEN]}" for t, ln in hits],
        "ok": ok,
    }


SEAM_S = 300


def _labels_of(sel: str) -> dict:
    """{k="v",...} -> dict, so two spellings of one selector compare equal."""
    return dict(re.findall(r'(\w+)\s*=\s*"((?:[^"\\]|\\.)*)"', sel.split("}", 1)[0]))


def pending_deletes(cfg) -> list:
    """Loki's delete requests that have NOT been processed yet.

    Loki (filter-and-delete) holds a request for delete_request_cancel_period (24h here) before
    it filters or purges anything, so a correct seam repair goes on being reported by verify for
    a day. A seam duplicate that such a request covers is therefore a WARNING with a known
    effective time, not a failure — and only one that no pending request covers fails.
    """
    status, body = http(f"{cfg['loki_url']}/loki/api/v1/delete")
    if status != 200:
        raise LokiError(f"GET /loki/api/v1/delete -> HTTP {status}: {body[:300]}")
    try:
        reqs = json.loads(body) or []
    except ValueError as e:
        raise LokiError(f"GET /loki/api/v1/delete -> unparseable: {body[:300]}") from e

    def _s(v):
        v = float(v)
        return v / 1000.0 if v > 1e11 else v  # Loki reports ms; accept seconds too

    out = []
    for r in reqs:
        if str(r.get("status", "")).lower() == "processed":
            continue
        out.append(
            {
                "labels": _labels_of(r.get("query", "")),
                "start": _s(r.get("start_time", 0)),
                "end": _s(r.get("end_time", 0)),
                "created": _s(r.get("created_at", 0)),
                "status": r.get("status"),
            }
        )
    return out


def covered(pend: list, stream_sel: str, ts_ns: int):
    """The pending request that covers this entry, or None."""
    labels = _labels_of(stream_sel)
    t = ts_ns / NS
    for r in pend:
        if r["labels"] == labels and r["start"] <= t <= r["end"] + 0.001:
            return r
    return None


def seam_duplicates(cfg, rst, cut_ns):
    """Backfilled entries near the seam whose exact text Alloy ALSO shipped near the seam.

    The per-stream compare reads only the backfill stream inside [start, cut), so a line pushed
    on BOTH sides of the seam is invisible to it. This reads both streams
    across +/- SEAM_S of the cut and returns [(ts_ns, line)] of backfilled copies of live lines.
    """
    if not rst.get("_live_sel"):
        return []
    lo, hi = cut_ns - SEAM_S * NS, cut_ns + SEAM_S * NS
    live = loki_all(cfg["loki_url"], rst["_live_sel"], lo, hi)
    live_text = {ln for ls in live.values() for ln in ls}
    back = loki_all(cfg["loki_url"], rst["stream"], lo, hi)

    # A FOLDED record (a line plus its continuation lines, joined by \n) is a copy when every
    # non-blank line in it was shipped live — Alloy ships those lines one entry each, so an
    # exact-text compare alone would miss it, and would refuse such a second as only partly
    # duplicate.
    def _copy(ln):
        parts = [p for p in ln.split("\n") if p.strip()]
        return bool(parts) and all(p in live_text for p in parts)

    return sorted((t, ln) for t, ls in back.items() for ln in ls if _copy(ln))


def repair_seams(cfg, report, pending, tz):
    """Delete backfilled copies of live lines at the seam — one exact SECOND per request.

    Each request is scoped to the backfill stream's own selector (it can never touch the live
    stream) and to one whole second, and is only sent when EVERY backfilled entry in that second
    is a duplicate; a second that also holds a unique line is refused and reported. Dry run
    unless cfg['apply'].
    """
    apply = bool(cfg.get("apply"))
    report["repair"] = []
    # DEFENCE IN DEPTH for the one function that DELETES. Every request must be scoped to a
    # backfill stream: its selector must carry `<backfill_label>="<campaign>"` with a non-empty
    # campaign. In LogQL `{backfill=""}` matches streams WITHOUT the label — the LIVE streams — so
    # an empty campaign would aim these deletes at live data. tasks/main.yml validates the campaign
    # too, but this script can be run directly, so the guard lives where the delete is issued.
    blabel = cfg.get("backfill_label", "backfill")
    campaign = str(cfg.get("campaign") or "")
    if not blabel or not campaign:
        raise LokiError(
            "refusing seam repair: empty backfill label or campaign would match LIVE streams"
        )
    scope = f'{blabel}="{campaign}"'
    for rst, _old, cut_ns in pending:
        # Checked BEFORE anything reads or writes Loki for this stream.
        if scope not in rst["stream"]:
            raise LokiError(f"refusing seam repair: {rst['stream']} is not scoped to {scope}")
        try:
            dups = seam_duplicates(cfg, rst, cut_ns)
        except LokiError as e:
            report["ok"] = False
            report["errors"].append(str(e))
            continue
        for sec in sorted({t // NS for t, _line in dups}):
            in_sec = loki_all(cfg["loki_url"], rst["stream"], sec * NS, (sec + 1) * NS)
            n_all = sum(len(v) for v in in_sec.values())
            n_dup = sum(1 for t, _line in dups if t // NS == sec)
            entry = {
                "stream": rst["stream"],
                "second": iso(sec * NS, tz),
                "duplicates": n_dup,
                "entries": n_all,
            }
            if n_dup != n_all:
                entry["action"] = "REFUSED: the second also holds lines that are not duplicates"
                report["ok"] = False
                report["errors"].append(
                    f"seam repair refused for {rst['stream']} at {entry['second']}"
                )
            elif not apply:
                entry["action"] = "would delete"
            else:
                body = urllib.parse.urlencode(
                    {
                        "query": rst["stream"],
                        "start": str(sec),
                        # .999, not sec+1: the delete range is inclusive at millisecond
                        # precision, and sec+1 would also take an entry stamped exactly on the
                        # next second.
                        "end": datetime.fromtimestamp(sec + 0.999, timezone.utc).strftime(
                            "%Y-%m-%dT%H:%M:%S.%fZ"
                        ),
                    }
                ).encode()
                # Parameters in the URL QUERY STRING, not a form body: Loki reads them from the
                # URL, and answers a form-encoded body with HTTP 400 (the gate below then fails
                # the play with nothing deleted).
                req = urllib.request.Request(
                    f"{cfg['loki_url']}/loki/api/v1/delete?{body.decode()}",
                    data=b"",
                    method="POST",
                )
                text = ""
                try:
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        status = resp.status
                except urllib.error.HTTPError as e:
                    status = e.code
                    text = e.read().decode("utf-8", "replace")[:300]
                if 200 <= status < 300:
                    entry["action"] = f"deleted (HTTP {status})"
                else:
                    entry["action"] = f"delete FAILED (HTTP {status}: {text.strip()})"
                    report["ok"] = False
                    report["errors"].append(
                        f"delete request HTTP {status} for {rst['stream']} at {entry['second']}: {text.strip()}"
                    )
            report["repair"].append(entry)


def verify_all(cfg, report, pending, tz, start_ns):
    """Compare every stream (and spot check) with Loki, POLLING while lines are only missing.

    Loki's querier asks the ingesters only for the last `query_ingesters_within` (3h by default) and
    storage for the rest, so a backfilled — by definition OLD — entry is accepted (204) but not
    queryable until its chunk flushes, ~chunk_idle_period (30m) after the stream goes quiet.
    An immediate read-back would therefore fail a correct push, so
    "missing" is re-read until `verify_wait` runs out. "Extra" is never retried: a duplicate or a
    mis-dated line does not go away by waiting.
    """
    wait = parse_duration(cfg.get("verify_wait", "0s"))
    interval = max(parse_duration(cfg.get("verify_interval", "60s")), 1.0)
    deadline = time.monotonic() + wait
    done: set = set()
    try:
        pend = pending_deletes(cfg)
    except LokiError as e:
        # Unknown is not "none pending": every seam duplicate then fails, which is the safe side.
        pend = []
        report["errors"].append(f"could not read pending delete requests: {e}")
        report["ok"] = False
    report["pending_delete_requests"] = len(pend)
    attempt = 0
    while True:
        attempt += 1
        missing_total = extra_total = 0
        errors = []
        for i, (rst, window, cut_ns) in enumerate(pending):
            if i in done:
                continue
            try:
                missing, extra = compare(cfg, rst, window, start_ns, cut_ns, tz)
            except LokiError as e:
                errors.append(str(e))
                continue
            try:
                dups = seam_duplicates(cfg, rst, cut_ns)
            except LokiError as e:
                errors.append(str(e))
                continue
            pend_hits = [covered(pend, rst["stream"], t) for t, _line in dups] if dups else []
            uncovered = [d for d, c in zip(dups, pend_hits) if c is None]
            rst["verify"]["seam_duplicates"] = len(uncovered)
            rst["verify"]["seam_pending_delete"] = len(dups) - len(uncovered)
            if len(uncovered) < len(dups):
                eff = (
                    max(c["created"] for c in pend_hits if c) + report["limits"]["delete_cancel_s"]
                )
                rst["verify"]["seam_pending_effective"] = iso(int(eff * NS), tz)
            rst["verify"]["seam_samples"] = [
                f"{iso(t, tz)} {ln[:SAMPLE_LEN]}" for t, ln in uncovered[:SAMPLES]
            ]
            missing_total += missing
            # an UNCOVERED seam duplicate is an EXTRA line: waiting will not remove it
            extra_total += extra + len(uncovered)
            if not missing and not extra and not uncovered:
                done.add(i)
        spots = []
        for sc in cfg.get("spot_checks", []):
            try:
                spots.append(spot_check(cfg, sc, tz))
            except LokiError as e:
                errors.append(str(e))
                spots.append({"query": str(sc), "at": sc.get("at"), "found": [], "ok": False})
        report["spot_checks"] = spots
        settled = not missing_total and not errors and all(s["ok"] for s in spots)
        if extra_total or settled or time.monotonic() + interval > deadline:
            break
        time.sleep(interval)
    report["verify_attempts"] = attempt
    for rst, _old, _cut in pending:
        v = rst.get("verify")
        if v and (v["missing_from_loki"] or v["extra_in_loki"] or v.get("seam_duplicates")):
            report["ok"] = False
            report["errors"].append(
                f"verify {rst['stream']}: {v['missing_from_loki']} missing from Loki, "
                f"{v['extra_in_loki']} extra in Loki, {v.get('seam_duplicates', 0)} also in the "
                "live stream at the seam (config_log_backfill_action=repair_seam removes them)"
            )
    warn = [
        (rst, rst["verify"])
        for rst, _old, _cut in pending
        if rst.get("verify", {}).get("seam_pending_delete")
    ]
    if warn:
        report["warnings"] = [
            f"{os.path.basename(r['live_filename'])}: {v['seam_pending_delete']} seam duplicate(s) covered by a "
            f"PENDING Loki delete request, effective ~{v.get('seam_pending_effective')}"
            for r, v in warn
        ]
    for sc in report["spot_checks"]:
        if not sc["ok"]:
            report["ok"] = False
            report["errors"].append(f"spot check failed: {sc['query']} at {sc['at']}")
    for e in errors:
        report["ok"] = False
        report["errors"].append(e)


def summarise(report) -> list:
    """Human-readable lines for the play output: one per stream, then totals and problems."""
    out = []
    w = report.get("window", {})
    out.append(
        f"window start {w.get('start')} (clamped to Loki max age: {w.get('clamped_to_loki_max_age')}), "
        f"end {w.get('end_mode')}; campaign {report['campaign']}"
    )
    for rst in report["streams"]:
        name = os.path.basename(rst["live_filename"])
        line = (
            f"{name}: window={rst['records_in_window']} rec/{rst.get('raw_lines_in_window', 0)} lines "
            f"loki_had={rst['already_in_loki']} to_push={rst['to_push']}"
        )
        if report["mode"] == "push":
            line += f" pushed={rst['pushed']} batches={rst['batches']} http={rst['http_statuses']}"
        if "verify" in rst:
            v = rst["verify"]
            line += (
                f" | verify disk={v['disk_records']} loki={v['loki_entries']} "
                f"missing={v['missing_from_loki']} extra={v['extra_in_loki']} "
                f"seam_dup={v.get('seam_duplicates', '?')} "
                f"seam_pending_delete={v.get('seam_pending_delete', 0)}"
            )
        line += f" | cut {rst['cut']['at']} ({rst['cut']['how']})"
        for f in rst["files"]:
            bits = []
            if f["orphan_lines"] or f["bad_timestamp"]:
                bits.append(f"UNPARSED {f['orphan_lines'] + f['bad_timestamp']}")
            if f["redactions"]:
                bits.append(f"redacted {f['redactions']}")
            if f["truncated"]:
                bits.append(f"truncated {f['truncated']}")
            if f["audit"]:
                bits.append("audit " + str({t: a["lines"] for t, a in f["audit"].items()}))
            if f["too_old"]:
                bits.append(f"older-than-window {f['too_old']} rec/{f['too_old_lines']} lines")
            if bits:
                line += f" | {os.path.basename(f['path'])}: " + ", ".join(bits)
        if rst.get("error"):
            line += f" | ERROR {rst['error']}"
        out.append(line)
    for rp in report.get("repair", []):
        out.append(
            f"seam repair {os.path.basename(rp['stream'].split('filename=')[-1].split(',')[0].strip(chr(34)))}"
            f" @ {rp['second']}: {rp['duplicates']}/{rp['entries']} duplicate -> {rp['action']}"
        )
    if report["mode"] == "repair" and not report.get("repair"):
        out.append("seam repair: no backfilled copies of live lines found")
    for sc in report.get("spot_checks", []):
        out.append(
            f"spot check {'OK' if sc['ok'] else 'FAILED'}: {sc['query']} @ {sc['at']} -> {sc['found']}"
        )
    if "verify_attempts" in report:
        out.append(f"verify: {report['verify_attempts']} read(s) of Loki before settling")
    for w in report.get("warnings", []):
        out.append(f"WARNING (not a failure): {w}")
    out.append(f"totals: {report.get('totals')}")
    for e in report["errors"]:
        out.append(f"ERROR: {e}")
    return out


def main(argv) -> int:
    with open(argv[1], encoding="utf-8") as fh:
        cfg = json.load(fh)
    mode = cfg.get("mode", "plan")
    report: dict = {
        "mode": mode,
        "campaign": cfg["campaign"],
        "ok": True,
        "errors": [],
        "streams": [],
    }
    now_s = float(cfg.get("now") or time.time())
    try:
        lim = read_limits(cfg)
        csrcs = [
            compile_source(s, cfg.get("redact_defaults", []), cfg.get("audit_terms", []), now_s)
            for s in cfg["sources"]
        ]
    except (ValueError, re.error, LokiError, KeyError) as e:
        report.update(ok=False, errors=[f"config: {e}"], summary=[f"ERROR: config: {e}"])
        report["totals"] = {
            k: 0 for k in ("records_in_window", "already_in_loki", "to_push", "pushed")
        }
        print(json.dumps(report))
        return 3
    report["limits"] = lim
    tz = csrcs[0]["_tz"] if csrcs else timezone.utc

    # ---- the window --------------------------------------------------------------------------
    since_s = parse_duration(cfg.get("since", "7d"))
    start_s = now_s - since_s
    margin = parse_duration(cfg.get("max_age_margin", "30m"))
    clamped = False
    if lim["reject_old_samples"] and start_s < now_s - lim["max_age_s"] + margin:
        start_s = now_s - lim["max_age_s"] + margin
        clamped = True
    # Whole seconds, so plan, push and verify — which the role runs with the SAME `now` — agree
    # on the boundary exactly. A later standalone verify slides the window with its own `now`,
    # and both sides of its comparison slide together.
    start_s = float(int(start_s))
    start_ns = int(start_s) * NS
    report["window"] = {
        "start": iso(start_ns, tz),
        "start_epoch": int(start_s),
        "requested_since_s": since_s,
        "clamped_to_loki_max_age": clamped,
        "end_mode": "auto" if cfg.get("end", "auto") in (None, "", "auto") else "fixed",
    }
    blabel = cfg.get("backfill_label", "backfill")
    now_ns = int(now_s * NS)

    streams = build_streams(cfg, csrcs, start_s, lim["max_line_bytes"])
    offline = bool(cfg.get("offline", False))

    # ---- label check: the backfill stream must carry the live streams' labels ----------------
    for csrc in csrcs:
        if offline or not csrc.get("live_selector"):
            continue
        try:
            series = loki_series(cfg["loki_url"], csrc["live_selector"], start_ns, now_ns)
        except LokiError as e:
            report["ok"] = False
            report["errors"].append(str(e))
            continue
        live = [s for s in series if blabel not in s]
        fl = csrc.get("filename_label", "filename")
        common = None
        for s in live:
            items = {(k, v) for k, v in s.items() if k != fl}
            common = items if common is None else common & items
        want = set((k, str(v)) for k, v in csrc.get("labels", {}).items())
        missing = sorted(f"{k}={v}" for k, v in (common or set()) - want)
        report.setdefault("label_check", []).append(
            {
                "source": csrc["name"],
                "live_streams": len(live),
                "live_common_labels": dict(sorted(common or set())),
                "missing_from_backfill": missing,
            }
        )
        if missing:
            report["ok"] = False
            report["errors"].append(
                f"source {csrc['name']}: live streams carry {missing} which the backfill labels lack — "
                "a query written for the live stream would not find the backfilled lines"
            )

    fixed_end_ns = (
        None
        if report["window"]["end_mode"] == "auto"
        else int(datetime.fromisoformat(cfg["end"]).timestamp() * NS)
    )

    pending: list = []  # (report stream, expected records, cut) for verify
    for key in sorted(streams):
        st = streams[key]
        labels_push = dict(st["labels"])
        labels_push[blabel] = cfg["campaign"]
        st["labels_push"] = labels_push
        rst = {
            "stream": selector(labels_push),
            "live_filename": st["live_filename"],
            "files": [],
            "cut": None,
            "records_in_window": 0,
            "already_in_loki": 0,
            "to_push": 0,
            "pushed": 0,
            "batches": 0,
            "http_statuses": {},
        }
        if len(labels_push) > lim["max_labels"]:
            rst["error"] = (
                f"{len(labels_push)} labels > Loki max_label_names_per_series {lim['max_labels']}"
            )
            report["ok"] = False
        # ---- end bound ----------------------------------------------------------------------
        cut_ns, cut_how = (
            (fixed_end_ns, "fixed") if fixed_end_ns else (now_ns, "now (no live lines)")
        )
        if not fixed_end_ns and not offline:
            live_sel = selector(st["labels"], {blabel: ""})
            try:
                # The first NON-BLANK live line. Steam opens every file with blank lines, and the
                # script never makes a record of a blank line, so matching against Loki's very
                # first live line could never succeed, and the time fallback would then let a
                # whole second of already-live lines into the backfill (in BOTH streams).
                edge = loki_edge(
                    cfg["loki_url"], live_sel + " |~ `\\S`", start_ns, now_ns, "forward"
                )
            except LokiError as e:
                rst["error"] = str(e)
                report["ok"] = False
                edge = None
            if edge:
                t0, l0 = edge
                # Fallback when no record matches: the START of that line's second. Backfilled
                # records carry whole-second stamps (+ns sequence) while the live line carries an
                # ingestion stamp later in the same second, so cutting at t0 itself would admit
                # every line of that second that Alloy ALSO shipped. Flooring may drop lines
                # written in that second before Alloy picked the file up; a 1s gap is preferred
                # to a duplicate, and the seam check in verify reports either way.
                cut_ns, cut_how = (t0 // NS) * NS, "earliest live line (second)"
                # refine: the exact record the live stream starts at, so the seam neither drops
                # nor repeats lines written in the same second Alloy started tailing
                for r in st["records"]:
                    if r["first"] == l0 and abs(r["ts_ns"] - t0) <= 300 * NS:
                        cut_ns, cut_how = r["ts_ns"], "earliest live line (matched)"
                        break
                rst["live_first"] = {"ts": iso(t0, tz), "line": l0[:SAMPLE_LEN]}
                rst["_live_sel"] = live_sel
        rst["cut"] = {"at": iso(cut_ns, tz), "ns": cut_ns, "how": cut_how}
        window = [r for r in st["records"] if r["ts_ns"] < cut_ns]
        for r in st["records"]:
            if r["ts_ns"] >= cut_ns:
                r["file"]["after_cut"] += 1
            else:
                r["file"]["records_in_window"] += 1
                r["file"]["raw_lines_in_window"] += r["nraw"]
        rst["records_in_window"] = len(window)
        rst["raw_lines_in_window"] = sum(r["nraw"] for r in window)
        rst["bytes_in_window"] = sum(len(r["line"].encode()) for r in window)
        if window:
            rst["first"] = iso(window[0]["ts_ns"], tz)
            rst["last"] = iso(window[-1]["ts_ns"], tz)

        # ---- what is already there ----------------------------------------------------------
        todo = window
        if not offline and window:
            try:
                wm = loki_edge(
                    cfg["loki_url"],
                    rst["stream"],
                    start_ns - int(lim["max_age_s"] * NS),
                    now_ns + 600 * NS,
                    "backward",
                )
            except LokiError as e:
                rst["error"] = str(e)
                report["ok"] = False
                wm = None
            if wm:
                rst["watermark"] = iso(wm[0], tz)
                todo = [r for r in window if r["ts_ns"] > wm[0]]
                rst["already_in_loki"] = len(window) - len(todo)
        rst["to_push"] = len(todo)

        if mode == "push" and todo and report["ok"]:
            if not push_stream(cfg, st, todo, lim, rst):
                report["ok"] = False
                report["errors"].append(f"push rejected for {rst['stream']}: {rst['push_error']}")

        if mode in ("verify", "repair") and not offline:
            pending.append((rst, window, cut_ns))

        for f in st["files"]:
            rst["files"].append(f)
        report["streams"].append(rst)

    if mode == "verify" and not offline:
        verify_all(cfg, report, pending, tz, start_ns)
    if mode == "repair" and not offline:
        repair_seams(cfg, report, pending, tz)
    for rst in report["streams"]:
        rst.pop("_live_sel", None)

    totals = {
        k: 0
        for k in (
            "records_in_window",
            "raw_lines_in_window",
            "already_in_loki",
            "to_push",
            "pushed",
        )
    }
    unparsed = 0
    for rst in report["streams"]:
        for k in totals:
            totals[k] += rst.get(k, 0)
        for f in rst["files"]:
            unparsed += f["orphan_lines"] + f["bad_timestamp"]
    totals["unparsed_lines"] = unparsed
    totals["files"] = sum(len(r["files"]) for r in report["streams"])
    totals["streams"] = len(report["streams"])
    report["totals"] = totals
    report["summary"] = summarise(report)
    print(json.dumps(report))
    return 0 if report["ok"] else 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
