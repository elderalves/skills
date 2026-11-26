"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import gate


POLICY = gate.load_policy([])
LENSES = ["requirements", "architecture", "testing-risk"]


def seats(*targets):
    """A resolved Council: one (connection, model) per lens, in LENSES order."""
    return {lens: {"target": {"providerInstanceId": instance, "model": model}}
            for lens, (instance, model) in zip(LENSES, targets)}


COUNCIL = seats(("codex", "gpt-6.2-sol"), ("claudeAgent", "claude-opus-5-5"),
                ("opencode", "opencode-go/muse-spark-1.3-contributor"))


MAJOR = {"criterion": "testing", "problem": "p", "evidence": "e", "fix": "f"}
BLOCKER = {"question": "Q?", "why_owner": "w", "evidence": "e"}


def review(score=95, lens="architecture", verdict="approve", seated=COUNCIL, **fields):
    """A review from the lens's seat, consistent with its verdict unless fields say otherwise."""
    scores = {criterion: score for criterion in POLICY["weights"]}
    scores.update(fields.pop("scores", {}))
    defaults = {"blockers": [BLOCKER] if verdict == "escalate" else [],
                "issues": [MAJOR] if verdict == "revise" else []}
    target = seated[lens]["target"]
    return {"reviewer": lens, "provider_instance": target["providerInstanceId"],
            "model": target["model"], "verdict": verdict,
            "scores": scores, "risk_flags": [], **defaults, **fields}


def council(*scores, verdicts=None, seated=COUNCIL, **fields):
    verdicts = verdicts or ["approve"] * len(scores)
    return [review(s, LENSES[i % 3], verdicts[i], seated, **fields) for i, s in enumerate(scores)]


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
     0, [], "escalate", "blockers"),
    ("a Blocker", council(95, 95)[:2] + [review(95, "testing-risk", "escalate")],
     0, [], "escalate", "blockers"),
    ("Issues alone never escalate", council(85, 85, 85, verdicts=["revise"] * 3),
     0, [], "revise", "below-bar"),
    ("approve with minor Issues implements", council(95, 95, 95, issues=[{**MAJOR, "minor": True}]),
     0, [], "implement", "meets-bar"),
    ("approve with a major Issue is invalid", council(95, 95)[:2] + [review(95, "testing-risk", issues=[MAJOR])],
     0, [], "escalate", "invalid-reviews"),
    ("revise with only minor Issues is invalid",
     council(95, 95)[:2] + [review(95, "testing-risk", "revise", issues=[{**MAJOR, "minor": True}])],
     0, [], "escalate", "invalid-reviews"),
    ("escalate without a Blocker is invalid", council(95, 95)[:2] + [review(95, "testing-risk", "escalate", blockers=[])],
     0, [], "escalate", "invalid-reviews"),
    ("non-boolean minor is invalid", council(95, 95)[:2] + [review(95, "testing-risk", issues=[{**MAJOR, "minor": "yes"}])],
     0, [], "escalate", "invalid-reviews"),
    ("plan declares a Risk flag", council(95, 95, 95), 0, ["auth"], "escalate", "risk-flags"),
    ("reviewer adds a Risk flag", council(95, 95)[:2] + [review(95, "testing-risk", risk_flags=["auth"])],
     0, [], "escalate", "risk-flags"),
    # strict-tier flags: the Plan can pass on its own, with every risk score at the strict bar
    ("strict flag, strong round", council(95, 95, 95), 0, ["dependency"], "implement", "meets-strict-bar"),
    ("strict flag added by a reviewer", council(95, 95)[:2] + [review(95, "testing-risk", risk_flags=["large-change"])],
     0, [], "implement", "meets-strict-bar"),
    ("strict flag, a risk score below 90", council(95, 95)[:2] + [review(95, "testing-risk", scores={"risk": 89})],
     0, ["infrastructure"], "escalate", "strict-risk-flags"),
    ("strict flag, below the bar revises", council(85, 82, 80), 0, ["dependency"], "revise", "below-bar"),
    ("strict flag, below the bar at the cap", council(85, 82, 80), 2, ["dependency"], "escalate", "revision-cap"),
    ("strict and escalate flags together", council(95, 95, 95), 0, ["dependency", "auth"], "escalate", "risk-flags"),
    ("breaking public contract escalates", council(95, 95, 95), 0, ["public-contract"], "escalate", "risk-flags"),
    ("review from another model than its seat",
     council(95, 95)[:2] + [review(95, "testing-risk", model="opencode/muse-spark-1.3-contributor")],
     0, [], "escalate", "council-mismatch"),
    ("review through another connection than its seat",
     council(95, 95)[:2] + [review(95, "testing-risk", provider_instance="claudeAgent")],
     0, [], "escalate", "council-mismatch"),
    ("reviewer with no seat", council(95, 95)[:2] + [{**review(95, "testing-risk"), "reviewer": "security"}],
     0, [], "escalate", "council-mismatch"),
    ("mismatch is reported before a Blocker",
     council(95, 95)[:2] + [review(95, "testing-risk", "escalate", model="other")],
     0, [], "escalate", "council-mismatch"),
    ("missing model is invalid", council(95, 95)[:2] + [{**review(95, "testing-risk"), "model": ""}],
     0, [], "escalate", "invalid-reviews"),
    ("missing connection is invalid",
     council(95, 95)[:2] + [{k: v for k, v in review(95, "testing-risk").items() if k != "provider_instance"}],
     0, [], "escalate", "invalid-reviews"),
    ("two reviews", council(95, 95), 0, [], "escalate", "too-few-reviews"),
    ("no reviews", [], 0, [], "escalate", "too-few-reviews"),
    ("score above 100", council(95, 95)[:2] + [review(95, "testing-risk", scores={"risk": 101})],
     0, [], "escalate", "invalid-reviews"),
    ("missing criterion", council(95, 95)[:2] + [
        {**review(95, "testing-risk"), "scores": {"requirements": 95}}], 0, [], "escalate", "invalid-reviews"),
    ("bad verdict", council(95, 95, 95, verdicts=["approve", "approve", "ship it"]),
     0, [], "escalate", "invalid-reviews"),
    ("boolean score", council(95, 95)[:2] + [review(95, "testing-risk", scores={"risk": True})],
     0, [], "escalate", "invalid-reviews"),
]


class GateRules(unittest.TestCase):
    def test_cases(self):
        for name, reviews, revision, flags, decision, rule in CASES:
            with self.subTest(name):
                record = gate.evaluate(reviews, revision, flags, POLICY, COUNCIL)
                self.assertEqual((record["decision"], record["rule"]), (decision, rule), record["reasons"])

    def test_plan_score_is_weighted(self):
        reviews = council(90, 90, 90)
        reviews[0]["scores"]["requirements"] = 50  # weight 25 of 100: costs 10 points
        record = gate.evaluate(reviews, 0, [], POLICY, COUNCIL)
        self.assertEqual(record["reviews"][0]["score"], 80.0)
        self.assertEqual(record["plan_score"], round((80 + 90 + 90) / 3, 1))

    def test_unknown_risk_flag_still_escalates_and_is_reported(self):
        record = gate.evaluate(council(95, 95, 95), 0, ["mystery"], POLICY, COUNCIL)
        self.assertEqual(record["decision"], "escalate")
        self.assertEqual(record["unknown_risk_flags"], ["mystery"])

    def test_policy_moves_a_flag_between_tiers(self):
        stricter = gate.merge(POLICY, {"risk_flags": {"dependency": {"tier": "escalate"}}})
        record = gate.evaluate(council(95, 95, 95), 0, ["dependency"], stricter, COUNCIL)
        self.assertEqual((record["decision"], record["rule"]), ("escalate", "risk-flags"))
        self.assertEqual(stricter["risk_flags"]["dependency"]["description"],
                         POLICY["risk_flags"]["dependency"]["description"])

    def test_a_plain_string_flag_is_escalate_tier(self):
        legacy = gate.merge(POLICY, {"risk_flags": {"large-change": "Changes more than 15 files"}})
        record = gate.evaluate(council(95, 95, 95), 0, ["large-change"], legacy, COUNCIL)
        self.assertEqual(record["rule"], "risk-flags")

    def test_record_names_each_flag_tier(self):
        record = gate.evaluate(council(95, 95, 95), 0, ["dependency"], POLICY, COUNCIL)
        self.assertEqual(record["risk_flag_tiers"], {"dependency": "strict"})

    def test_policy_override_changes_threshold(self):
        policy = gate.merge(POLICY, {"implement": {"min_average": 80, "min_lowest": 80, "max_spread": 20}})
        self.assertEqual(gate.evaluate(council(85, 82, 80), 0, [], policy, COUNCIL)["decision"], "implement")

    def test_record_lists_connection_model_and_distinct_models(self):
        record = gate.evaluate(council(95, 95, 95), 0, [], POLICY, COUNCIL)
        self.assertEqual(record["models"],
                         ["claude-opus-5-5", "gpt-6-2-sol", "muse-spark-1-3-contributor"])
        self.assertEqual((record["reviews"][1]["provider_instance"], record["reviews"][1]["model"]),
                         ("claudeAgent", "claude-opus-5-5"))


class ModelFloor(unittest.TestCase):
    OPUS = ("claudeAgent", "claude-opus-5-5")
    SONNET = ("claudeAgent", "claude-sonnet-5-5")

    def decide(self, seated, **policy):
        record = gate.evaluate(council(95, 95, 95, seated=seated), 0, [],
                               gate.merge(POLICY, policy), seated)
        return record["decision"], record["rule"]

    def test_one_model_on_every_lens_passes_by_default(self):
        self.assertEqual(POLICY["min_models"], 1)
        self.assertEqual(self.decide(seats(self.OPUS, self.OPUS, self.OPUS)), ("implement", "meets-bar"))

    def test_floor_counts_distinct_models(self):
        mixed = seats(self.OPUS, self.SONNET, self.OPUS)
        self.assertEqual(self.decide(mixed, min_models=2), ("implement", "meets-bar"))
        self.assertEqual(self.decide(mixed, min_models=3), ("escalate", "too-few-models"))

    def test_one_model_through_two_connections_counts_once(self):
        via_copilot = seats(self.OPUS, ("acpRegistry_github_copilot", "claude-opus-5.5"), self.SONNET)
        self.assertEqual(self.decide(via_copilot, min_models=3), ("escalate", "too-few-models"))
        record = gate.evaluate(council(95, 95, 95, seated=via_copilot), 0, [], POLICY, via_copilot)
        self.assertEqual(record["models"], ["claude-opus-5-5", "claude-sonnet-5-5"])

    def test_model_identity(self):
        for raw, identity in [("claude-opus-5.5", "claude-opus-5-5"),
                              ("opencode-go/muse-spark-1.3-contributor", "muse-spark-1-3-contributor"),
                              (" GPT-6.2-Sol ", "gpt-6-2-sol"),
                              ("opencode/claude-opus-5-5", "claude-opus-5-5")]:
            self.assertEqual(gate.model_identity(raw), identity)

    def test_retired_min_providers_is_rejected(self):
        with self.assertRaisesRegex(gate.PolicyError, "min_models"):
            gate.check_policy(gate.merge(POLICY, {"min_providers": 2}))


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.reviews = self.tmp / "reviews"
        self.reviews.mkdir()
        self.council = self.tmp / "council.json"
        self.council.write_text(json.dumps(COUNCIL), encoding="utf-8")

    def run_gate(self, *args, council=True):
        if council and "--check" not in args:
            args = (*args, "--council", str(self.council))
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

    def test_model_floor_layers_without_reducing_reviews(self):
        opus, sonnet = ("claudeAgent", "claude-opus-5-5"), ("claudeAgent", "claude-sonnet-5-5")
        mixed = seats(opus, sonnet, opus)
        self.council.write_text(json.dumps(mixed), encoding="utf-8")
        owner = self.tmp / "owner.json"
        owner.write_text(json.dumps({"min_models": 2}), encoding="utf-8")
        project = self.tmp / "project.json"
        project.write_text(json.dumps({"min_models": 3}), encoding="utf-8")
        self.write_reviews(council(95, 95, 95, seated=mixed))

        self.assertEqual(self.run_gate("--revision", "0")[1], "implement")
        self.assertEqual(self.run_gate("--revision", "0", "--policy", str(owner))[1], "implement")
        self.assertEqual(self.run_gate("--revision", "0", "--policy", str(owner),
                                      "--policy", str(project))[1], "escalate")
        record = json.loads((self.tmp / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual(record["rule"], "too-few-models")
        self.assertEqual(record["policy"]["min_models"], 3)

        (self.reviews / "r2.json").unlink()
        self.assertEqual(self.run_gate("--revision", "0")[1], "escalate")
        record = json.loads((self.tmp / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual(record["rule"], "too-few-reviews")

    def test_review_off_its_seat_escalates(self):
        self.write_reviews(council(95, 95)[:2] + [review(95, "testing-risk", model="claude-opus-5-5")])
        self.assertEqual(self.run_gate("--revision", "0")[1], "escalate")
        record = json.loads((self.tmp / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual(record["rule"], "council-mismatch")
        self.assertIn("testing-risk: written by claude-opus-5-5 via opencode", record["reasons"][0])

    def test_check_mode_validates_without_deciding(self):
        self.write_reviews(council(95, 95, 95))
        self.assertEqual(self.run_gate("--check")[:2], (0, "ok"))
        self.assertFalse((self.tmp / "decision.json").exists())
        self.write_reviews([review(95, "requirements", "revise", issues=[])])
        code, out, _ = self.run_gate("--check")
        self.assertEqual(code, 1)
        self.assertIn("revise needs", out)

    def test_decision_mode_requires_revision_and_council(self):
        self.write_reviews(council(95, 95, 95))
        for args in [(), ("--revision", "0")]:
            with self.subTest(args), self.assertRaises(SystemExit):
                self.run_gate(*args, council=False)

    def test_unreadable_council_exits_2(self):
        self.write_reviews(council(95, 95, 95))
        for content in ["{broken", "[]", "{}"]:
            with self.subTest(content):
                self.council.write_text(content, encoding="utf-8")
                code, _, err = self.run_gate("--revision", "0")
                self.assertEqual(code, 2)
                self.assertIn("council", err)

    def test_broken_policy_exits_2(self):
        bad = self.tmp / "bad.json"
        for override, message in [({"max_revisions": "two"}, "threshold"),
                                  ({"weights": {"risk": -5}}, "weights"),
                                  ({"risk_flags": {"auth": {"tier": "maybe"}}}, "tier"),
                                  ({"strict": {"min_risk_score": "high"}}, "threshold"),
                                  ({"min_providers": 2}, "min_models"),
                                  ([1, 2], "JSON object")]:
            with self.subTest(override):
                bad.write_text(json.dumps(override), encoding="utf-8")
                code, _, err = self.run_gate("--revision", "0", "--policy", str(bad))
                self.assertEqual(code, 2)
                self.assertIn(message, err)


class ReadText(unittest.TestCase):
    def test_every_encoding_a_shell_redirect_writes(self):
        # PowerShell 5.1's `>` writes UTF-16; Out-File -Encoding utf8 adds a BOM.
        with tempfile.TemporaryDirectory() as tmp:
            for encoding in ("utf-8", "utf-8-sig", "utf-16", "utf-16-le"):
                with self.subTest(encoding):
                    path = Path(tmp) / "council.json"
                    text = '{"lens": "Prüfung"}'
                    data = text.encode(encoding)
                    if encoding == "utf-16-le":
                        data = b"\xff\xfe" + data
                    path.write_bytes(data)
                    self.assertEqual(json.loads(gate.read_text(path)), {"lens": "Prüfung"})


if __name__ == "__main__":
    unittest.main()
