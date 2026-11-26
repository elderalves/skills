"""Find the factory's stuck, dropped and finished work, and fix what a script can fix.

    python sweep.py plan --project <match> [--project <match> ...] [--config FILE] [--now ISO] [--out FILE]
    python sweep.py apply <sweep.json>

`plan` reads Linear, GitHub and Jira (read-only) for the given projects.json entries and
writes the actions it decides (to --out, default stdout):

    {"swept_at", "actions": [...], "start": <one action or null>, "deferred": [...], "notes": [...]}

- restart: a run died (no factory activity past the stale limit); the sweep moves the
  ticket back to its trigger status, which starts a new run.
- block: it died again right after a sweep restart; the owner decides.
- done: the factory PR merged.
- note: the factory PR closed without merging (said once; the status is left alone).
- start-*: a run whose trigger never fired (a ticket waiting in Ready or Plan Approved,
  triage that decided work but filed nothing, an assigned ticket never triaged). The
  sweep's caller runs `start` itself; the rest wait in `deferred` for the next pass.

`apply` makes the restart, block, done and note writes on Linear, skipping any ticket
whose status changed since `plan` read it. It never starts a run.

Exit codes: 0 when the plan or apply finished, 1 on an API error, 2 on unusable config.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

RUN_SCRIPTS = Path(__file__).resolve().parents[2] / "alves-factory-run" / "scripts"
sys.path.insert(0, str(RUN_SCRIPTS))
import github_account  # noqa: E402
from factory_home import factory_home  # noqa: E402
import project as project_mod  # noqa: E402
import linear as linear_mod  # noqa: E402

CONFIG = factory_home() / "projects.json"
TRIAGE_ROOT = factory_home() / "triage"
DEFAULT_LIMITS = {
    "stale_planning_hours": 3,
    "stale_implementing_hours": 6,
    "dropped_trigger_minutes": 30,
    "triage_window_days": 14,
}
NATIVE = "linear-project:"
PLANNING = {"Planning", "Plan Review"}
IMPLEMENTING = {"In Progress"}
TRIGGERS = {"Ready": "alves-factory-run", "Plan Approved": "alves-factory-implement"}
REVIEW = {"In Review", "Team Review"}
SWEPT_STATES = sorted(PLANNING | IMPLEMENTING | set(TRIGGERS) | REVIEW)
RESTART_TO = {**{s: "Ready" for s in PLANNING}, **{s: "Plan Approved" for s in IMPLEMENTING}}
RESTARTED = "## Sweep: restarted"
CLOSED = "## Sweep: PR closed"
DECISION_LINE = re.compile(r"\*\*Decision:\*\*\s*(work|unsure|not[ -]work)\b", re.IGNORECASE)
SITE_LINE = re.compile(r"Site:\s*(\S+)")


class ConfigError(Exception):
    pass


# Pure helpers

def slug(ref):
    """The work-dir and branch name of an upstream ref: / # : become -."""
    return re.sub(r"[/#:]", "-", ref)


def ref_from_url(url):
    """The upstream ref an Upstream link's URL names, per linear-record.md, or None."""
    if m := re.match(r"https://[^/]+/browse/([A-Z][A-Z0-9_]*-\d+)/?$", url):
        return m.group(1)
    if m := re.match(r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)/?$", url):
        return f"github:{m.group(1)}/{m.group(2)}#{m.group(3)}"
    if m := re.match(r"https://factory\.invalid/pasted/([^/]+)$", url):
        return f"pasted:{m.group(1)}"
    return None


def ticket_ref(ticket, entry):
    """The ticket's upstream ref when it belongs to entry, else None."""
    if entry["match"].startswith(NATIVE):
        linked = [r for r in map(ref_from_url, ticket["attachment_urls"]) if r]
        return None if linked else ticket["identifier"]
    for ref in filter(None, map(ref_from_url, ticket["attachment_urls"])):
        if ref.startswith(entry["match"]):
            return ref
    return None


def linear_project(entry):
    if entry["match"].startswith(NATIVE):
        return entry["match"][len(NATIVE):]
    if not entry.get("linear_project"):
        raise ConfigError(f"projects.json entry {entry['match']!r} has no linear_project")
    return entry["linear_project"]


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def factory_heading(comment):
    """The first line after the marker of a factory comment, else ''."""
    if not comment["from_factory"]:
        return ""
    body = comment["body"].lstrip()[len(linear_mod.MARKER):].lstrip()
    return body.split("\n", 1)[0].strip()


def hours(delta):
    return round(delta.total_seconds() / 3600, 1)


# Decisions

def decide(projects, now, limits):
    """Return the sweep's actions for a gathered snapshot (see gather) at time now."""
    actions, starts = [], []
    for project in projects:
        for t in project["tickets"]:
            actions_for_ticket(t, project, now, limits, actions, starts)
        for u in project.get("upstream", []):
            start_for_upstream(u, project, starts)
    starts.sort(key=lambda s: (s["priority"], s["since"] or ""))
    for s in starts:
        del s["priority"]
    return {
        "swept_at": now.isoformat(),
        "limits": limits,
        "actions": actions,
        "start": starts[0] if starts else None,
        "deferred": starts[1:],
    }


def actions_for_ticket(t, project, now, limits, actions, starts):
    state = t["state"]
    entered = parse_time(t["entered_state_at"] or t["updated_at"])
    factory = [c for c in t["comments"] if c["from_factory"]]
    last = factory[-1] if factory else None
    active = max([entered] + ([parse_time(last["created_at"])] if last else []))
    base = {"ticket": t["identifier"], "ref": t["ref"], "project": project["match"], "from_status": state}

    if state in RESTART_TO:
        limit = limits["stale_planning_hours" if state in PLANNING else "stale_implementing_hours"]
        idle = now - active
        if idle <= timedelta(hours=limit):
            return
        if last and factory_heading(last) == RESTARTED:
            actions.append({**base, "kind": "block", "to_status": "Blocked",
                            "reason": f"no factory activity for {hours(idle)} h in {state}, right after a sweep restart",
                            "comment": block_comment(state, idle)})
        else:
            to = RESTART_TO[state]
            actions.append({**base, "kind": "restart", "to_status": to,
                            "reason": f"no factory activity for {hours(idle)} h in {state} (limit {limit} h)",
                            "comment": restart_comment(state, idle, to)})
    elif state in TRIGGERS:
        waited = now - entered
        if waited > timedelta(minutes=limits["dropped_trigger_minutes"]):
            starts.append({**base, "kind": "start-implement" if state == "Plan Approved" else "start-plan",
                           "skill": TRIGGERS[state], "argument": t["identifier"], "priority": 0,
                           "since": t["entered_state_at"] or t["updated_at"],
                           "reason": f"waiting in {state} for {round(waited.total_seconds() / 60)} min with no run"})
    elif state in REVIEW:
        pr = t.get("pr")
        if not pr:
            return
        if pr["state"] == "MERGED":
            actions.append({**base, "kind": "done", "to_status": "Done", "pr": pr["url"],
                            "reason": f"PR merged at {pr.get('mergedAt')}",
                            "comment": done_comment(pr)})
        elif pr["state"] == "CLOSED":
            said = any(factory_heading(c) == CLOSED and pr["url"] in c["body"] for c in factory)
            if not said:
                actions.append({**base, "kind": "note", "to_status": None, "pr": pr["url"],
                                "reason": f"PR closed without merging at {pr.get('closedAt')}",
                                "comment": closed_comment(pr, state)})


def start_for_upstream(u, project, starts):
    if u["has_factory_ticket"] or u["triage"] == "not work":
        return
    base = {"ticket": None, "ref": u["ref"], "project": project["match"], "from_status": None,
            "argument": u["ref"], "since": None}
    if u["triage"] == "work":
        starts.append({**base, "kind": "start-plan", "skill": "alves-factory-run", "priority": 1,
                       "reason": "triage decided work, but no Factory ticket exists"})
    else:
        why = "triage decided unsure, but no Factory ticket exists" if u["triage"] else "assigned, never triaged"
        starts.append({**base, "kind": "start-triage", "skill": "alves-factory-triage", "priority": 2,
                       "reason": why})


# Comments

def restart_comment(state, idle, to):
    return (f"{RESTARTED}\n\nThis ticket has been in **{state}** with no factory activity for {hours(idle)} h, "
            f"so the run that owned it appears to have died. The sweep moved it to **{to}**, which starts a new run.\n\n"
            "If the new run stalls the same way, the next sweep marks the ticket Blocked.")


def block_comment(state, idle):
    return ("## Sweep: run died again\n\nThe run the sweep restarted has also stopped: the ticket has been in "
            f"**{state}** with no factory activity for {hours(idle)} h. The sweep does not restart a ticket twice "
            "in a row, so it is now **Blocked**.\n\n**To continue:** read the run's T3 thread for the cause, then "
            "move the ticket to **Ready** to re-plan or to **Plan Approved** to implement.")


def done_comment(pr):
    return f"## Sweep: merged\n\n{pr['url']} merged at {pr.get('mergedAt')}. The sweep moved the ticket to **Done**."


def closed_comment(pr, state):
    return (f"{CLOSED}\n\n{pr['url']} was closed without merging at {pr.get('closedAt')}. The ticket stays in "
            f"**{state}**: move it to **Canceled** to drop the work, or to **Ready** to re-plan it.")


# Gathering (read-only)

def read_text(path):
    """A file's text, honouring a UTF-8 or UTF-16 byte-order mark (PowerShell's `>` writes UTF-16)."""
    data = Path(path).expanduser().read_bytes()
    return data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")


def load_config(path):
    try:
        config = json.loads(read_text(path))
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    if not isinstance(config, dict) or not isinstance(config.get("projects"), list):
        raise ConfigError(f"{path} needs a projects list")
    limits = dict(DEFAULT_LIMITS)
    for key, value in (config.get("sweep") or {}).items():
        if key not in DEFAULT_LIMITS:
            raise ConfigError(f"unknown sweep setting {key!r}; known: {sorted(DEFAULT_LIMITS)}")
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ConfigError(f"sweep.{key} must be a positive number")
        limits[key] = value
    return config, limits


def select(config, matches):
    entries = []
    for match in matches:
        found = [e for e in config["projects"] if e.get("match") == match]
        if not found:
            raise ConfigError(f"no projects.json entry has match {match!r}")
        try:
            entries.append(project_mod.resolve_entry(found[0]))
        except project_mod.ProjectError as error:
            raise ConfigError(str(error)) from error
    return entries


def find_pr(entry, ref, token, runner):
    env = {**os.environ, "GH_TOKEN": token}
    code, out = runner(["gh", "pr", "list", "--head", f"factory/{slug(ref)}", "--state", "all",
                        "--json", "number,url,state,mergedAt,closedAt", "--limit", "10"],
                       env=env, cwd=entry["repo"])
    if code != 0:
        raise RuntimeError(out.strip())
    prs = json.loads(out)
    return max(prs, key=lambda p: p["number"]) if prs else None


def gh_token(entry, runner, notes):
    try:
        account = github_account.resolve(entry["repo"], entry.get("github_account"), runner)
    except github_account.AccountError as error:
        notes.append(f"{entry['match']}: PRs not checked: {error}")
        return None
    code, token = runner(["gh", "auth", "token", "--hostname", account["host"], "--user", account["account"]])
    if code != 0 or not token.strip():
        notes.append(f"{entry['match']}: PRs not checked: no gh token for {account['account']}")
        return None
    return token.strip()


def jira_assigned(entry, window_days, runner, notes):
    """Open tickets assigned to the owner within the window, or None when Jira cannot be read."""
    site = entry.get("upstream", {}).get("site")
    code, out = runner(["acli", "jira", "auth", "status"])
    signed_in = SITE_LINE.search(out or "")
    if code != 0 or not signed_in or signed_in.group(1) != site:
        notes.append(f"{entry['match']}: Jira not checked: acli is signed in to "
                     f"{signed_in.group(1) if signed_in else 'no site'}, the project is on {site}")
        return None
    project = entry["match"].rstrip("-")
    jql = (f"project = {project} AND assignee = currentUser() AND statusCategory != Done "
           f"AND assignee CHANGED TO currentUser() AFTER -{int(window_days)}d ORDER BY created ASC")
    code, out = runner(["acli", "jira", "workitem", "search", "--jql", jql, "--fields", "key,status", "--json", "--paginate"])
    if code != 0:
        notes.append(f"{entry['match']}: Jira not checked: {out.strip()[:300]}")
        return None
    # acli prints null items when only `key` is requested, so ask for status too and skip anything odd.
    items = [i for i in json.loads(out) or [] if isinstance(i, dict)]
    return [i["key"] for i in items if str(i.get("key", "")).startswith(entry["match"])]


def triage_decision(ref, triage_root):
    try:
        text = (Path(triage_root) / slug(ref) / "triage.md").read_text(encoding="utf-8-sig")
    except OSError:
        return None
    m = DECISION_LINE.search(text)
    return m.group(1).lower().replace("-", " ") if m else None


def gather(entries, team, limits, linear, runner=github_account.run, triage_root=TRIAGE_ROOT):
    """Read everything decide needs, for the given entries. Read-only."""
    notes, projects, listed = [], [], {}
    for entry in entries:
        name = linear_project(entry)
        if name not in listed:
            listed[name] = linear.list_issues(team, name, SWEPT_STATES)
        tickets = []
        for t in listed[name]:
            ref = ticket_ref(t, entry)
            if ref:
                tickets.append({**t, "ref": ref})

        reviewing = [t for t in tickets if t["state"] in REVIEW]
        token = gh_token(entry, runner, notes) if reviewing else None
        for t in reviewing:
            if token is None:
                continue
            try:
                t["pr"] = find_pr(entry, t["ref"], token, runner)
            except (RuntimeError, ValueError) as error:
                notes.append(f"{t['identifier']}: PR not checked: {error}")

        upstream = []
        if entry.get("upstream", {}).get("type") == "jira":
            assigned = jira_assigned(entry, limits["triage_window_days"], runner, notes)
            site = entry["upstream"]["site"]
            for ref in assigned or []:
                upstream.append({
                    "ref": ref,
                    "triage": triage_decision(ref, triage_root),
                    "has_factory_ticket": bool(linear.find_by_url(f"https://{site}/browse/{ref}")),
                })
        projects.append({"match": entry["match"], "tickets": tickets, "upstream": upstream})
    return projects, notes


# Applying

def apply(sweep, linear):
    """Make the Linear writes of every non-start action; return what was done or skipped."""
    done = []
    for action in sweep["actions"]:
        current = linear.issue(action["ticket"])["state"]["name"]
        if current != action["from_status"]:
            done.append({**action, "applied": False, "why": f"status is now {current}"})
            continue
        linear.comment(action["ticket"], action["comment"])
        if action["to_status"]:
            linear.set_state(action["ticket"], action["to_status"])
        done.append({**action, "applied": True})
    return [{k: a[k] for k in ("kind", "ticket", "from_status", "to_status", "applied") if k in a}
            | ({"why": a["why"]} if "why" in a else {}) for a in done]


def main(argv=None, linear=None, runner=github_account.run, triage_root=TRIAGE_ROOT):
    parser = argparse.ArgumentParser(description="Sweep the factory's stuck, dropped and finished work.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--project", action="append", required=True, dest="matches",
                   help="a projects.json entry's exact match value; repeat for several")
    p.add_argument("--config", default=str(CONFIG))
    p.add_argument("--now", help="ISO time to sweep as of (default: now)")
    p.add_argument("--out", type=Path)
    p = sub.add_parser("apply")
    p.add_argument("plan_file", type=Path)
    args = parser.parse_args(argv)

    linear = linear or linear_mod.Linear()
    try:
        if args.command == "apply":
            result = apply(json.loads(read_text(args.plan_file)), linear)
        else:
            config, limits = load_config(args.config)
            entries = select(config, args.matches)
            now = parse_time(args.now) if args.now else datetime.now(timezone.utc)
            projects, notes = gather(entries, config.get("linear_team", "Alves"), limits, linear, runner, triage_root)
            result = decide(projects, now, limits) | {"notes": notes}
    except ConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (linear_mod.LinearError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2)
    if args.command == "plan" and args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
