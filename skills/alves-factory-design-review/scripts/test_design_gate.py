"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import design_gate as gate


POLICY = gate.load_policy([])
SEATS = POLICY["seats"]
COUNCIL = {
    "product-designer": {"target": {"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5"}},
    "art-director": {"target": {"providerInstanceId": "codex", "model": "gpt-6.2-sol"}},
    "design-system": {"target": {"providerInstanceId": "claudeAgent", "model": "claude-sonnet-5-5"}},
}
MAJOR = {"severity": "major", "element": "the filter bar", "problem": "p", "fix": "f"}
DEFECT = {"category": "accessibility", "element": "grey body text", "problem": "contrast 2.1:1"}


def design(did="A", screens=("desktop",)):
    return {"id": did, "hypothesis": f"hypothesis {did}", "file_key": "k",
            "screens": [{"node_id": "1:2", "label": s, "path": f"screens/{did}/{s}.png"} for s in screens]}


def review(seat, d, score=8, council=COUNCIL, **fields):
    """A valid review from the seat, scoring every own criterion `score` unless fields override."""
    own = SEATS[seat]
    target = council[seat]["target"]
    scores = {c: score for c in own}
    scores.update(fields.pop("scores", {}))
    findings = fields.pop("findings", [{**MAJOR, "criterion": c} for c in own
                                           if isinstance(scores[c], (int, float)) and scores[c] < POLICY["finding_below"]])
    return {"seat": seat, "design": d["id"], "provider_instance": target["providerInstanceId"],
            "model": target["model"], "screens_viewed": [s["path"] for s in d["screens"]],
            "scores": scores, "rationale": {c: "the New order button, top right" for c in own},
            "critical_defects": fields.pop("critical_defects", []), "findings": findings,
            "strengths": ["clear primary action"], **fields}


def full(d, score=8, **by_seat):
    """Reviews from every seat for one design; by_seat maps a seat (with _ for -) to review fields."""
    return {seat: review(seat, d, score, **by_seat.get(seat.replace("-", "_"), {})) for seat in SEATS}


def run(mode, designs, reviews, history=()):
    problems = []
    for d in designs:
        for seat in SEATS:
            if seat not in reviews[d["id"]]:
                problems.append(f"{d['id']}: no review from {seat}")
        for seat, r in reviews[d["id"]].items():
            problems += gate.validate_review(r, d, seat, POLICY)
    return gate.evaluate(mode, designs, reviews, problems, COUNCIL, POLICY, history)


class Scoring(unittest.TestCase):
    def test_weighted_score_uses_every_seat_criterion(self):
        d = design()
        reviews = {"A": full(d, 8, product_designer={"scores": {"usability": 10}})}
        result = run("explore", [d], reviews)
        # usability 10 (w15), every other criterion 8: (150 + 8 * 85) / 100
        self.assertEqual(result["designs"][0]["score"], 8.3)

    def test_criteria_record_their_seat_and_model(self):
        d = design()
        c = run("explore", [d], {"A": full(d)})["designs"][0]["criteria"]["typography"]
        self.assertEqual((c["seat"], c["model"]), ("art-director", "gpt-6.2-sol"))


class Explore(unittest.TestCase):
    def setUp(self):
        self.designs = [design("A"), design("B"), design("C")]

    def test_ranks_by_score_and_recommends_the_best(self):
        reviews = {"A": full(self.designs[0], 7), "B": full(self.designs[1], 9), "C": full(self.designs[2], 8)}
        result = run("explore", self.designs, reviews)
        self.assertEqual((result["decision"], result["rule"]), ("ranked", "recommend"))
        self.assertEqual(result["ranking"], ["B", "C", "A"])
        self.assertEqual(result["recommendation"], "B")

    def test_a_critical_accessibility_defect_vetoes_whatever_the_score(self):
        reviews = {"A": full(self.designs[0], 7), "C": full(self.designs[2], 8),
                   "B": full(self.designs[1], 10, design_system={"critical_defects": [DEFECT]})}
        result = run("explore", self.designs, reviews)
        self.assertEqual(result["ranking"], ["C", "A", "B"])
        self.assertEqual(result["recommendation"], "C")
        self.assertTrue(result["designs"][1]["vetoed"])

    def test_a_critical_usability_defect_vetoes(self):
        reviews = {"A": full(self.designs[0], 9, product_designer={"critical_defects": [{**DEFECT, "category": "usability"}]}),
                   "B": full(self.designs[1], 7), "C": full(self.designs[2], 6)}
        self.assertEqual(run("explore", self.designs, reviews)["recommendation"], "B")

    def test_an_other_critical_defect_does_not_veto(self):
        reviews = {"A": full(self.designs[0], 9, art_director={"critical_defects": [{**DEFECT, "category": "other"}]}),
                   "B": full(self.designs[1], 7), "C": full(self.designs[2], 6)}
        self.assertEqual(run("explore", self.designs, reviews)["recommendation"], "A")

    def test_every_design_vetoed_recommends_none(self):
        veto = {"design_system": {"critical_defects": [DEFECT]}}
        reviews = {d["id"]: full(d, 9, **veto) for d in self.designs}
        result = run("explore", self.designs, reviews)
        self.assertEqual((result["rule"], result["recommendation"]), ("all-vetoed", None))

    def test_ties_break_by_id(self):
        reviews = {d["id"]: full(d, 8) for d in self.designs}
        self.assertEqual(run("explore", self.designs, reviews)["ranking"], ["A", "B", "C"])

    def test_major_findings_sort_before_minor_and_by_weight(self):
        d = self.designs[0]
        minor = {**MAJOR, "severity": "minor", "criterion": "usability"}
        heavy = {**MAJOR, "criterion": "composition"}
        light = {**MAJOR, "criterion": "figma_structure"}
        reviews = {"A": full(d, 8, art_director={"findings": [heavy]}, design_system={"findings": [light]},
                             product_designer={"findings": [minor]})}
        findings = run("explore", [d], reviews)["designs"][0]["findings"]
        self.assertEqual([f["criterion"] for f in findings], ["composition", "figma_structure", "usability"])


class Validation(unittest.TestCase):
    def setUp(self):
        self.d = design()

    def problems(self, seat="product-designer", **fields):
        return gate.validate_review(review(seat, self.d, **fields), self.d, seat, POLICY)

    def test_a_valid_review_has_no_problems(self):
        self.assertEqual(self.problems(), [])

    def test_scores_must_be_integers_from_0_to_10(self):
        for bad in (11, -1, 7.5, True, "8"):
            self.assertTrue(self.problems(scores={"usability": bad}, findings=[]), bad)

    def test_scores_must_cover_exactly_the_seats_criteria(self):
        r = review("product-designer", self.d)
        r["scores"]["typography"] = 8
        self.assertTrue(gate.validate_review(r, self.d, "product-designer", POLICY))
        del r["scores"]["typography"], r["scores"]["usability"]
        self.assertTrue(gate.validate_review(r, self.d, "product-designer", POLICY))

    def test_a_low_score_needs_a_major_finding_or_critical_defect(self):
        self.assertTrue(self.problems(scores={"usability": 6}, findings=[]))
        self.assertEqual(self.problems(scores={"usability": 6}, findings=[{**MAJOR, "criterion": "usability"}]), [])
        self.assertEqual(self.problems("design-system", scores={"accessibility": 3}, findings=[],
                                       critical_defects=[DEFECT]), [])
        self.assertTrue(self.problems(scores={"usability": 6}, findings=[{**MAJOR, "criterion": "usability", "severity": "minor"}]))

    def test_every_screen_must_be_viewed(self):
        d = design(screens=("desktop", "empty"))
        r = review("art-director", d, screens_viewed=["screens/A/desktop.png"])
        self.assertIn("A/art-director: did not view screens/A/empty.png", gate.validate_review(r, d, "art-director", POLICY))
        r["screens_viewed"] = [".\\screens\\A\\desktop.png", "screens/A/empty.png"]
        self.assertEqual(gate.validate_review(r, d, "art-director", POLICY), [])

    def test_rationale_cites_every_own_criterion(self):
        self.assertTrue(self.problems(rationale={"usability": "x"}))

    def test_findings_and_defects_have_their_fields(self):
        self.assertTrue(self.problems(findings=[{**MAJOR, "criterion": "usability", "severity": "blocker"}]))
        self.assertTrue(self.problems(findings=[{**MAJOR, "criterion": "colour"}]))
        self.assertTrue(self.problems(critical_defects=[{**DEFECT, "category": "typography"}]))
        self.assertTrue(self.problems(critical_defects=[{"category": "usability", "element": "", "problem": "p"}]))

    def test_seat_and_design_fields_must_match_the_path(self):
        self.assertTrue(self.problems(seat="product-designer", design="B"))
        r = review("product-designer", self.d)
        r["seat"] = "art-director"
        self.assertTrue(gate.validate_review(r, self.d, "product-designer", POLICY))

    def test_a_missing_review_invalidates_the_round(self):
        reviews = {"A": full(self.d)}
        del reviews["A"]["art-director"]
        result = run("explore", [self.d], reviews)
        self.assertEqual((result["decision"], result["rule"]), ("invalid", "invalid-reviews"))

    def test_a_review_from_the_wrong_model_is_a_council_mismatch(self):
        reviews = {"A": full(self.d)}
        reviews["A"]["art-director"]["model"] = "claude-opus-5-5"
        result = run("explore", [self.d], reviews)
        self.assertEqual((result["decision"], result["rule"]), ("invalid", "council-mismatch"))


class Refine(unittest.TestCase):
    def setUp(self):
        self.d = design("Refined")

    def round(self, score, history=(), **by_seat):
        return run("refine", [self.d], {"Refined": full(self.d, score, **by_seat)},
                   [{"round": i + 1, "score": s} for i, s in enumerate(history)])

    def with_major(self, score, history=()):
        return self.round(score, history, art_director={"findings": [{**MAJOR, "criterion": "composition"}]})

    def test_no_critical_defect_or_major_finding_stops_clean(self):
        result = self.round(8)
        self.assertEqual((result["decision"], result["rule"], result["round"]), ("stop", "clean", 1))

    def test_a_major_finding_continues(self):
        self.assertEqual(self.with_major(8)["decision"], "continue")

    def test_round_four_stops_at_the_cap(self):
        result = self.with_major(9, [6, 7, 8])
        self.assertEqual((result["decision"], result["rule"], result["round"]), ("stop", "round-cap", 4))
        self.assertEqual([h["score"] for h in result["history"]], [6, 7, 8, 9])

    def test_two_small_gains_in_a_row_plateau(self):
        result = self.with_major(7, [6.8, 6.9])
        self.assertEqual((result["decision"], result["rule"]), ("stop", "plateau"))

    def test_one_small_gain_after_a_big_one_continues(self):
        self.assertEqual(self.with_major(7, [5.0, 6.8])["decision"], "continue")

    def test_a_gain_of_exactly_the_delta_continues(self):
        self.assertEqual(self.with_major(7, [6.4, 6.7])["decision"], "continue")

    def test_a_score_drop_counts_toward_a_plateau(self):
        self.assertEqual(self.with_major(7, [7.5, 7.6])["rule"], "plateau")

    def test_round_two_cannot_plateau_yet(self):
        self.assertEqual(self.with_major(7, [7.0])["decision"], "continue")

    def test_a_vetoed_design_never_stops_clean(self):
        result = self.round(9, design_system={"critical_defects": [DEFECT]})
        self.assertEqual((result["decision"], result["design"]["vetoed"]), ("continue", True))

    def test_the_pass_mark_stops_a_design_without_a_veto(self):
        policy = gate.merge(POLICY, {"refine": {"pass_mark": 8.5}})
        reviews = {"Refined": full(self.d, 9, art_director={"findings": [{**MAJOR, "criterion": "composition"}]})}
        result = gate.evaluate("refine", [self.d], reviews, [], COUNCIL, policy)
        self.assertEqual(result["rule"], "meets-pass-mark")
        reviews["Refined"]["design-system"]["critical_defects"] = [DEFECT]
        self.assertEqual(gate.evaluate("refine", [self.d], reviews, [], COUNCIL, policy)["rule"], "below-stop")


class Councils(unittest.TestCase):
    def test_the_default_council_is_valid(self):
        gate.check_council(json.loads(gate.DEFAULT_POLICY.with_name("default-council.json").read_text()), POLICY)

    def test_copilot_is_excluded(self):
        council = {**COUNCIL, "art-director": {"target": {"providerInstanceId": "acpRegistry_github_copilot", "model": "gpt-6.2-sol"}}}
        with self.assertRaisesRegex(gate.PolicyError, "excluded"):
            gate.check_council(council, POLICY)

    def test_the_model_floor_counts_one_model_once_across_connections(self):
        council = {
            "product-designer": {"target": {"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5"}},
            "art-director": {"target": {"providerInstanceId": "opencode", "model": "opencode/claude-opus-5.5"}},
            "design-system": {"target": {"providerInstanceId": "claudeAgent", "model": "claude-opus-5-5"}},
        }
        with self.assertRaisesRegex(gate.PolicyError, "1 distinct model"):
            gate.check_council(council, POLICY)

    def test_the_council_must_seat_exactly_the_policy_seats(self):
        with self.assertRaisesRegex(gate.PolicyError, "must seat exactly"):
            gate.check_council({k: v for k, v in COUNCIL.items() if k != "art-director"}, POLICY)


class Policies(unittest.TestCase):
    def test_weights_must_match_the_seat_criteria(self):
        with self.assertRaisesRegex(gate.PolicyError, "one weight per seat criterion"):
            gate.check_policy(gate.merge(POLICY, {"weights": {"colour": 5}}))

    def test_a_criterion_belongs_to_one_seat(self):
        with self.assertRaisesRegex(gate.PolicyError, "exactly one seat"):
            gate.check_policy(gate.merge(POLICY, {"seats": {"art-director": ["composition", "typography", "usability"]}}))

    def test_veto_categories_are_criteria(self):
        with self.assertRaisesRegex(gate.PolicyError, "veto_categories"):
            gate.check_policy(gate.merge(POLICY, {"veto_categories": ["delight"]}))

    def test_pass_mark_is_null_or_on_the_scale(self):
        with self.assertRaisesRegex(gate.PolicyError, "pass_mark"):
            gate.check_policy(gate.merge(POLICY, {"refine": {"pass_mark": 85}}))


class CommandLine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "council.json").write_text(json.dumps(COUNCIL))

    def tearDown(self):
        self.tmp.cleanup()

    def write_round(self, name, designs, reviews, encoding="utf-8"):
        root = self.dir / name
        (root / "reviews").mkdir(parents=True)
        (root / "designs.json").write_text(json.dumps({"designs": designs}), encoding=encoding)
        for did, by_seat in reviews.items():
            (root / "reviews" / did).mkdir()
            for seat, r in by_seat.items():
                (root / "reviews" / did / f"{seat}.json").write_text(json.dumps(r), encoding=encoding)
        return root

    def main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = gate.main([str(a) for a in args])
        return code, out.getvalue().strip(), err.getvalue().strip()

    def test_explore_writes_a_decision(self):
        a, b = design("A"), design("B")
        root = self.write_round("explore-0", [a, b], {"A": full(a, 7), "B": full(b, 9)})
        code, out, _ = self.main(root, "--mode", "explore", "--council", self.dir / "council.json")
        self.assertEqual((code, out), (0, "ranked B (recommend)"))
        record = json.loads((root / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual(record["ranking"], ["B", "A"])
        self.assertIn("policy", record)

    def test_check_reports_problems_and_exits_1(self):
        a = design("A")
        reviews = {"A": full(a)}
        del reviews["A"]["design-system"]
        root = self.write_round("explore-0", [a], reviews)
        self.assertEqual(self.main(root, "--check")[:2], (1, "A: no review from design-system"))

    def test_check_passes_utf16_reviews(self):
        a = design("A")
        root = self.write_round("explore-0", [a], {"A": full(a)}, encoding="utf-16")
        self.assertEqual(self.main(root, "--check")[:2], (0, "ok"))

    def test_check_council(self):
        self.assertEqual(self.main("--check-council", self.dir / "council.json")[0], 0)
        bad = self.dir / "bad.json"
        bad.write_text(json.dumps({**COUNCIL, "design-system": COUNCIL["product-designer"],
                                   "art-director": COUNCIL["product-designer"]}))
        code, _, err = self.main("--check-council", bad)
        self.assertEqual(code, 2)
        self.assertIn("distinct model", err)

    def test_refine_chains_previous_rounds(self):
        d = design("Refined")
        major = {"art_director": {"findings": [{**MAJOR, "criterion": "composition"}]}}
        first = self.write_round("refine-1", [d], {"Refined": full(d, 7, **major)})
        self.assertEqual(self.main(first, "--mode", "refine", "--council", self.dir / "council.json")[1],
                         "continue (below-stop)")
        second = self.write_round("refine-2", [d], {"Refined": full(d, 8, **major)})
        code, out, _ = self.main(second, "--mode", "refine", "--council", self.dir / "council.json",
                                 "--previous", first / "decision.json")
        self.assertEqual((code, out), (0, "continue (below-stop)"))
        record = json.loads((second / "decision.json").read_text(encoding="utf-8"))
        self.assertEqual((record["round"], [h["score"] for h in record["history"]]), (2, [7.0, 8.0]))

    def test_refine_rejects_previous_rounds_out_of_order(self):
        d = design("Refined")
        first = self.write_round("refine-1", [d], {"Refined": full(d, 7, art_director={"findings": [{**MAJOR, "criterion": "composition"}]})})
        self.main(first, "--mode", "refine", "--council", self.dir / "council.json")
        third = self.write_round("refine-3", [d], {"Refined": full(d, 8)})
        code, _, err = self.main(third, "--mode", "refine", "--council", self.dir / "council.json",
                                 "--previous", first / "decision.json", "--previous", first / "decision.json")
        self.assertEqual(code, 2)
        self.assertIn("expected round 2", err)

    def test_refine_reviews_exactly_one_design(self):
        a, b = design("A"), design("B")
        root = self.write_round("refine-1", [a, b], {"A": full(a), "B": full(b)})
        code, _, err = self.main(root, "--mode", "refine", "--council", self.dir / "council.json")
        self.assertEqual(code, 2)
        self.assertIn("exactly one design", err)

    def test_an_unusable_designs_file_exits_2(self):
        root = self.dir / "explore-0"
        root.mkdir()
        (root / "designs.json").write_text(json.dumps({"designs": [{"id": "A", "screens": []}]}))
        code, _, err = self.main(root, "--check")
        self.assertEqual(code, 2)
        self.assertIn("at least one screen", err)


if __name__ == "__main__":
    unittest.main()
