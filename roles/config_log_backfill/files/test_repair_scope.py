# SPDX-License-Identifier: GPL-3.0-or-later
"""repair_seams must refuse any delete not scoped to a backfill stream. Stdlib only.

Both directions: a delete aimed at a LIVE stream must be
refused before any HTTP request is made, and a correctly scoped dry run must not be.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import loki_backfill as lb  # noqa: E402

LIVE = '{filename="/x/a.txt",hostname="ws1",log_source="steam"}'
SCOPED = '{backfill="steam-history-1",filename="/x/a.txt",hostname="ws1",log_source="steam"}'


class RepairScope(unittest.TestCase):
    def setUp(self):
        # Any network call is a failure: the guard must decide before Loki is touched.
        def boom(*a, **k):
            raise AssertionError("Loki was contacted")

        self._saved = (lb.seam_duplicates, lb.loki_all)
        lb.seam_duplicates = lambda cfg, rst, cut: [(5 * lb.NS, "dup")]
        lb.loki_all = boom

    def tearDown(self):
        lb.seam_duplicates, lb.loki_all = self._saved

    def run_repair(self, cfg, stream):
        cfg = {"loki_url": "http://loki.invalid", **cfg}
        report = {"ok": True, "errors": []}
        lb.repair_seams(cfg, report, [({"stream": stream}, None, 0)], None)
        return report

    def test_empty_campaign_is_refused(self):
        # {backfill=""} matches streams WITHOUT the label: the live ones.
        with self.assertRaises(lb.LokiError):
            self.run_repair({"campaign": "", "apply": True}, SCOPED)

    def test_empty_label_is_refused(self):
        with self.assertRaises(lb.LokiError):
            self.run_repair(
                {"campaign": "steam-history-1", "backfill_label": "", "apply": True},
                SCOPED,
            )

    def test_live_stream_is_refused(self):
        with self.assertRaises(lb.LokiError):
            self.run_repair({"campaign": "steam-history-1", "apply": True}, LIVE)

    def test_scoped_stream_passes_the_guard(self):
        # Near-miss: correctly scoped, so the guard lets it through to the (stubbed) read.
        lb.loki_all = lambda url, stream, a, b: {"x": [(5 * lb.NS, "dup")]}
        report = self.run_repair({"campaign": "steam-history-1", "apply": False}, SCOPED)
        self.assertEqual(report["repair"][0]["action"], "would delete")


if __name__ == "__main__":
    unittest.main(verbosity=1)
