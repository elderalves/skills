"""Run with: python -m unittest discover <this-dir>. No network: Linear, gh and acli are fakes."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path

import sweep
from linear import MARKER

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
LIMITS = dict(sweep.DEFAULT_LIMITS)
JIRA = {"match": "PCS-", "repo": "C:/r", "upstream": {"type": "jira", "site": "x.atlassian.net"},
        "linear_project": "AgileKit"}
NATIVE = {"match": "linear-project:Side", "repo": "C:/s", "upstream": {"type": "linear"}}


def comment(at, body, factory=True):
    return {"created_at": at, "from_factory": factory, "body": f"{MARKER}\n\n{body}" if factory else body}


def ticket(state, entered="2026-11-26T11:50:00Z", comments=(), ref="PCS-1", identifier="ALV-1", pr=None):
    t = {"id": "i", "identifier": identifier, "url": "u", "state": state, "updated_at": entered,
         "entered_state_at": entered, "attachment_urls": [f"https://x.atlassian.net/browse/{ref}"],
         "comments": list(comments), "ref": ref}
    if pr:
        t["pr"] = pr
    return t


def run(*tickets, upstream=()):
    return sweep.decide([{"match": "PCS-", "tickets": list(tickets), "upstream": list(upstream)}], NOW, LIMITS)


class Refs(unittest.TestCase):
    def test_ref_from_each_url_shape(self):
        self.assertEqual(sweep.ref_from_url("https://x.atlassian.net/browse/PCS-12"), "PCS-12")
        self.assertEqual(sweep.ref_from_url("https://github.com/acme/w/issues/3"), "github:acme/w#3")
        self.assertEqual(sweep.ref_from_url("https://factory.invalid/pasted/note"), "pasted:note")
        self.assertIsNone(sweep.ref_from_url("https://figma.com/file/abc"))

    def test_slug_matches_the_work_dir_rule(self):
        self.assertEqual(sweep.slug("github:acme/w#3"), "github-acme-w-3")

    def test_ticket_ref_picks_the_attachment_its_entry_matches(self):
        t = {"identifier": "ALV-2", "attachment_urls": ["https://figma.com/f", "https://x.atlassian.net/browse/PCS-4"]}
        self.assertEqual(sweep.ticket_ref(t, JIRA), "PCS-4")
        self.assertIsNone(sweep.ticket_ref(t, {**JIRA, "match": "DXPX-"}))

    def test_a_native_ticket_is_its_own_ref_unless_it_links_upstream(self):
        self.assertEqual(sweep.ticket_ref({"identifier": "ALV-9", "attachment_urls": []}, NATIVE), "ALV-9")
        t = {"identifier": "ALV-2", "attachment_urls": ["https://x.atlassian.net/browse/PCS-4"]}
        self.assertIsNone(sweep.ticket_ref(t, NATIVE))


class StuckRuns(unittest.TestCase):
    def test_a_live_planning_run_is_left_alone(self):
        t = ticket("Plan Review", entered="2026-11-26T08:00:00Z", comments=[comment("2026-11-26T10:30:00Z", "## Council round 0")])
        self.assertEqual(run(t)["actions"], [])

    def test_a_stale_planning_run_is_restarted_from_ready(self):
        [action] = run(ticket("Planning", entered="2026-11-26T08:00:00Z"))["actions"]
        self.assertEqual((action["kind"], action["to_status"]), ("restart", "Ready"))
        self.assertTrue(action["comment"].startswith(sweep.RESTARTED))
        self.assertIn("4.0 h", action["reason"])

    def test_a_stale_implementation_run_is_restarted_from_plan_approved(self):
        [action] = run(ticket("In Progress", entered="2026-11-26T05:00:00Z"))["actions"]
        self.assertEqual((action["kind"], action["to_status"]), ("restart", "Plan Approved"))

    def test_implementation_gets_the_longer_limit(self):
        self.assertEqual(run(ticket("In Progress", entered="2026-11-26T08:00:00Z"))["actions"], [])

    def test_a_run_that_dies_right_after_a_restart_is_blocked(self):
        restarted = comment("2026-11-26T07:00:00Z", sweep.restart_comment("Planning", sweep.timedelta(hours=4), "Ready"))
        [action] = run(ticket("Planning", entered="2026-11-26T07:05:00Z", comments=[restarted]))["actions"]
        self.assertEqual((action["kind"], action["to_status"]), ("block", "Blocked"))

    def test_progress_after_a_restart_earns_another_restart(self):
        comments = [comment("2026-11-26T05:00:00Z", sweep.RESTARTED), comment("2026-11-26T06:00:00Z", "## Council round 0")]
        [action] = run(ticket("Plan Review", entered="2026-11-26T06:00:00Z", comments=comments))["actions"]
        self.assertEqual(action["kind"], "restart")

    def test_owner_comments_are_not_factory_activity(self):
        owner = comment("2026-11-26T11:00:00Z", "any news?", factory=False)
        [action] = run(ticket("Planning", entered="2026-11-26T08:00:00Z", comments=[owner]))["actions"]
        self.assertEqual(action["kind"], "restart")


class DroppedTriggers(unittest.TestCase):
    def test_a_fresh_trigger_waits(self):
        self.assertIsNone(run(ticket("Ready", entered="2026-11-26T11:45:00Z"))["start"])

    def test_a_ticket_waiting_in_plan_approved_is_started(self):
        start = run(ticket("Plan Approved", entered="2026-11-26T11:00:00Z"))["start"]
        self.assertEqual((start["kind"], start["skill"], start["argument"]),
                         ("start-implement", "alves-factory-implement", "ALV-1"))

    def test_one_start_per_pass_triggers_first_then_oldest(self):
        result = run(ticket("Ready", entered="2026-11-26T10:00:00Z", identifier="ALV-2"),
                     ticket("Ready", entered="2026-11-26T09:00:00Z", identifier="ALV-3"),
                     upstream=[{"ref": "PCS-9", "triage": None, "has_factory_ticket": False}])
        self.assertEqual(result["start"]["argument"], "ALV-3")
        self.assertEqual([d["argument"] for d in result["deferred"]], ["ALV-2", "PCS-9"])
        self.assertNotIn("priority", result["start"])


class Upstream(unittest.TestCase):
    CASES = [
        ("work but no ticket", "work", False, ("start-plan", "alves-factory-run")),
        ("never triaged", None, False, ("start-triage", "alves-factory-triage")),
        ("unsure but no ticket", "unsure", False, ("start-triage", "alves-factory-triage")),
        ("not work", "not work", False, None),
        ("already tracked", "work", True, None),
    ]

    def test_each_upstream_case(self):
        for name, triage, tracked, expected in self.CASES:
            with self.subTest(name):
                start = run(upstream=[{"ref": "PCS-9", "triage": triage, "has_factory_ticket": tracked}])["start"]
                self.assertEqual(start and (start["kind"], start["skill"]), expected)

    def test_triage_decision_reads_the_record(self):
        root = Path(tempfile.mkdtemp())
        for ref, line in [("PCS-1", "- **Decision:** work"), ("PCS-2", "- **Decision:** not work"),
                          ("PCS-3", "**Decision:** Not-work"), ("PCS-4", "no decision here")]:
            (root / ref).mkdir()
            (root / ref / "triage.md").write_text(f"# Triage\n\n{line}\n", encoding="utf-8")
        self.assertEqual([sweep.triage_decision(r, root) for r in ["PCS-1", "PCS-2", "PCS-3", "PCS-4", "PCS-5"]],
                         ["work", "not work", "not work", None, None])


class PullRequests(unittest.TestCase):
    MERGED = {"number": 60, "url": "https://github.com/o/r/pull/60", "state": "MERGED", "mergedAt": "2026-11-26T10:00:00Z"}
    CLOSED = {"number": 61, "url": "https://github.com/o/r/pull/61", "state": "CLOSED", "closedAt": "2026-11-26T10:00:00Z"}

    def test_a_merged_pr_moves_the_ticket_to_done(self):
        [action] = run(ticket("In Review", pr=self.MERGED))["actions"]
        self.assertEqual((action["kind"], action["to_status"], action["pr"]), ("done", "Done", self.MERGED["url"]))

    def test_a_closed_pr_is_noted_once_and_the_status_kept(self):
        [action] = run(ticket("Team Review", pr=self.CLOSED))["actions"]
        self.assertEqual((action["kind"], action["to_status"]), ("note", None))
        noted = comment("2026-11-26T11:00:00Z", action["comment"])
        self.assertEqual(run(ticket("Team Review", pr=self.CLOSED, comments=[noted]))["actions"], [])

    def test_an_open_pr_needs_nothing(self):
        self.assertEqual(run(ticket("In Review", pr={"number": 1, "url": "u", "state": "OPEN"}))["actions"], [])


class FakeLinear:
    def __init__(self, tickets=(), states=None, tracked=()):
        self.tickets, self.states, self.tracked, self.writes = list(tickets), states or {}, set(tracked), []

    def list_issues(self, team, project, states):
        return [t for t in self.tickets if t["state"] in states]

    def find_by_url(self, url):
        return [{"identifier": "ALV-7"}] if url in self.tracked else []

    def issue(self, ref):
        return {"state": {"name": self.states[ref]}}

    def comment(self, ref, body):
        self.writes.append(("comment", ref))

    def set_state(self, ref, name):
        self.writes.append(("state", ref, name))


def fake_runner(responses):
    calls = []

    def runner(args, env=None, cwd=None):
        calls.append(args)
        for prefix, answer in responses.items():
            if " ".join(args).startswith(prefix):
                return answer
        return 1, f"unexpected: {args}"
    runner.calls = calls
    return runner


class Gather(unittest.TestCase):
    def test_reads_prs_and_jira_for_a_jira_project(self):
        t = ticket("In Review", ref="PCS-1")
        del t["ref"]
        linear = FakeLinear([t], tracked={"https://x.atlassian.net/browse/PCS-1"})
        runner = fake_runner({
            "git -C C:/r remote get-url origin": (0, "https://github.com/o/r.git"),
            "gh auth token": (0, "tok"),
            "git -C C:/r ls-remote": (0, ""),
            "gh pr list": (0, json.dumps([{"number": 3, "url": "u3", "state": "MERGED"},
                                          {"number": 5, "url": "u5", "state": "OPEN"}])),
            "acli jira auth status": (0, "  Site: x.atlassian.net\n"),
            "acli jira workitem search": (0, json.dumps([{"key": "PCS-1"}, None, {"key": "PCS-2"}])),
        })
        [project], notes = sweep.gather([{**JIRA, "github_account": "me"}], "Alves", LIMITS, linear, runner,
                                        Path(tempfile.mkdtemp()))
        self.assertEqual(notes, [])
        self.assertEqual(project["tickets"][0]["pr"]["number"], 5)
        self.assertEqual(project["upstream"], [
            {"ref": "PCS-1", "triage": None, "has_factory_ticket": True},
            {"ref": "PCS-2", "triage": None, "has_factory_ticket": False}])
        search = next(c for c in runner.calls if c[:4] == ["acli", "jira", "workitem", "search"])
        self.assertIn("project = PCS AND assignee = currentUser()", search[search.index("--jql") + 1])

    def test_another_acli_site_skips_jira_with_a_note(self):
        runner = fake_runner({"acli jira auth status": (0, "Site: other.atlassian.net")})
        [project], notes = sweep.gather([JIRA], "Alves", LIMITS, FakeLinear(), runner, Path(tempfile.mkdtemp()))
        self.assertEqual(project["upstream"], [])
        self.assertIn("acli is signed in to other.atlassian.net", notes[0])


class Apply(unittest.TestCase):
    def test_writes_only_where_the_status_is_unchanged(self):
        plan = run(ticket("Planning", entered="2026-11-26T08:00:00Z", identifier="ALV-1"),
                   ticket("In Progress", entered="2026-11-26T01:00:00Z", identifier="ALV-2"))
        linear = FakeLinear(states={"ALV-1": "Planning", "ALV-2": "Blocked"})
        result = sweep.apply(plan, linear)
        self.assertEqual(linear.writes, [("comment", "ALV-1"), ("state", "ALV-1", "Ready")])
        self.assertEqual([r["applied"] for r in result], [True, False])
        self.assertEqual(result[1]["why"], "status is now Blocked")


class Config(unittest.TestCase):
    def write(self, data):
        path = Path(tempfile.mkdtemp()) / "projects.json"
        path.write_text(json.dumps(data), encoding="utf-8-sig")
        return path

    def test_sweep_settings_override_the_defaults(self):
        _, limits = sweep.load_config(self.write({"projects": [], "sweep": {"stale_planning_hours": 1}}))
        self.assertEqual(limits["stale_planning_hours"], 1)
        self.assertEqual(limits["dropped_trigger_minutes"], 30)

    def test_bad_settings_are_unusable(self):
        for bad in [{"stale_hours": 1}, {"triage_window_days": 0}, {"dropped_trigger_minutes": True}]:
            with self.subTest(bad), self.assertRaises(sweep.ConfigError):
                sweep.load_config(self.write({"projects": [], "sweep": bad}))

    def test_cli_names_an_unknown_project(self):
        path = self.write({"projects": [JIRA]})
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = sweep.main(["plan", "--project", "NOPE-", "--config", str(path)], linear=FakeLinear())
        self.assertEqual(code, 2)
        self.assertIn("NOPE-", err.getvalue())


if __name__ == "__main__":
    unittest.main()
