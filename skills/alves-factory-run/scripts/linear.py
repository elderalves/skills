"""Read and write the factory's record on Linear (the Factory tracker) via the GraphQL API.

Needs a Linear personal API key: the LINEAR_ALVES_API_KEY environment variable, or a
LINEAR_ALVES_API_KEY=... line in ~/.factory/.env. Every command prints JSON.

    python linear.py find-by-url <upstream-url>
    python linear.py get <issue>
    python linear.py create --team <name> --title <t> --upstream-url <u> [--upstream-title <t>] [--state <s>] [--description-file <f>]
    python linear.py set-state <issue> <state-name>
    python linear.py set-label <issue> <label>          # replaces any label sharing the prefix before ':'
    python linear.py put-doc <issue> --title <t> --file <f>   # creates, or updates the doc with that title
    python linear.py get-doc <issue> --title <t> [--out <f>]  # prints the doc, or writes its content to <f>
    python linear.py comment <issue> --file <f>
    python linear.py comments <issue> [--since <iso-datetime>]
    python linear.py mark-duplicate <issue> --of <original-issue>

<issue> is an identifier such as ALV-12 or an issue UUID. Exit 1 on any API error.
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path


API_URL = "https://api.linear.app/graphql"
MARKER = "[alves-factory]"
KEY_NAME = "LINEAR_ALVES_API_KEY"
ENV_FILE = Path.home() / ".factory" / ".env"

ISSUE_FIELDS = """
  id identifier title description url createdAt
  project { id name }
  state { id name type }
  team { id name key }
  labels { nodes { id name } }
  attachments { nodes { id url title } }
  documents { nodes { id title url updatedAt } }
"""


class LinearError(Exception):
    pass


def api_key(environ=os.environ, env_file=ENV_FILE):
    """The key from the environment, else from env_file's KEY_NAME=... line."""
    if environ.get(KEY_NAME):
        return environ[KEY_NAME].strip()
    try:
        lines = env_file.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        name, sep, value = line.strip().partition("=")
        if sep and name.strip().removeprefix("export ").strip() == KEY_NAME:
            return value.strip().strip("'\"")
    raise LinearError(f"{KEY_NAME} is not set (environment variable, or a line in {env_file})")


def http_transport(query, variables):
    key = api_key()
    request = urllib.request.Request(
        API_URL,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": key},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        raise LinearError(f"HTTP {error.code}: {error.read().decode('utf-8', 'replace')[:500]}") from error
    except urllib.error.URLError as error:
        raise LinearError(f"cannot reach Linear: {error.reason}") from error
    if payload.get("errors"):
        raise LinearError("; ".join(e.get("message", str(e)) for e in payload["errors"]))
    return payload["data"]


class Linear:
    def __init__(self, transport=http_transport):
        self.gql = transport

    # Reads

    def issue(self, ref):
        return self.gql(f"query($id: String!) {{ issue(id: $id) {{ {ISSUE_FIELDS} }} }}", {"id": ref})["issue"]

    def find_by_url(self, url):
        """Every issue linked to url, oldest first, without repeats."""
        data = self.gql(
            "query($url: String!) { attachmentsForURL(url: $url, first: 50) "
            "{ nodes { issue { id identifier url createdAt state { name } } } } }",
            {"url": url},
        )
        seen, issues = set(), []
        for node in data["attachmentsForURL"]["nodes"]:
            issue = node["issue"]
            if issue["id"] not in seen:
                seen.add(issue["id"])
                issues.append(issue)
        return sorted(issues, key=lambda i: i["createdAt"])

    def team_id(self, name):
        teams = self.gql(
            "query($name: String!) { teams(filter: { or: [{ name: { eq: $name } }, { key: { eq: $name } }] }) "
            "{ nodes { id name } } }",
            {"name": name},
        )["teams"]["nodes"]
        if not teams:
            raise LinearError(f"no Linear team named {name!r}")
        return teams[0]["id"]

    def state_id(self, team_id, name):
        states = self.gql(
            "query($team: ID!, $name: String!) { workflowStates(filter: "
            "{ team: { id: { eq: $team } }, name: { eqIgnoreCase: $name } }) { nodes { id name } } }",
            {"team": team_id, "name": name},
        )["workflowStates"]["nodes"]
        if not states:
            raise LinearError(f"the team has no status named {name!r}")
        return states[0]["id"]

    def comments(self, ref, since=None):
        issue_id = self.issue(ref)["id"]
        data = self.gql(
            "query($id: String!) { issue(id: $id) { comments(first: 250) "
            "{ nodes { id body createdAt user { id name isMe } botActor { name } } } } }",
            {"id": issue_id},
        )
        result = []
        for c in sorted(data["issue"]["comments"]["nodes"], key=lambda c: c["createdAt"]):
            if since and c["createdAt"] <= since:
                continue
            result.append({
                "id": c["id"],
                "created_at": c["createdAt"],
                "author": (c.get("user") or {}).get("name") or (c.get("botActor") or {}).get("name"),
                "from_factory": c["body"].lstrip().startswith(MARKER),
                "body": c["body"],
            })
        return result

    # Writes

    def create(self, team, title, upstream_url, upstream_title=None, state=None, description=None):
        team_id = self.team_id(team)
        payload = {"teamId": team_id, "title": title}
        if description:
            payload["description"] = description
        if state:
            payload["stateId"] = self.state_id(team_id, state)
        created = self.gql(
            "mutation($input: IssueCreateInput!) { issueCreate(input: $input) { success issue { id identifier } } }",
            {"input": payload},
        )["issueCreate"]["issue"]
        self.gql(
            "mutation($issue: String!, $url: String!, $title: String) "
            "{ attachmentLinkURL(issueId: $issue, url: $url, title: $title) { success } }",
            {"issue": created["id"], "url": upstream_url, "title": upstream_title or upstream_url},
        )
        return self.issue(created["id"])

    def set_state(self, ref, name):
        issue = self.issue(ref)
        state_id = self.state_id(issue["team"]["id"], name)
        self.gql("mutation($id: String!, $state: String!) { issueUpdate(id: $id, input: { stateId: $state }) "
                 "{ success } }", {"id": issue["id"], "state": state_id})
        return self.issue(issue["id"])

    def set_label(self, ref, name):
        """Add label name, removing any other label with the same 'prefix:'."""
        issue = self.issue(ref)
        prefix = name.split(":", 1)[0] + ":" if ":" in name else None
        stale = [l["id"] for l in issue["labels"]["nodes"]
                 if prefix and l["name"].startswith(prefix) and l["name"] != name]
        label_id = self.label_id(issue["team"]["id"], name)
        self.gql(
            "mutation($id: String!, $add: [String!], $remove: [String!]) { issueUpdate(id: $id, input: "
            "{ addedLabelIds: $add, removedLabelIds: $remove }) { success } }",
            {"id": issue["id"], "add": [label_id], "remove": stale},
        )
        return self.issue(issue["id"])

    def label_id(self, team_id, name):
        labels = self.gql(
            "query($name: String!) { issueLabels(filter: { name: { eq: $name } }) "
            "{ nodes { id name team { id } } } }",
            {"name": name},
        )["issueLabels"]["nodes"]
        usable = [l for l in labels if l.get("team") is None or l["team"]["id"] == team_id]
        if usable:
            return usable[0]["id"]
        return self.gql(
            "mutation($input: IssueLabelCreateInput!) { issueLabelCreate(input: $input) "
            "{ issueLabel { id } } }",
            {"input": {"name": name, "teamId": team_id}},
        )["issueLabelCreate"]["issueLabel"]["id"]

    def put_doc(self, ref, title, content):
        issue = self.issue(ref)
        existing = [d for d in issue["documents"]["nodes"] if d["title"] == title]
        if existing:
            doc = self.gql(
                "mutation($id: String!, $input: DocumentUpdateInput!) { documentUpdate(id: $id, input: $input) "
                "{ document { id title url } } }",
                {"id": existing[0]["id"], "input": {"content": content}},
            )["documentUpdate"]["document"]
        else:
            doc = self.gql(
                "mutation($input: DocumentCreateInput!) { documentCreate(input: $input) "
                "{ document { id title url } } }",
                {"input": {"title": title, "content": content, "issueId": issue["id"]}},
            )["documentCreate"]["document"]
        return doc

    def get_doc(self, ref, title):
        issue = self.issue(ref)
        matches = [d for d in issue["documents"]["nodes"] if d["title"] == title]
        if not matches:
            raise LinearError(f"{issue['identifier']} has no document titled {title!r}")
        return self.gql("query($id: String!) { document(id: $id) { id title url content updatedAt } }",
                        {"id": matches[0]["id"]})["document"]

    def comment(self, ref, body):
        if not body.lstrip().startswith(MARKER):
            body = f"{MARKER}\n\n{body}"
        issue = self.issue(ref)
        return self.gql(
            "mutation($input: CommentCreateInput!) { commentCreate(input: $input) "
            "{ comment { id url createdAt } } }",
            {"input": {"issueId": issue["id"], "body": body}},
        )["commentCreate"]["comment"]

    def mark_duplicate(self, ref, original):
        issue, keep = self.issue(ref), self.issue(original)
        self.gql(
            "mutation($input: IssueRelationCreateInput!) { issueRelationCreate(input: $input) { success } }",
            {"input": {"issueId": issue["id"], "relatedIssueId": keep["id"], "type": "duplicate"}},
        )
        return self.set_state(issue["id"], "Duplicate")


def main(argv=None, linear=None):
    parser = argparse.ArgumentParser(description="The factory's record on Linear.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("find-by-url").add_argument("url")
    sub.add_parser("get").add_argument("issue")
    p = sub.add_parser("create")
    p.add_argument("--team", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--upstream-url", required=True)
    p.add_argument("--upstream-title")
    p.add_argument("--state")
    p.add_argument("--description-file", type=Path)
    p = sub.add_parser("set-state")
    p.add_argument("issue")
    p.add_argument("state")
    p = sub.add_parser("set-label")
    p.add_argument("issue")
    p.add_argument("label")
    p = sub.add_parser("put-doc")
    p.add_argument("issue")
    p.add_argument("--title", required=True)
    p.add_argument("--file", type=Path, required=True)
    p = sub.add_parser("get-doc")
    p.add_argument("issue")
    p.add_argument("--title", required=True)
    p.add_argument("--out", type=Path)
    p = sub.add_parser("comment")
    p.add_argument("issue")
    p.add_argument("--file", type=Path, required=True)
    p = sub.add_parser("comments")
    p.add_argument("issue")
    p.add_argument("--since")
    p = sub.add_parser("mark-duplicate")
    p.add_argument("issue")
    p.add_argument("--of", required=True, dest="original")
    args = parser.parse_args(argv)

    linear = linear or Linear()
    read = lambda path: path.read_text(encoding="utf-8")
    try:
        if args.command == "find-by-url":
            result = linear.find_by_url(args.url)
        elif args.command == "get":
            result = linear.issue(args.issue)
        elif args.command == "create":
            description = read(args.description_file) if args.description_file else None
            result = linear.create(args.team, args.title, args.upstream_url, args.upstream_title,
                                   args.state, description)
        elif args.command == "set-state":
            result = linear.set_state(args.issue, args.state)
        elif args.command == "set-label":
            result = linear.set_label(args.issue, args.label)
        elif args.command == "put-doc":
            result = linear.put_doc(args.issue, args.title, read(args.file))
        elif args.command == "get-doc":
            result = linear.get_doc(args.issue, args.title)
            if args.out:
                args.out.write_text(result.get("content") or "", encoding="utf-8")
                result = {k: v for k, v in result.items() if k != "content"} | {"written": str(args.out)}
        elif args.command == "comment":
            result = linear.comment(args.issue, read(args.file))
        elif args.command == "comments":
            result = linear.comments(args.issue, args.since)
        else:
            result = linear.mark_duplicate(args.issue, args.original)
    except (LinearError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
