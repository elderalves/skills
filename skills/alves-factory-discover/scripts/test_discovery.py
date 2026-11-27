"""Run with: python -m unittest discover <this-dir>. No network: Linear is a fake."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import discovery
import council

LENSES = ["architecture", "testing", "performance", "ux-accessibility", "security",
          "maintainability", "developer-experience"]


def native(repo, **discovery_settings):
    return {"match": "linear-project:Side", "repo": repo, "base_branch": "main",
            "upstream": {"type": "linear"}, "discovery": discovery_settings}


def jira(repo, upstream_file=None, **discovery_settings):
    upstream = {"type": "jira", "site": "x.atlassian.net"}
    if upstream_file is not None:
        upstream["file"] = upstream_file
    return {"match": "RTP-", "repo": repo, "base_branch": "main", "linear_project": "Explore",
            "upstream": upstream, "discovery": discovery_settings}


def ticket(identifier, state, labels=()):
    return {"id": identifier, "identifier": identifier, "url": f"https://linear.app/{identifier}",
            "title": f"t {identifier}", "description": "", "state": state, "labels": list(labels),
            "priority": 0, "attachment_urls": [], "comments": []}


class FakeLinear:
    def __init__(self, tickets=()):
        self.tickets, self.calls, self.created = list(tickets), [], []

    def list_all(self, team, project):
        self.calls.append(("list_all", team, project))
        return self.tickets


class Rules(unittest.TestCase):
    def test_lens_rotates_by_date(self):
        day = date(2026, 11, 27)
        first = discovery.lens_for(day, LENSES)
        second = discovery.lens_for(day + timedelta(days=1), LENSES)
        self.assertEqual(LENSES.index(second), (LENSES.index(first) + 1) % len(LENSES))
        self.assertEqual(discovery.lens_for(day + timedelta(days=7), LENSES), first)

    def test_room_never_negative(self):
        self.assertEqual(discovery.room(3, 10, 12), 0)
        self.assertEqual(discovery.room(3, 10, 10), 0)
        self.assertEqual(discovery.room(3, 10, 8), 2)
        self.assertEqual(discovery.room(3, 10, 0), 3)


class Settings(unittest.TestCase):
    def setUp(self):
        self.policy = discovery.load_policy([])

    def test_settings_refuses_jira_without_upstream_file(self):
        with self.assertRaisesRegex(discovery.DiscoveryError, "upstream.file"):
            discovery.settings(jira("C:/r"), self.policy)
        with self.assertRaisesRegex(discovery.DiscoveryError, "project_key"):
            discovery.settings(jira("C:/r", {"issue_type": "Task"}), self.policy)
        github = {"match": "github:acme/w#", "repo": "C:/w", "upstream": {"type": "github"}, "discovery": {}}
        with self.assertRaisesRegex(discovery.DiscoveryError, "upstream.file"):
            discovery.settings(github, self.policy)
        self.assertEqual(discovery.settings(jira("C:/r", {"project_key": "RTP"}), self.policy)["max_new"], 3)

    def test_settings_refuses_an_entry_without_discovery(self):
        entry = native("C:/s")
        del entry["discovery"]
        with self.assertRaisesRegex(discovery.DiscoveryError, "no discovery"):
            discovery.settings(entry, self.policy)

    def test_settings_defaults_caps_and_lenses(self):
        self.assertEqual(discovery.settings(native("C:/s"), self.policy),
                         {"lenses": LENSES, "max_new": 3, "max_open": 10, "scorer_target": None})

    def test_entry_lenses_and_caps_override_the_policy(self):
        got = discovery.settings(native("C:/s", lenses=["security"], max_new=1, max_open=4,
                                        scorer={"target": {"providerInstanceId": "codex", "model": "gpt-6.1-sol"}}),
                                 self.policy)
        self.assertEqual(got, {"lenses": ["security"], "max_new": 1, "max_open": 4,
                               "scorer_target": {"providerInstanceId": "codex", "model": "gpt-6.1-sol"}})

    def test_settings_refuses_bad_caps(self):
        for bad in ({"max_new": -1}, {"max_open": "10"}, {"max_new": True}, {"lenses": []},
                    {"scorer": {"target": {"model": "x"}}}):
            with self.subTest(bad=bad), self.assertRaises(discovery.DiscoveryError):
                discovery.settings(native("C:/s", **bad), self.policy)

    def test_policy_defaults_match_the_spec(self):
        self.assertEqual(self.policy["weights"],
                         {"impact": 30, "engineering": 25, "reach": 15, "evidence": 15, "urgency": 15})
        self.assertEqual(self.policy["bands"], {"high": 70, "medium": 50, "low": 30})
        self.assertEqual(self.policy["max_candidates"], 5)
        self.assertEqual(self.policy["lenses"], LENSES)

    def test_policy_layers_deep_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_bytes(json.dumps({"weights": {"impact": 40}, "lenses": ["testing"]}).encode("utf-16"))
            policy = discovery.load_policy([path])
        self.assertEqual(policy["weights"]["impact"], 40)
        self.assertEqual(policy["weights"]["engineering"], 25)
        self.assertEqual(policy["lenses"], ["testing"])
        self.assertEqual(discovery.settings(native("C:/s"), policy)["lenses"], ["testing"])

    def test_policy_refuses_an_unknown_criterion(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "p.json"
            path.write_text(json.dumps({"weights": {"vibes": 10}}), encoding="utf-8")
            with self.assertRaisesRegex(discovery.DiscoveryError, "vibes"):
                discovery.load_policy([path])


class Scorer(unittest.TestCase):
    def config(self, entry):
        return {"linear_team": "Alves", "projects": [entry]}

    def test_scorer_defaults_to_testing_risk_seat(self):
        entry = native("C:/s")
        entry["council"] = {"testing-risk": {"target": {"providerInstanceId": "codex", "model": "gpt-6.1-sol"}}}
        self.assertEqual(discovery.scorer_seat(self.config(entry), entry, "claude-opus-5-5"),
                         {"providerInstanceId": "codex", "model": "gpt-6.1-sol"})
        bare = native("C:/s")
        default = council.resolve(self.config(bare), bare["match"])["testing-risk"]["target"]
        self.assertEqual(discovery.scorer_seat(self.config(bare), bare, "claude-opus-5-5"), default)

    def test_scorer_set_on_the_entry_wins(self):
        target = {"providerInstanceId": "claudeAgent", "model": "claude-sonnet-5-5"}
        entry = native("C:/s", scorer={"target": target})
        self.assertEqual(discovery.scorer_seat(self.config(entry), entry, "gpt-6.2-sol"), target)

    def test_scorer_of_a_shared_prefix_uses_its_own_entry(self):
        one = jira("C:/r", {"project_key": "RTP"})
        two = {**jira("C:/q", {"project_key": "RTP"}), "linear_project": "Other",
               "council": {"testing-risk": {"target": {"providerInstanceId": "codex", "model": "gpt-6.1-sol"}}}}
        config = {"linear_team": "Alves", "projects": [one, two]}
        self.assertEqual(discovery.scorer_seat(config, two, "claude-opus-5-5")["model"], "gpt-6.1-sol")

    def test_scorer_same_model_as_discoverer_refuses(self):
        entry = native("C:/s", scorer={"target": {"providerInstanceId": "acpRegistry_github_copilot",
                                                  "model": "claude-opus-5.5"}})
        with self.assertRaises(discovery.DiscoveryError) as caught:
            discovery.scorer_seat(self.config(entry), entry, "claude-opus-5-5")
        self.assertIn("claude-opus-5.5", str(caught.exception))
        self.assertIn("claude-opus-5-5", str(caught.exception))


class Prepare(unittest.TestCase):
    CLOCK = datetime(2026, 11, 27, 9, 30, 15, tzinfo=timezone.utc)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.out = self.root / "out"

    def tearDown(self):
        self.tmp.cleanup()

    def write_config(self, entry, encoding="utf-8-sig"):
        path = self.root / "projects.json"
        path.write_bytes(json.dumps({"linear_team": "Alves", "projects": [entry]}).encode(encoding))
        return path

    def prepare(self, entry, linear, project="Side", encoding="utf-8-sig"):
        argv = ["prepare", "--linear-project", project, "--discoverer-model", "claude-opus-5-5",
                "--date", "2026-11-27", "--out", str(self.out), "--config", str(self.write_config(entry, encoding))]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = discovery.main(argv, linear=linear, clock=lambda: self.CLOCK)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_prepare_counts_only_discovered_backlog(self):
        linear = FakeLinear([ticket("ALV-1", "Backlog", ["discovered"]), ticket("ALV-2", "Backlog"),
                             ticket("ALV-3", "Canceled", ["discovered"])])
        code, out, err = self.prepare(native(str(self.repo)), linear, encoding="utf-16")
        self.assertEqual(code, 0, err)
        prepared = json.loads((self.out / "prepare.json").read_text(encoding="utf-8"))
        self.assertEqual(json.loads(out), prepared)
        self.assertEqual(prepared["open_backlog"], 1)
        self.assertEqual(prepared["room"], 3)
        self.assertEqual(linear.calls, [("list_all", "Alves", "Side")])
        self.assertEqual(json.loads((self.out / "tickets.json").read_text(encoding="utf-8")), linear.tickets)
        self.assertEqual(prepared["match"], "linear-project:Side")
        self.assertEqual(prepared["linear_project"], "Side")
        self.assertEqual(prepared["team"], "Alves")
        self.assertEqual(prepared["lens"], discovery.lens_for(date(2026, 11, 27), LENSES))
        self.assertEqual(prepared["max_candidates"], 5)
        self.assertEqual(prepared["upstream_type"], "linear")
        self.assertEqual(prepared["policy"], discovery.load_policy([]))
        self.assertEqual(prepared["scorer"], council.resolve({"projects": [native("x")]},
                                                             "linear-project:Side")["testing-risk"]["target"])

    def test_prepare_with_a_full_backlog_has_no_room(self):
        linear = FakeLinear([ticket(f"ALV-{n}", "Backlog", ["discovered"]) for n in range(12)])
        code, out, err = self.prepare(native(str(self.repo)), linear)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["open_backlog"], 12)
        self.assertEqual(json.loads(out)["room"], 0)

    def test_prepare_since_is_a_day_before_at_the_clock_time(self):
        code, out, err = self.prepare(native(str(self.repo)), FakeLinear())
        self.assertEqual(code, 0, err)
        since = datetime.fromisoformat(json.loads(out)["since"])
        self.assertIsNotNone(since.tzinfo)
        self.assertEqual(since.replace(tzinfo=None), datetime(2026, 11, 26, 9, 30, 15))

    def test_prepare_finds_a_prefix_entry_by_its_linear_project(self):
        entry = jira(str(self.repo), {"project_key": "RTP"})
        linear = FakeLinear()
        code, out, err = self.prepare(entry, linear, project="explore")
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["linear_project"], "Explore")
        self.assertEqual(json.loads(out)["upstream_type"], "jira")
        self.assertEqual(linear.calls, [("list_all", "Alves", "Explore")])

    def test_prepare_layers_the_entry_policy(self):
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({"lenses": ["security"], "max_candidates": 2}), encoding="utf-8")
        code, out, err = self.prepare(native(str(self.repo), policy=str(policy)), FakeLinear())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["lens"], "security")
        self.assertEqual(json.loads(out)["max_candidates"], 2)

    def test_prepare_exits_2_on_config_errors(self):
        linear = FakeLinear()
        code, _, err = self.prepare(jira(str(self.repo)), linear, project="Explore")
        self.assertEqual(code, 2)
        self.assertIn("upstream.file", err)
        self.assertEqual(linear.calls, [])
        code, _, err = self.prepare(native(str(self.repo)), linear, project="Nowhere")
        self.assertEqual(code, 2)
        self.assertFalse((self.out / "prepare.json").exists())

    def test_prepare_exits_1_on_a_linear_error(self):
        class Failing(FakeLinear):
            def list_all(self, team, project):
                raise discovery.linear_mod.LinearError("boom")
        code, _, err = self.prepare(native(str(self.repo)), Failing())
        self.assertEqual(code, 1)
        self.assertIn("boom", err)


if __name__ == "__main__":
    unittest.main()
