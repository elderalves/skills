"""File an approved Discovered ticket on its Upstream tracker exactly once, and search that tracker.

    python upstream.py file <factory-ticket> --linear-project <name> [--account <gh-account>] [--config FILE]
    python upstream.py search --linear-project <name> --text <words> [--account <gh-account>] [--config FILE]

The Linear project selects the projects.json entry (project.py --linear-project). Its
`upstream.type` must be `jira` or `github` (references/trackers.md, **Filing a Discovered ticket**).

`file` follows ADR 0009, and a restart repeats it safely:
1. A Factory ticket already linked to an Upstream ticket of this tracker is done: it prints
   that ticket and makes no other call.
2. The latest factory comment headed `## Filing upstream` holds the filing intent (its Title and
   Since lines); with none, one is posted naming the ticket's title and the current time.
3. A ticket the owner reported with that exact title, created at or after Since, is reused;
   otherwise one is created **unassigned**: summary = the title, body = the description up to
   the `## Factory notes` line, then `_Found by automated analysis._`. No Factory URL, factory
   label or score goes upstream.
4. The Factory ticket is linked to it and renamed `<ref>: <title>`.
5. Only then is the Upstream ticket assigned to the owner.

It prints {"ref", "url", "reused", "already_linked"}. `search` prints the open Upstream tickets
matching the words, as [{"ref", "title", "url"}].

Jira goes through `acli`, after checking that `acli jira auth status` names `upstream.site`; it
never switches sites. GitHub goes through `gh`, with GH_TOKEN from `gh auth token --user
<account>` (--account, else the entry's `github_account`, else the account that reaches the repo).

Exit 1 on a tool or Linear error, 2 on unusable config or arguments, with `error: ...` on stderr.
"""

import argparse
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import github_account  # noqa: E402
import linear as linear_mod  # noqa: E402
import project as project_mod  # noqa: E402
from factory_home import factory_home  # noqa: E402

FILING_HEADING = "## Filing upstream"
CLOSING_LINE = "_Found by automated analysis._"
NOTES_HEADING = "## Factory notes"
GITHUB_HOST = "github.com"
SITE_LINE = re.compile(r"Site:\s*(\S+)")
INTENT_LINE = re.compile(r"^- \*\*(Title|Since):\*\*[ \t]*(.*?)\s*$", re.MULTILINE)
# Characters Jira's text search (and GitHub's search syntax) read as operators, not words.
SEARCH_OPERATORS = re.compile(r'[+\-&|!(){}\[\]^~*?\\:"/]')


class UpstreamError(Exception):
    pass


class ConfigError(UpstreamError):
    """The entry cannot be filed upstream: exit 2, not a tool failure."""


# Text

def public_part(description):
    """The description up to the first line that is exactly `## Factory notes`, then the closing line."""
    lines = (description or "").replace("\r\n", "\n").split("\n")
    cut = next((i for i, line in enumerate(lines) if line.rstrip() == NOTES_HEADING), len(lines))
    text = "\n".join(lines[:cut]).strip()
    if text.endswith(CLOSING_LINE):
        text = text[: -len(CLOSING_LINE)].rstrip()
    return f"{text}\n\n{CLOSING_LINE}" if text else CLOSING_LINE


def jql_string(text):
    """A double-quoted JQL literal."""
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def search_words(text):
    """The words of text, without characters a tracker's search would read as operators
    (a hyphen would exclude the word after it), so a fuzzy search still finds the title."""
    return " ".join(SEARCH_OPERATORS.sub(" ", text).split())


def parse_time(value):
    """An ISO timestamp as an aware UTC datetime; Jira's `-0300` offsets and `Z` both read."""
    text = re.sub(r"([+-]\d\d)(\d\d)$", r"\1:\2", str(value).strip().replace("Z", "+00:00"))
    try:
        moment = datetime.fromisoformat(text)
    except ValueError as error:
        raise UpstreamError(f"cannot read the time {value!r}") from error
    if moment.tzinfo is None:
        raise UpstreamError(f"the time {value!r} has no timezone")
    return moment.astimezone(timezone.utc)


# The Upstream tracker

class Upstream:
    def __init__(self, entry, account=None, run=github_account.run):
        self.entry, self.run = entry, run
        tracker = entry.get("upstream") or {}
        self.type = tracker.get("type")
        if self.type == "jira":
            self.site = tracker.get("site")
            if not self.site:
                raise ConfigError(f"{entry.get('match')!r}: upstream.site is not set")
            filing = tracker.get("file") or {}
            self.project_key = filing.get("project_key") or entry["match"].rstrip("-")
            self.issue_type = filing.get("issue_type") or "Task"
            self.labels = list(filing.get("labels") or [])
            self.url_root = f"https://{self.site}/browse/"
            self.site_checked = False
        elif self.type == "github":
            match = entry.get("match", "")
            if not (match.startswith("github:") and match.endswith("#")):
                raise ConfigError(f"a GitHub entry's match must be github:<owner>/<repo>#, not {match!r}")
            self.repo = match[len("github:"):-1]
            self.url_root = f"https://{GITHUB_HOST}/{self.repo}/issues/"
            self.account = account or entry.get("github_account")
            self.token = None
        else:
            raise ConfigError(f"{entry.get('match')!r} has upstream.type {self.type!r}; "
                              "only jira and github tickets are filed upstream")

    # Running commands

    def call(self, what, args, env=None):
        code, out = self.run(args, env=env)
        if code != 0:
            raise UpstreamError(f"{what} failed: {out.strip()[:500]}")
        return out

    def acli(self, what, *args):
        self.check_site()
        return self.call(what, ["acli", "jira", "workitem", *args])

    def gh(self, what, *args):
        if self.token is None:
            account, host = self.account, GITHUB_HOST
            if not account:
                try:
                    found = github_account.resolve(self.entry["repo"], None, self.run)
                except github_account.AccountError as error:
                    raise UpstreamError(str(error)) from error
                account, host = found["account"], found["host"]
            code, token = self.run(["gh", "auth", "token", "--hostname", host, "--user", account])
            if code != 0 or not token.strip():
                raise UpstreamError(f"no gh token for account {account!r} on {host}")
            self.token = token.strip()
        return self.call(what, ["gh", "issue", *args], env={**os.environ, "GH_TOKEN": self.token})

    def json_out(self, what, out):
        try:
            return json.loads(out)
        except ValueError as error:
            raise UpstreamError(f"{what} printed no JSON: {out.strip()[:300]}") from error

    # Operations

    def check_site(self):
        """Jira only: acli must be signed in to this project's site. It never switches sites."""
        if self.type != "jira" or self.site_checked:
            return
        code, out = self.run(["acli", "jira", "auth", "status"])
        signed_in = SITE_LINE.search(out or "")
        if code != 0 or not signed_in or signed_in.group(1) != self.site:
            raise UpstreamError(f"acli is signed in to {signed_in.group(1) if signed_in else 'no site'}, "
                                f"but this project's Jira is {self.site}; sign acli in to {self.site} "
                                "(the factory never switches sites)")
        self.site_checked = True

    def jira_items(self, what, jql, fields, limit):
        out = self.acli(what, "search", "--jql", jql, "--fields", fields, "--limit", str(limit), "--json")
        items = self.json_out(what, out) or []
        return [i for i in items if isinstance(i, dict) and i.get("key")]

    def search_open(self, text):
        """Open tickets matching text, most recently updated first: [{ref, title, url}]."""
        words = search_words(text)
        if self.type == "jira":
            clause = f" AND text ~ {jql_string(words)}" if words else ""
            jql = f"project = {self.project_key} AND statusCategory != Done{clause} ORDER BY updated DESC"
            return [{"ref": i["key"], "title": (i.get("fields") or {}).get("summary"), "url": self.url_root + i["key"]}
                    for i in self.jira_items("searching open tickets", jql, "key,summary", 20)]
        out = self.gh("searching open issues", "list", "--repo", self.repo, "--state", "open", "--search", words,
                      "--json", "number,title,url", "--limit", "20")
        return [{"ref": self.ref(i["number"]), "title": i["title"], "url": i["url"]}
                for i in self.json_out("searching open issues", out)]

    def find_filed(self, title, since_iso):
        """The earliest ticket the owner reported with exactly this title at or after since_iso, or None."""
        since = parse_time(since_iso)
        words = search_words(title)
        if self.type == "jira":
            day = (since - timedelta(days=1)).strftime("%Y-%m-%d")
            clause = f" AND summary ~ {jql_string(words)}" if words else ""
            jql = f"project = {self.project_key} AND reporter = currentUser(){clause} AND created >= \"{day}\""
            hits = [(i["key"], (i.get("fields") or {}).get("summary"), (i.get("fields") or {}).get("created"))
                    for i in self.jira_items("looking for a ticket already filed", jql, "key,summary,created", 50)]
            hits = [(key, self.url_root + key, summary, created) for key, summary, created in hits]
        else:
            out = self.gh("looking for an issue already filed", "list", "--repo", self.repo, "--author", "@me",
                          "--state", "all", "--search", f"in:title {words}",
                          "--json", "number,title,url,createdAt", "--limit", "50")
            hits = [(self.ref(i["number"]), i["url"], i["title"], i.get("createdAt"))
                    for i in self.json_out("looking for an issue already filed", out)]
        filed = [(parse_time(created), ref, url) for ref, url, summary, created in hits
                 if isinstance(summary, str) and summary.strip() == title.strip()]
        filed = sorted(f for f in filed if f[0] >= since)
        return {"ref": filed[0][1], "url": filed[0][2]} if filed else None

    def create(self, title, body):
        """A new ticket, left unassigned: {ref, url}. The body goes through a temp file."""
        handle, path = tempfile.mkstemp(suffix=".md", prefix="upstream-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            if self.type == "jira":
                args = ["create", "--project", self.project_key, "--type", self.issue_type, "--summary", title,
                        "--description-file", path]
                if self.labels:
                    args += ["--label", ",".join(self.labels)]
                out = self.acli("creating the ticket", *args, "--json")
            else:
                out = self.gh("creating the issue", "create", "--repo", self.repo, "--title", title,
                              "--body-file", path)
        finally:
            os.unlink(path)
        if self.type == "jira":
            key = self.created_key(out)
            return {"ref": key, "url": self.url_root + key}
        found = re.search(re.escape(self.url_root) + r"(\d+)", out)
        if not found:
            raise UpstreamError(f"gh issue create printed no issue URL: {out.strip()[:300]}")
        return {"ref": self.ref(found.group(1)), "url": found.group(0)}

    def created_key(self, out):
        try:
            data = json.loads(out)
        except ValueError:
            data = None
        if isinstance(data, dict) and isinstance(data.get("key"), str):
            return data["key"]
        found = re.search(rf"\b{re.escape(self.project_key)}-\d+\b", out)
        if not found:
            raise UpstreamError(f"acli created a ticket but printed no key: {out.strip()[:300]}")
        return found.group(0)

    def assign_owner(self, ref):
        if self.type == "jira":
            self.acli("assigning the ticket", "assign", "--key", ref, "--assignee", "@me", "--yes")
        else:
            self.gh("assigning the issue", "edit", ref.rsplit("#", 1)[-1], "--repo", self.repo,
                    "--add-assignee", "@me")

    # Refs

    def ref(self, number):
        return f"github:{self.repo}#{number}"

    def ref_of_url(self, url):
        """The ref of a URL on this tracker, or None."""
        if not isinstance(url, str) or not url.startswith(self.url_root):
            return None
        rest = url[len(self.url_root):].split("?", 1)[0].split("#", 1)[0].strip("/")
        if self.type == "jira":
            return rest if re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", rest) else None
        return self.ref(rest) if rest.isdigit() else None


# Filing a Discovered ticket

def filing_intent(comments):
    """(title, since) from the latest factory comment headed `## Filing upstream`, or None."""
    for comment in reversed(comments):
        if comment.get("from_factory") and FILING_HEADING in comment.get("body", ""):
            lines = dict(INTENT_LINE.findall(comment["body"]))
            missing = [name for name in ("Title", "Since") if not lines.get(name)]
            if missing:
                raise UpstreamError(f"the {FILING_HEADING!r} comment of {comment.get('created_at')} has no "
                                    f"{' or '.join(missing)} line; fix it or delete it, then rerun")
            return lines["Title"], lines["Since"]
    return None


def file_discovered(linear, upstream, issue_ref, now_iso):
    issue = linear.issue(issue_ref)
    for attachment in issue["attachments"]["nodes"]:
        ref = upstream.ref_of_url(attachment["url"])
        if ref:
            return {"ref": ref, "url": attachment["url"], "reused": False, "already_linked": True}
    upstream.check_site()
    intent = filing_intent(linear.comments(issue_ref))
    if intent is None:
        intent = (issue["title"], now_iso)
        linear.comment(issue_ref, f"{FILING_HEADING}\n\n- **Title:** {intent[0]}\n- **Since:** {intent[1]}")
    title, since = intent
    found = upstream.find_filed(title, since)
    ticket = found or upstream.create(title, public_part(issue.get("description")))
    linear.link(issue_ref, ticket["url"], ticket["ref"])
    linear.update(issue_ref, title=f"{ticket['ref']}: {title}")
    upstream.assign_owner(ticket["ref"])
    return {"ref": ticket["ref"], "url": ticket["url"], "reused": found is not None, "already_linked": False}


def main(argv=None, linear=None, run=None):
    parser = argparse.ArgumentParser(description="File a Discovered ticket upstream, or search the Upstream tracker.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("file", "search"):
        p = sub.add_parser(name)
        if name == "file":
            p.add_argument("issue", help="the Factory ticket, such as ALV-12")
        else:
            p.add_argument("--text", required=True, help="the words to search open Upstream tickets for")
        p.add_argument("--linear-project", required=True, help="the Factory ticket's Linear project")
        p.add_argument("--account", help="the gh account for a GitHub tracker")
        p.add_argument("--config", default=str(factory_home() / "projects.json"))
    args = parser.parse_args(argv)
    try:
        entry = project_mod.find(project_mod.read_config(args.config), linear_project=args.linear_project)
        tracker = Upstream(entry, args.account, run or github_account.run)
    except (project_mod.ProjectError, ConfigError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    try:
        if args.command == "search":
            result = tracker.search_open(args.text)
        else:
            now = datetime.now(timezone.utc).isoformat(timespec="seconds")
            result = file_discovered(linear or linear_mod.Linear(), tracker, args.issue, now)
    except (UpstreamError, linear_mod.LinearError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
