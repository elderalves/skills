"""Run with: python -m unittest discover <this-dir>. No network: a fake runner and a fake Linear."""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import upstream


SITE = "x.atlassian.net"


def jira_entry(repo="C:/r", **file):
    return {"match": "RTP-", "repo": repo, "linear_project": "Explore Frontend",
            "upstream": {"type": "jira", "site": SITE, "file": {"project_key": "RTP", **file}}}


GITHUB = {"match": "github:acme/widgets#", "repo": "C:/w", "github_account": "me",
          "upstream": {"type": "github"}}


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
                     "attachments": {"nodes": [{"url": u, "title": u} for u in attachments]}}
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

    def test_jql_string_escapes_quotes_and_backslashes(self):
        self.assertEqual(upstream.jql_string('a "b" \\c'), '"a \\"b\\" \\\\c"')

    def test_search_words_drop_text_search_operators(self):
        self.assertEqual(upstream.search_words('Add aria-label to "icon" buttons (a11y)?'),
                         "Add aria label to icon buttons a11y")


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

    def test_create_is_unassigned_with_type_and_labels(self):
        runner = fake_runner({"acli jira auth status": (0, f"Site: {SITE}"),
                              "acli jira workitem create": (0, json.dumps({"key": "RTP-8", "id": "1"}))})
        up = upstream.Upstream(jira_entry(issue_type="Story", labels=["a11y", "ui"]), run=runner)
        self.assertEqual(up.create("Add labels", "body"), {"ref": "RTP-8", "url": f"https://{SITE}/browse/RTP-8"})
        args = runner.calls[-1][0]
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
            "acli jira workitem assign": (0, ""),
        }, log)
        linear = FakeLinear(log=log)
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        self.assertEqual(result, {"ref": "RTP-7", "url": f"https://{SITE}/browse/RTP-7",
                                  "reused": False, "already_linked": False})
        self.assertEqual([name for _, name in log], [
            "acli jira auth status", "comment", "acli jira workitem search", "acli jira workitem create",
            "link", "update", "acli jira workitem assign"])
        self.assertEqual(linear.posted, ["## Filing upstream\n\n- **Title:** Add aria label to icon buttons\n"
                                         f"- **Since:** {self.NOW}"])
        create = next(args for args, _ in runner.calls if args[3:4] == ["create"])
        self.assertNotIn("--assignee", create)
        [body] = runner.bodies
        self.assertTrue(body.endswith(upstream.CLOSING_LINE))
        self.assertNotIn("linear.app", body)
        self.assertNotIn("score", body)
        self.assertEqual(linear.linked, [("ALV-9", f"https://{SITE}/browse/RTP-7", "RTP-7")])
        self.assertEqual(linear.updated, [("ALV-9", "RTP-7: Add aria label to icon buttons", None)])

    def test_file_restart_reuses_ticket_found_by_intent_title(self):
        since = "2026-11-27T10:00:00+00:00"
        runner = fake_runner({
            "acli jira auth status": (0, f"Site: {SITE}"),
            "acli jira workitem search": hits(("RTP-7", "Old title", "2026-11-27T10:00:05.000+0000")),
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
        self.assertEqual(linear.posted, [])
        self.assertFalse(any(args[3:4] == ["create"] for args, _ in runner.calls))
        search = next(args for args, _ in runner.calls if args[3:4] == ["search"])
        self.assertIn('summary ~ "Old title" AND created >= "2026-11-26"', search[search.index("--jql") + 1])
        self.assertEqual(linear.updated, [("ALV-9", "RTP-7: Old title", None)])
        self.assertEqual(runner.calls[-1][0][3], "assign")

    def test_already_linked_does_nothing_else(self):
        runner = fake_runner({})
        linear = FakeLinear(attachments=["https://github.com/o/r/pull/3", f"https://{SITE}/browse/RTP-4"])
        result = upstream.file_discovered(linear, upstream.Upstream(jira_entry(), run=runner), "ALV-9", self.NOW)
        self.assertEqual(result, {"ref": "RTP-4", "url": f"https://{SITE}/browse/RTP-4",
                                  "reused": False, "already_linked": True})
        self.assertEqual(runner.calls, [])
        self.assertEqual((linear.posted, linear.linked, linear.updated), ([], [], []))

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

    def test_find_filed_and_assign_and_search(self):
        runner = self.runner(**{
            "gh issue list --repo acme/widgets --author": (0, json.dumps([
                {"number": 3, "title": "Add labels", "url": "u3", "createdAt": "2026-11-27T09:00:00Z"},
                {"number": 4, "title": "Add labels!", "url": "u4", "createdAt": "2026-11-27T13:00:00Z"},
                {"number": 5, "title": "Add labels", "url": "u5", "createdAt": "2026-11-27T13:00:00Z"}])),
            "gh issue list --repo acme/widgets --state open": (0, json.dumps([
                {"number": 9, "title": "Labels", "url": "u9"}])),
            "gh issue edit": (0, ""),
        })
        up = upstream.Upstream(GITHUB, run=runner)
        self.assertEqual(up.find_filed("Add labels", "2026-11-27T12:00:00Z"), {"ref": "github:acme/widgets#5", "url": "u5"})
        self.assertIn("in:title Add labels", runner.calls[-1][0])
        self.assertEqual(up.search_open("labels"), [{"ref": "github:acme/widgets#9", "title": "Labels", "url": "u9"}])
        up.assign_owner("github:acme/widgets#5")
        self.assertEqual(runner.calls[-1][0], ["gh", "issue", "edit", "5", "--repo", "acme/widgets",
                                               "--add-assignee", "@me"])
        self.assertEqual(sum(1 for args, _ in runner.calls if args[:3] == ["gh", "auth", "token"]), 1)

    def test_linked_github_issue_is_recognised(self):
        linear = FakeLinear(attachments=["https://github.com/acme/widgets/issues/12"])
        result = upstream.file_discovered(linear, upstream.Upstream(GITHUB, run=fake_runner({})), "ALV-9",
                                          "2026-11-27T12:00:00Z")
        self.assertEqual(result["ref"], "github:acme/widgets#12")
        self.assertTrue(result["already_linked"])


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

    def test_cli_unknown_project_exits_2(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(upstream.main(["search", "--linear-project", "Nope", "--text", "x",
                                            "--config", str(self.config)], linear=FakeLinear(),
                                           run=fake_runner({})), 2)


if __name__ == "__main__":
    unittest.main()
