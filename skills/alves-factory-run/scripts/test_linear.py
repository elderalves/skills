"""Run with: python -m unittest discover <this-dir>. No network: a fake transport answers by operation."""

import unittest
from pathlib import Path

import linear as linear_mod
from linear import MARKER, Linear, LinearError


def issue(id="i1", identifier="ALV-1", labels=(), docs=(), created="2026-01-01T00:00:00Z"):
    return {
        "id": id, "identifier": identifier, "title": "t", "url": f"https://linear.app/x/{identifier}",
        "createdAt": created, "state": {"id": "s0", "name": "Ready", "type": "unstarted"},
        "team": {"id": "team1", "name": "Alves", "key": "ALV"},
        "labels": {"nodes": [{"id": f"l-{n}", "name": n} for n in labels]},
        "attachments": {"nodes": []},
        "documents": {"nodes": [{"id": f"d-{t}", "title": t, "url": "u", "updatedAt": "x"} for t in docs]},
    }


class Fake:
    """Records every call; answers each by the first matching keyword."""

    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def __call__(self, query, variables):
        self.calls.append((query, variables))
        for keyword, answer in self.answers.items():
            if keyword in query:
                return answer(variables) if callable(answer) else answer
        raise AssertionError(f"unexpected query: {query[:80]}")

    def called(self, keyword):
        return [v for q, v in self.calls if keyword in q]


class LinearTests(unittest.TestCase):
    def test_find_by_url_dedupes_and_sorts_oldest_first(self):
        newer = {"id": "b", "identifier": "ALV-2", "url": "u", "createdAt": "2026-02-01", "state": {"name": "Planning"}}
        older = {"id": "a", "identifier": "ALV-1", "url": "u", "createdAt": "2026-01-01", "state": {"name": "Ready"}}
        fake = Fake({"attachmentsForURL": {"attachmentsForURL": {"nodes": [
            {"issue": newer}, {"issue": older}, {"issue": newer}]}}})
        self.assertEqual([i["identifier"] for i in Linear(fake).find_by_url("u")], ["ALV-1", "ALV-2"])

    def create_fake(self, projects):
        return Fake({
            "teams(": {"teams": {"nodes": [{"id": "team1", "name": "Alves"}]}},
            "projects(": {"projects": {"nodes": projects}},
            "issueCreate": {"issueCreate": {"success": True, "issue": {"id": "i1", "identifier": "ALV-1"}}},
            "attachmentLinkURL": {"attachmentLinkURL": {"success": True}},
            "issue(id": {"issue": issue()},
        })

    def test_create_files_the_ticket_in_its_project(self):
        fake = self.create_fake([{"id": "p1", "name": "Metronome"}])
        Linear(fake).create("Alves", "t", "https://x/browse/DXPX-1", project="Metronome")
        self.assertEqual(fake.called("issueCreate")[0]["input"]["projectId"], "p1")

    def test_create_with_unknown_project_writes_nothing(self):
        fake = self.create_fake([])
        with self.assertRaises(LinearError):
            Linear(fake).create("Alves", "t", "https://x/browse/DXPX-1", project="Nope")
        self.assertEqual(fake.called("issueCreate"), [])

    def test_set_label_replaces_same_prefix_only(self):
        fake = Fake({
            "issueLabels(": {"issueLabels": {"nodes": [{"id": "new", "name": "gate:implement", "team": None}]}},
            "issueUpdate": {"issueUpdate": {"success": True}},
            "issue(id": {"issue": issue(labels=["gate:revise", "bug"])},
        })
        Linear(fake).set_label("ALV-1", "gate:implement")
        update = fake.called("issueUpdate")[0]
        self.assertEqual((update["add"], update["remove"]), (["new"], ["l-gate:revise"]))

    def test_set_label_creates_missing_team_label(self):
        fake = Fake({
            "issueLabels(": {"issueLabels": {"nodes": [{"id": "other", "name": "gate:x", "team": {"id": "team9"}}]}},
            "issueLabelCreate": {"issueLabelCreate": {"issueLabel": {"id": "created"}}},
            "issueUpdate": {"issueUpdate": {"success": True}},
            "issue(id": {"issue": issue()},
        })
        Linear(fake).set_label("ALV-1", "gate:x")
        self.assertEqual(fake.called("issueLabelCreate")[0]["input"], {"name": "gate:x", "teamId": "team1"})

    def test_put_doc_updates_existing_title_else_creates(self):
        doc = {"document": {"id": "d", "title": "Plan", "url": "u"}}
        fake = Fake({"documentUpdate": {"documentUpdate": doc}, "documentCreate": {"documentCreate": doc},
                     "issue(id": {"issue": issue(docs=["Plan"])}})
        Linear(fake).put_doc("ALV-1", "Plan", "v2")
        self.assertEqual(len(fake.called("documentUpdate")), 1)
        self.assertEqual(len(fake.called("documentCreate")), 0)
        fake.answers["issue(id"] = {"issue": issue(docs=["Other"])}
        Linear(fake).put_doc("ALV-1", "Plan", "v1")
        self.assertEqual(fake.called("documentCreate")[0]["input"]["issueId"], "i1")

    def test_get_doc_by_title(self):
        fake = Fake({"document(id": {"document": {"id": "d-Plan", "title": "Plan", "content": "# Plan"}},
                     "issue(id": {"issue": issue(docs=["Plan"])}})
        self.assertEqual(Linear(fake).get_doc("ALV-1", "Plan")["content"], "# Plan")
        with self.assertRaises(LinearError):
            Linear(fake).get_doc("ALV-1", "Missing")

    def test_comment_adds_marker_once(self):
        fake = Fake({"commentCreate": {"commentCreate": {"comment": {"id": "c"}}}, "issue(id": {"issue": issue()}})
        Linear(fake).comment("ALV-1", "hello")
        Linear(fake).comment("ALV-1", f"{MARKER}\n\nagain")
        bodies = [v["input"]["body"] for v in fake.called("commentCreate")]
        self.assertEqual(bodies, [f"{MARKER}\n\nhello", f"{MARKER}\n\nagain"])

    def test_comments_flags_factory_and_filters_since(self):
        nodes = [
            {"id": "1", "body": f"{MARKER}\nquestions", "createdAt": "2026-01-02", "user": {"name": "A"}},
            {"id": "2", "body": "my answer", "createdAt": "2026-01-03", "user": {"name": "A"}},
            {"id": "0", "body": "old", "createdAt": "2026-01-01", "user": {"name": "A"}},
        ]
        fake = Fake({"comments(": {"issue": {"comments": {"nodes": nodes}}}, "issue(id": {"issue": issue()}})
        result = Linear(fake).comments("ALV-1", since="2026-01-01")
        self.assertEqual([(c["id"], c["from_factory"]) for c in result], [("1", True), ("2", False)])

    def test_missing_state_is_an_error(self):
        fake = Fake({"workflowStates": {"workflowStates": {"nodes": []}}, "issue(id": {"issue": issue()}})
        with self.assertRaises(LinearError):
            Linear(fake).set_state("ALV-1", "Nope")

    def test_api_key_prefers_environment_then_env_file(self):
        import tempfile
        env_file = Path(tempfile.mkdtemp()) / ".env"
        env_file.write_text("OTHER=x\nexport LINEAR_ALVES_API_KEY='lin_api_file'\n", encoding="utf-8")
        self.assertEqual(linear_mod.api_key({"LINEAR_ALVES_API_KEY": "lin_api_env"}, env_file), "lin_api_env")
        self.assertEqual(linear_mod.api_key({}, env_file), "lin_api_file")
        self.assertEqual(linear_mod.api_key({"LINEAR_API_KEY": "generic"}, env_file), "lin_api_file")
        with self.assertRaises(LinearError):
            linear_mod.api_key({}, env_file.with_name("missing.env"))

    def test_list_issues_reports_when_each_entered_its_status(self):
        node = {
            "id": "i1", "identifier": "ALV-13", "url": "u", "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-03T00:00:00Z", "state": {"name": "In Review"},
            "attachments": {"nodes": [{"url": "https://x.atlassian.net/browse/PCS-1", "title": "PCS-1"}]},
            "history": {"nodes": [
                {"createdAt": "2026-01-02T00:00:00Z", "toState": {"name": "In Review"}},
                {"createdAt": "2026-01-01T12:00:00Z", "toState": {"name": "In Progress"}},
                {"createdAt": "2026-01-01T06:00:00Z", "toState": {"name": "In Review"}},
                {"createdAt": "2026-01-02T01:00:00Z", "toState": None},
            ]},
            "comments": {"nodes": [
                {"createdAt": "2026-01-02T00:00:00Z", "body": f"{MARKER}\n\nlater"},
                {"createdAt": "2026-01-01T00:00:00Z", "body": "owner"},
            ]},
        }
        fake = Fake({"teams(": {"teams": {"nodes": [{"id": "team1", "name": "Alves"}]}},
                     "issues(": {"issues": {"nodes": [node]}}})
        [found] = Linear(fake).list_issues("Alves", "AgileKit", ["In Review"])
        self.assertEqual(found["entered_state_at"], "2026-01-02T00:00:00Z")
        self.assertEqual(found["attachment_urls"], ["https://x.atlassian.net/browse/PCS-1"])
        self.assertEqual([c["from_factory"] for c in found["comments"]], [False, True])
        self.assertEqual(fake.called("issues(")[0]["states"], ["In Review"])

    def test_cli_reports_errors_with_exit_1(self):
        def boom(query, variables):
            raise LinearError("LINEAR_ALVES_API_KEY is not set")
        self.assertEqual(linear_mod.main(["get", "ALV-1"], linear=Linear(boom)), 1)


if __name__ == "__main__":
    unittest.main()
