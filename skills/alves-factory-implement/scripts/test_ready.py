"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import ready


DECISION = {"decision": "implement", "rule": "meets-bar", "risk_flags": []}
GREEN = [{"name": "Build & Test", "bucket": "pass"}, {"name": "license/snyk", "bucket": "pass"}]


def verification(**fields):
    base = {
        "checks": [{"command": "yarn test", "result": "pass", "baseline": "pass"}],
        "deviations": ["import path corrected"],
        "ci_fixes": 0,
        "evidence": {"required": True, "missing": []},
    }
    base.update(fields)
    return base


def run(pr_ready="auto", decision=DECISION, verify=None, checks=GREEN, flags=()):
    return ready.evaluate(pr_ready, decision, verify or verification(), checks, flags)


class Evaluate(unittest.TestCase):
    def test_every_condition_met_promotes(self):
        self.assertEqual(run(), {"ready": True, "reasons": ["all conditions met"]})

    def test_deviations_never_block(self):
        self.assertTrue(run(verify=verification(deviations=["a", "b"]))["ready"])

    def test_skipped_checks_count_as_green(self):
        self.assertTrue(run(checks=GREEN + [{"name": "deploy-preview", "bucket": "skipping"}])["ready"])

    def test_no_evidence_block_needs_no_screenshots(self):
        verify = verification(evidence={"required": False, "missing": ["no app to serve"]})
        self.assertTrue(run(verify=verify)["ready"])

    def test_missing_evidence_field_means_none_required(self):
        verify = verification()
        del verify["evidence"]
        self.assertTrue(run(verify=verify)["ready"])

    CASES = [
        # (name, run kwargs, expected reason fragment)
        ("draft-only project", {"pr_ready": "draft"}, "pr_ready: draft"),
        ("owner approved an escalation", {"decision": {"decision": "escalate", "risk_flags": []}},
         "Gate decision: escalate"),
        ("Plan declares a strict flag", {"flags": ["dependency"]}, "Risk flag dependency"),
        ("reviewer added a flag", {"decision": {**DECISION, "risk_flags": ["large-change"]}},
         "Risk flag large-change"),
        ("no CI checks", {"checks": []}, "runs no CI checks"),
        ("dry run", {"checks": None}, "dry run"),
        ("red CI check", {"checks": GREEN + [{"name": "lint", "bucket": "fail"}]}, "CI check lint is fail"),
        ("pending CI check", {"checks": [{"name": "build", "bucket": "pending"}]}, "CI check build is pending"),
        ("only skipped checks", {"checks": [{"name": "x", "bucket": "skipping"}]}, "no CI check passed"),
        ("CI fixed by the run", {"verify": verification(ci_fixes=1)}, "after 1 fix commit"),
        ("screenshot missing", {"verify": verification(evidence={"required": True, "missing": ["Docs after: timeout"]})},
         "screenshot missing: Docs after: timeout"),
        ("check broken by the change",
         {"verify": verification(checks=[{"command": "yarn lint", "result": "fail", "baseline": "pass"}])},
         "`yarn lint` fails on the branch"),
        ("check already failing on base",
         {"verify": verification(checks=[{"command": "yarn build-storybook", "result": "fail", "baseline": "fail"}])},
         "fails on the branch, as it did on the base branch"),
    ]

    def test_each_failed_condition_keeps_a_draft(self):
        for name, kwargs, fragment in self.CASES:
            with self.subTest(name):
                result = run(**kwargs)
                self.assertFalse(result["ready"])
                self.assertTrue(any(fragment in r for r in result["reasons"]), result["reasons"])

    def test_reasons_list_every_failure(self):
        result = run(pr_ready="draft", checks=[], flags=["auth"])
        self.assertEqual(len(result["reasons"]), 3)

    def test_a_flag_in_both_plan_and_decision_is_named_once(self):
        result = run(decision={**DECISION, "risk_flags": ["auth"]}, flags=["auth"])
        self.assertEqual(result["reasons"], ["the Plan carries the Risk flag auth"])


class Main(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def write(self, name, data):
        path = self.dir / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return str(path)

    def call(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = ready.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def args(self, verify=None, checks=GREEN, mode="auto"):
        argv = ["--pr-ready", mode, "--decision", self.write("decision.json", DECISION),
                "--verification", self.write("verification.json", verify or verification())]
        if checks is not None:
            argv += ["--checks", self.write("checks.json", checks)]
        return argv

    def test_writes_and_prints_the_result(self):
        out = self.dir / "ready.json"
        code, printed, _ = self.call(*self.args(), "--out", str(out))
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(printed)["ready"])
        self.assertEqual(json.loads(out.read_text(encoding="utf-8")), json.loads(printed))

    def test_dry_run_without_checks(self):
        code, printed, _ = self.call(*self.args(checks=None))
        self.assertEqual(code, 0)
        self.assertFalse(json.loads(printed)["ready"])

    def test_unknown_mode_is_unusable(self):
        code, _, err = self.call(*self.args(mode="yes"))
        self.assertEqual(code, 2)
        self.assertIn("--pr-ready", err)

    def test_bad_inputs_are_unusable(self):
        bad = [
            ("no checks run", verification(checks=[])),
            ("unknown result", verification(checks=[{"command": "x", "result": "ok"}])),
            ("negative fixes", verification(ci_fixes=-1)),
            ("evidence not an object", verification(evidence=["x"])),
        ]
        for name, verify in bad:
            with self.subTest(name):
                self.assertEqual(self.call(*self.args(verify=verify))[0], 2)

    def test_malformed_checks_are_unusable(self):
        self.assertEqual(self.call(*self.args(checks=[{"name": "x"}]))[0], 2)

    def test_unreadable_file_is_unusable(self):
        argv = self.args()
        argv[argv.index("--decision") + 1] = str(self.dir / "missing.json")
        self.assertEqual(self.call(*argv)[0], 2)


if __name__ == "__main__":
    unittest.main()
