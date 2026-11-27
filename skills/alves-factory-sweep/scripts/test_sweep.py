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
from test_github_account import PIN_KEY, PINNED, Repo, fake, which

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
LIMITS = dict(sweep.DEFAULT_LIMITS)
JIRA = {"match": "PCS-", "repo": "C:/r", "upstream": {"type": "jira", "site": "x.atlassian.net"},
        "linear_project": "AgileKit"}
NATIVE = {"match": "linear-project:Side", "repo": "C:/s", "upstream": {"type": "linear"}}


def comment(at, body, factory=True):
    return {"created_at": at, "from_factory": factory, "body": f"{MARKER}\n\n{body}" if factory else body}


def ticket(state, entered="2026-11-26T11:50:00Z", comments=(), ref="PCS-1", identifier="ALV-1", pr=None):
    url = f"https://x.atlassian.net/browse/{ref}"
    t = {"id": "i", "identifier": identifier, "url": "u", "state": state, "updated_at": entered,
         "entered_state_at": entered, "attachment_urls": [url], "attachments": [{"url": url, "title": ref}],
         "comments": list(comments), "ref": ref}
    if pr:
        t["pr"] = pr
    return t


def discovered(links, comments=(), identifier="ALV-7"):
    """A Discovered ticket linked to each (ref, title) on JIRA's site."""
    attachments = [{"url": f"https://x.atlassian.net/browse/{ref}", "title": title} for ref, title in links]
    return {"identifier": identifier, "labels": ["discovered"], "comments": list(comments),
            "attachments": attachments, "attachment_urls": [a["url"] for a in attachments]}


FILED_PCS_7 = comment("2026-11-26T10:00:00Z", "## Filed upstream\n\n- **Ref:** `PCS-7`")
FILING = comment("2026-11-26T09:00:00Z", '## Filing upstream\n\n- **Title:** `"Fix it"`\n- **Since:** 2026-11-26T09:00:00Z')


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

    def test_a_github_link_matches_whatever_its_casing_and_takes_the_matchs(self):
        entry = {"match": "github:acme/widgets#", "repo": "C:/g", "linear_project": "Widgets"}
        t = {"identifier": "ALV-3", "attachment_urls": ["https://github.com/Acme/Widgets/issues/12"]}
        self.assertEqual(sweep.ticket_ref(t, entry), "github:acme/widgets#12")
        self.assertIsNone(sweep.ticket_ref(t, {**entry, "match": "github:acme/gadgets#"}))

    def test_an_unlinked_discovered_ticket_is_its_own_ref(self):
        t = {"identifier": "ALV-5", "attachment_urls": ["https://figma.com/f"], "labels": ["Discovered"],
             "attachments": [{"url": "https://figma.com/f", "title": "Design"}], "comments": []}
        self.assertEqual(sweep.ticket_ref(t, JIRA), "ALV-5")

    def test_an_unlinked_ticket_without_the_label_is_not_the_entrys(self):
        t = {"identifier": "ALV-6", "attachment_urls": [], "labels": ["bug"]}
        self.assertIsNone(sweep.ticket_ref(t, JIRA))

    def test_a_discovered_ticket_with_only_an_owner_link_is_its_own_ref(self):
        # The owner attached a same-tracker ticket for context; the factory has filed nothing.
        self.assertEqual(sweep.ticket_ref(discovered([("PCS-3", "Related work")]), JIRA), "ALV-7")
        self.assertEqual(sweep.ticket_ref(discovered([("PCS-3", "PCS-3")]), JIRA), "ALV-7")

    def test_a_filed_discovered_ticket_takes_the_ref_its_filed_comment_names(self):
        links = [("PCS-3", "Related work"), ("PCS-7", "PCS-7")]
        for order in (links, links[::-1]):
            self.assertEqual(sweep.ticket_ref(discovered(order, [FILED_PCS_7]), JIRA), "PCS-7")

    def test_a_half_filed_discovered_ticket_takes_the_link_titled_with_its_ref(self):
        t = discovered([("PCS-3", "Related work"), ("PCS-7", "PCS-7")], [FILING])
        self.assertEqual(sweep.ticket_ref(t, JIRA), "PCS-7")

    def test_a_discovered_ticket_belongs_only_to_the_entry_owning_its_projects_discovered_tickets(self):
        t = discovered([])
        self.assertIsNone(sweep.ticket_ref(t, {**JIRA, "owns_discovered": False}))
        self.assertEqual(sweep.ticket_ref(t, {**JIRA, "owns_discovered": True}), "ALV-7")


class Discovered(unittest.TestCase):
    """A Discovered ticket in a non-Native entry, before a planning run linked it upstream."""

    GITHUB = {"match": "github:acme/widgets#", "repo": "C:/g", "upstream": {"type": "github"},
              "linear_project": "Widgets"}

    def sweep(self, *tickets):
        [project], notes = sweep.gather([self.GITHUB], "Alves", LIMITS, FakeLinear(tickets), fake_runner({}),
                                        Path(tempfile.mkdtemp()))
        self.assertEqual(notes, [])
        return sweep.decide([project], NOW, LIMITS)

    @staticmethod
    def unlinked(state, entered, labels=("discovered",), identifier="ALV-5"):
        t = ticket(state, entered=entered, identifier=identifier)
        del t["ref"]
        return {**t, "attachment_urls": [], "attachments": [], "labels": list(labels)}

    def test_a_dropped_ready_trigger_is_retriggered(self):
        [action] = self.sweep(self.unlinked("Ready", "2026-11-26T11:00:00Z"))["actions"]
        self.assertEqual((action["kind"], action["ticket"], action["ref"], action["to_status"]),
                         ("retrigger", "ALV-5", "ALV-5", "Ready"))

    def test_a_planning_run_that_died_before_filing_is_restarted(self):
        [action] = self.sweep(self.unlinked("Planning", "2026-11-26T08:00:00Z"))["actions"]
        self.assertEqual((action["kind"], action["ticket"], action["to_status"]), ("restart", "ALV-5", "Ready"))

    def test_an_unlinked_ticket_without_the_label_is_ignored(self):
        result = self.sweep(self.unlinked("Planning", "2026-11-26T08:00:00Z", labels=("bug",)),
                            self.unlinked("Ready", "2026-11-26T11:00:00Z", labels=(), identifier="ALV-6"))
        self.assertEqual((result["actions"], result["deferred"]), ([], []))


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

    def test_a_ticket_waiting_in_a_trigger_status_is_retriggered_not_started(self):
        for state in ("Ready", "Plan Approved"):
            with self.subTest(state):
                result = run(ticket(state, entered="2026-11-26T11:00:00Z"))
                [action] = result["actions"]
                self.assertEqual((action["kind"], action["via_status"], action["to_status"]),
                                 ("retrigger", "Backlog", state))
                self.assertTrue(action["comment"].startswith(sweep.RETRIGGERED))
                self.assertIsNone(result["start"])

    def test_a_trigger_that_drops_again_after_a_retrigger_is_blocked(self):
        again = comment("2026-11-26T11:00:00Z", sweep.retrigger_comment("Ready", sweep.timedelta(minutes=40)))
        [action] = run(ticket("Ready", entered="2026-11-26T11:00:00Z", comments=[again]))["actions"]
        self.assertEqual((action["kind"], action["to_status"]), ("block", "Blocked"))
        self.assertIn("trigger", action["comment"])

    def test_one_retrigger_per_pass_oldest_first_the_rest_deferred(self):
        result = run(ticket("Ready", entered="2026-11-26T10:00:00Z", identifier="ALV-2"),
                     ticket("Plan Approved", entered="2026-11-26T09:00:00Z", identifier="ALV-3"))
        self.assertEqual([(a["kind"], a["ticket"]) for a in result["actions"]], [("retrigger", "ALV-3")])
        self.assertEqual([(d["kind"], d["ticket"]) for d in result["deferred"]], [("retrigger", "ALV-2")])

    def test_one_start_per_pass_in_order(self):
        result = run(upstream=[{"ref": "PCS-9", "triage": None, "has_factory_ticket": False},
                               {"ref": "PCS-8", "triage": "work", "has_factory_ticket": False}])
        self.assertEqual(result["start"]["argument"], "PCS-8")
        self.assertEqual([d["argument"] for d in result["deferred"]], ["PCS-9"])
        self.assertNotIn("priority", result["start"])


class Upstream(unittest.TestCase):
    CASES = [
        ("work but no ticket", "work", False, ("start-triage", "alves-factory-triage")),
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
        self.listed = getattr(self, "listed", []) + [project]
        return [t for t in self.tickets if t["state"] in states and t.get("project", project) == project]

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

    def test_a_filed_discovered_ticket_in_review_finds_the_pr_of_the_factorys_link(self):
        t = {**ticket("In Review", identifier="ALV-7"), **discovered([("PCS-3", "Related work"), ("PCS-7", "PCS-7")],
                                                                      [FILED_PCS_7])}
        del t["ref"]
        runner = fake_runner({
            "git -C C:/r remote get-url origin": (0, "https://github.com/o/r.git"),
            "gh auth token": (0, "tok"),
            "git -C C:/r ls-remote": (0, ""),
            "gh pr list": (0, json.dumps([{"number": 4, "url": "u4", "state": "MERGED", "mergedAt": "t"}])),
            "acli jira auth status": (0, "Site: x.atlassian.net"),
            "acli jira workitem search": (0, "[]"),
        })
        [project], notes = sweep.gather([{**JIRA, "github_account": "me"}], "Alves", LIMITS, FakeLinear([t]), runner,
                                        Path(tempfile.mkdtemp()))
        self.assertEqual(notes, [])
        self.assertEqual(project["tickets"][0]["ref"], "PCS-7")
        pr_list = next(c for c in runner.calls if c[:3] == ["gh", "pr", "list"])
        self.assertEqual(pr_list[pr_list.index("--head") + 1], "factory/PCS-7")
        [action] = sweep.decide([project], NOW, LIMITS)["actions"]
        self.assertEqual((action["kind"], action["ticket"], action["ref"]), ("done", "ALV-7", "PCS-7"))

    def test_another_acli_site_skips_jira_with_a_note(self):
        runner = fake_runner({"acli jira auth status": (0, "Site: other.atlassian.net")})
        [project], notes = sweep.gather([JIRA], "Alves", LIMITS, FakeLinear(), runner, Path(tempfile.mkdtemp()))
        self.assertEqual(project["upstream"], [])
        self.assertIn("acli is signed in to other.atlassian.net", notes[0])


class SharedPrefix(unittest.TestCase):
    """One Jira prefix feeding two repos, each with its own Linear project."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        for name in ("empower", "explore"):
            (self.root / name).mkdir()
        self.empower = {"match": "RTP-", "repo": str(self.root / "empower"), "linear_project": "Empower Widgets",
                        "upstream": {"type": "jira", "site": "g.atlassian.net"}}
        self.explore = {**self.empower, "repo": str(self.root / "explore"), "linear_project": "Explore Frontend"}

    def test_select_takes_every_entry_of_the_match(self):
        notes = []
        entries = sweep.select({"projects": [self.empower, self.explore, JIRA]}, ["RTP-"], notes)
        self.assertEqual([e["linear_project"] for e in entries], ["Empower Widgets", "Explore Frontend"])
        self.assertEqual(notes, [])

    def test_select_skips_a_shared_entry_whose_repo_is_missing(self):
        notes = []
        gone = {**self.explore, "repo": str(self.root / "gone")}
        entries = sweep.select({"projects": [self.empower, gone]}, ["RTP-"], notes)
        self.assertEqual([e["linear_project"] for e in entries], ["Empower Widgets"])
        self.assertIn("Explore Frontend", notes[0])

    def test_jira_is_searched_once_per_prefix(self):
        explore_ticket = {**ticket("Ready", ref="RTP-2"), "project": "Explore Frontend"}
        del explore_ticket["ref"]
        explore_ticket["attachment_urls"] = ["https://g.atlassian.net/browse/RTP-2"]
        linear = FakeLinear([explore_ticket])
        runner = fake_runner({
            "acli jira auth status": (0, "Site: g.atlassian.net"),
            "acli jira workitem search": (0, json.dumps([{"key": "RTP-5"}])),
        })
        projects, notes = sweep.gather([self.empower, self.explore], "Alves", LIMITS, linear, runner, self.root)
        self.assertEqual(linear.listed, ["Empower Widgets", "Explore Frontend"])
        self.assertEqual([len(p["upstream"]) for p in projects], [1, 0])
        self.assertEqual([[t["ref"] for t in p["tickets"]] for p in projects], [[], ["RTP-2"]])
        self.assertEqual(sum(c[:4] == ["acli", "jira", "workitem", "search"] for c in runner.calls), 1)


class SharedLinearProject(unittest.TestCase):
    """Two Jira prefixes filing into one Linear project; the entry with `discovery` owns its Discovered tickets."""

    def test_an_unlinked_discovered_ticket_is_planned_only_under_the_discovery_entry(self):
        root = Path(tempfile.mkdtemp())
        site = {"type": "jira", "site": "x.atlassian.net"}
        dxpx = {"match": "DXPX-", "repo": str(root), "linear_project": "Metronome", "upstream": site}
        ai = {**dxpx, "match": "AI-", "discovery": {}}
        config = {"projects": [dxpx, ai]}
        notes = []
        entries = sweep.select(config, ["DXPX-"], notes) + sweep.select(config, ["AI-"], notes)
        self.assertEqual([e["owns_discovered"] for e in entries], [False, True])
        t = ticket("Ready", entered="2026-11-26T11:00:00Z", identifier="ALV-5")
        del t["ref"]
        t = {**t, "attachment_urls": [], "attachments": [], "labels": ["discovered"]}
        runner = fake_runner({"acli jira auth status": (0, "Site: other.atlassian.net")})
        projects, _ = sweep.gather(entries, "Alves", LIMITS, FakeLinear([t]), runner, root)
        self.assertEqual([[t["ref"] for t in p["tickets"]] for p in projects], [[], ["ALV-5"]])
        [action] = sweep.decide(projects, NOW, LIMITS)["actions"]
        self.assertEqual((action["kind"], action["ticket"], action["project"]), ("retrigger", "ALV-5", "AI-"))


class Apply(unittest.TestCase):
    def test_a_retrigger_bounces_through_its_via_status(self):
        plan = run(ticket("Plan Approved", entered="2026-11-26T11:00:00Z", identifier="ALV-4"))
        linear = FakeLinear(states={"ALV-4": "Plan Approved"})
        sweep.apply(plan, linear)
        self.assertEqual(linear.writes, [("comment", "ALV-4"), ("state", "ALV-4", "Backlog"),
                                         ("state", "ALV-4", "Plan Approved")])

    def test_writes_only_where_the_status_is_unchanged(self):
        plan = run(ticket("Planning", entered="2026-11-26T08:00:00Z", identifier="ALV-1"),
                   ticket("In Progress", entered="2026-11-26T01:00:00Z", identifier="ALV-2"))
        linear = FakeLinear(states={"ALV-1": "Planning", "ALV-2": "Blocked"})
        result = sweep.apply(plan, linear)
        self.assertEqual(linear.writes, [("comment", "ALV-1"), ("state", "ALV-1", "Ready")])
        self.assertEqual([r["applied"] for r in result], [True, False])
        self.assertEqual(result[1]["why"], "status is now Blocked")


class Pins(unittest.TestCase):
    """Each entry's repo pins its GitHub account, so T3's plain worktree fetch can authenticate."""

    def pins(self, repo, *entries):
        return sweep.gather_pins(list(entries) or [{**JIRA, "github_account": "work-user"}], repo, which)

    def test_a_repo_with_no_pin_gets_a_pin_action(self):
        [action], notes = self.pins(Repo())
        self.assertEqual(notes, [])
        self.assertEqual({k: action[k] for k in ("kind", "repo", "account", "from_status", "to_status")},
                         {"kind": "pin_account", "repo": "C:/r", "account": "work-user",
                          "from_status": None, "to_status": "work-user"})
        plan = sweep.decide([], NOW, LIMITS, [action])
        self.assertEqual([a["kind"] for a in plan["actions"]], ["pin_account"])

    def test_a_correct_pin_needs_nothing(self):
        self.assertEqual(self.pins(Repo(PINNED)), ([], []))

    def test_a_pin_for_another_account_is_replaced(self):
        [action], _ = self.pins(Repo(PINNED), {**JIRA, "github_account": "personal-user"})
        self.assertEqual((action["from_status"], action["to_status"]), ("work-user", "personal-user"))

    def test_entries_sharing_a_repo_pin_it_once(self):
        entry = {**JIRA, "github_account": "work-user"}
        pins, _ = self.pins(Repo(), entry, {**entry, "match": "AI-", "linear_project": "Other"})
        self.assertEqual(len(pins), 1)

    def test_entries_sharing_a_repo_with_different_accounts_are_noted_not_pinned(self):
        entry = {**JIRA, "github_account": "work-user"}
        pins, [note] = self.pins(Repo(), entry, {**entry, "match": "AI-", "github_account": "personal-user"})
        self.assertEqual(pins, [])
        self.assertIn("different github_accounts", note)

    def test_ssh_and_the_owners_own_helper_are_noted_not_pinned(self):
        for repo, said in ((Repo(remote="git@github.com:me/repo.git"), "SSH"),
                           (Repo({"credential.helper": ["manager"]}), "did not write")):
            pins, [note] = self.pins(repo)
            self.assertEqual(pins, [])
            self.assertIn(said, note)

    def test_an_entry_with_no_account_pins_the_detected_one_and_says_so(self):
        repo, accounts = Repo(), fake({"personal-user"})

        def runner(args, env=None, cwd=None):
            return (accounts if args[:1] == ["gh"] or (env and "GH_TOKEN" in env) else repo)(args, env, cwd)
        [action], [note] = sweep.gather_pins([JIRA], runner, which)
        self.assertEqual(action["account"], "personal-user")
        self.assertIn("detected personal-user, pin it there", note)

    def test_apply_writes_the_pin_and_nothing_on_linear(self):
        repo, linear = Repo(), FakeLinear()
        pins, _ = self.pins(repo)
        [result] = sweep.apply({"actions": pins}, linear, repo, which)
        self.assertEqual(result, {"kind": "pin_account", "ticket": None, "repo": "C:/r", "from_status": None,
                                  "to_status": "work-user", "applied": True})
        self.assertEqual(repo.config[PIN_KEY], ["work-user"])
        self.assertEqual(linear.writes, [])

    def test_apply_reports_a_pin_that_cannot_reach_the_repo(self):
        repo = Repo(reachable=False)
        pins, _ = self.pins(repo)
        [result] = sweep.apply({"actions": pins}, FakeLinear(), repo, which)
        self.assertFalse(result["applied"])
        self.assertIn("still fails", result["why"])


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

    def test_cli_stops_when_the_repo_is_not_on_this_machine(self):
        path = self.write({"projects": [{**JIRA, "repo": "~/no-such-factory-checkout"}]})
        err = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(err):
            code = sweep.main(["plan", "--project", "PCS-", "--config", str(path)], linear=FakeLinear())
        self.assertEqual(code, 2)
        self.assertIn("not a directory on this machine", err.getvalue())


if __name__ == "__main__":
    unittest.main()
