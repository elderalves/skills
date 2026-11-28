"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

import run_cost


class Ledger(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.ledger = Path(self.tmp.name) / "explore-1" / "cost.json"
        run_cost.start(self.ledger, "2026-11-28T10:00:00+00:00")

    def tearDown(self):
        self.tmp.cleanup()

    def test_totals_time_tokens_and_figma_calls(self):
        run_cost.add(self.ledger, "page setup", figma=1, tokens=12000)
        run_cost.add(self.ledger, "variation A", figma=9, tokens=410000)
        run_cost.add(self.ledger, "variation B", figma=7)
        s = run_cost.summary(run_cost.read(self.ledger), "2026-11-28T10:47:20+00:00")
        self.assertEqual((s["elapsed_minutes"], s["figma_calls"], s["tokens"], s["tokens_unreported"]),
                         (47, 17, 422000, ["variation B"]))

    def test_render_names_what_reported_no_tokens(self):
        run_cost.add(self.ledger, "variation B", figma=7)
        self.assertEqual(run_cost.render(run_cost.read(self.ledger), "2026-11-28T11:00:00Z"),
                         "**Run cost:** 60 min · 0 tokens (not reported by: variation B) · 7 Figma calls")

    def test_start_resets_an_existing_ledger(self):
        run_cost.add(self.ledger, "old", figma=3)
        run_cost.start(self.ledger, "2026-11-28T12:00:00+00:00")
        self.assertEqual(run_cost.read(self.ledger)["entries"], [])

    def test_negative_counts_are_rejected(self):
        with self.assertRaises(ValueError):
            run_cost.add(self.ledger, "x", figma=-1)

    def test_cli_add_prints_the_running_summary(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = run_cost.main(["add", str(self.ledger), "--label", "review", "--figma", "6", "--tokens", "90000",
                                  "--now", "2026-11-28T10:30:00+00:00"])
        self.assertEqual((code, json.loads(out.getvalue())["figma_calls"]), (0, 6))


class FigmaLimit(unittest.TestCase):
    def test_rate_limit_errors_are_recognised(self):
        for text in ("Rate limit exceeded for this plan", "HTTP 429 Too Many Requests",
                     "You have reached the daily call limit", "MCP quota exhausted", "rate_limited"):
            self.assertTrue(run_cost.is_limit(text), text)

    def test_other_errors_are_not(self):
        for text in ("Figma could not access the requested file", "Component set has existing errors",
                     "node 4:29 not found"):
            self.assertFalse(run_cost.is_limit(text), text)

    def test_the_limit_comment(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "cost.json"
            run_cost.start(ledger, "2026-11-28T10:00:00+00:00")
            run_cost.add(ledger, "variation A", figma=14, tokens=1000)
            text = run_cost.limit_comment(run_cost.read(ledger), "Build the Variations",
                                          "\nHTTP 429: Rate limit exceeded\nretry later", now="2026-11-28T10:20:00+00:00")
        self.assertTrue(text.startswith("## Figma limit\n"))
        self.assertIn("at **Build the Variations**: `HTTP 429: Rate limit exceeded`", text)
        self.assertIn("200 Figma MCP calls a day and 15 a minute", text)
        self.assertIn("**Run cost:** 20 min · 1,000 tokens · 14 Figma calls", text)
        self.assertIn("move the ticket back to **Ready for Design**", text)

    def test_cli_is_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = Path(tmp) / "error.txt"
            err.write_text("Too many requests", encoding="utf-16")
            out = io.StringIO()
            with redirect_stdout(out):
                run_cost.main(["is-limit", "--error-file", str(err)])
        self.assertEqual(json.loads(out.getvalue()), {"limit": True})


if __name__ == "__main__":
    unittest.main()
