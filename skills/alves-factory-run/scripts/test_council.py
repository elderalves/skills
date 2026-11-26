"""Run with: python -m unittest discover -s <this-dir> -p test_council.py."""

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import council


OPUS = ("claudeAgent", "claude-opus-5-5")
SONNET = ("claudeAgent", "claude-sonnet-5-5")
OPUS_VIA_COPILOT = ("acpRegistry_github_copilot", "claude-opus-5.5")


def seat(instance, model, **options):
    target = {"providerInstanceId": instance, "model": model}
    if options:
        target["options"] = options
    return {"target": target}


def seats(*targets):
    lenses = ["requirements", "architecture", "testing-risk"]
    return {lens: seat(*target) for lens, target in zip(lenses, targets)}


def config(**fields):
    return {"projects": [{"match": "PCS-"}, {"match": "SIDE-"}], **fields}


def policy(**fields):
    return council.gate.merge(council.gate.load_policy([]), fields)


class Resolve(unittest.TestCase):
    def test_existing_projects_use_the_pinned_default_council(self):
        result = council.resolve(config(), "PCS-")
        self.assertEqual(result, {
            "requirements": seat("codex", "gpt-6.2-sol"),
            "architecture": seat("claudeAgent", "claude-opus-5-5"),
            "testing-risk": seat("opencode", "opencode-go/muse-spark-1.3-contributor", variant="high"),
        })

    def test_project_replaces_owner_target_without_leaking_options(self):
        owner = seat("opencode", "opencode-go/muse-spark-1.3-contributor", variant="xhigh")
        project = seat("codex", "gpt-6.1-sol", reasoningEffort="high")
        settings = config(council={"testing-risk": owner})
        settings["projects"][0]["council"] = {"testing-risk": project}
        before = copy.deepcopy(settings)

        selected = council.resolve(settings, "PCS-")
        other = council.resolve(settings, "SIDE-")
        self.assertEqual(selected["testing-risk"], project)
        self.assertNotIn("variant", selected["testing-risk"]["target"]["options"])
        self.assertEqual(other["testing-risk"], owner)
        self.assertEqual(selected["requirements"], other["requirements"])
        self.assertEqual(settings, before)

    def test_one_model_may_sit_on_every_lens(self):
        same = seats(OPUS, OPUS, OPUS)
        self.assertEqual(council.resolve(config(council=same), "PCS-"), same)

    def test_seat_without_options_leaves_reasoning_to_the_reviewer(self):
        settings = config(council={"testing-risk": seat("opencode", "opencode-go/another-model")})
        self.assertNotIn("options", council.resolve(settings, "PCS-")["testing-risk"]["target"])

    def test_missing_or_ambiguous_project_is_an_error(self):
        for settings, match in [
            (config(), "UNKNOWN-"),
            ({"projects": [{"match": "PCS-"}] * 2}, "PCS-"),
        ]:
            with (
                self.subTest(settings=settings),
                self.assertRaisesRegex(council.ConfigError, "exactly one"),
            ):
                council.resolve(settings, match)

    def test_bad_config_names_the_field(self):
        cases = [
            ({"projects": {}}, "projects"),
            ({"council": None}, "council"),
            ({"council": {"testing": seat("opencode", "model")}}, "unknown lenses"),
            ({"council": {"testing-risk": {}}}, "exactly a target"),
            ({"council": {"testing-risk": {"provider": "anthropic", **seat("claudeAgent", "m")}}},
             "provider was removed"),
            ({"council": {"testing-risk": {"target": {"model": "m"}}}}, "providerInstanceId"),
            ({"council": {"testing-risk": {"target": {"providerInstanceId": "opencode"}}}},
             "target.model"),
            ({"council": {"testing-risk": seat("opencode", "")}}, "target.model"),
            ({"council": {"testing-risk": seat("opencode", "model", variant=3)}}, "options"),
            ({"council": {"testing-risk": {"target": {"providerInstanceId": "opencode", "modelId": "m"}}}},
             "providerInstanceId, model and options"),
        ]
        for fields, message in cases:
            with (
                self.subTest(fields=fields),
                self.assertRaisesRegex(council.ConfigError, message),
            ):
                council.resolve(config(**fields), "PCS-")


class NamedCouncils(unittest.TestCase):
    def test_entries_share_a_named_council(self):
        metronome = seats(OPUS, SONNET, ("claudeAgent", "claude-haiku-5-5"))
        settings = {"councils": {"metronome": metronome},
                    "projects": [{"match": "DXPX-", "council": "metronome"},
                                 {"match": "RTP-", "council": "metronome"},
                                 {"match": "PCS-"}]}
        self.assertEqual(council.resolve(settings, "DXPX-"), metronome)
        self.assertEqual(council.resolve(settings, "RTP-"), metronome)
        self.assertEqual(council.resolve(settings, "PCS-")["architecture"],
                         seat("claudeAgent", "claude-opus-5-5"))

    def test_shared_prefix_entries_are_told_apart_by_linear_project(self):
        explore = seats(OPUS, OPUS, SONNET)
        settings = {"councils": {"explore": explore},
                    "projects": [{"match": "RTP-", "linear_project": "Empower Widgets"},
                                 {"match": "RTP-", "linear_project": "Explore Frontend", "council": "explore"}]}
        self.assertEqual(council.resolve(settings, "RTP-", linear_project="explore frontend"), explore)
        self.assertEqual(council.resolve(settings, "RTP-", linear_project="Empower Widgets")["architecture"],
                         seat("claudeAgent", "claude-opus-5-5"))
        with self.assertRaisesRegex(council.ConfigError, "exactly one"):
            council.resolve(settings, "RTP-")
        with self.assertRaisesRegex(council.ConfigError, "exactly one"):
            council.resolve(settings, "RTP-", linear_project="Metronome")

    def test_partial_named_council_layers_over_owner_and_defaults(self):
        owner = {"requirements": seat(*SONNET)}
        agilekit = {"testing-risk": seat("codex", "gpt-6.1-sol")}
        settings = config(council=owner, councils={"agilekit": agilekit})
        settings["projects"][0]["council"] = "agilekit"
        result = council.resolve(settings, "PCS-")
        self.assertEqual(result["requirements"], seat(*SONNET))
        self.assertEqual(result["architecture"], seat("claudeAgent", "claude-opus-5-5"))
        self.assertEqual(result["testing-risk"], agilekit["testing-risk"])

    def test_unknown_name_is_an_error_not_a_fallback(self):
        settings = config(councils={"metronome": seats(OPUS)})
        settings["projects"][0]["council"] = "metronom"
        with self.assertRaisesRegex(council.ConfigError, r"'metronom'.*\['metronome'\]"):
            council.resolve(settings, "PCS-")

    def test_named_council_is_validated_with_its_name(self):
        settings = config(councils={"metronome": {"testing-risk": seat("claudeAgent", "")}})
        settings["projects"][0]["council"] = "metronome"
        with self.assertRaisesRegex(council.ConfigError, r"councils\.metronome\.testing-risk"):
            council.resolve(settings, "PCS-")

    def test_councils_must_be_an_object(self):
        settings = config(councils=[])
        settings["projects"][0]["council"] = "metronome"
        with self.assertRaisesRegex(council.ConfigError, "councils must be an object"):
            council.resolve(settings, "PCS-")


class ModelFloor(unittest.TestCase):
    def test_default_policy_has_no_floor(self):
        same = config(council=seats(OPUS, OPUS, OPUS))
        self.assertEqual(council.resolve(same, "PCS-", policy()), seats(OPUS, OPUS, OPUS))

    def test_floor_counts_distinct_models(self):
        mixed = config(council=seats(OPUS, SONNET, OPUS))
        council.resolve(mixed, "PCS-", policy(min_models=2))
        with self.assertRaisesRegex(council.ConfigError, r"min_models is 3.*2 distinct"):
            council.resolve(mixed, "PCS-", policy(min_models=3))

    def test_one_model_through_two_connections_counts_once(self):
        settings = config(council=seats(OPUS, OPUS_VIA_COPILOT, SONNET))
        with self.assertRaisesRegex(council.ConfigError, "2 distinct"):
            council.resolve(settings, "PCS-", policy(min_models=3))

    def test_error_names_each_seat_and_its_layer(self):
        settings = config(councils={"metronome": seats(OPUS, OPUS, OPUS)})
        settings["projects"][0]["council"] = "metronome"
        with self.assertRaisesRegex(council.ConfigError, r"architecture=claude-opus-5-5 \(councils\.metronome\)"):
            council.resolve(settings, "PCS-", policy(min_models=2))


class BillingWarnings(unittest.TestCase):
    def test_go_default_has_no_warning(self):
        warnings = []
        council.resolve(config(), "PCS-", warnings=warnings)
        self.assertEqual(warnings, [])

    def test_credit_billed_model_is_allowed_but_named_with_its_layer(self):
        settings = config(
            council={"testing-risk": seat("opencode", "opencode/muse-spark-1.3")},
            councils={"side": {"architecture": seat("opencode", "opencode/muse-wonder-1.0")}},
        )
        settings["projects"][0]["council"] = "side"
        warnings = []
        result = council.resolve(settings, "PCS-", warnings=warnings)
        self.assertEqual(result["testing-risk"]["target"]["model"], "opencode/muse-spark-1.3")
        self.assertEqual(len(warnings), 2)
        self.assertIn("councils.side.architecture", warnings[0])
        self.assertIn("council.testing-risk uses opencode/muse-spark-1.3", warnings[1])
        self.assertIn("OpenCode Models credits", warnings[1])

    def test_other_connections_are_not_flagged(self):
        settings = config(council={"requirements": seat("codex", "opencode/lookalike")})
        warnings = []
        council.resolve(settings, "PCS-", warnings=warnings)
        self.assertEqual(warnings, [])


class Cli(unittest.TestCase):
    def run_cli(self, work, settings, *extra):
        path = Path(work) / "projects.json"
        if settings is not None:
            path.write_text(settings if isinstance(settings, str) else json.dumps(settings),
                            encoding="utf-8")
        output = Path(work) / "council.json"
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = council.main(["--project", "PCS-", "--config", str(path),
                                 "--out", str(output), *extra])
        return code, output, stdout.getvalue(), stderr.getvalue()

    def test_cli_warns_on_stderr_and_still_writes(self):
        with tempfile.TemporaryDirectory() as work:
            code, output, _, stderr = self.run_cli(
                work, config(council={"testing-risk": seat("opencode", "opencode/x")}))
            self.assertEqual(code, 0)
            self.assertTrue(output.exists())
            self.assertRegex(stderr, r"^warning: council\.testing-risk uses opencode/x")

    def test_cli_writes_dispatch_configuration(self):
        with tempfile.TemporaryDirectory() as work:
            code, output, stdout, _ = self.run_cli(work, config())
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(stdout), json.loads(output.read_text(encoding="utf-8")))

    def test_cli_applies_policy_layers_in_order(self):
        with tempfile.TemporaryDirectory() as work:
            owner = Path(work) / "owner.json"
            owner.write_text(json.dumps({"min_models": 3}), encoding="utf-8")
            project = Path(work) / "project.json"
            project.write_text(json.dumps({"min_models": 2}), encoding="utf-8")
            settings = config(council=seats(OPUS, SONNET, OPUS))

            code, output, _, stderr = self.run_cli(work, settings, "--policy", str(owner))
            self.assertEqual(code, 2)
            self.assertIn("min_models is 3", stderr)
            self.assertFalse(output.exists())
            code, *_ = self.run_cli(work, settings, "--policy", str(owner), "--policy", str(project))
            self.assertEqual(code, 0)

    def test_cli_rejects_bad_files_without_writing_output(self):
        with tempfile.TemporaryDirectory() as work:
            bad_policy = Path(work) / "bad-policy.json"
            bad_policy.write_text(json.dumps({"min_providers": 2}), encoding="utf-8")
            cases = [(None, ()), ("{broken", ()), ("[]", ()), ('{"projects": []}', ()),
                     (json.dumps(config()), ("--policy", str(bad_policy)))]
            for content, extra in cases:
                with self.subTest(content=content, extra=extra):
                    code, output, _, _ = self.run_cli(work, content, *extra)
                    self.assertEqual(code, 2)
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
