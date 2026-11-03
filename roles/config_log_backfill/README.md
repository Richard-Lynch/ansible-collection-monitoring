# config_log_backfill

Push the **history** in log files into Loki, at each line's **original**
timestamp — the lines a file already held before anything was shipping it.

Sibling of `config_logs`: `config_logs` ships what a file gets from now on; this
ships what it had before. Same split as every `config_*` role — the role is the
**mechanism**, the files, labels and formats belong to the caller's play.

"We need history from files we weren't shipping" recurs — a fault is explained
by logs written in the days before a collector tailed them — so this is a role
rather than a one-off.

## Usage

```yaml
- name: Backfill a host's qBittorrent logs
  hosts: media
  gather_facts: false
  vars:
    config_log_backfill_campaign: qbittorrent-history-1 # FIXED; see "Label scheme"
    config_log_backfill_loki_url: "http://loki.example.test:3100" # as seen from THIS host
    config_log_backfill_since: 3d
    config_log_backfill_sources:
      - name: qbittorrent
        paths: ["/var/log/qbittorrent/*.log"]
        labels: { component: qbittorrent, job: media, hostname: media } # = the live stream's labels
        live_selector: '{component="qbittorrent"}'
        timezone: UTC
        formats:
          - regex: '^\((?P<ts>\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2})\)'
            strptime: "%d/%m/%Y %H:%M:%S"
  roles:
    - role: richard_lynch.monitoring.config_log_backfill
```

| `config_log_backfill_action` | with `config_log_backfill_apply` | does                                                                                                                                                                                 |
| ---------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `backfill` _(default)_       | `false` _(default)_              | **PLAN**: per file — records in the window, how many Loki already has, where the window ends and why, unparsed lines (with samples), redactions, and a keyword audit. Pushes nothing |
| `backfill`                   | `true`                           | push, then read every line back from Loki's QUERY API and compare it with the files                                                                                                  |
| `verify`                     | —                                | the read-back alone, any time later — files vs Loki line by line, plus the seam check                                                                                                |
| `repair_seam`                | `false` / `true`                 | report backfilled copies of lines Alloy ALSO shipped at the seam; with apply, delete them (one Loki delete per second, backfill selector only)                                       |

Pass = `missing=0 extra=0 seam_dup=0` on every stream and every spot check OK. A
`seam_pending_delete=N` with a `WARNING (not a failure)` line means a seam copy
is covered by a delete request Loki has not yet acted on; it is reported with
its effective time. Run verify again once `delete_request_cancel_period` has
elapsed and the compactor has purged them: `pending_delete_requests` drops to 0
and nothing else changes.

Run the plan first and read it: it is where a missing live label or a format
that matches nothing shows up, and both are fixed in the caller's data, not the
role.

## Label scheme, and why

Every backfilled stream carries **the live stream's labels plus
`backfill="<campaign>"`**:

```
live:      {log_source="steam", job="workstations", hostname="ws1", filename=".../steamui_system.txt"}
backfill:  {...the same..., backfill="steam-history-1"}
```

- **A separate stream is required, not a preference.** With `unordered_writes`,
  Loki rejects an entry more than `max_chunk_age / 2` (1h by default) behind its
  stream's newest entry: a 2-day-old entry into a stream with a current entry is
  **HTTP 400
  `entry too far behind ... oldest acceptable timestamp is: <now-1h>`**, and the
  identical entry into a stream with one extra label is **204**.
- **The plan refuses to push if a live stream carries a label the backfill
  lacks** — then a query written for the live stream would silently not find the
  history.
- **The value is a fixed campaign id, never the run date.** The idempotency
  watermark is per stream; a run-dated value would make every re-run a new
  stream and duplicate everything. Use a new campaign only to backfill a period
  OLDER than one already pushed for the same files (inside one stream, the same
  1h rule rejects it).
- **Rotated files join their live name.** Steam, for example, renames `foo.txt`
  to `foo.previous.txt`; those lines are pushed under `filename=".../foo.txt"`,
  so one selector returns the file's whole past.

### Querying

Selecting by the live labels returns **both** streams, merged in time order — no
change to any existing query:

```logql
{log_source="steam", filename="/home/user/.local/share/Steam/logs/steamui_system.txt"}
```

Only the backfill, or only what Alloy shipped:

```logql
{log_source="steam", backfill="steam-history-1"}
{log_source="steam", backfill=""}       # label absent = the live stream
```

## Timestamps

Each line carries the time **parsed from the line**, never ingestion time. Per
source: a list of `{regex with (?P<ts>…), strptime}` formats (first match
decides), and a `timezone` for timestamps with no offset (Steam, for one, writes
local wall-clock time).

- **Continuation lines** (no timestamp of their own) are folded into the
  previous record with `\n` (or attached as their own entry at its time,
  `continuation: attach`).
- **Lines before a file's first timestamp** have no time to inherit: **reported
  as UNPARSED with samples, never silently dropped**. Blank lines are counted
  separately and never pushed.
- **Year-less formats** (Chromium's `[MMDD/HHMMSS.us:…]`) take the year from the
  **file's mtime**, not from now — a stale file last written a year ago must not
  land in this week's window.
- **Every line gets a unique nanosecond**: lines sharing a second get +0, +1, +2
  ns in file order. Loki stores an identical (stream, timestamp, line) once, so
  two genuinely repeated lines in one second would otherwise collapse and the
  on-disk count could never match.
- The plan shows **records AND raw lines** dropped as older than the window. A
  record that swallowed far more lines than it should is the tell of a format
  that does not match — a handful of out-of-window records hiding hundreds of
  today's lines means the format missed a prefix.

## Loki's limits — read live, not assumed

The role reads `GET /config` (the daemon's MERGED config, not a template) on
every run, and acts on what it finds:

| setting                                | consequence                                                                                                        |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| `reject_old_samples` / `_max_age`      | `since` is clamped to max_age − `max_age_margin` (30m), and the report says the clamp applied                      |
| `unordered_writes`, `max_chunk_age`    | out-of-order window → separate stream, ascending order                                                             |
| `max_line_size` / `_truncate`          | longer records are truncated client-side, marked, and counted (an over-long line would be a 400)                   |
| `ingestion_rate_mb` / `_burst_size_mb` | batches ≤ half the burst, paced to `config_log_backfill_rate_fraction` of the tenant rate (shared with live Alloy) |
| `per_stream_rate_limit`                | also bounds the pacing                                                                                             |
| `max_label_names_per_series`           | checked per stream before pushing                                                                                  |
| `query_ingesters_within`               | see "Visibility" — the reason verify polls                                                                         |
| `ingester.chunk_idle_period`           | ditto                                                                                                              |

## Idempotency

Before pushing a stream the script asks **Loki** for that stream's newest entry
and skips everything at or before it. Pushes are ascending and stop at the first
non-2xx, so "newest in Loki" means "everything up to here landed" — a re-run, or
a resume after a failure, pushes exactly what is missing. The authority is Loki
itself rather than a state file on the host, which could disagree with it after
a retention sweep or a half-failed run.

Loki additionally stores an identical (stream, timestamp, line) once, and every
entry here is deterministic (same nanosecond, same redaction), so even a line
pushed twice would not duplicate.

## Visibility: why verify waits

`query_ingesters_within` (3h by default) means the querier asks ingesters only
for the last 3h and storage for everything older. A backfilled entry is old **by
definition**, so until its chunk flushes — after `chunk_idle_period` (30m) of no
new entries in that stream — **it is in Loki and not queryable**: accepted (204)
and absent from an immediate query.

So the post-push verify **polls**: it re-reads until every expected line is
present, up to `config_log_backfill_verify_wait` (default 45m). Only "missing"
is retried; an **extra** entry (a duplicate, a mis-dated line) fails
immediately. The same delay means a re-run **within ~30 minutes of a push**
cannot see the watermark for older lines; it then fails LOUDLY
(`entry too far behind`, because the unflushed stream still holds the newer
lines) rather than duplicating.

## Sensitive content

Before anything leaves the host, credential-shaped values are replaced with
`<redacted>` (`config_log_backfill_redact`: `key=value` for
token/password/secret/sessionid…, bearer headers, JWTs; extend per source).
Deterministic, so redaction does not break idempotency. The plan also counts
**audit terms** per file with masked samples showing the term's own argument —
enough to tell `--password-store=basic` from a credential without printing a
credential into the run log.

## The seam

Where the window ends, the backfill must stop exactly where the live stream
begins, or the first second of each live file lands in BOTH streams. Many files
open with blank lines, so Loki's earliest live line can be BLANK, and the script
never makes a record of a blank line — an exact-match cut against it never
matches, and a time fallback at the live line's INGESTION stamp lets the whole
second through. Verify alone cannot see that: it compares the backfill stream
with the files, and those lines ARE in the files.

So: the live edge is the first **non-blank** live line (`|~ \`\S\``); the
fallback cuts at the **start** of that second; and verify runs a **seam check**
— backfilled entries within ±300s of the cut whose text (every line of a folded
record; Alloy ships those as separate lines) Alloy also shipped — which fails
the run.

`config_log_backfill_action=repair_seam` removes such copies: one delete request
per affected second, each `query=<that stream's backfill selector>` (so it
cannot match a live stream), `start=<second>`, `end=<second>.999` (the range is
inclusive at ms precision), sent only for a second in which every backfilled
entry is a copy. Loki reads the delete parameters from the URL query string, not
a form body. Loki filters deleted entries from queries shortly after accepting a
request, and the compactor purges them after `delete_request_cancel_period`.
Until Loki marks a request `processed`, verify reads `/loki/api/v1/delete` and
reports a seam copy covered by a pending request — same stream labels, inside
its time range — as a WARNING with its effective time, never as a pass with no
comment and never as a failure. An uncovered copy, a missing line or an extra
line still fails.

## Tests

`molecule/default` drives the real role and script against `fake_loki.py`, a
stub that enforces the three Loki rules the design depends on (too old, too far
behind, dedupe): plan → push+verify → re-run (no HTTP request at all) → injected
HTTP 500 (play fails) → resume (exactly the remainder) → `action=verify` → seam
copy (verify fails; dry-run repair changes nothing; applied repair removes it; a
pending delete is a warning) → an interpreter that exits 0 with no report
(fails) → campaign guard. `files/test_repair_scope.py` unit-tests that a delete
not scoped to a backfill stream is refused before any request.

Each of these is mutation-tested — a deliberate break makes `molecule test` go
red:

| #   | mutation                                         | caught by                                                 |
| --- | ------------------------------------------------ | --------------------------------------------------------- |
| M1  | no per-second nanosecond sequence                | `dup_count == 2` (Loki's dedupe ate a real repeated line) |
| M2  | watermark ignored (always push the whole window) | re-run sends an HTTP request                              |
| M3  | redaction off                                    | the credential reaches Loki                               |
| M4  | push error swallowed, batch counted as pushed    | failure must come from the PUSH gate, not verify          |
| M5  | rotated file not relabelled to its live name     | one stream expected, two produced                         |
| M6  | live cut ignored (push to now)                   | to_push 8, not 6                                          |
| M7  | campaign guard removed                           | path-shaped campaign accepted                             |
| M8  | verify gate removed                              | tampered file must fail verify                            |
| M9  | verify reads once (no polling)                   | stub hides old entries from the first reads               |
| M10 | push gate removed                                | ditto M4                                                  |
| M11 | rc-only `failed_when` on the script task         | `/usr/bin/true` (rc 0, no output) must fail               |
| M12 | live edge may be a blank line                    | cut no longer `matched` against a blank-first live stream |
| M13 | seam duplicates not failed on                    | injected seam copy must fail verify                       |
| M14 | pending deletes ignored                          | covered copy must be a warning, not a failure             |
| M15 | pending match ignores the time range             | a copy in a second no request covers must still fail      |

M11 exists because a module result that cannot be deserialised (a login shell's
terminal escape queries ahead of an `async` wrapper's JSON, say) arrives with
`rc: 0` and no stdout, and an rc-only `failed_when` turns that failure into
**ok**. Every script task therefore also requires the report in stdout, and
`async` is not used.

## Limitations

- A continuation line written inside the window but folded into a record from
  before it is dropped with that record. The rec/lines split in the plan makes
  it visible; a format that matches the file is the fix.
- If a file loses lines between push and verify (Steam rotates on restart and
  keeps only one `.previous`), verify reports them as **extra** in Loki.
  Correct, and loud.
- Runs on the host with the files. Python 3.9+ stdlib only.
