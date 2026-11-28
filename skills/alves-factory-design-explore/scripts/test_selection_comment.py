"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import design_ticket
import run_cost
import selection_comment as sc

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "alves-factory-design-review" / "scripts"))
import design_gate  # noqa: E402

POLICY = design_gate.load_policy([])
COUNCIL = json.loads((design_gate.DEFAULT_POLICY.parent / "default-council.json").read_text())


def design(did, name):
    return {"id": did, "hypothesis": f"{name}: premise of {did}", "tradeoff": f"gives up something for {did}",
            "file_key": "K", "screens": [{"node_id": f"6{ord(did)}:1", "label": "desktop", "path": f"screens/{did}/desktop.png"}]}


def review(seat, d, score, **fields):
    target = COUNCIL[seat]["target"]
    own = POLICY["seats"][seat]
    findings = fields.pop("findings", [{"criterion": c, "severity": "major", "element": f"{c} element",
                                        "problem": f"{c} problem", "fix": f"{c} fix"} for c in own if score < 7])
    return {"seat": seat, "design": d["id"], "provider_instance": target["providerInstanceId"], "model": target["model"],
            "screens_viewed": [s["path"] for s in d["screens"]], "scores": {c: score for c in own},
            "rationale": {c: "the KPI row" for c in own}, "critical_defects": fields.pop("critical_defects", []),
            "findings": findings, "strengths": fields.pop("strengths", [f"{seat} likes {d['id']}"])}


def decision(designs, scores, vetoed=()):
    reviews = {}
    for d, s in zip(designs, scores):
        reviews[d["id"]] = {seat: review(seat, d, s) for seat in POLICY["seats"]}
        if d["id"] in vetoed:
            reviews[d["id"]]["design-system"]["critical_defects"] = [
                {"category": "accessibility", "element": "grey labels", "problem": "contrast 2.4:1"}]
    record = design_gate.evaluate("explore", designs, reviews, [], COUNCIL, POLICY)
    record["policy"] = POLICY
    return record


DESIGNS = [design("A", "Productivity first"), design("B", "Clarity first"), design("C", "Guided")]
UPLOADS = {"A": "https://uploads.linear.app/a.png", "B": "https://uploads.linear.app/b.png", "C": "https://uploads.linear.app/c.png"}


def build(scores=(6, 9, 8), vetoed=(), uploads=UPLOADS, cost=None):
    return sc.build(decision(DESIGNS, scores, vetoed), DESIGNS, uploads, 2, "https://figma.com/design/K/?node-id=50-1",
                    "50:1", cost)


class Comment(unittest.TestCase):
    def test_heading_and_ranked_score_table(self):
        text = build()
        self.assertTrue(text.startswith("## Selection: Exploration 2\n"))
        self.assertIn("| Criterion (weight) | B | C | A |", text)
        self.assertIn("| **Score (0–10)** | **9.00** | 8.00 | 6.00 |", text)
        self.assertIn("| usability (15) | 9 | 8 | 6 |", text)

    def test_each_variation_has_screenshot_hypothesis_findings_strengths_and_tradeoffs(self):
        text = build()
        section = text.split("### A — Productivity first")[1].split("### ")[0]
        self.assertIn("![A — desktop](https://uploads.linear.app/a.png)", section)
        self.assertIn("**Hypothesis:** premise of A", section)
        self.assertIn("1. **major · usability**: usability problem _(usability element)_ → usability fix", section)
        self.assertEqual(section.count("\n1. ") + section.count("\n2. ") + section.count("\n3. "), 3)
        self.assertIn("- product-designer likes A", section)
        self.assertIn("**Trade-offs:** gives up something for A Weakest criterion: usability (6).", section)

    def test_a_veto_shows_in_the_table_the_section_and_the_recommendation(self):
        text = build(scores=(6, 9, 8), vetoed=("B",))
        self.assertIn("| **Score (0–10)** | **8.00** | 6.00 | 9.00 ⛔ veto |", text)
        self.assertIn("- ⛔ **accessibility**: contrast 2.4:1 _(grey labels)_", text)
        self.assertIn("**C**. C scores 8.0, the highest of the designs without a veto", text)

    def test_every_design_vetoed_recommends_none(self):
        self.assertIn("**None.** every design has a critical usability or accessibility defect",
                      build(vetoed=("A", "B", "C")))

    def test_the_council_never_selects_and_the_owner_is_told_how_to_continue(self):
        text = build()
        self.assertIn("The Council recommends; it never selects.", text)
        self.assertIn("**Refining**", text)
        self.assertIn("**Ready for Design**", text)
        self.assertIn("**Canceled**", text)
        self.assertIn("[the ticket's page in the Factory Figma file](https://figma.com/design/K/?node-id=50-1)", text)

    def test_a_missing_upload_is_said_not_fatal(self):
        self.assertIn("_The screenshot did not upload; open the Variation in Figma._", build(uploads={"A": "u", "B": "u"}))

    def test_the_cost_line_is_included(self):
        self.assertIn("**Run cost:** 5 min", build(cost="**Run cost:** 5 min · 0 tokens · 3 Figma calls"))

    def test_the_design_record_round_trips_through_design_ticket_settings(self):
        text = build()
        record = json.loads(re.search(r"```json\n(.*)\n```", text).group(1))
        self.assertEqual(record["recommendation"], "B")
        self.assertEqual([(d["id"], d["node_id"]) for d in record["designs"]], [("B", "666:1"), ("C", "667:1"), ("A", "665:1")])
        comment = {"created_at": "2026-11-28T10:00:00Z", "from_factory": True, "body": "[alves-factory]\n\n" + text}
        settings = design_ticket.settings({"labels": {"nodes": []}}, [comment])
        self.assertEqual((settings["round"], settings["previous_selection"]), (3, record))

    def test_a_calibration_arm_is_shown_and_recorded(self):
        text = sc.build(decision(DESIGNS, (6, 9, 8)), DESIGNS, UPLOADS, 1, "u", "p", arm="browser-first")
        self.assertIn("**Calibration arm:** `browser-first`", text)
        self.assertEqual(json.loads(re.search(r"```json\n(.*)\n```", text).group(1))["arm"], "browser-first")

    def test_a_refine_decision_is_refused(self):
        with self.assertRaises(ValueError):
            sc.build({"mode": "refine", "decision": "continue"}, DESIGNS, UPLOADS, 1, "u", "p")


class Cli(unittest.TestCase):
    def test_cli_writes_the_comment_with_the_cost_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "explore-1"
            root.mkdir()
            (root / "decision.json").write_text(json.dumps(decision(DESIGNS, (6, 9, 8))), encoding="utf-8")
            (root / "designs.json").write_text(json.dumps({"designs": DESIGNS}), encoding="utf-8")
            (root / "uploads.json").write_text(json.dumps(UPLOADS), encoding="utf-16")
            ledger = root / "cost.json"
            run_cost.start(ledger, "2026-11-28T10:00:00+00:00")
            run_cost.add(ledger, "review", figma=6, tokens=5000)
            out_file = root / "selection.md"
            with redirect_stdout(io.StringIO()):
                code = sc.main([str(root), "--round", "1", "--figma-url", "https://f", "--page-id", "50:1",
                                "--uploads", str(root / "uploads.json"), "--ledger", str(ledger),
                                "--now", "2026-11-28T10:30:00+00:00", "--out", str(out_file)])
            self.assertEqual(code, 0)
            self.assertIn("**Run cost:** 30 min · 5,000 tokens · 6 Figma calls", out_file.read_text(encoding="utf-8"))

    def test_cli_exits_2_on_a_missing_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                code = sc.main([tmp, "--round", "1", "--figma-url", "u", "--page-id", "p", "--uploads", f"{tmp}/u.json"])
            self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
