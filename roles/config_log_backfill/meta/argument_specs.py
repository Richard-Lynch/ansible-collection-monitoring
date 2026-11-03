# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

DEFAULT_AUTHOR = "Collection maintainers"
from ansible_devkit.argspec.models import ArgumentSpec, ArgumentSpecs, OptionSpec

argument_specs = ArgumentSpecs(
    argument_specs={
        "main": ArgumentSpec(
            short_description="Backfill historical log files into Loki at their original timestamps",
            description=[
                "MECHANISM ONLY — the files, labels and timestamp formats belong to the caller.",
                "Sibling of config_logs: config_logs ships what a file gets from NOW on; this",
                "ships what the file already held before anyone was shipping it. Runs on the host",
                "that holds the files and pushes from there with a stdlib-only python3 script",
                "(files/loki_backfill.py), because a target may be an image-based OS where",
                "nothing can be pip-installed.",
                "",
                "GENERATE-DON'T-APPLY. The default run parses every file, reads Loki's own limits",
                "and its existing data, and REPORTS what it would push — per stream: records in the",
                "window, how many Loki already holds, where the window ends and why, unparsed",
                "lines, redactions. Nothing is pushed without config_log_backfill_apply=true, and a",
                "push is followed by a read-back from Loki's QUERY API (not the push response).",
                "",
                "A DISTINCT STREAM PER CAMPAIGN. Loki (unordered_writes) rejects an entry more than",
                "max_chunk_age/2 behind its stream's newest entry, so history pushed into the stream",
                "Alloy is writing now is 'entry too far behind'. Every backfilled stream carries the",
                "caller's labels PLUS <config_log_backfill_label>=<campaign>, so a selector written",
                "for the live stream matches both and Loki merges them in time order.",
                "",
                "IDEMPOTENT. Before pushing a stream the script asks Loki for that stream's newest",
                "entry and skips everything at or before it; pushes are ascending and stop at the",
                "first failure, so a re-run (or a resumed half-failed run) pushes exactly what is",
                "missing.",
            ],
            version_added="1.0",
            author=DEFAULT_AUTHOR,
            options={
                "config_log_backfill_action": OptionSpec(
                    type="str",
                    required=False,
                    default="backfill",
                    choices=["backfill", "verify", "repair_seam"],
                    description=[
                        "'backfill' plans (and with config_log_backfill_apply=true, pushes then",
                        "verifies). 'verify' only compares the files on disk with what Loki returns",
                        "for the same window, and never pushes.",
                        "'repair_seam' finds backfilled entries whose exact text Alloy ALSO",
                        "shipped near the seam and reports them; with config_log_backfill_apply=true",
                        "it sends one Loki delete request per affected SECOND, scoped to the",
                        "backfill stream's own selector, and only for a second in which every",
                        'backfilled entry is such a copy. See the README\'s "The seam".',
                    ],
                ),
                "config_log_backfill_apply": OptionSpec(
                    type="bool",
                    required=False,
                    default=False,
                    description=[
                        "Actually push. Off by default: the plan is the review step, and it is",
                        "cheap — it reads the files and queries Loki, nothing more.",
                    ],
                ),
                "config_log_backfill_campaign": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "The value of the backfill label on every pushed stream — a FIXED id for",
                        "this backfill ('steam-history-1'), never computed from the run date. Re-runs",
                        "of the same campaign resume the same streams (the idempotency watermark is",
                        "per stream); a run-dated value would make every re-run a NEW stream and",
                        "duplicate everything. Use a NEW campaign id only to backfill a period",
                        "OLDER than one already pushed for the same files — inside one stream Loki",
                        "rejects entries older than the stream's newest by more than the",
                        "out-of-order window. Restricted to [a-z0-9._-].",
                    ],
                ),
                "config_log_backfill_loki_url": OptionSpec(
                    type="str",
                    required=True,
                    description=[
                        "Loki's base URL AS SEEN FROM THE TARGET HOST (the push runs there), e.g.",
                        "http://loki.example.test:3100. Installation config, so no default.",
                    ],
                ),
                "config_log_backfill_sources": OptionSpec(
                    type="list",
                    elements="dict",
                    required=True,
                    description=[
                        "One entry per file set. Keys:",
                        "  name (str, required) — for the report.",
                        "  paths (list of globs, required) — files to read.",
                        "  exclude (list of fnmatch globs) — files to skip.",
                        "  labels (dict, required) — the stream labels, WITHOUT filename (added",
                        "    per file as `filename_label`, default 'filename', full path). Must",
                        "    include every label the LIVE streams carry or the plan fails — see",
                        "    live_selector.",
                        "  live_selector (LogQL selector) — the live streams this backfill joins.",
                        "    Used to check the labels match and to find where the window ends.",
                        "  formats (list, required) — [{regex, strptime}]; regex must contain",
                        "    (?P<ts>...). strptime is a Python format, or 'epoch' / 'epoch_ms'.",
                        "    The first format that MATCHES a line decides it.",
                        "  timezone (str, default UTC) — IANA zone for timestamps with no offset.",
                        "  continuation ('fold' | 'attach', default fold) — a line with no",
                        "    timestamp is appended to the previous record, or pushed as its own",
                        "    entry at the previous record's time.",
                        "  rotated (list) — [{regex, live}]: a file whose path matches `regex` is",
                        "    rotated history of the file named by re.sub(regex, live, path), and is",
                        "    pushed under THAT filename so one selector covers both.",
                        "  redact (list) — extra [{name, regex}] with a (?P<secret>...) group,",
                        "    added to config_log_backfill_redact for this source.",
                    ],
                ),
                "config_log_backfill_since": OptionSpec(
                    type="str",
                    required=False,
                    default="7d",
                    description=[
                        "How far back to go (Go-style duration). CLAMPED to Loki's",
                        "reject_old_samples_max_age minus config_log_backfill_max_age_margin, read",
                        "from the running Loki — a line older than that is rejected with HTTP 400,",
                        "and the report says when the clamp applied and how many lines it cost.",
                    ],
                ),
                "config_log_backfill_max_age_margin": OptionSpec(
                    type="str",
                    required=False,
                    default="30m",
                    description=[
                        "Safety margin inside reject_old_samples_max_age, so the oldest lines are",
                        "not rejected by the time the push (and its retries) reaches them.",
                    ],
                ),
                "config_log_backfill_end": OptionSpec(
                    type="str",
                    required=False,
                    default="auto",
                    description=[
                        "'auto': per stream, end where the LIVE stream (live_selector's labels with",
                        "no backfill label) begins inside the window — at the exact record whose",
                        "first line equals Loki's earliest live line, else at that line's time; a",
                        "stream with no live lines runs to now. Otherwise an ISO-8601 timestamp",
                        "with offset, applied to every stream.",
                    ],
                ),
                "config_log_backfill_label": OptionSpec(
                    type="str",
                    required=False,
                    default="backfill",
                    description=[
                        "Name of the label that separates backfilled streams from live ones.",
                    ],
                ),
                "config_log_backfill_redact": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[
                        {
                            "name": "key=value credential",
                            "regex": (
                                r"(?i)\b(?:access_?token|refresh_?token|webapi_?token|auth_?token"
                                r"|api_?key|apikey|password|passwd|secret|client_secret"
                                r"|steamLoginSecure|sessionid)\b[\"']?\s*[:=]\s*[\"']?"
                                r"(?P<secret>[^\s\"'&,;]{6,})"
                            ),
                        },
                        {
                            "name": "bearer header",
                            "regex": r"(?i)\bbearer\s+(?P<secret>[A-Za-z0-9._~+/=-]{12,})",
                        },
                        {
                            "name": "JWT",
                            "regex": (
                                r"(?P<secret>eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})"
                            ),
                        },
                    ],
                    description=[
                        "Credential-shaped patterns replaced with '<redacted>' before anything",
                        "leaves the host (the (?P<secret>) group is what is replaced, so the key",
                        "stays readable). Applied to every source; the report counts hits per",
                        "pattern per file so a hit is visible rather than silent. Deterministic,",
                        "so redaction does not break idempotency.",
                    ],
                ),
                "config_log_backfill_audit_terms": OptionSpec(
                    type="list",
                    elements="str",
                    required=False,
                    default=[
                        "token",
                        "password",
                        "passwd",
                        "secret",
                        "bearer",
                        "authorization",
                        "cookie",
                        "apikey",
                        "api_key",
                        "sessionid",
                    ],
                    description=[
                        "Case-insensitive words COUNTED per file, with up to three samples in which",
                        "every token-shaped run of 16+ characters is masked. This is the review",
                        "step for 'is anything sensitive in these files' — a redact pattern only",
                        "catches the shapes someone thought of, while a word count shows where to",
                        "look. Counting is not redaction: anything found here that IS a credential",
                        "needs a redact pattern before the push.",
                    ],
                ),
                "config_log_backfill_spot_checks": OptionSpec(
                    type="list",
                    elements="dict",
                    required=False,
                    default=[],
                    description=[
                        "Extra verify assertions: [{labels, contains, at}] — a line containing",
                        "`contains` must be returned by Loki for the selector built from `labels`",
                        "in the one-second window at `at` (ISO-8601 with offset). Proves a known",
                        "line landed at its ORIGINAL time rather than at ingestion time.",
                    ],
                ),
                "config_log_backfill_verify_wait": OptionSpec(
                    type="str",
                    required=False,
                    default="45m",
                    description=[
                        "How long verify keeps re-reading while lines are only MISSING. Loki's",
                        "querier reads ingesters only for the last query_ingesters_within (3h by",
                        "default), so a backfilled — old — line is accepted but invisible until its",
                        "chunk flushes, ~chunk_idle_period (30m) after the stream goes quiet.",
                        "An EXTRA line is never retried. Set it past",
                        "chunk_idle_period plus a margin; '0s' reads once.",
                    ],
                ),
                "config_log_backfill_verify_interval": OptionSpec(
                    type="str",
                    required=False,
                    default="60s",
                    description=["Pause between verify reads while waiting."],
                ),
                "config_log_backfill_batch_bytes": OptionSpec(
                    type="int",
                    required=False,
                    default=524288,
                    description=[
                        "Upper bound on one push body. Further capped at half of Loki's",
                        "ingestion_burst_size_mb, read live.",
                    ],
                ),
                "config_log_backfill_rate_fraction": OptionSpec(
                    type="float",
                    required=False,
                    default=0.5,
                    description=[
                        "Fraction of Loki's per-tenant ingestion rate (read live) the push may use.",
                        "The tenant is usually SHARED with every Alloy shipping live logs, so a",
                        "backfill that used the whole budget would 429 the live fleet.",
                    ],
                ),
                "config_log_backfill_python": OptionSpec(
                    type="str",
                    required=False,
                    default="python3",
                    description=["Interpreter on the target for files/loki_backfill.py (3.9+)."],
                ),
            },
        )
    }
)
