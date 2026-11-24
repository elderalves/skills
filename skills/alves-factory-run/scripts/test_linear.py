"""Run with: python -m unittest discover <this-dir>. No network: a fake transport answers by operation."""

import unittest

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

    def test_cli_reports_errors_with_exit_1(self):
        def boom(query, variables):
            raise LinearError("LINEAR_API_KEY is not set")
        self.assertEqual(linear_mod.main(["get", "ALV-1"], linear=Linear(boom)), 1)


if __name__ == "__main__":
    unittest.main()
