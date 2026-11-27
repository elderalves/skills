"""File an approved Discovered ticket on its Upstream tracker exactly once, and search that tracker.

    python upstream.py file <factory-ticket> --linear-project <name> [--account <gh-account>] [--config FILE]
    python upstream.py search --linear-project <name> --text <words> [--account <gh-account>] [--config FILE]

The Linear project selects the projects.json entry (project.py --linear-project). Its
`upstream.type` must be `jira` or `github` (references/trackers.md, **Filing a Discovered ticket**).

`file` follows ADR 0009, and a restart repeats it safely:
1. A Factory ticket already linked to an Upstream ticket of this tracker only finishes what a
   run that died after linking left undone: it is renamed `<ref>: <title>` when its title lacks
   the ref, and the Upstream ticket is assigned to the owner when nobody holds it. A ticket
   someone else holds is never reassigned.
2. The latest factory comment headed `## Filing upstream` holds the filing intent (its Title and
   Since lines); with none, one is posted naming the ticket's title and the current time.
3. A ticket the owner reported with that exact title, created at or after Since less
   CLOCK_SKEW (in UTC), is reused (GitHub: read from the REST issue listing, never the lagging
   search index); otherwise one is created **unassigned**: summary = the title, body = the
   description up to the `## Factory notes` line, then `_Found by automated analysis._`. No
   Factory URL, factory label or score goes upstream.
4. The Factory ticket is renamed `<ref>: <title>`, then linked to it (later stages key on the link).
5. Only then is the Upstream ticket assigned to the owner; a reused one only when nobody holds it.

It prints {"ref", "url", "reused", "already_linked", "assigned"}, plus "default_assignee" when
Jira gave a new ticket its project's default assignee (the owner should set that to
Unassigned). `search` prints the open Upstream tickets matching the words, as [{"ref", "title", "url"}].

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
SEARCH_BOOLEANS = re.compile(r"\b(AND|OR|NOT)\b")
# Since is the runner's clock and `created` the tracker's: a ticket created up to this much
# "before" Since still counts, so a fast runner clock cannot hide the ticket it just created.
# The exact title and the owner as reporter keep the wider window safe.
CLOCK_SKEW = timedelta(minutes=10)


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
    (a hyphen would exclude the word after it, NOT would negate it), so a fuzzy search still
    finds the title."""
    words = SEARCH_BOOLEANS.sub(lambda m: m.group(1).lower(), SEARCH_OPERATORS.sub(" ", text))
    return " ".join(words.split())


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
            self.token = self.login = None
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
        """A `gh issue …` command with the account's token."""
        return self.gh_any(what, "issue", *args)

    def gh_any(self, what, *args):
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
        return self.call(what, ["gh", *args], env={**os.environ, "GH_TOKEN": self.token})

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
        """The earliest ticket the owner reported with exactly this title, created at or after
        since_iso less CLOCK_SKEW (compared in UTC), or None."""
        since = parse_time(since_iso) - CLOCK_SKEW
        what = "looking for a ticket already filed"
        if self.type == "jira":
            words = search_words(title)
            day = (since - timedelta(days=1)).strftime("%Y-%m-%d")
            clause = f" AND summary ~ {jql_string(words)}" if words else ""
            jql = f"project = {self.project_key} AND reporter = currentUser(){clause} AND created >= \"{day}\""
            hits = [(i["key"], (i.get("fields") or {}).get("summary"), (i.get("fields") or {}).get("created"))
                    for i in self.jira_items(what, jql, "key,summary,created", 50)]
            hits = [(key, self.url_root + key, summary, created) for key, summary, created in hits]
        else:
            # The REST listing, not the search index: the index lags, and a restart seconds after
            # a create must still find the issue.
            if self.login is None:
                self.login = self.gh_any("reading the gh account's login", "api", "user", "--jq", ".login").strip()
                if not self.login:
                    raise UpstreamError("gh api user printed no login")
            out = self.gh_any(what, "api", f"repos/{self.repo}/issues?state=all&creator={self.login}"
                                            "&sort=created&direction=desc&per_page=100")
            hits = [(self.ref(i["number"]), i.get("html_url"), i.get("title"), i.get("created_at"))
                    for i in self.json_out(what, out) or [] if isinstance(i, dict) and "pull_request" not in i]
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
            created = {"ref": key, "url": self.url_root + key}
            # acli cannot create "unassigned": the project's default assignee applies. Say so, don't fail.
            try:
                holder = self.assignee(key)
            except UpstreamError:
                holder = None
            return {**created, "default_assignee": holder} if holder else created
        found = re.search(re.escape(self.url_root) + r"(\d+)", out, re.IGNORECASE)
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

    def assignee(self, ref):
        """Who holds the ticket (a name, email, account ID or login), or None when nobody does."""
        if self.type == "jira":
            out = self.acli("reading the assignee", "view", ref, "--fields", "assignee", "--json")
            data = self.json_out("reading the assignee", out)
            item = data[0] if isinstance(data, list) and data else data
            person = ((item or {}).get("fields") or {}).get("assignee")
            if not person:
                return None
            if isinstance(person, dict):
                return next((person[k] for k in ("displayName", "emailAddress", "accountId") if person.get(k)),
                            "someone")
            return str(person)
        out = self.gh("reading the assignees", "view", ref.rsplit("#", 1)[-1], "--repo", self.repo,
                      "--json", "assignees")
        people = (self.json_out("reading the assignees", out) or {}).get("assignees") or []
        return next((p.get("login") or "someone" for p in people), None)

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
        """The ref of a URL on this tracker, or None. Hosts and GitHub owner/repo ignore case."""
        if not isinstance(url, str) or not url.casefold().startswith(self.url_root.casefold()):
            return None
        rest = url[len(self.url_root):].split("?", 1)[0].split("#", 1)[0].strip("/")
        if self.type == "jira":
            return rest if re.fullmatch(r"[A-Z][A-Z0-9_]*-\d+", rest) else None
        return self.ref(rest) if rest.isdigit() else None


# Filing a Discovered ticket

def intent_body(title, since):
    """The filing intent comment. The title is a JSON string in a code span, so Markdown
    normalisation (`__init__` to bold, `*` escaped) cannot change it; a backtick is written as
    \\u0060, so it cannot close the span."""
    literal = json.dumps(title, ensure_ascii=False).replace("`", "\\u0060")
    return f"{FILING_HEADING}\n\n- **Title:** `{literal}`\n- **Since:** {since}"


def intent_title(value):
    """The title from an intent's Title line: the JSON code span, or the older plain text."""
    span = re.fullmatch(r"`(\".*\")`", value)
    if span:
        try:
            return json.loads(span.group(1))
        except ValueError:
            pass
    return value


def filing_intent(comments):
    """(title, since) from the latest factory comment headed `## Filing upstream`, or None."""
    for comment in reversed(comments):
        if comment.get("from_factory") and FILING_HEADING in comment.get("body", ""):
            lines = dict(INTENT_LINE.findall(comment["body"]))
            missing = [name for name in ("Title", "Since") if not lines.get(name)]
            if missing:
                raise UpstreamError(f"the {FILING_HEADING!r} comment of {comment.get('created_at')} has no "
                                    f"{' or '.join(missing)} line; fix it or delete it, then rerun")
            return intent_title(lines["Title"]), lines["Since"]
    return None


def assign_if_unassigned(upstream, ref):
    """Assign the ticket to the owner unless somebody holds it; True when it was assigned now."""
    if upstream.assignee(ref) is not None:
        return False
    upstream.assign_owner(ref)
    return True


def file_discovered(linear, upstream, issue_ref, now_iso):
    issue = linear.issue(issue_ref)
    for attachment in issue["attachments"]["nodes"]:
        ref = upstream.ref_of_url(attachment["url"])
        if ref:
            # A run died after linking: finish the rename and the assignment, nothing else.
            if not issue["title"].startswith(f"{ref}: "):
                linear.update(issue_ref, title=f"{ref}: {issue['title']}")
            assigned = assign_if_unassigned(upstream, ref)
            return {"ref": ref, "url": attachment["url"], "reused": False, "already_linked": True,
                    "assigned": assigned}
    upstream.check_site()
    intent = filing_intent(linear.comments(issue_ref))
    if intent is None:
        intent = (issue["title"], now_iso)
        linear.comment(issue_ref, intent_body(*intent))
    title, since = intent
    found = upstream.find_filed(title, since)
    ticket = found or upstream.create(title, public_part(issue.get("description")))
    linear.update(issue_ref, title=f"{ticket['ref']}: {title}")
    linear.link(issue_ref, ticket["url"], ticket["ref"])
    if found:
        assigned = assign_if_unassigned(upstream, ticket["ref"])
    else:
        upstream.assign_owner(ticket["ref"])  # created unassigned a moment ago
        assigned = True
    result = {"ref": ticket["ref"], "url": ticket["url"], "reused": found is not None, "already_linked": False,
              "assigned": assigned}
    if ticket.get("default_assignee"):
        result["default_assignee"] = ticket["default_assignee"]
    return result


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
