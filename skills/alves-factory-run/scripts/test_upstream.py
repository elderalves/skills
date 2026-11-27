"""Run with: python -m unittest discover <this-dir>. No network: a fake runner and a fake Linear."""

import io
import json
import tempfile
import unittest
from datetime import timedelta
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import upstream


SITE = "x.atlassian.net"


def jira_entry(repo="C:/r", **file):
    return {"match": "RTP-", "repo": repo, "linear_project": "Explore Frontend",
            "upstream": {"type": "jira", "site": SITE, "file": {"project_key": "RTP", **file}}}


GITHUB = {"match": "github:acme/widgets#", "repo": "C:/w", "github_account": "me",
          "upstream": {"type": "github", "file": {}}}


def fake_runner(responses, log=None):
    """Answers by the longest matching argv prefix; records (argv, env) and, on create, the body file."""
    log = [] if log is None else log
    calls, bodies = [], []

    def runner(args, env=None, cwd=None):
        calls.append((args, env))
        line = " ".join(args)
        for flag in ("--description-file", "--body-file"):
            if flag in args:
                bodies.append(Path(args[args.index(flag) + 1]).read_text(encoding="utf-8"))
        prefix = max((p for p in responses if line.startswith(p)), key=len, default=None)
        if prefix is None:
            return 1, f"unexpected: {args}"
        log.append(("run", " ".join(args[:4])))
        answer = responses[prefix]
        return answer.pop(0) if isinstance(answer, list) else answer

    runner.calls, runner.bodies, runner.log = calls, bodies, log
    return runner


def hits(*items):
    return 0, json.dumps([{"key": k, "fields": {"summary": s, "created": c}} for k, s, c in items])


class FakeLinear:
    def __init__(self, title="Add aria label to icon buttons", description="## Problem\nx\n\n## Factory notes\nscore 80",
                 attachments=(), comments=(), log=None):
        self.data = {"id": "u1", "identifier": "ALV-9", "title": title, "description": description,
                     "url": "https://linear.app/alves/issue/ALV-9", "project": {"name": "Explore Frontend"},
                     "attachments": {"nodes": [{"url": a, "title": a} if isinstance(a, str)
                                               else {"url": a[0], "title": a[1]} for a in attachments]}}
        self.stored = list(comments)
        self.log = [] if log is None else log
        self.posted, self.linked, self.updated = [], [], []

    def issue(self, ref):
        return self.data

    def comments(self, ref, since=None):
        return list(self.stored)

    def comment(self, ref, body):
        self.log.append(("linear", "comment"))
        self.posted.append(body)
        return {"id": "c1"}

    def link(self, ref, url, title):
        self.log.append(("linear", "link"))
        self.linked.append((ref, url, title))
        return self.data

    def update(self, ref, title=None, description=None):
        self.log.append(("linear", "update"))
        self.updated.append((ref, title, description))
        return self.data


def intent(title, since):
    return {"created_at": since, "from_factory": True,
            "body": f"[alves-factory]\n\n## Filing upstream\n\n- **Title:** {title}\n- **Since:** {since}"}


def filed(ref, at="2026-11-27T10:01:00+00:00"):
    return {"created_at": at, "from_factory": True,
            "body": f"[alves-factory]\n\n## Filed upstream\n\n- **Ref:** `{ref}`"}


class Text(unittest.TestCase):
    def test_public_part_cuts_at_factory_notes(self):
        self.assertEqual(upstream.public_part("## Problem\nx\n\n## Factory notes\nscore 80"),
                         "## Problem\nx\n\n_Found by automated analysis._")

    def test_public_part_without_heading_files_whole_description(self):
        text = "## Problem\nThe buttons have no label.\n\n## Acceptance criteria\n- a label\n"
        self.assertEqual(upstream.public_part(text),
                         "## Problem\nThe buttons have no label.\n\n## Acceptance criteria\n- a label"
                         "\n\n_Found by automated analysis._")

    def test_public_part_keeps_a_lookalike_heading_and_adds_the_line_once(self):
        text = "## Factory notes are out of scope\nx\n\n_Found by automated analysis._\r\n## Factory notes\r\nscore"
        self.assertEqual(upstream.public_part(text),
                         "## Factory notes are out of scope\nx\n\n_Found by automated analysis._")
        self.assertEqual(upstream.public_part(None), "_Found by automated analysis._")

    def test_jira_text_renders_the_public_part_as_plain_text(self):
        text = ("## Problem\nThe `IconButton` has no label.\n\n## Acceptance criteria\n\n- `aria-label` set\n"
                "- tests pass\n\n## Factory notes\nscore 80")
        self.assertEqual(upstream.jira_text(text),
                         "Problem\n\nThe IconButton has no label.\n\nAcceptance criteria\n\n- aria-label set\n"
                         "- tests pass\n\nFound by automated analysis.")
        self.assertEqual(upstream.jira_text(None), "Found by automated analysis.")

    def test_jql_string_escapes_quotes_and_backslashes(self):
        self.assertEqual(upstream.jql_string('a "b" \\c'), '"a \\"b\\" \\\\c"')

    def test_search_words_drop_text_search_operators(self):
        self.assertEqual(upstream.search_words('Add aria-label to "icon" buttons (a11y)?'),
                         "Add aria label to icon buttons a11y")

    def test_search_words_lowercase_boolean_words(self):
        self.assertEqual(upstream.search_words("Support NOT NULL columns"), "Support not NULL columns")
        self.assertEqual(upstream.search_words("Cats AND dogs OR birds ANDROID"), "Cats and dogs or birds ANDROID")

    def test_intent_title_round_trips_through_markdown(self):
        title = 'Remove `__init__` side effects in *core* "loader" \\ path _now_'
        body = upstream.intent_body(title, "2026-11-27T12:00:00+00:00")
        [line] = [l for l in body.splitlines() if l.startswith("- **Title:**")]
        # one code span holding a JSON string, so Markdown leaves __init__, * and _ alone
        self.assertRegex(line, r'^- \*\*Title:\*\* `"[^`]*"`$')
        comment = {"created_at": "x", "from_factory": True, "body": f"[alves-factory]\n\n{body}"}
        self.assertEqual(upstream.filing_intent([comment]), (title, "2026-11-27T12:00:00+00:00"))

    def test_intent_in_the_old_plain_form_still_reads(self):
        self.assertEqual(upstream.filing_intent([intent("Plain title", "2026-11-27T12:00:00Z")]),
                         ("Plain title", "2026-11-27T12:00:00Z"))


class Jira(unittest.TestCase):
    def test_find_filed_ignores_fuzzy_and_earlier_matches(self):
        title = 'Add "aria" label to icon buttons'
        runner = fake_runner({
            "acli jira auth status": (0, f"  Site: {SITE}\n"),
            "acli jira workitem search": hits(
                ("RTP-5", 'Add "aria" labels to icon buttons', "2026-11-27T16:00:00.000+0000"),
                ("RTP-6", title, "2026-11-27T14:30:00.000+0000"),
                ("RTP-7", title, "2026-11-27T12:30:00.000-0300"),
            ),
        })
        found = upstream.Upstream(jira_entry(), run=runner).find_filed(title, "2026-11-27T12:00:00-03:00")
        self.assertEqual(found, {"ref": "RTP-7", "url": f"https://{SITE}/browse/RTP-7"})
        args = runner.calls[-1][0]
        jql = args[args.index("--jql") + 1]
        self.assertEqual(jql, 'project = RTP AND reporter = currentUser() '
                              'AND summary ~ "Add aria label to icon buttons" AND created >= "2026-11-26"')
        self.assertEqual(args[args.index("--fields") + 1], "key,summary,created")

    def find(self, since, *items, title="Add labels"):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem search": hits(*items)})
        return upstream.Upstream(jira_entry(), run=runner).find_filed(title, since)

    def test_find_filed_compares_created_in_utc(self):
        # 12:10 UTC is 14:50 before Since (15:00 UTC); compared without offsets it would look later.
        self.assertIsNone(self.find("2026-11-27T12:00:00-03:00", ("RTP-1", "Add labels", "2026-11-27T12:10:00.000+0000")))

    def test_find_filed_needs_the_exact_title(self):
        self.assertIsNone(self.find("2026-11-27T12:00:00Z", ("RTP-1", "Add labels!", "2026-11-27T13:00:00.000+0000")))

    def test_find_filed_allows_ten_minutes_of_clock_skew(self):
        self.assertEqual(upstream.CLOCK_SKEW, timedelta(minutes=10))
        since = "2026-11-27T12:00:00Z"
        self.assertEqual(self.find(since, ("RTP-1", "Add labels", "2026-11-27T11:52:00.000+0000"))["ref"], "RTP-1")
        self.assertIsNone(self.find(since, ("RTP-1", "Add labels", "2026-11-27T11:49:00.000+0000")))

    def test_create_reports_a_default_assignee(self):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem create": (0, json.dumps({"key": "RTP-8"})),
                              "acli jira workitem view RTP-8": (0, json.dumps(
                                  {"key": "RTP-8", "fields": {"assignee": {"displayName": "Pat"}}}))})
        self.assertEqual(upstream.Upstream(jira_entry(), run=runner).create("t", "b"),
                         {"ref": "RTP-8", "url": f"https://{SITE}/browse/RTP-8", "default_assignee": "Pat"})

    def test_create_is_unassigned_with_type_and_labels(self):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem create": (0, json.dumps({"key": "RTP-8", "id": "1"})),
                              "acli jira workitem view RTP-8": (0, json.dumps({"key": "RTP-8",
                                                                               "fields": {"assignee": None}}))})
        up = upstream.Upstream(jira_entry(issue_type="Story", labels=["a11y", "ui"]), run=runner)
        self.assertEqual(up.create("Add labels", "body"), {"ref": "RTP-8", "url": f"https://{SITE}/browse/RTP-8"})
        args = next(a for a, _ in runner.calls if a[3:4] == ["create"])
        self.assertEqual(args[:4], ["acli", "jira", "workitem", "create"])
        for flag, value in (("--project", "RTP"), ("--type", "Story"), ("--summary", "Add labels"),
                            ("--label", "a11y,ui")):
            self.assertEqual(args[args.index(flag) + 1], value)
        self.assertNotIn("--assignee", args)
        self.assertEqual(runner.bodies, ["body"])
        self.assertFalse(Path(args[args.index("--description-file") + 1]).exists())

    def test_assign_owner_confirms_without_prompting(self):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"), "acli jira workitem assign": (0, "")})
        upstream.Upstream(jira_entry(), run=runner).assign_owner("RTP-8")
        self.assertEqual(runner.calls[-1][0], ["acli", "jira", "workitem", "assign", "--key", "RTP-8",
                                               "--assignee", "@me", "--yes"])

    def test_jira_site_mismatch_stops_naming_both_sites(self):
        runner = fake_runner({"acli jira auth status": (0, "Site: other.atlassian.net")})
        linear = FakeLinear()
        with self.assertRaisesRegex(upstream.UpstreamError, f"other.atlassian.net.*{SITE}"):
            upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9",
                                     "2026-11-27T12:00:00+00:00")
        self.assertEqual(linear.posted, [])
        self.assertEqual([c[0][:3] for c in runner.calls], [["acli", "jira", "auth"]])

    def test_a_failing_command_names_its_output(self):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem create": (1, "unauthorized")})
        with self.assertRaisesRegex(upstream.UpstreamError, "unauthorized"):
            upstream.Upstream(jira_entry(), run=runner).create("t", "b")

    def test_without_upstream_file_search_works_but_filing_is_refused(self):
        entry = jira_entry()
        del entry["upstream"]["file"]
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem search": hits(("RTP-3", "Labels", "2026-01-01"))})
        up = upstream.Upstream(entry, run=runner)
        self.assertEqual([t["ref"] for t in up.search_open("labels")], ["RTP-3"])
        calls = len(runner.calls)
        with self.assertRaisesRegex(upstream.ConfigError, "upstream.file"):
            up.create("t", "b")
        linear = FakeLinear()
        with self.assertRaisesRegex(upstream.ConfigError, "upstream.file"):
            upstream.file_discovered(linear, up, "ALV-9", "2026-11-27T12:00:00+00:00")
        self.assertEqual(len(runner.calls), calls)
        self.assertEqual((linear.posted, linear.updated, linear.linked), ([], [], []))

    def test_other_tracker_types_are_refused(self):
        for entry in ({"match": "linear-project:X", "upstream": {"type": "linear"}}, {"match": "X-"}):
            with self.assertRaises(upstream.UpstreamError):
                upstream.Upstream(entry, run=fake_runner({}))


class FileDiscovered(unittest.TestCase):
    NOW = "2026-11-27T12:00:00+00:00"

    def test_file_posts_intent_then_creates_unassigned_then_links_then_assigns(self):
        log = []
        runner = fake_runner({
            "acli jira auth status": (0, f"Site: {SITE}"),
            "acli jira workitem search": (0, "[]"),
            "acli jira workitem create": (0, json.dumps({"key": "RTP-7"})),
            "acli jira workitem view RTP-7": (0, json.dumps({"key": "RTP-7", "fields": {"assignee": None}})),
            "acli jira workitem assign": (0, ""),
        }, log)
        linear = FakeLinear(log=log)
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        self.assertEqual(result, {"ref": "RTP-7", "url": f"https://{SITE}/browse/RTP-7",
                                  "reused": False, "already_linked": False, "assigned": True, "finished": True})
        self.assertEqual([name for _, name in log], [
            "acli jira auth status", "comment", "acli jira workitem search", "acli jira workitem create",
            "acli jira workitem view", "update", "link", "acli jira workitem assign", "comment"])
        self.assertEqual(linear.posted, ['## Filing upstream\n\n- **Title:** `"Add aria label to icon buttons"`\n'
                                         f"- **Since:** {self.NOW}",
                                         "## Filed upstream\n\n- **Ref:** `RTP-7`"])
        create = next(args for args, _ in runner.calls if args[3:4] == ["create"])
        self.assertNotIn("--assignee", create)
        [body] = runner.bodies
        self.assertEqual(body, "Problem\n\nx\n\nFound by automated analysis.")
        self.assertNotIn("linear.app", body)
        self.assertNotIn("score", body)
        self.assertEqual(linear.linked, [("ALV-9", f"https://{SITE}/browse/RTP-7", "RTP-7")])
        self.assertEqual(linear.updated, [("ALV-9", "RTP-7: Add aria label to icon buttons", None)])

    def test_file_surfaces_the_jira_default_assignee(self):
        runner = fake_runner({
            "acli jira auth status": (0, f"Site: {SITE}"),
            "acli jira workitem search": (0, "[]"),
            "acli jira workitem create": (0, json.dumps({"key": "RTP-7"})),
            "acli jira workitem view RTP-7": (0, json.dumps({"key": "RTP-7",
                                                             "fields": {"assignee": {"displayName": "Pat"}}})),
            "acli jira workitem assign": (0, ""),
        })
        linear = FakeLinear()
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        self.assertEqual(result["default_assignee"], "Pat")
        self.assertTrue(result["assigned"])
        self.assertEqual(linear.posted[-1], "## Filed upstream\n\n- **Ref:** `RTP-7`\n- **Default assignee:** Pat")

    def test_file_restart_reuses_ticket_found_by_intent_title(self):
        since = "2026-11-27T10:00:00+00:00"
        runner = fake_runner({
            "acli jira auth status": (0, f"Site: {SITE}"),
            "acli jira workitem search": hits(("RTP-7", "Old title", "2026-11-27T10:00:05.000+0000")),
            "acli jira workitem view RTP-7": (0, json.dumps({"key": "RTP-7", "fields": {"assignee": None}})),
            "acli jira workitem assign": (0, ""),
        })
        linear = FakeLinear(title="New title", comments=[
            intent("Older attempt", "2026-11-26T09:00:00+00:00"),
            {"created_at": since, "from_factory": False, "body": "## Filing upstream\n\n- **Title:** Owner's"},
            intent("Old title", since),
        ])
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        self.assertTrue(result["reused"])
        self.assertEqual(result["ref"], "RTP-7")
        self.assertEqual(linear.posted, ["## Filed upstream\n\n- **Ref:** `RTP-7`"])  # no second intent
        self.assertFalse(any(args[3:4] == ["create"] for args, _ in runner.calls))
        search = next(args for args, _ in runner.calls if args[3:4] == ["search"])
        self.assertIn('summary ~ "Old title" AND created >= "2026-11-26"', search[search.index("--jql") + 1])
        self.assertEqual(linear.updated, [("ALV-9", "RTP-7: Old title", None)])
        self.assertEqual([args[3] for args, _ in runner.calls[-2:]], ["view", "assign"])
        self.assertTrue(result["assigned"])

    def test_reused_ticket_someone_holds_is_not_reassigned(self):
        runner = fake_runner({
            "acli jira auth status": (0, f"Site: {SITE}"),
            "acli jira workitem search": hits(("RTP-7", "Old title", "2026-11-27T10:00:05.000+0000")),
            "acli jira workitem view RTP-7": (0, json.dumps(
                {"key": "RTP-7", "fields": {"assignee": {"displayName": "teammate", "accountId": "a1"}}})),
        })
        linear = FakeLinear(comments=[intent("Old title", "2026-11-27T10:00:00+00:00")])
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        self.assertFalse(result["assigned"])
        self.assertFalse(any(args[3:4] == ["assign"] for args, _ in runner.calls))
        self.assertEqual(linear.posted, ["## Filed upstream\n\n- **Ref:** `RTP-7`"])

    def linked(self, assignee, title="Add aria label to icon buttons", comments=None):
        log = []
        runner = fake_runner({
            "acli jira auth status": (0, f"Site: {SITE}"),
            "acli jira workitem view RTP-4": (0, json.dumps({"key": "RTP-4", "fields": {"assignee": assignee}})),
            "acli jira workitem assign": (0, ""),
        }, log)
        if comments is None:
            comments = [intent("Add aria label to icon buttons", "2026-11-27T10:00:00+00:00")]
        linear = FakeLinear(title=title, log=log, comments=comments,
                            attachments=["https://github.com/o/r/pull/3", (f"https://{SITE}/browse/RTP-4", "RTP-4")])
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        return result, linear, runner, [name for _, name in log]

    def test_already_linked_and_filed_calls_nothing(self):
        for assignee in (None, {"displayName": "teammate"}):
            result, linear, runner, log = self.linked(
                assignee, comments=[intent("Add aria label to icon buttons", "2026-11-27T10:00:00+00:00"),
                                    filed("RTP-4")])
            self.assertEqual(result, {"ref": "RTP-4", "url": f"https://{SITE}/browse/RTP-4", "reused": False,
                                      "already_linked": True, "assigned": False, "finished": False})
            self.assertEqual(runner.calls, [])
            self.assertEqual((linear.posted, linear.linked, linear.updated), ([], [], []))

    def test_already_linked_with_intent_but_not_filed_finishes_and_records_it(self):
        result, linear, runner, log = self.linked(None)
        self.assertEqual(result, {"ref": "RTP-4", "url": f"https://{SITE}/browse/RTP-4", "reused": False,
                                  "already_linked": True, "assigned": True, "finished": True})
        self.assertEqual(linear.updated, [("ALV-9", "RTP-4: Add aria label to icon buttons", None)])
        self.assertEqual(linear.linked, [])
        self.assertEqual(linear.posted, ["## Filed upstream\n\n- **Ref:** `RTP-4`"])
        self.assertEqual(log, ["update", "acli jira auth status", "acli jira workitem view",
                               "acli jira workitem assign", "comment"])
        self.assertEqual(runner.calls[-1][0][:6], ["acli", "jira", "workitem", "assign", "--key", "RTP-4"])
        self.assertFalse(any(args[3:4] in (["search"], ["create"]) for args, _ in runner.calls))

    def test_already_linked_leaves_someone_elses_assignment(self):
        result, linear, runner, log = self.linked({"displayName": "teammate"}, title="RTP-4: Add labels")
        self.assertFalse(result["assigned"])
        self.assertTrue(result["already_linked"])
        self.assertEqual((linear.linked, linear.updated), ([], []))
        self.assertEqual(linear.posted, ["## Filed upstream\n\n- **Ref:** `RTP-4`"])
        self.assertNotIn("acli jira workitem assign", log)
        self.assertEqual(runner.calls[-1][0][:7], ["acli", "jira", "workitem", "view", "RTP-4",
                                                   "--fields", "assignee"])

    def test_an_owner_attached_link_is_context_and_filing_proceeds(self):
        runner = fake_runner({
            "acli jira auth status": (0, f"Site: {SITE}"),
            "acli jira workitem search": (0, "[]"),
            "acli jira workitem create": (0, json.dumps({"key": "RTP-7"})),
            "acli jira workitem view RTP-7": (0, json.dumps({"key": "RTP-7", "fields": {"assignee": None}})),
            "acli jira workitem assign": (0, ""),
        })
        linear = FakeLinear(attachments=[(f"https://{SITE}/browse/RTP-3", "RTP-3")])
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        self.assertEqual((result["ref"], result["already_linked"], result["reused"]), ("RTP-7", False, False))
        self.assertTrue(any(args[3:4] == ["create"] for args, _ in runner.calls))
        self.assertFalse(any("RTP-3" in " ".join(args) for args, _ in runner.calls))
        self.assertEqual(linear.linked, [("ALV-9", f"https://{SITE}/browse/RTP-7", "RTP-7")])

    def test_a_link_is_the_factorys_only_when_its_comments_say_so(self):
        up = upstream.Upstream(jira_entry(), run=fake_runner({}))
        rtp3 = {"url": f"https://{SITE}/browse/RTP-3", "title": "RTP-3"}
        rtp4 = {"url": f"https://{SITE}/browse/RTP-4", "title": f"https://{SITE}/browse/RTP-4"}
        since = "2026-11-27T10:00:00+00:00"
        self.assertIsNone(upstream.factory_link(up, [rtp3, rtp4], []))
        self.assertEqual(upstream.factory_link(up, [rtp3, rtp4], [filed("RTP-4")]), ("RTP-4", rtp4["url"], True))
        self.assertEqual(upstream.factory_link(up, [rtp4, rtp3], [intent("t", since)]),
                         ("RTP-3", rtp3["url"], False))
        owner = {"created_at": since, "from_factory": False, "body": "## Filed upstream\n\n- **Ref:** `RTP-3`"}
        self.assertIsNone(upstream.factory_link(up, [rtp3], [owner]))

    def test_an_intent_without_its_lines_stops(self):
        linear = FakeLinear(comments=[{"created_at": self.NOW, "from_factory": True,
                                       "body": "[alves-factory]\n\n## Filing upstream\n\n- **Title:** t"}])
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}")})
        with self.assertRaisesRegex(upstream.UpstreamError, "Since"):
            upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)


class GitHub(unittest.TestCase):
    def runner(self, **responses):
        return fake_runner({"gh auth token --hostname github.com --user me": (0, "tok\n"), **responses})

    def test_github_ref_and_url_from_create_stdout(self):
        runner = self.runner(**{"gh issue create": (0, "https://github.com/acme/widgets/issues/12\n")})
        up = upstream.Upstream(GITHUB, run=runner)
        self.assertEqual(up.create("Add labels", "body"),
                         {"ref": "github:acme/widgets#12", "url": "https://github.com/acme/widgets/issues/12"})
        args, env = runner.calls[-1]
        self.assertEqual(args[:5], ["gh", "issue", "create", "--repo", "acme/widgets"])
        self.assertNotIn("--assignee", args)
        self.assertEqual(env["GH_TOKEN"], "tok")

    def test_create_matches_the_printed_url_whatever_its_casing(self):
        runner = self.runner(**{"gh issue create": (0, "https://github.com/Acme/Widgets/issues/12\n")})
        self.assertEqual(upstream.Upstream(GITHUB, run=runner).create("t", "b"),
                         {"ref": "github:acme/widgets#12", "url": "https://github.com/Acme/Widgets/issues/12"})

    def test_find_filed_reads_the_rest_listing_not_the_search_index(self):
        listing = "repos/acme/widgets/issues?state=all&creator=me-login&sort=created&direction=desc&per_page=100"
        runner = self.runner(**{
            "gh api user": (0, "me-login\n"),
            f"gh api {listing}": (0, json.dumps([
                {"number": 6, "title": "Add labels", "html_url": "u6", "created_at": "2026-11-27T12:30:00Z",
                 "pull_request": {"url": "p6"}},
                {"number": 5, "title": "Add labels", "html_url": "u5", "created_at": "2026-11-27T13:00:00Z"},
                {"number": 4, "title": "Add labels!", "html_url": "u4", "created_at": "2026-11-27T12:20:00Z"},
                {"number": 3, "title": "Add labels", "html_url": "u3", "created_at": "2026-11-27T09:00:00Z"}])),
        })
        up = upstream.Upstream(GITHUB, run=runner)
        self.assertEqual(up.find_filed("Add labels", "2026-11-27T12:00:00Z"), {"ref": "github:acme/widgets#5", "url": "u5"})
        api = [(args, env) for args, env in runner.calls if args[:2] == ["gh", "api"]]
        self.assertEqual([args for args, _ in api], [["gh", "api", "user", "--jq", ".login"], ["gh", "api", listing]])
        self.assertTrue(all(env["GH_TOKEN"] == "tok" for _, env in api))
        self.assertFalse(any("--search" in args for args, _ in runner.calls))

    def test_assign_and_search(self):
        runner = self.runner(**{
            "gh issue list --repo acme/widgets --state open": (0, json.dumps([
                {"number": 9, "title": "Labels", "url": "u9"}])),
            "gh issue edit": (0, ""),
        })
        up = upstream.Upstream(GITHUB, run=runner)
        self.assertEqual(up.search_open("labels"), [{"ref": "github:acme/widgets#9", "title": "Labels", "url": "u9"}])
        up.assign_owner("github:acme/widgets#5")
        self.assertEqual(runner.calls[-1][0], ["gh", "issue", "edit", "5", "--repo", "acme/widgets",
                                               "--add-assignee", "@me"])
        self.assertEqual(sum(1 for args, _ in runner.calls if args[:3] == ["gh", "auth", "token"]), 1)

    def test_github_body_stays_markdown(self):
        runner = self.runner(**{
            "gh api user": (0, "me\n"),
            "gh api repos/acme/widgets/issues": (0, "[]"),
            "gh issue create": (0, "https://github.com/acme/widgets/issues/12\n"),
            "gh issue edit": (0, ""),
        })
        linear = FakeLinear(description="## Problem\nThe `x` fails.\n\n## Factory notes\nscore")
        result = upstream.file_discovered(linear, upstream.Upstream(GITHUB, run=runner), "ALV-9",
                                          "2026-11-27T12:00:00Z")
        self.assertEqual(result["ref"], "github:acme/widgets#12")
        self.assertEqual(runner.bodies, ["## Problem\nThe `x` fails.\n\n_Found by automated analysis._"])

    def test_linked_github_issue_is_recognised_and_its_assignees_read(self):
        linear = FakeLinear(title="github:acme/widgets#12: Add labels",
                            comments=[intent("Add labels", "2026-11-27T10:00:00Z")],
                            attachments=[("https://github.com/acme/widgets/issues/12", "github:acme/widgets#12")])
        runner = self.runner(**{"gh issue view 12 --repo acme/widgets --json assignees":
                                (0, json.dumps({"assignees": [{"login": "teammate"}]}))})
        result = upstream.file_discovered(linear, upstream.Upstream(GITHUB, run=runner), "ALV-9",
                                          "2026-11-27T12:00:00Z")
        self.assertEqual(result["ref"], "github:acme/widgets#12")
        self.assertTrue(result["already_linked"])
        self.assertFalse(result["assigned"])
        self.assertEqual(linear.updated, [])
        nobody = self.runner(**{"gh issue view": (0, json.dumps({"assignees": []}))})
        self.assertIsNone(upstream.Upstream(GITHUB, run=nobody).assignee("github:acme/widgets#12"))

    def test_linked_issue_in_another_casing_is_recognised(self):
        linear = FakeLinear(title="github:acme/widgets#12: Add labels",
                            comments=[intent("Add labels", "2026-11-27T10:00:00Z")],
                            attachments=[("https://github.com/Acme/Widgets/issues/12", "github:acme/widgets#12")])
        runner = self.runner(**{"gh issue view 12": (0, json.dumps({"assignees": [{"login": "me"}]}))})
        result = upstream.file_discovered(linear, upstream.Upstream(GITHUB, run=runner), "ALV-9",
                                          "2026-11-27T12:00:00Z")
        self.assertEqual((result["ref"], result["already_linked"]), ("github:acme/widgets#12", True))
        self.assertEqual(linear.updated, [])


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "explore").mkdir()
        self.config = root / "projects.json"
        data = json.dumps({"projects": [jira_entry(repo=str(root / "explore"))]})
        self.config.write_bytes(data.encode("utf-16"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_cli_search_prints_matches(self):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem search": hits(("RTP-3", "Missing aria label", "2026-01-01"))})
        out = io.StringIO()
        with redirect_stdout(out):
            code = upstream.main(["search", "--linear-project", "Explore Frontend", "--text", "aria label",
                                  "--config", str(self.config)], linear=FakeLinear(), run=runner)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out.getvalue()),
                         [{"ref": "RTP-3", "title": "Missing aria label", "url": f"https://{SITE}/browse/RTP-3"}])
        args = runner.calls[-1][0]
        self.assertEqual(args[args.index("--jql") + 1], 'project = RTP AND statusCategory != Done '
                                                         'AND text ~ "aria label" ORDER BY updated DESC')

    def test_cli_file_prints_the_result_and_exits_1_on_a_tool_error(self):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem search": (0, "[]"),
                              "acli jira workitem create": (1, "boom")})
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = upstream.main(["file", "ALV-9", "--linear-project", "Explore Frontend",
                                  "--config", str(self.config)], linear=FakeLinear(), run=runner)
        self.assertEqual(code, 1)
        self.assertIn("boom", err.getvalue())

    def test_cli_file_without_upstream_file_exits_2_and_search_still_runs(self):
        entry = jira_entry(repo=str(Path(self.tmp.name) / "explore"))
        del entry["upstream"]["file"]
        self.config.write_text(json.dumps({"projects": [entry]}), encoding="utf-8")
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem search": (0, "[]")})
        linear = FakeLinear()
        err = io.StringIO()
        with redirect_stderr(err), redirect_stdout(io.StringIO()):
            code = upstream.main(["file", "ALV-9", "--linear-project", "Explore Frontend",
                                  "--config", str(self.config)], linear=linear, run=runner)
        self.assertEqual(code, 2)
        self.assertIn("upstream.file", err.getvalue())
        self.assertEqual((runner.calls, linear.posted), ([], []))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(upstream.main(["search", "--linear-project", "Explore Frontend", "--text", "x",
                                            "--config", str(self.config)], linear=linear, run=runner), 0)

    def test_cli_unknown_project_exits_2(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(upstream.main(["search", "--linear-project", "Nope", "--text", "x",
                                            "--config", str(self.config)], linear=FakeLinear(),
                                           run=fake_runner({})), 2)


if __name__ == "__main__":
    unittest.main()
