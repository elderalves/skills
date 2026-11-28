"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import design_ticket as dt


def issue(*labels, state="Ready for Design"):
    return {"identifier": "ALV-7", "state": {"name": state}, "labels": {"nodes": [{"name": l} for l in labels]}}


def comment(at, body, factory=False, author="Owner"):
    return {"created_at": at, "author": author, "from_factory": factory,
            "body": f"[alves-factory]\n\n{body}" if factory else body}


SELECTION_1 = comment("2026-11-28T10:00:00Z", '## Selection: Exploration 1\n\ntext\n\n**Design record**\n\n```json\n'
                      '{"exploration": 1, "page_id": "50:1", "recommendation": "B", "designs": [{"id": "B", "node_id": "51:2"}]}\n```',
                      factory=True)

BRIEF = """# Design brief

## User goal
Find an order fast.

## Requirements
1. Search.

## Design system
AgileKit.

## States and breakpoints
- empty

## Design hypotheses

### A — Productivity first
**Premise:** Power users scan many orders.
**Optimizes for:** throughput
**Trade-off:** dense for newcomers

### B — Clarity first
**Premise:** Most users check one order.
**Optimizes for:** comprehension
**Trade-off:** fewer rows on screen

## Out of scope
Nothing.
"""


class Settings(unittest.TestCase):
    def test_defaults(self):
        s = dt.settings(issue(), [])
        self.assertEqual((s["variations"], s["arm"], s["arm_source"], s["round"], s["re_entry"], s["calibration"]),
                         (3, "direct", "default", 1, False, False))

    def test_labels_set_the_arm_and_the_number_of_variations(self):
        s = dt.settings(issue("calibration", "arm:browser-first", "variations:4"), [])
        self.assertEqual((s["arm"], s["variations"], s["calibration"]), ("browser-first", 4, True))

    def test_a_calibration_ticket_must_name_its_arm(self):
        with self.assertRaisesRegex(dt.SettingsError, "must name its arm"):
            dt.settings(issue("calibration"), [])

    def test_contradictory_or_unknown_labels_are_errors(self):
        for labels in (("arm:direct", "arm:browser-first"), ("arm:storybook",), ("variations:1",),
                       ("variations:6",), ("variations:x",), ("variations:3", "variations:4")):
            with self.assertRaises(dt.SettingsError, msg=labels):
                dt.settings(issue(*labels), [])

    def test_first_round_feedback_is_every_owner_comment(self):
        s = dt.settings(issue(), [comment("2026-11-27T09:00:00Z", "Keep it simple"),
                                  comment("2026-11-27T09:05:00Z", "## Sweep: restart", factory=True)])
        self.assertEqual([f["body"] for f in s["feedback"]], ["Keep it simple"])

    def test_re_entry_reads_only_the_owners_comments_after_the_last_selection(self):
        comments = [comment("2026-11-27T09:00:00Z", "old note"), SELECTION_1,
                    comment("2026-11-28T11:00:00Z", "Explore again: bigger KPIs"),
                    comment("2026-11-28T11:01:00Z", "## Figma limit", factory=True)]
        s = dt.settings(issue(), comments)
        self.assertEqual((s["round"], s["re_entry"]), (2, True))
        self.assertEqual([f["body"] for f in s["feedback"]], ["Explore again: bigger KPIs"])
        self.assertEqual(s["previous_selection"]["recommendation"], "B")

    def test_an_owner_comment_quoting_a_selection_heading_does_not_count(self):
        s = dt.settings(issue(), [comment("2026-11-28T11:00:00Z", "## Selection: Exploration 1\nB please")])
        self.assertEqual(s["round"], 1)


class Claim(unittest.TestCase):
    def test_ready_for_design_is_claimed(self):
        self.assertEqual(dt.claim("Ready for Design"), {"action": "claim", "set": "Exploring",
                                                        "reason": "Ready for Design starts an Exploration run"})

    def test_exploring_and_other_statuses_exit(self):
        self.assertIn("owns", dt.claim("Exploring")["reason"])
        for state in ("Ready", "Awaiting Selection", "Refining", "Blocked"):
            self.assertEqual(dt.claim(state)["action"], "exit", state)


class Brief(unittest.TestCase):
    def test_a_well_formed_brief(self):
        hypotheses, problems = dt.check_brief(BRIEF, 2)
        self.assertEqual(problems, [])
        self.assertEqual([(h["id"], h["name"], h["tradeoff"]) for h in hypotheses],
                         [("A", "Productivity first", "dense for newcomers"), ("B", "Clarity first", "fewer rows on screen")])

    def test_the_count_must_match_the_run(self):
        self.assertIn("2 Design hypotheses, the run asks for 3", dt.check_brief(BRIEF, 3)[1])

    def test_missing_sections_and_fields_are_named(self):
        broken = BRIEF.replace("## States and breakpoints", "## States").replace("**Trade-off:** fewer rows on screen\n", "")
        problems = dt.check_brief(broken, 2)[1]
        self.assertIn("missing section: ## States and breakpoints", problems)
        self.assertIn("hypothesis B has no **Trade-off:** line", problems)

    def test_hypotheses_are_lettered_in_order(self):
        self.assertTrue(any("lettered" in p for p in dt.check_brief(BRIEF.replace("### B —", "### C —"), 2)[1]))

    def test_headings_after_the_hypotheses_section_are_not_hypotheses(self):
        self.assertEqual(len(dt.parse_hypotheses(BRIEF + "\n### Z — not a hypothesis\n")), 2)


class Designs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.round = Path(self.tmp.name) / "explore-1"
        (self.round / "variations").mkdir(parents=True)
        self.brief = Path(self.tmp.name) / "brief.md"
        self.brief.write_text(BRIEF + "\n### C — x\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args):
        out = io.StringIO()
        with redirect_stdout(out), redirect_stderr(io.StringIO()):
            code = dt.main(list(args))
        return code, out.getvalue()

    def test_builds_designs_from_variations_that_returned_a_frame(self):
        (self.round / "variations" / "A.json").write_text(json.dumps({"id": "A", "frame_node_id": "60-12", "arm": "direct"}))
        (self.round / "variations" / "B.json").write_text(json.dumps({"id": "B", "frame_node_id": "61:3", "arm": "direct"}),
                                                          encoding="utf-16")
        code, out = self.run_cli("designs", str(self.round), "--brief", str(self.brief), "--file-key", "K")
        self.assertEqual((code, json.loads(out)["designs"]), (0, ["A", "B"]))
        designs = json.loads((self.round / "designs.json").read_text(encoding="utf-8"))["designs"]
        self.assertEqual(designs[0]["screens"], [{"node_id": "60:12", "label": "desktop", "path": "screens/A/desktop.png"}])
        self.assertEqual((designs[1]["hypothesis"], designs[1]["tradeoff"], designs[1]["file_key"]),
                         ("Clarity first: Most users check one order.", "fewer rows on screen", "K"))

    def test_fewer_than_two_variations_exit_1(self):
        (self.round / "variations" / "A.json").write_text(json.dumps({"id": "A", "frame_node_id": "60:12"}))
        (self.round / "variations" / "B.json").write_text(json.dumps({"id": "B", "error": "Figma rate limit"}))
        code, out = self.run_cli("designs", str(self.round), "--brief", str(self.brief), "--file-key", "K")
        result = json.loads(out)
        self.assertEqual((code, result["enough"]), (1, False))
        self.assertEqual([m["id"] for m in result["missing"]], ["B"])
        self.assertEqual(result["missing"][0]["reason"], "Figma rate limit")


class Cli(unittest.TestCase):
    def test_settings_errors_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp:
            i, c = Path(tmp) / "i.json", Path(tmp) / "c.json"
            i.write_text(json.dumps(issue("calibration")))
            c.write_text("[]")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(dt.main(["settings", "--issue", str(i), "--comments", str(c)]), 2)
            self.assertIn("must name its arm", err.getvalue())

    def test_check_brief_exits_1_with_problems(self):
        with tempfile.TemporaryDirectory() as tmp:
            b = Path(tmp) / "brief.md"
            b.write_text(BRIEF, encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(dt.main(["check-brief", str(b), "--variations", "3"]), 1)
            self.assertIn("run asks for 3", out.getvalue())


if __name__ == "__main__":
    unittest.main()
