"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import gate


POLICY = gate.load_policy([])
PROVIDERS = ["anthropic", "openai", "google"]


def review(score=95, provider="anthropic", verdict="approve", **fields):
    scores = {criterion: score for criterion in POLICY["weights"]}
    scores.update(fields.pop("scores", {}))
    return {"reviewer": f"{provider}-reviewer", "provider": provider, "verdict": verdict,
            "scores": scores, "blockers": [], "issues": [], "risk_flags": [], **fields}


def council(*scores, verdicts=None, **fields):
    verdicts = verdicts or ["approve"] * len(scores)
    return [review(s, PROVIDERS[i % 3], verdicts[i], **fields) for i, s in enumerate(scores)]


CASES = [
    # (name, reviews, revision, plan risk flags, expected decision, expected rule)
    ("strong unanimous round", council(95, 92, 90), 0, [], "implement", "meets-bar"),
    ("exactly on every threshold", council(90, 85, 95), 0, [], "implement", "meets-bar"),
    ("high average but one low reviewer", council(98, 98, 60), 0, [], "revise", "below-bar"),
    ("one low reviewer at the cap", council(98, 98, 60), 2, [], "escalate", "revision-cap"),
    ("one reviewer below lowest bar", council(98, 98, 84), 0, [], "revise", "below-bar"),
    ("spread too wide", council(100, 100, 89), 0, [], "revise", "below-bar"),
    ("good scores but a revise vote", council(95, 95, 95, verdicts=["approve", "revise", "approve"]),
     0, [], "revise", "below-bar"),
    ("middling round", council(85, 82, 80), 0, [], "revise", "below-bar"),
    ("middling round at the cap", council(85, 82, 80), 2, [], "escalate", "revision-cap"),
    ("strong round at the cap still implements", council(95, 95, 95), 2, [], "implement", "meets-bar"),
    ("weak round", council(70, 72, 74), 0, [], "escalate", "score-too-low"),
    ("a reviewer escalates", council(95, 95, 95, verdicts=["approve", "approve", "escalate"]),
     0, [], "escalate", "reviewer-escalated"),
    ("a Blocker", council(95, 95, 95)[:2] + [review(95, "google", blockers=[{"question": "Q?"}])],
     0, [], "escalate", "blockers"),
    ("Issues alone never escalate", council(85, 85, 85, issues=[{"issue": "x"}]),
     0, [], "revise", "below-bar"),
    ("plan declares a Risk flag", council(95, 95, 95), 0, ["auth"], "escalate", "risk-flags"),
    ("reviewer adds a Risk flag", council(95, 95)[:2] + [review(95, "google", risk_flags=["dependency"])],
     0, [], "escalate", "risk-flags"),
    ("single provider", [review(95, "anthropic") for _ in range(3)], 0, [], "escalate", "single-provider"),
    ("two reviews", council(95, 95), 0, [], "escalate", "too-few-reviews"),
    ("no reviews", [], 0, [], "escalate", "too-few-reviews"),
    ("score above 100", council(95, 95)[:2] + [review(95, "google", scores={"risk": 101})],
     0, [], "escalate", "invalid-reviews"),
    ("missing criterion", council(95, 95)[:2] + [
        {**review(95, "google"), "scores": {"requirements": 95}}], 0, [], "escalate", "invalid-reviews"),
    ("bad verdict", council(95, 95, 95, verdicts=["approve", "approve", "ship it"]),
     0, [], "escalate", "invalid-reviews"),
    ("boolean score", council(95, 95)[:2] + [review(95, "google", scores={"risk": True})],
     0, [], "escalate", "invalid-reviews"),
]


class GateRules(unittest.TestCase):
    def test_cases(self):
        for name, reviews, revision, flags, decision, rule in CASES:
            with self.subTest(name):
                record = gate.evaluate(reviews, revision, flags, POLICY)
                self.assertEqual((record["decision"], record["rule"]), (decision, rule), record["reasons"])

    def test_plan_score_is_weighted(self):
        reviews = council(90, 90, 90)
        reviews[0]["scores"]["requirements"] = 50  # weight 25 of 100: costs 10 points
        record = gate.evaluate(reviews, 0, [], POLICY)
        self.assertEqual(record["reviews"][0]["score"], 80.0)
        self.assertEqual(record["plan_score"], round((80 + 90 + 90) / 3, 1))

    def test_unknown_risk_flag_still_escalates_and_is_reported(self):
        record = gate.evaluate(council(95, 95, 95), 0, ["mystery"], POLICY)
        self.assertEqual(record["decision"], "escalate")
        self.assertEqual(record["unknown_risk_flags"], ["mystery"])

    def test_policy_override_changes_threshold(self):
        policy = gate.merge(POLICY, {"implement": {"min_average": 80, "min_lowest": 80, "max_spread": 20}})
        self.assertEqual(gate.evaluate(council(85, 82, 80), 0, [], policy)["decision"], "implement")


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reviews = self.tmp / "reviews"
        self.reviews.mkdir()

    def run_gate(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gate.main([str(self.reviews), *args])
        return code, out.getvalue().strip(), err.getvalue()

    def write_reviews(self, reviews):
        for i, r in enumerate(reviews):
            (self.reviews / f"r{i}.json").write_text(json.dumps(r), encoding="utf-8")

    def test_writes_decision_next_to_reviews(self):
        self.write_reviews(council(95, 95, 95))
        code, out, _ = self.run_gate("--revision", "0")
        self.assertEqual((code, out), (0, "implement"))
        record = json.loads((self.tmp / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual(record["rule"], "meets-bar")
        self.assertIn("policy", record)

    def test_unreadable_review_escalates(self):
        self.write_reviews(council(95, 95, 95))
        (self.reviews / "broken.json").write_text("{not json", encoding="utf-8")
        code, out, _ = self.run_gate("--revision", "0")
        self.assertEqual((code, out), (0, "escalate"))

    def test_policy_files_layer_in_order(self):
        self.write_reviews(council(85, 85, 85))
        loose = self.tmp / "loose.json"
        loose.write_text(json.dumps({"implement": {"min_average": 80, "min_lowest": 80}}), encoding="utf-8")
        strict = self.tmp / "strict.json"
        strict.write_text(json.dumps({"implement": {"min_average": 99}}), encoding="utf-8")
        self.assertEqual(self.run_gate("--revision", "0", "--policy", str(loose))[1], "implement")
        self.assertEqual(self.run_gate("--revision", "0", "--policy", str(loose), "--policy", str(strict))[1],
                         "revise")

    def test_broken_policy_exits_2(self):
        bad = self.tmp / "bad.json"
        for override, message in [({"max_revisions": "two"}, "threshold"),
                                  ({"weights": {"risk": -5}}, "weights"),
                                  ([1, 2], "JSON object")]:
            with self.subTest(override):
                bad.write_text(json.dumps(override), encoding="utf-8")
                code, _, err = self.run_gate("--revision", "0", "--policy", str(bad))
                self.assertEqual(code, 2)
                self.assertIn(message, err)


if __name__ == "__main__":
    unittest.main()
