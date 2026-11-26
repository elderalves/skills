"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import diff_gate


COUNCIL = {
    "requirements": {"target": {"providerInstanceId": "codex", "model": "gpt-6.2-sol"}},
    "architecture": {"target": {"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5"}},
    "testing-risk": {"target": {"providerInstanceId": "opencode", "model": "opencode-go/muse-spark-1.3-contributor"}},
}


def finding(severity="minor", **fields):
    base = {"severity": severity, "file": "src/a.ts", "line": 12, "problem": "p", "evidence": "e", "fix": "f"}
    base.update(fields)
    return base


def review(lens, verdict="approve", findings=(), **fields):
    seat = COUNCIL[lens]["target"]
    base = {"reviewer": lens, "provider_instance": seat["providerInstanceId"], "model": seat["model"],
            "verdict": verdict, "summary": "s", "findings": list(findings)}
    base.update(fields)
    return base


def clean_round():
    return [review(lens) for lens in COUNCIL]


class Evaluate(unittest.TestCase):
    def test_three_approvals_are_clean(self):
        result = diff_gate.evaluate(clean_round(), COUNCIL, 0)
        self.assertEqual(result["result"], "clean")
        self.assertEqual([r["verdict"] for r in result["reviews"]], ["approve"] * 3)

    def test_minor_findings_stay_clean_and_are_kept(self):
        reviews = clean_round()
        reviews[0]["findings"] = [finding("minor", problem="rename x")]
        result = diff_gate.evaluate(reviews, COUNCIL, 0)
        self.assertEqual(result["result"], "clean")
        self.assertEqual(result["minors"][0]["problem"], "rename x")
        self.assertEqual(result["minors"][0]["reviewer"], "requirements")

    def test_a_major_finding_on_the_first_pass_asks_for_a_fix(self):
        reviews = clean_round()
        reviews[1] = review("architecture", "changes", [finding("major", problem="dead branch")])
        result = diff_gate.evaluate(reviews, COUNCIL, 0)
        self.assertEqual(result["result"], "fix")
        self.assertEqual(result["reasons"], ["architecture: dead branch (src/a.ts:12)"])

    def test_a_major_finding_on_the_last_pass_is_unresolved(self):
        reviews = clean_round()
        reviews[2] = review("testing-risk", "changes", [finding("major", line=None)])
        result = diff_gate.evaluate(reviews, COUNCIL, diff_gate.MAX_FIX_PASSES)
        self.assertEqual(result["result"], "unresolved")
        self.assertEqual(result["reasons"], ["testing-risk: p (src/a.ts)"])

    def test_a_missing_seat_is_incomplete(self):
        result = diff_gate.evaluate(clean_round()[:2], COUNCIL, 0)
        self.assertEqual(result["result"], "incomplete")
        self.assertEqual(result["reasons"], ["testing-risk: no review"])

    def test_a_review_off_its_seat_is_incomplete(self):
        reviews = clean_round()
        reviews[0]["model"] = "claude-opus-5-5"
        result = diff_gate.evaluate(reviews, COUNCIL, 0)
        self.assertEqual(result["result"], "incomplete")
        self.assertIn("requirements: written by claude-opus-5-5", result["reasons"][0])

    def test_unreadable_files_are_incomplete(self):
        result = diff_gate.evaluate(clean_round(), COUNCIL, 0, ["x.json: unreadable"])
        self.assertEqual(result["result"], "incomplete")


class Validate(unittest.TestCase):
    CASES = [
        ("unknown verdict", review("requirements", "ok"), "verdict must be"),
        ("findings not a list", review("requirements") | {"findings": "x"}, "findings must be a list"),
        ("unknown severity", review("requirements", findings=[finding("blocker")]), "severity must be"),
        ("finding without evidence", review("requirements", findings=[finding(evidence="")]), "evidence is missing"),
        ("line zero", review("requirements", findings=[finding(line=0)]), "line must be"),
        ("approve with a major", review("requirements", "approve", [finding("major")]), "approve allows only minor"),
        ("changes with only minors", review("requirements", "changes", [finding("minor")]), "changes needs"),
        ("no model", review("requirements", model=""), "model is missing"),
    ]

    def test_each_malformed_review_is_named(self):
        for name, bad, fragment in self.CASES:
            with self.subTest(name):
                problems = diff_gate.validate_review(bad)
                self.assertTrue(any(fragment in p for p in problems), problems)

    def test_a_good_review_has_no_problems(self):
        self.assertEqual(diff_gate.validate_review(review("architecture", "changes", [finding("major")])), [])


class Main(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.reviews = self.dir / "reviews"
        self.reviews.mkdir()
        self.council = self.dir / "council.json"
        self.council.write_text(json.dumps(COUNCIL), encoding="utf-8")

    def write_reviews(self, reviews, encoding="utf-8"):
        for r in reviews:
            (self.reviews / f"{r['reviewer']}.json").write_text(json.dumps(r), encoding=encoding)

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = diff_gate.main([str(a) for a in argv])
        return code, out.getvalue(), err.getvalue()

    def test_writes_the_result_beside_the_reviews(self):
        self.write_reviews(clean_round())
        code, printed, _ = self.call(self.reviews, "--council", self.council, "--pass", 0)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed)["result"], "clean")
        written = json.loads((self.dir / "diff-review.json").read_text(encoding="utf-8"))
        self.assertEqual(written["result"], "clean")
        self.assertEqual(len(written["reviews"]), 3)

    def test_reads_files_with_a_byte_order_mark(self):
        self.write_reviews(clean_round(), encoding="utf-8-sig")
        code, printed, _ = self.call(self.reviews, "--council", self.council, "--pass", 0)
        self.assertEqual(json.loads(printed)["result"], "clean")

    def test_check_mode_reports_problems(self):
        self.write_reviews([review("requirements", "changes")])
        code, printed, _ = self.call(self.reviews, "--check")
        self.assertEqual(code, 1)
        self.assertIn("changes needs", printed)

    def test_check_mode_passes_good_reviews(self):
        self.write_reviews(clean_round())
        self.assertEqual(self.call(self.reviews, "--check")[:2], (0, "ok\n"))

    def test_unreadable_council_is_unusable(self):
        self.write_reviews(clean_round())
        code, _, err = self.call(self.reviews, "--council", self.dir / "none.json", "--pass", 0)
        self.assertEqual(code, 2)
        self.assertIn("cannot read council", err)


if __name__ == "__main__":
    unittest.main()
