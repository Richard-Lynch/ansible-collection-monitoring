#!/usr/bin/env bash
#
# Emits HOW STALE Home Assistant's recorder is, for node_exporter's textfile collector.
#
# WHY THIS EXISTS. HA's recorder can stop persisting history while HA itself stays healthy, and
# nothing else reports it:
#
#   - HA's prometheus integration exports entity STATES and nothing about whether history is
#     being PERSISTED: there is no `recorder` metric among them. So no Prometheus-only rule can see
#     this, however it is written.
#   - Writes are accepted and dropped, and disk usage gives no hint.
#
# So this cannot be answered from HA's metrics endpoint. It has to be answered by asking HA's
# HISTORY API what the newest row it will admit to is, and comparing that to the clock.
#
# THE WINDOW IS SHORT ON PURPOSE. `/api/logbook/<since>` returns only ~24 HOURS from `since` and
# caps the window silently, so with a long window "newest row" tracks the START of the window, not
# now, and a healthy recorder reads as days stale. Hence the WINDOW argument here is deliberately
# SHORT (default 1h).
#
# WHAT IT EXPORTS.
#   ha_recorder_probe_success 1|0          -- could we reach the logbook API and parse it this run
#   ha_recorder_newest_row_timestamp_seconds -- unix ts of the newest row in the window
#   ha_recorder_staleness_seconds          -- now minus that; THE alertable number
#   ha_recorder_rows_in_window             -- context: a live-but-idle home vs a dead recorder
#
# FOUR SERIES, NOT ONE, for the reason the WAN exporter beside this one gives at length: if a
# probe failure emitted "stale", an unreachable HA and a dead recorder would look identical and
# the alert would fire for the wrong reason. And on failure the staleness series is deliberately
# NOT emitted — a stale value of 0 would read as "perfectly fresh" for as long as Prometheus
# retains it.
#
# WHERE THIS RUNS: NOT on Home Assistant. Deliberately, and for the same reason the WireGuard
# exporter runs on the monitored end of a site link rather than the far end — an exporter must not
# depend on the thing it is watching. Running this on the HAOS box would mean a dead HA produces
# no metric at all, and absence is indistinguishable from a dead exporter. Run from a monitoring
# host it keeps reporting right up to the moment HA stops answering, and then reports a FAILED
# PROBE, which is a different and more useful alert.
#
# WHY NOT A PLAY. A play runs when somebody runs it. This question needs answering unattended and
# continuously.
#
# WRITES ATOMICALLY (.tmp + rename) — node_exporter may scrape mid-write and would otherwise read
# a truncated file. Same contract as the other exporters in this role.
#
# Usage: ha-recorder-metrics.sh <output.prom> <base_url> <token_file> [window_seconds]

set -uo pipefail

OUT="${1:?usage: $0 <output.prom> <base_url> <token_file> [window_seconds]}"
BASE="${2:?base_url required, e.g. http://ha.example.test:8123}"
TOKEN_FILE="${3:?token_file required}"
WINDOW="${4:-3600}"
TMP="${OUT}.tmp"

now="$(date -u +%s)"
since="$(date -u -d "@$((now - WINDOW))" +%Y-%m-%dT%H:%M:%S 2>/dev/null \
         || date -u -r "$((now - WINDOW))" +%Y-%m-%dT%H:%M:%S)"

# --- ask HA for the newest row it has -------------------------------------------------------------
# Parsed with python3 rather than grep/sed: the body is a JSON array of objects and the field
# needed is the MAXIMUM of a timestamp across all of them. A regex over JSON would silently pick
# whichever `when` happened to appear last in the serialisation, which is not the same thing.
#
# Prints two space-separated fields on success: "<newest_epoch> <row_count>". Prints nothing on
# any failure, so the caller cannot mistake a parse error for a fresh database.
probe() {
    # The token's PATH is passed, never its value: argv is world-readable via /proc, and a
    # long-lived HA token is a full-access credential. Python opens the file itself, so the secret
    # exists only inside that process -- it is never a shell variable and never reaches a command
    # line.
    python3 - "$BASE" "$TOKEN_FILE" "$since" <<'PY' 2>/dev/null
import json, sys, urllib.request
base, token_file, since = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    with open(token_file, encoding="utf-8") as fh:
        bearer = fh.read().strip()
except OSError:
    sys.exit(1)
if not bearer:
    sys.exit(1)
req = urllib.request.Request(
    f"{base}/api/logbook/{since}",
    headers={"Authorization": f"Bearer {bearer}", "Content-Type": "application/json"},
)
try:
    body = urllib.request.urlopen(req, timeout=20).read().decode()
except Exception:
    sys.exit(1)
try:
    rows = json.loads(body)
except Exception:
    sys.exit(1)
if not isinstance(rows, list):
    sys.exit(1)

import datetime
newest = None
for r in rows:
    w = r.get("when") if isinstance(r, dict) else None
    if not w:
        continue
    try:
        # HA emits ISO-8601 with an offset; fromisoformat handles it on py3.11+.
        ts = datetime.datetime.fromisoformat(w).timestamp()
    except Exception:
        continue
    if newest is None or ts > newest:
        newest = ts

# An EMPTY window is not a failure and must not be reported as one: a genuinely idle home can
# write nothing for an hour. Report success with a row count of 0 and no newest timestamp, and
# let the alert rule decide -- that distinction is exactly what rows_in_window exists for.
if newest is None:
    print(f"- {len(rows)}")
else:
    print(f"{newest:.0f} {len(rows)}")
PY
}

result="$(probe || true)"

newest=""
rows=""
if [ -n "$result" ]; then
    newest="$(printf '%s' "$result" | awk '{print $1}')"
    rows="$(printf '%s' "$result" | awk '{print $2}')"
fi

# --- emit -----------------------------------------------------------------------------------------
# Exactly ONE HELP and ONE TYPE line per metric name: a duplicate makes node_exporter reject the
# WHOLE FILE (node_textfile_scrape_error=1) while it sits on disk looking healthy.
{
    echo "# HELP ha_recorder_probe_success Whether Home Assistant's logbook API could be read and parsed this run (1) or not (0)."
    echo "# TYPE ha_recorder_probe_success gauge"
    if [ -n "$rows" ]; then
        echo "ha_recorder_probe_success 1"
    else
        echo "ha_recorder_probe_success 0"
    fi

    if [ -n "$rows" ]; then
        echo "# HELP ha_recorder_rows_in_window Rows the logbook returned for the probe window."
        echo "# TYPE ha_recorder_rows_in_window gauge"
        echo "ha_recorder_rows_in_window ${rows}"
    fi

    # Emitted ONLY when a real timestamp was found. On a failed probe, or an empty window, these
    # are absent rather than zero -- see the header: a 0 here reads as "epoch 1970", i.e. maximally
    # stale, and a 0 on staleness reads as "perfectly fresh". Both are lies in the failure case.
    if [ -n "$newest" ] && [ "$newest" != "-" ]; then
        echo "# HELP ha_recorder_newest_row_timestamp_seconds Unix timestamp of the newest row the recorder has persisted."
        echo "# TYPE ha_recorder_newest_row_timestamp_seconds gauge"
        echo "ha_recorder_newest_row_timestamp_seconds ${newest}"

        echo "# HELP ha_recorder_staleness_seconds Age of the newest persisted row. Grows without bound if the recorder stops writing."
        echo "# TYPE ha_recorder_staleness_seconds gauge"
        echo "ha_recorder_staleness_seconds $((now - newest))"
    fi
} > "$TMP"

mv -f "$TMP" "$OUT"
