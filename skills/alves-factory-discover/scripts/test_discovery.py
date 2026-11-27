"""Run with: python -m unittest discover <this-dir>. No network: Linear is a fake."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import discovery
import council
import upstream

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
        github = {"match": "github:acme/w#", "repo": "C:/w", "upstream": {"type": "github"}, "discovery": {}}
        with self.assertRaisesRegex(discovery.DiscoveryError, "upstream.file"):
            discovery.settings(github, self.policy)
        with self.assertRaisesRegex(discovery.DiscoveryError, "upstream.file"):
            discovery.settings(jira("C:/r", "yes"), self.policy)
        self.assertEqual(discovery.settings(jira("C:/r", {"project_key": "RTP"}), self.policy)["max_new"], 3)

    def test_settings_takes_an_empty_upstream_file_as_the_opt_in(self):
        # project_key defaults to the match without its trailing -, as upstream.py does.
        self.assertEqual(discovery.settings(jira("C:/r", {}), self.policy)["max_new"], 3)
        self.assertEqual(discovery.settings(jira("C:/r", {"issue_type": "Task"}), self.policy)["max_new"], 3)
        github = {"match": "github:acme/w#", "repo": "C:/w", "upstream": {"type": "github", "file": {}},
                  "discovery": {}}
        self.assertEqual(discovery.settings(github, self.policy)["max_new"], 3)
        with self.assertRaisesRegex(discovery.DiscoveryError, "project_key"):
            discovery.settings(jira("C:/r", {"project_key": " "}), self.policy)

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
        self.assertIs(prepared["native"], True)
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
        self.assertIs(json.loads(out)["native"], False)
        self.assertEqual(linear.calls, [("list_all", "Alves", "Explore")])

    def test_prepare_marks_a_native_entry_without_an_upstream_key(self):
        # Step 4 skips the upstream search on `native`, so an entry with no `upstream` cannot fail it.
        entry = native(str(self.repo))
        del entry["upstream"]
        code, out, err = self.prepare(entry, FakeLinear())
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(out)["native"], True)
        self.assertIsNone(json.loads(out)["upstream_type"])

    def test_prepare_layers_the_entry_policy(self):
        policy = self.root / "policy.json"
        policy.write_text(json.dumps({"lenses": ["security"], "max_candidates": 2}), encoding="utf-8")
        code, out, err = self.prepare(native(str(self.repo), policy=str(policy)), FakeLinear())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["lens"], "security")
        self.assertEqual(json.loads(out)["max_candidates"], 2)

    def test_prepare_expands_a_tilde_out_dir(self):
        home = self.root / "home"
        home.mkdir()
        cwd = self.root / "cwd"
        cwd.mkdir()
        self.out = Path("~/pass")
        old = os.getcwd()
        os.chdir(cwd)
        try:
            with mock.patch.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home)}):
                code, out, err = self.prepare(native(str(self.repo)), FakeLinear())
        finally:
            os.chdir(old)
        self.assertEqual(code, 0, err)
        self.assertTrue((home / "pass" / "prepare.json").is_file())
        self.assertTrue((home / "pass" / "tickets.json").is_file())
        self.assertFalse((cwd / "~").exists())

    def test_prepare_starts_each_pass_clean(self):
        self.out.mkdir()
        for name in ("candidates.json", "scored.json", "selected.json", "filed.json", "notes.txt"):
            (self.out / name).write_text("[]", encoding="utf-8")
        for folder in ("scores", "record", "keep"):
            (self.out / folder).mkdir()
            (self.out / folder / "x.json").write_text("{}", encoding="utf-8")
        code, _, err = self.prepare(native(str(self.repo)), FakeLinear())
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(p.name for p in self.out.iterdir()),
                         ["keep", "notes.txt", "prepare.json", "tickets.json"])
        self.assertTrue((self.out / "keep" / "x.json").is_file())

    def test_prepare_that_fails_leaves_the_work_dir_alone(self):
        self.out.mkdir()
        (self.out / "candidates.json").write_text("[]", encoding="utf-8")
        code, _, _ = self.prepare(native(str(self.repo)), FakeLinear(), project="Nowhere")
        self.assertEqual(code, 2)
        self.assertTrue((self.out / "candidates.json").is_file())

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


SEAT = {"providerInstanceId": "codex", "model": "gpt-6.1-sol"}
RATIONALE = {c: f"why {c}" for c in discovery.CRITERIA}


def candidate(cid, title=None, **fields):
    return {"id": cid, "title": title or f"Fix {cid}", "problem": f"{cid} is broken",
            "why": f"{cid} costs time", "acceptance_criteria": [f"{cid} works", f"{cid} is tested"],
            "evidence": [f"src/{cid}.py:12"], "closest": {"identifier": "ALV-3", "why_different": "other module"},
            "regression_of": None, **fields}


def score(values, effort="M", seat=SEAT, rationale=RATIONALE):
    return {"scores": dict(zip(discovery.CRITERIA, values)) if isinstance(values, tuple) else values,
            "effort": effort, "rationale": dict(rationale), "seat": dict(seat)}


# Value scores 92, 81, 38 and 25 under the default weights.
S92, S81, S38, S25 = (9, 8, 10, 10, 10), (5, 9, 9, 10, 10), (0, 2, 2, 10, 10), (0, 1, 1, 7, 7)


class WorkDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.prepared = {"match": "linear-project:Side", "linear_project": "Side", "team": "Alves",
                         "lens": "testing", "room": 3, "open_backlog": 0, "max_candidates": 5,
                         "since": "2026-11-26T09:30:15-03:00", "scorer": SEAT,
                         "policy": discovery.load_policy([]), "upstream_type": "linear"}
        self.write("prepare.json", self.prepared)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, name, value, encoding="utf-8"):
        path = self.dir / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(json.dumps(value).encode(encoding))

    def put(self, *pairs):
        """Write candidates.json and scores/<id>.json from (candidate, score) pairs."""
        self.write("candidates.json", [c for c, _ in pairs])
        for c, s in pairs:
            if s is not None:
                self.write(f"scores/{c['id']}.json", {"title": c.get("title"), **s})

    def run_cli(self, *argv, linear=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = discovery.main(list(argv), linear=linear)
        return code, stdout.getvalue(), stderr.getvalue()


class Check(WorkDir):
    def test_check_passes_good_input(self):
        self.put((candidate("c1"), score(S92, "S")), (candidate("c2"), score(S81)))
        self.assertEqual(discovery.check(self.dir), [])
        self.assertEqual(self.run_cli("check", str(self.dir))[:2], (0, "ok\n"))

    def test_check_names_each_bad_score(self):
        bad = score({"impact": "8", "engineering": 7, "evidence": 6, "urgency": 11}, effort="XL",
                    seat={"providerInstanceId": "codex", "model": "claude-opus-5-5"})
        self.put((candidate("c1"), bad), (candidate("c2"), score(S81)))
        problems = discovery.check(self.dir)
        self.assertEqual(len(problems), 5, problems)
        for problem in problems:
            self.assertTrue(problem.startswith("c1: "), problem)
        for needle in ("scores.urgency", "scores.reach", "scores.impact", "effort", "seat"):
            self.assertEqual(sum(needle in p for p in problems), 1, (needle, problems))
        code, out, _ = self.run_cli("check", str(self.dir))
        self.assertEqual(code, 1)
        self.assertEqual(out.splitlines(), problems)

    def test_check_refuses_floats_booleans_and_a_wrong_connection(self):
        for value in (8.0, True, -1, None):
            with self.subTest(value=value):
                self.put((candidate("c1"), score(dict(zip(discovery.CRITERIA, S92)) | {"impact": value})))
                self.assertEqual(len(discovery.check(self.dir)), 1)
        self.put((candidate("c1"), score(S92, seat={"providerInstanceId": "opencode", "model": "gpt-6.1-sol"})))
        self.assertEqual(len(discovery.check(self.dir)), 1)
        self.put((candidate("c1"), score(S92, seat={"providerInstanceId": "codex", "model": "gpt-6.1-SOL"})))
        self.assertEqual(discovery.check(self.dir), [])

    def test_check_names_a_missing_score_file_and_rationale(self):
        self.put((candidate("c1"), None), (candidate("c2"), score(S81, rationale={"impact": "x"})))
        problems = discovery.check(self.dir)
        self.assertTrue(any(p.startswith("c1: ") and "scores/c1.json" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("c2: ") and "rationale" in p for p in problems), problems)

    def test_check_names_a_score_for_another_title(self):
        self.put((candidate("c1", "Fix the importer"), {**score(S81), "title": "Fix the exporter"}),
                 (candidate("c2"), score(S81)))
        problems = discovery.check(self.dir)
        self.assertEqual(len(problems), 1, problems)
        self.assertTrue(problems[0].startswith("c1: "), problems)
        self.assertIn("Fix the exporter", problems[0])
        self.assertIn("Fix the importer", problems[0])
        self.write("scores/c2.json", score(S81))
        self.assertTrue(any(p.startswith("c2: ") and "title" in p for p in discovery.check(self.dir)))

    def test_check_refuses_more_than_max_candidates(self):
        self.put(*[(candidate(f"c{n}"), score(S81)) for n in range(1, 7)])
        problems = discovery.check(self.dir)
        self.assertEqual(len(problems), 1, problems)
        self.assertIn("6", problems[0])
        self.assertIn("5", problems[0])

    def test_check_requires_closest_why_different(self):
        self.put((candidate("c1", closest={"identifier": "ALV-3", "why_different": " "}), score(S81)),
                 (candidate("c2", closest={"identifier": None}), score(S81)),
                 (candidate("c3", closest=None), score(S81)))
        problems = discovery.check(self.dir)
        for cid in ("c1", "c2", "c3"):
            self.assertTrue(any(p.startswith(f"{cid}: ") and "closest" in p for p in problems), problems)
        self.put((candidate("c1", closest={"identifier": None, "why_different": "nothing close"}), score(S81)))
        self.assertEqual(discovery.check(self.dir), [])

    def test_check_refuses_bad_candidate_fields(self):
        self.put((candidate("c1", acceptance_criteria=[]), score(S81)),
                 (candidate("c1"), score(S81)),
                 (candidate("../x"), None),
                 (candidate("c4", evidence="a file"), score(S81)),
                 (candidate("c5", regression_of=3), score(S81)))
        problems = discovery.check(self.dir)
        self.assertTrue(any("acceptance_criteria" in p for p in problems), problems)
        self.assertTrue(any("c1" in p and "twice" in p for p in problems), problems)
        self.assertTrue(any("../x" in p and "id" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("c4: ") and "evidence" in p for p in problems), problems)
        self.assertTrue(any(p.startswith("c5: ") and "regression_of" in p for p in problems), problems)

    def test_score_refuses_until_check_passes(self):
        self.put((candidate("c1"), score(S92, effort="XL")))
        code, out, _ = self.run_cli("score", str(self.dir))
        self.assertEqual(code, 1)
        self.assertIn("c1: ", out)
        self.assertFalse((self.dir / "selected.json").exists())
        self.assertFalse((self.dir / "scored.json").exists())


class Scoring(unittest.TestCase):
    WEIGHTS = discovery.load_policy([])["weights"]
    BANDS = discovery.load_policy([])["bands"]

    def test_value_score_uses_weights(self):
        self.assertEqual(discovery.value_score(dict(zip(discovery.CRITERIA, (9, 8, 7, 9, 8))), self.WEIGHTS), 83)
        # 82.5 rounds half up, not to the even 82.
        self.assertEqual(discovery.value_score(dict(zip(discovery.CRITERIA, (9, 9, 8, 7, 7))), self.WEIGHTS), 83)
        self.assertEqual(discovery.value_score(dict(zip(discovery.CRITERIA, S92)), self.WEIGHTS), 92)
        self.assertEqual(discovery.value_score(dict(zip(discovery.CRITERIA, S25)), self.WEIGHTS), 25)

    def test_band_edges(self):
        for value, expected in ((100, "High"), (70, "High"), (69, "Medium"), (50, "Medium"), (49, "Low"),
                                (30, "Low"), (29, None), (0, None)):
            with self.subTest(value=value):
                self.assertEqual(discovery.band(value, self.BANDS), expected)

    def test_select_drops_below_low_and_keeps_room(self):
        policy = discovery.load_policy([])
        candidates = [candidate("c38"), candidate("c81"), candidate("c25"), candidate("c92")]
        scores = {"c38": score(S38), "c81": score(S81), "c25": score(S25), "c92": score(S92)}
        chosen = discovery.select(candidates, scores, policy, 2)
        self.assertEqual([(c["id"], c["value_score"], c["band"]) for c in chosen],
                         [("c92", 92, "High"), ("c81", 81, "High")])
        everything = discovery.select(candidates, scores, policy, 5)
        self.assertEqual([c["id"] for c in everything], ["c92", "c81", "c38"])
        self.assertEqual(everything[2]["band"], "Low")
        self.assertEqual(discovery.select(candidates, scores, policy, 0), [])

    def test_select_keeps_candidate_order_on_ties_and_carries_the_breakdown(self):
        policy = discovery.load_policy([])
        candidates = [candidate("b"), candidate("a")]
        chosen = discovery.select(candidates, {"a": score(S81), "b": score(S81, "L")}, policy, 3)
        self.assertEqual([c["id"] for c in chosen], ["b", "a"])
        self.assertEqual(chosen[0]["effort"], "L")
        self.assertEqual(chosen[0]["title"], "Fix b")
        self.assertEqual(chosen[0]["breakdown"][0],
                         {"criterion": "impact", "weight": 30, "score": 5, "rationale": "why impact"})
        self.assertEqual([b["criterion"] for b in chosen[0]["breakdown"]], list(discovery.CRITERIA))

    def test_quick_win_only_high_and_small(self):
        policy = discovery.load_policy([])
        medium = (5, 5, 5, 5, 5)
        cases = [("high-s", S92, "S", True), ("high-m", S92, "M", False), ("high-l", S81, "L", False),
                 ("medium-s", medium, "S", False)]
        chosen = discovery.select([candidate(c) for c, *_ in cases],
                                  {c: score(v, e) for c, v, e, _ in cases}, policy, 4)
        self.assertEqual({c["id"]: c["quick_win"] for c in chosen}, {c: q for c, _, _, q in cases})


def selected_item(cid="c1", values=S92, effort="S", **fields):
    item = discovery.select([candidate(cid, **fields)], {cid: score(values, effort)},
                            discovery.load_policy([]), 1)[0]
    return {**item, "lens": "testing"}


class Description(unittest.TestCase):
    def test_render_description_public_part_has_no_scores(self):
        text = discovery.render_description(selected_item())
        public = text.split("## Factory notes")[0]
        self.assertNotIn("/100", public)
        self.assertNotIn("Effort", public)
        self.assertNotIn("testing", public.replace("is tested", ""))
        self.assertEqual(upstream.public_part(text).strip(), f"{public.strip()}\n\n{upstream.CLOSING_LINE}")
        for heading in ("## Problem", "## Why it matters", "## Acceptance criteria"):
            self.assertIn(heading, public)
        self.assertIn("- c1 works\n- c1 is tested", public)

    def test_render_description_factory_notes(self):
        item = selected_item(regression_of="ALV-1", closest={"identifier": "ALV-3", "why_different": "other module"})
        item["breakdown"][1]["rationale"] = "a | b\nc"
        text = discovery.render_description(item)
        notes = text.split("## Factory notes")[1]
        for needle in ("**Lens:** testing", "- src/c1.py:12", "92/100 (High)", "| impact | 30 | 9 | why impact |",
                       "| engineering | 25 | 8 | a \\| b c |", "**Effort:** S", "ALV-3", "other module", "ALV-1"):
            self.assertIn(needle, notes)
        self.assertLess(notes.index("Lens"), notes.index("Evidence"))
        self.assertLess(notes.index("Evidence"), notes.index("/100"))
        self.assertLess(notes.index("/100"), notes.index("Effort"))
        self.assertLess(notes.index("Effort"), notes.index("ALV-3"))


class FakeCreating(FakeLinear):
    def create(self, team, title, upstream_url=None, upstream_title=None, state=None, description=None,
               project=None, labels=(), priority=None):
        self.created.append({"team": team, "title": title, "upstream_url": upstream_url, "state": state,
                             "description": description, "project": project, "labels": list(labels),
                             "priority": priority})
        return {"identifier": f"ALV-{len(self.created) + 10}", "title": title}


class Filing(WorkDir):
    def score_and_file(self, *extra, linear=None):
        self.put((candidate("c1", "Speed up the importer"), score(S81, "M")),
                 (candidate("c2", "Test the parser"), score(S92, "S")),
                 (candidate("c3", "Rename a variable"), score(S25)))
        code, out, err = self.run_cli("score", str(self.dir))
        self.assertEqual(code, 0, err)
        selected = json.loads((self.dir / "selected.json").read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in json.loads(out)["selected"]], [s["id"] for s in selected])
        return self.run_cli("file", str(self.dir), *extra, linear=linear)

    def test_score_writes_every_scored_candidate_with_its_outcome(self):
        self.prepared["room"] = 2
        self.write("prepare.json", self.prepared)
        self.put((candidate("c38", "Tidy the logger"), score(S38)),
                 (candidate("c92", "Test the parser"), score(S92, "S")),
                 (candidate("c25", "Rename a variable"), score(S25, "L")),
                 (candidate("c81", "Speed up the importer"), score(S81)))
        code, out, err = self.run_cli("score", str(self.dir))
        self.assertEqual(code, 0, err)
        scored = json.loads((self.dir / "scored.json").read_text(encoding="utf-8"))
        self.assertEqual(scored, [
            {"id": "c92", "title": "Test the parser", "value_score": 92, "band": "High", "effort": "S",
             "quick_win": True, "outcome": "selected"},
            {"id": "c81", "title": "Speed up the importer", "value_score": 81, "band": "High", "effort": "M",
             "quick_win": False, "outcome": "selected"},
            {"id": "c38", "title": "Tidy the logger", "value_score": 38, "band": "Low", "effort": "M",
             "quick_win": False, "outcome": "past the room"},
            {"id": "c25", "title": "Rename a variable", "value_score": 25, "band": None, "effort": "L",
             "quick_win": False, "outcome": "below the bar"}])
        self.assertEqual(json.loads(out), {"selected": scored[:2], "dropped": scored[2:]})
        selected = json.loads((self.dir / "selected.json").read_text(encoding="utf-8"))
        self.assertEqual([s["id"] for s in selected], ["c92", "c81"])
        self.assertEqual(selected[0]["lens"], "testing")
        self.assertIn("breakdown", selected[0])

    def test_score_with_no_room_drops_every_banded_candidate_past_the_room(self):
        self.prepared["room"] = 0
        self.write("prepare.json", self.prepared)
        self.put((candidate("c92"), score(S92)), (candidate("c25"), score(S25)))
        code, out, err = self.run_cli("score", str(self.dir))
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads((self.dir / "selected.json").read_text(encoding="utf-8")), [])
        self.assertEqual([(d["id"], d["outcome"]) for d in json.loads(out)["dropped"]],
                         [("c92", "past the room"), ("c25", "below the bar")])

    def test_file_sends_labels_priority_and_backlog(self):
        linear = FakeCreating()
        code, out, err = self.score_and_file(linear=linear)
        self.assertEqual(code, 0, err)
        first, second = linear.created
        self.assertEqual(first, {"team": "Alves", "title": "Test the parser", "upstream_url": None,
                                 "state": "Backlog", "project": "Side", "labels": ["discovered", "quick-win"],
                                 "priority": 2, "description": first["description"]})
        self.assertIn("92/100 (High)", first["description"])
        self.assertIn("**Lens:** testing", first["description"])
        self.assertEqual((second["title"], second["labels"], second["priority"], second["state"]),
                         ("Speed up the importer", ["discovered"], 2, "Backlog"))
        self.assertEqual(json.loads(out), [
            {"identifier": "ALV-11", "title": "Test the parser", "value_score": 92, "band": "High", "effort": "S"},
            {"identifier": "ALV-12", "title": "Speed up the importer", "value_score": 81, "band": "High",
             "effort": "M"}])

    def test_file_maps_each_band_to_its_priority(self):
        self.assertEqual(discovery.PRIORITY, {"High": 2, "Medium": 3, "Low": 4})
        linear = FakeCreating()
        self.put((candidate("m"), score((5, 5, 5, 5, 5))), (candidate("l"), score(S38)))
        self.assertEqual(self.run_cli("score", str(self.dir))[0], 0)
        self.assertEqual(self.run_cli("file", str(self.dir), linear=linear)[0], 0)
        self.assertEqual([(c["priority"], c["labels"]) for c in linear.created],
                         [(3, ["discovered"]), (4, ["discovered"])])

    def test_file_respects_room(self):
        self.prepared["room"] = 1
        self.write("prepare.json", self.prepared)
        linear = FakeCreating()
        code, out, err = self.score_and_file(linear=linear)
        self.assertEqual(code, 0, err)
        self.assertEqual([c["title"] for c in linear.created], ["Test the parser"])

    def test_file_dry_run_writes_records_and_creates_nothing(self):
        linear = FakeCreating()
        code, out, err = self.score_and_file("--dry-run", linear=linear)
        self.assertEqual(code, 0, err)
        self.assertEqual(linear.created, [])
        first = (self.dir / "record" / "01-ticket.md").read_text(encoding="utf-8")
        second = (self.dir / "record" / "02-ticket.md").read_text(encoding="utf-8")
        self.assertFalse((self.dir / "record" / "03-ticket.md").exists())
        self.assertIn("Test the parser", first)
        self.assertIn("discovered, quick-win", first)
        self.assertIn("2 (High)", first)
        self.assertIn(discovery.render_description(json.loads(
            (self.dir / "selected.json").read_text(encoding="utf-8"))[0]), first)
        self.assertIn("Speed up the importer", second)
        self.assertEqual([r["identifier"] for r in json.loads(out)], [None, None])

    def test_file_exits_1_on_a_linear_error_naming_what_was_filed(self):
        class Failing(FakeCreating):
            def create(self, *args, **kwargs):
                if self.created:
                    raise discovery.linear_mod.LinearError("boom")
                return super().create(*args, **kwargs)
        code, _, err = self.score_and_file(linear=Failing())
        self.assertEqual(code, 1)
        self.assertIn("boom", err)
        self.assertIn("ALV-11", err)

    def test_file_records_each_create_and_a_rerun_files_only_the_rest(self):
        class Failing(FakeCreating):
            def create(self, *args, **kwargs):
                if self.created:
                    raise discovery.linear_mod.LinearError("boom")
                return super().create(*args, **kwargs)
        code, _, err = self.score_and_file(linear=Failing())
        self.assertEqual(code, 1)
        self.assertIn("rerun `file`", err)
        filed = json.loads((self.dir / "filed.json").read_text(encoding="utf-8"))
        self.assertEqual(filed, [{"number": 1, "identifier": "ALV-11", "title": "Test the parser"}])
        linear = FakeCreating()
        code, out, err = self.run_cli("file", str(self.dir), linear=linear)
        self.assertEqual(code, 0, err)
        self.assertEqual([c["title"] for c in linear.created], ["Speed up the importer"])
        self.assertEqual([(r["identifier"], r["title"]) for r in json.loads(out)],
                         [("ALV-11", "Test the parser"), ("ALV-11", "Speed up the importer")])
        self.assertEqual([f["number"] for f in json.loads((self.dir / "filed.json").read_text(encoding="utf-8"))],
                         [1, 2])
        again = FakeCreating()
        self.assertEqual(self.run_cli("file", str(self.dir), linear=again)[0], 0)
        self.assertEqual(again.created, [])

    def test_dry_run_neither_reads_nor_writes_filed_json(self):
        self.write("filed.json", [{"number": 1, "identifier": "ALV-1", "title": "Test the parser"}])
        code, out, err = self.score_and_file("--dry-run", linear=FakeCreating())
        self.assertEqual(code, 0, err)
        self.assertTrue((self.dir / "record" / "01-ticket.md").is_file())
        self.assertIn("Test the parser", (self.dir / "record" / "01-ticket.md").read_text(encoding="utf-8"))
        self.assertEqual(len(json.loads((self.dir / "filed.json").read_text(encoding="utf-8"))), 1)

    def test_work_dir_commands_expand_a_tilde(self):
        self.put((candidate("c1", "Test the parser"), score(S92, "S")))
        home = self.dir.parent
        tilde = str(Path("~") / self.dir.name)
        linear = FakeCreating()
        cwd = self.dir / "cwd"
        cwd.mkdir()
        old = os.getcwd()
        os.chdir(cwd)
        try:
            with mock.patch.dict(os.environ, {"USERPROFILE": str(home), "HOME": str(home)}):
                self.assertEqual(self.run_cli("check", tilde)[:2], (0, "ok\n"))
                self.assertEqual(self.run_cli("score", tilde)[0], 0)
                self.assertEqual(self.run_cli("file", tilde, linear=linear)[0], 0)
        finally:
            os.chdir(old)
        self.assertFalse((cwd / "~").exists())
        self.assertEqual(len(linear.created), 1)
        self.assertTrue((self.dir / "selected.json").is_file())
        self.assertTrue((self.dir / "filed.json").is_file())

    def test_file_without_score_exits_2(self):
        code, _, err = self.run_cli("file", str(self.dir), linear=FakeCreating())
        self.assertEqual(code, 2)
        self.assertIn("selected.json", err)


if __name__ == "__main__":
    unittest.main()
