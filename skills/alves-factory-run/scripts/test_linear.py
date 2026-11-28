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

    def labels_fake(self):
        fake = self.create_fake([{"id": "p1", "name": "Explore"}])
        fake.answers = {"issueLabels(": lambda v: {"issueLabels": {"nodes": [
            {"id": f"l-{v['name']}", "name": v["name"], "team": None}]}},
            "workflowStates": {"workflowStates": {"nodes": [{"id": "s-backlog", "name": "Backlog"}]}},
            **fake.answers}
        return fake

    def test_create_without_upstream_url_attaches_nothing(self):
        fake = self.labels_fake()
        Linear(fake).create("Alves", "Add labels", state="Backlog", project="Explore")
        self.assertEqual(fake.called("attachmentLinkURL"), [])
        self.assertEqual(len(fake.called("issueCreate")), 1)

    def test_create_sends_labels_and_priority(self):
        fake = self.labels_fake()
        Linear(fake).create("Alves", "Add labels", labels=("discovered", "quick-win"), priority=2)
        payload = fake.called("issueCreate")[0]["input"]
        self.assertEqual(payload["labelIds"], ["l-discovered", "l-quick-win"])
        self.assertEqual(payload["priority"], 2)

    def test_list_all_has_no_state_filter_and_keeps_canceled(self):
        node = {
            "id": "i1", "identifier": "ALV-20", "url": "u", "createdAt": "2026-01-01T00:00:00Z",
            "title": "Add labels", "description": "d", "priority": 3, "state": {"name": "Canceled"},
            "labels": {"nodes": [{"name": "discovered"}]},
            "attachments": {"nodes": []},
            "comments": {"nodes": [{"createdAt": "2026-01-02T00:00:00Z", "body": "not now",
                                    "user": {"name": "Owner"}}]},
        }
        fake = Fake({"teams(": {"teams": {"nodes": [{"id": "team1", "name": "Alves"}]}},
                     "issues(": {"issues": {"nodes": [node]}}})
        [found] = Linear(fake).list_all("Alves", "Explore")
        self.assertNotIn("state: { name", fake.calls[-1][0])
        self.assertEqual((found["state"], found["labels"]), ("Canceled", ["discovered"]))
        self.assertIs(found["comments"][0]["from_factory"], False)
        self.assertEqual(found["comments"][0]["author"], "Owner")

    def test_list_all_reads_every_page(self):
        def node(n, created):
            return {"id": f"i{n}", "identifier": f"ALV-{n}", "url": "u", "createdAt": created, "title": "t",
                    "description": None, "priority": 0, "state": {"name": "Done"}, "labels": {"nodes": []},
                    "attachments": {"nodes": []}, "comments": {"nodes": []}}
        pages = [{"pageInfo": {"hasNextPage": True, "endCursor": "c1"}, "nodes": [node(2, "2026-02-01")]},
                 {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [node(1, "2026-01-01")]}]
        afters = []

        def transport(query, variables):
            if "teams(" in query:
                return {"teams": {"nodes": [{"id": "team1", "name": "Alves"}]}}
            afters.append(variables["after"])
            return {"issues": pages[len(afters) - 1]}

        found = Linear(transport).list_all("Alves", "Explore")
        self.assertEqual(afters, [None, "c1"])
        self.assertEqual([i["identifier"] for i in found], ["ALV-1", "ALV-2"])

    def test_link_attaches_url_with_title(self):
        fake = Fake({"attachmentLinkURL": {"attachmentLinkURL": {"success": True}},
                     "issue(id": {"issue": issue(id="i9", identifier="ALV-9")}})
        Linear(fake).link("ALV-9", "https://x.atlassian.net/browse/RTP-1", "RTP-1")
        sent = fake.called("attachmentLinkURL")[0]
        self.assertEqual((sent["issue"], sent["url"], sent["title"]),
                         ("i9", "https://x.atlassian.net/browse/RTP-1", "RTP-1"))

    def test_update_sets_only_given_fields(self):
        fake = Fake({"issueUpdate": {"issueUpdate": {"success": True}},
                     "issue(id": {"issue": issue(id="i9", identifier="ALV-9")}})
        Linear(fake).update("ALV-9", title="RTP-1: Add labels")
        self.assertEqual(fake.called("issueUpdate")[0]["input"], {"title": "RTP-1: Add labels"})

    def test_cli_create_without_upstream_url(self):
        fake_linear = Linear(self.labels_fake())
        argv = ["create", "--team", "Alves", "--title", "t", "--label", "discovered", "--priority", "3"]
        self.assertEqual(linear_mod.main(argv, linear=fake_linear), 0)

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
            "updatedAt": "2026-01-03T00:00:00Z", "state": {"name": "In Review"}, "labels": {"nodes": []},
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

    def test_list_issues_carries_each_attachments_title(self):
        # The sweep tells the factory's own Upstream link on a Discovered ticket by its title.
        node = {
            "id": "i1", "identifier": "ALV-15", "url": "u", "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z", "state": {"name": "In Review"}, "labels": {"nodes": []},
            "attachments": {"nodes": [{"url": "https://x.atlassian.net/browse/RTP-3", "title": "Owner's context"},
                                      {"url": "https://x.atlassian.net/browse/RTP-7", "title": "RTP-7"}]},
            "history": {"nodes": []}, "comments": {"nodes": []},
        }
        fake = Fake({"teams(": {"teams": {"nodes": [{"id": "team1", "name": "Alves"}]}},
                     "issues(": {"issues": {"nodes": [node]}}})
        [found] = Linear(fake).list_issues("Alves", "AgileKit", ["In Review"])
        self.assertEqual(found["attachments"], [
            {"url": "https://x.atlassian.net/browse/RTP-3", "title": "Owner's context"},
            {"url": "https://x.atlassian.net/browse/RTP-7", "title": "RTP-7"}])
        self.assertEqual(found["attachment_urls"], [a["url"] for a in found["attachments"]])

    def test_list_issues_carries_each_issues_label_names(self):
        node = {
            "id": "i1", "identifier": "ALV-14", "url": "u", "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z", "state": {"name": "Ready"},
            "labels": {"nodes": [{"name": "discovered"}, {"name": "Bug"}]},
            "attachments": {"nodes": []}, "history": {"nodes": []}, "comments": {"nodes": []},
        }
        fake = Fake({"teams(": {"teams": {"nodes": [{"id": "team1", "name": "Alves"}]}},
                     "issues(": {"issues": {"nodes": [node]}}})
        [found] = Linear(fake).list_issues("Alves", "AgileKit", ["Ready"])
        self.assertEqual(found["labels"], ["discovered", "Bug"])
        self.assertEqual(found["attachment_urls"], [])
        self.assertIn("labels { nodes { name } }", next(q for q, _ in fake.calls if "issues(" in q))

    def test_cli_reports_errors_with_exit_1(self):
        def boom(query, variables):
            raise LinearError("LINEAR_ALVES_API_KEY is not set")
        self.assertEqual(linear_mod.main(["get", "ALV-1"], linear=Linear(boom)), 1)



class UploadTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.png = Path(self.tmp.name) / "B-desktop.png"
        self.png.write_bytes(b"\x89PNG fake bytes")
        self.fake = Fake({"fileUpload": {"fileUpload": {"success": True, "uploadFile": {
            "uploadUrl": "https://storage.example/put?sig=1", "assetUrl": "https://uploads.linear.app/a/b/B-desktop.png",
            "headers": [{"key": "x-goog-meta", "value": "m"}]}}}})
        self.requests = []

    def tearDown(self):
        self.tmp.cleanup()

    def http(self, get_status=200, get_body=None, put_status=200):
        def request(method, url, data=None, headers=None):
            self.requests.append((method, url, headers))
            if method == "PUT":
                return put_status, b""
            return get_status, self.png.read_bytes() if get_body is None else get_body
        return request

    def test_upload_puts_the_bytes_with_linears_headers_and_reads_them_back(self):
        result = Linear(self.fake, self.http(), key=lambda: "k").upload(self.png)
        self.assertEqual(result["asset_url"], "https://uploads.linear.app/a/b/B-desktop.png")
        self.assertTrue(result["verified"])
        self.assertEqual(self.fake.called("fileUpload")[0], {"type": "image/png", "name": "B-desktop.png", "size": len(self.png.read_bytes())})
        put, get = self.requests
        self.assertEqual((put[0], put[2]["x-goog-meta"], put[2]["Content-Type"]), ("PUT", "m", "image/png"))
        self.assertEqual((get[0], get[2]["Authorization"]), ("GET", "k"))

    def test_a_failed_put_raises(self):
        with self.assertRaisesRegex(LinearError, "HTTP 403"):
            Linear(self.fake, self.http(put_status=403), key=lambda: "k").upload(self.png)

    def test_a_short_read_back_raises(self):
        with self.assertRaisesRegex(LinearError, "did not read back"):
            Linear(self.fake, self.http(get_body=b"partial"), key=lambda: "k").upload(self.png)


class StateTests(unittest.TestCase):
    BOARD = [{"id": "s1", "name": "Ready", "type": "unstarted", "color": "c", "position": 1.0, "description": None},
             {"id": "s2", "name": "Planning", "type": "started", "color": "c", "position": 2.0, "description": None},
             {"id": "s3", "name": "Done", "type": "completed", "color": "c", "position": 9.0, "description": None}]

    def fake(self):
        created = iter(range(100))
        return Fake({
            "teams(": {"teams": {"nodes": [{"id": "team1", "name": "Alves"}]}},
            "workflowStateCreate": lambda v: {"workflowStateCreate": {"success": True, "workflowState": {
                "id": f"new{next(created)}", "name": v["input"]["name"], "type": v["input"]["type"],
                "color": v["input"]["color"], "position": v["input"].get("position", 50.0)}}},
            "workflowStates(": {"workflowStates": {"nodes": list(reversed(self.BOARD))}},
        })

    def test_states_come_in_board_order(self):
        self.assertEqual([s["name"] for s in Linear(self.fake()).states("Alves")], ["Ready", "Planning", "Done"])

    def test_creates_only_missing_statuses_and_keeps_existing_ones(self):
        fake = self.fake()
        result = Linear(fake).ensure_states("Alves", [
            {"name": "ready", "type": "unstarted"},
            {"name": "Ready for Design", "type": "unstarted", "after": "Ready", "description": "trigger"},
            {"name": "Exploring", "type": "started", "after": "Ready for Design"},
        ])
        self.assertEqual([(r["name"], r["created"]) for r in result],
                         [("Ready", False), ("Ready for Design", True), ("Exploring", True)])
        first, second = [v["input"] for v in fake.called("workflowStateCreate")]
        self.assertEqual((first["position"], first["description"], first["teamId"]), (1.5, "trigger", "team1"))
        self.assertEqual(second["position"], 1.75)
        self.assertFalse(any("Update" in q or "Archive" in q or "Delete" in q for q, _ in fake.calls))

    def test_a_type_mismatch_is_reported_not_changed(self):
        [result] = Linear(self.fake()).ensure_states("Alves", [{"name": "Planning", "type": "unstarted"}])
        self.assertEqual((result["created"], result["type_matches"]), (False, False))

    def test_an_unknown_after_status_writes_nothing(self):
        fake = self.fake()
        with self.assertRaisesRegex(LinearError, "does not have"):
            Linear(fake).ensure_states("Alves", [{"name": "Exploring", "type": "started", "after": "Nope"}])
        self.assertEqual(fake.called("workflowStateCreate"), [])

    def test_a_bad_type_writes_nothing(self):
        fake = self.fake()
        with self.assertRaises(LinearError):
            Linear(fake).ensure_states("Alves", [{"name": "Exploring", "type": "doing"}])
        self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
