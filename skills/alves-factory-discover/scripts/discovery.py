"""Run one Discovery pass's deterministic steps: what to look at, how much room, who scores,
and which scored candidates become Discovered tickets.

    python discovery.py prepare --linear-project <name> --discoverer-model <model> --date YYYY-MM-DD --out <dir> [--config FILE]
    python discovery.py check <work-dir>
    python discovery.py score <work-dir>
    python discovery.py file <work-dir> [--dry-run]

`prepare` finds the projects.json entry of the Linear project (project.py --linear-project),
which must carry a `discovery` object, and layers the entry's `discovery.policy` file over the
bundled assets/default-policy.json. It reads every Factory ticket of the project (any status)
into <dir>/tickets.json and writes <dir>/prepare.json, which it also prints. Each pass starts
clean: before writing, it deletes the previous pass's candidates.json, scores/, scored.json,
selected.json, filed.json and record/ from <dir>, and nothing else.

    {"match", "linear_project", "team", "repo", "base_branch", "github_account", "lens", "room", "open_backlog",
     "max_candidates", "since", "scorer", "policy", "upstream_type", "native"}

- lens: lenses[date.toordinal() % len(lenses)]; `discovery.lenses` replaces the policy's list.
- room: max(0, min(max_new, max_open - open_backlog)), where open_backlog counts the tickets in
  Backlog labelled `discovered`; room 0 ends the pass before it looks.
- since: the date at the current local clock time, less 24 hours (ISO 8601 with offset).
- scorer: the seat that scores every candidate: `discovery.scorer.target`, else the entry's
  resolved Council testing-risk seat. It is never the Discovery agent's own model.
- native: the match starts with `linear-project:`. upstream_type is the entry's
  `upstream.type`, or null when it has none.

An entry with an Upstream tracker (jira, github) needs an `upstream.file` object, which may be
`{}`: it is the owner's opt-in to filing approved Discovered tickets there. Jira's
`project_key` is optional (upstream.py defaults it to the match without its trailing `-`).

The agent then writes <work-dir>/candidates.json and the scorer each scores/<id>.json, in the
shapes of references/candidate-schema.md.

`check` prints `ok`, or one problem per line naming the candidate (exit 1): a criterion missing,
not an integer or outside 0-10, an Effort other than S, M or L, a seat other than prepare.json's
scorer, a score file whose `title` is not its candidate's, more than max_candidates
candidates, a candidate without `closest.why_different`.
`score` runs the same check and scores nothing until it passes. Then each candidate's Value
score is sum(weight * score) / 10, rounded half up, its band High, Medium or Low (below Low it
is dropped), and the best `room` of them, ties in candidate order, go to selected.json.
scored.json lists every candidate, best first, as {id, title, value_score, band (null below
Low), effort, quick_win, outcome}, outcome "selected", "below the bar" or "past the room"; it
prints {"selected": [...], "dropped": [...]}, those entries split by outcome. `file` files each selected item in Backlog of the Linear project, labelled
`discovered` (plus `quick-win` for High with Effort S), with priority 2, 3 or 4 by band and the
description of references/candidate-schema.md; it prints [{identifier, title, value_score,
band, effort}]. After each create it appends {number, identifier, title} to filed.json, and a
rerun skips every item filed.json records, so a `file` that failed part-way is rerun as is.
`--dry-run` writes record/NN-ticket.md for each instead, files nothing and ignores filed.json.

Every path argument may start with `~`, which is expanded here (PowerShell 5.1 and a quoted
bash argument pass it through literally).

Exit codes: 0 ok, 1 on check problems or a Linear or file error, 2 on unusable config,
arguments or work-dir input, with `error: ...` on stderr.
"""

import argparse
import json
import math
import re
import shutil
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

RUN_SCRIPTS = Path(__file__).resolve().parents[2] / "alves-factory-run" / "scripts"
sys.path.insert(0, str(RUN_SCRIPTS))
import council  # noqa: E402  (also puts the review skill's gate on sys.path)
import gate  # noqa: E402
import linear as linear_mod  # noqa: E402
import project as project_mod  # noqa: E402
from factory_home import factory_home  # noqa: E402
from upstream import NOTES_HEADING  # noqa: E402  (where upstream.py ends the public part)

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "assets" / "default-policy.json"
CRITERIA = ("impact", "engineering", "reach", "evidence", "urgency")
BANDS = ("high", "medium", "low")
EFFORTS = ("S", "M", "L")
PRIORITY = {"High": 2, "Medium": 3, "Low": 4}
DEFAULT_CAPS = {"max_new": 3, "max_open": 10}
NATIVE = project_mod.NATIVE
DISCOVERED = "discovered"
QUICK_WIN = "quick-win"
BACKLOG = "Backlog"
FILED_UPSTREAM = {"jira", "github"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]+$")
# What one pass leaves in its work dir after prepare; the next prepare deletes exactly these.
PASS_FILES = ("candidates.json", "scored.json", "selected.json", "filed.json")
PASS_DIRS = ("scores", "record")


class DiscoveryError(Exception):
    pass


# Policy and settings

def read_json(path):
    """A JSON file whether it is UTF-8, UTF-8 with a BOM, or UTF-16."""
    data = Path(path).expanduser().read_bytes()
    return json.loads(data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"))


def is_count(value, minimum=0):
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def check_lenses(lenses, source):
    if (not isinstance(lenses, list) or not lenses
            or any(not isinstance(lens, str) or not lens.strip() for lens in lenses)):
        raise DiscoveryError(f"{source} must be a non-empty list of Lens names")


def load_policy(paths):
    """The bundled default policy, deep-merged with each path in order, then checked."""
    policy = read_json(DEFAULT_POLICY)
    for path in paths:
        try:
            layer = read_json(path)
        except (OSError, ValueError) as error:
            raise DiscoveryError(f"cannot read Discovery policy {path}: {error}") from error
        if not isinstance(layer, dict):
            raise DiscoveryError(f"Discovery policy {path} must be a JSON object")
        policy = gate.merge(policy, layer)
    weights = policy.get("weights")
    if not isinstance(weights, dict) or set(weights) != set(CRITERIA):
        raise DiscoveryError(f"policy.weights must weigh exactly {list(CRITERIA)}; "
                             f"found {sorted(weights) if isinstance(weights, dict) else weights!r}")
    if any(not is_number(w) or w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise DiscoveryError("policy.weights must be non-negative numbers with a positive sum")
    bands = policy.get("bands")
    if (not isinstance(bands, dict) or set(bands) != set(BANDS)
            or any(not is_number(bands[b]) for b in BANDS)
            or not bands["high"] >= bands["medium"] >= bands["low"]):
        raise DiscoveryError("policy.bands must set numbers high >= medium >= low")
    if not is_count(policy.get("max_candidates"), 1):
        raise DiscoveryError("policy.max_candidates must be a positive integer")
    check_lenses(policy.get("lenses"), "policy.lenses")
    return policy


def entry_policy_paths(entry):
    """The entry's `discovery.policy` layer(s), as paths."""
    value = (entry.get("discovery") or {}).get("policy") if isinstance(entry.get("discovery"), dict) else None
    if value is None:
        return []
    values = value if isinstance(value, list) else [value]
    if any(not isinstance(v, str) or not v.strip() for v in values):
        raise DiscoveryError(f"{entry['match']!r}: discovery.policy must name a policy file")
    return [Path(v).expanduser() for v in values]


def check_target(target, source):
    if not isinstance(target, dict) or target.keys() - council.TARGET_FIELDS:
        raise DiscoveryError(f"{source} accepts providerInstanceId, model and options")
    for field in ("providerInstanceId", "model"):
        if not isinstance(target.get(field), str) or not target[field].strip():
            raise DiscoveryError(f"{source}.{field} must be a non-empty string")


def settings(entry, policy):
    """The pass's Lenses, caps and explicit scorer target (None: the Council's testing-risk seat)."""
    match = entry.get("match")
    found = entry.get("discovery")
    if not isinstance(found, dict):
        raise DiscoveryError(f"{match!r} has no discovery object, so it does not run Discovery")
    upstream = entry.get("upstream") or {}
    kind = upstream.get("type")
    if kind in FILED_UPSTREAM:
        filing = upstream.get("file")
        if not isinstance(filing, dict):
            raise DiscoveryError(f"{match!r} has a {kind} Upstream tracker but no upstream.file object (it may "
                                 "be {}), the owner's opt-in to filing approved Discovered tickets there")
        # project_key is optional: upstream.py defaults it to the match without its trailing -.
        if kind == "jira" and "project_key" in filing and not is_text(filing["project_key"]):
            raise DiscoveryError(f"{match!r}: upstream.file.project_key must be a Jira project key")
    lenses = found.get("lenses", policy["lenses"])
    check_lenses(lenses, f"{match}: discovery.lenses")
    caps = {}
    for name, default in DEFAULT_CAPS.items():
        caps[name] = found.get(name, default)
        if not is_count(caps[name]):
            raise DiscoveryError(f"{match!r}: discovery.{name} must be a non-negative integer")
    target = None
    if "scorer" in found:
        scorer = found["scorer"]
        if not isinstance(scorer, dict) or scorer.keys() != {"target"}:
            raise DiscoveryError(f"{match!r}: discovery.scorer needs exactly a target")
        check_target(scorer["target"], f"{match}: discovery.scorer.target")
        target = scorer["target"]
    return {"lenses": list(lenses), **caps, "scorer_target": target}


def lens_for(day, lenses):
    return lenses[day.toordinal() % len(lenses)]


def room(max_new, max_open, open_backlog):
    return max(0, min(max_new, max_open - open_backlog))


def scorer_seat(config, entry, discoverer_model):
    """The target that scores the candidates; never the Discovery agent's own model."""
    found = entry.get("discovery") if isinstance(entry.get("discovery"), dict) else {}
    scorer = found.get("scorer")
    if isinstance(scorer, dict) and scorer.get("target") is not None:
        check_target(scorer["target"], f"{entry['match']}: discovery.scorer.target")
        target, source = scorer["target"], "discovery.scorer"
    else:
        native = entry["match"].startswith(NATIVE)
        try:
            seats = council.resolve(config, entry["match"],
                                    linear_project=None if native else entry.get("linear_project"))
        except council.ConfigError as error:
            raise DiscoveryError(str(error)) from error
        target, source = seats["testing-risk"]["target"], "the Council's testing-risk seat"
    if gate.model_identity(target["model"]) == gate.model_identity(discoverer_model):
        raise DiscoveryError(f"the scorer ({source}) is {target['model']}, the same model as the Discovery "
                             f"agent's {discoverer_model}; set discovery.scorer to another model")
    return target


def linear_project(entry):
    if entry["match"].startswith(NATIVE):
        return entry["match"][len(NATIVE):]
    name = entry.get("linear_project")
    if not isinstance(name, str) or not name.strip():
        raise DiscoveryError(f"{entry['match']!r} has no linear_project")
    return name


def since(day, clock):
    """The day at the clock's local time of day, less 24 hours, in ISO 8601 with its offset."""
    moment = datetime.combine(day, clock().time()).astimezone()
    return (moment - timedelta(hours=24)).isoformat(timespec="seconds")


def open_backlog(tickets):
    return sum(1 for t in tickets if t.get("state") == BACKLOG
               and any(l.casefold() == DISCOVERED for l in t.get("labels") or []))


def prepare(config, name, discoverer_model, day, linear, clock):
    """Return (prepare, tickets) for the Linear project `name`."""
    entry = project_mod.find(config, linear_project=name)
    policy = load_policy(entry_policy_paths(entry))
    found = settings(entry, policy)
    scorer = scorer_seat(config, entry, discoverer_model)
    team = config.get("linear_team")
    if not isinstance(team, str) or not team.strip():
        raise DiscoveryError("projects.json has no linear_team")
    project = linear_project(entry)
    tickets = linear.list_all(team, project)
    backlog = open_backlog(tickets)
    return {
        "match": entry["match"],
        "linear_project": project,
        "team": team,
        "repo": entry["repo"],
        "base_branch": entry.get("base_branch"),
        "github_account": entry.get("github_account"),
        "lens": lens_for(day, found["lenses"]),
        "room": room(found["max_new"], found["max_open"], backlog),
        "open_backlog": backlog,
        "max_candidates": policy["max_candidates"],
        "since": since(day, clock),
        "scorer": scorer,
        "policy": policy,
        "upstream_type": (entry.get("upstream") or {}).get("type"),
        "native": entry["match"].startswith(NATIVE),
    }, tickets


# Checking the candidates and their scores (references/candidate-schema.md)

def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def is_text_list(value):
    return isinstance(value, list) and bool(value) and all(is_text(v) for v in value)


def candidate_problems(candidate):
    problems = [f"{field} must be non-empty text" for field in ("title", "problem", "why")
                if not is_text(candidate.get(field))]
    problems += [f"{field} must be a non-empty list of non-empty text" for field in ("acceptance_criteria", "evidence")
                 if not is_text_list(candidate.get(field))]
    closest = candidate.get("closest")
    if not isinstance(closest, dict):
        problems.append("closest must be {identifier, why_different}: the nearest Factory ticket, or null and why")
    else:
        identifier = closest.get("identifier", "")
        if identifier is not None and not is_text(identifier):
            problems.append("closest.identifier must be a ticket identifier or null")
        if not is_text(closest.get("why_different")):
            problems.append("closest.why_different must say why this differs from the closest ticket")
    regression = candidate.get("regression_of", "")
    if regression is not None and not is_text(regression):
        problems.append("regression_of must be the Done ticket it regresses, or null")
    return problems


def score_problems(work_dir, cid, title, scorer):
    name = f"scores/{cid}.json"
    try:
        data = read_json(work_dir / "scores" / f"{cid}.json")
    except FileNotFoundError:
        return [f"{name} is missing"]
    except (OSError, ValueError) as error:
        return [f"cannot read {name}: {error}"]
    if not isinstance(data, dict):
        return [f"{name} must be a JSON object"]
    problems = []
    if not is_text(data.get("title")):
        problems.append(f"{name} needs the title of the candidate it scored")
    elif isinstance(title, str) and data["title"] != title:
        problems.append(f"{name} scored {data['title']!r}, not this candidate's title {title!r}")
    scores = data.get("scores")
    if not isinstance(scores, dict):
        problems.append(f"scores must be an object of {', '.join(CRITERIA)}")
    else:
        for criterion in CRITERIA:
            value = scores.get(criterion)
            if criterion not in scores:
                problems.append(f"scores.{criterion} is missing")
            elif not isinstance(value, int) or isinstance(value, bool):
                problems.append(f"scores.{criterion} must be an integer from 0 to 10, not {value!r}")
            elif not 0 <= value <= 10:
                problems.append(f"scores.{criterion} is {value}, outside 0 to 10")
        if scores.keys() - set(CRITERIA):
            problems.append(f"scores has unknown criteria {sorted(scores.keys() - set(CRITERIA))}")
    if data.get("effort") not in EFFORTS:
        problems.append(f"effort must be S, M or L, not {data.get('effort')!r}")
    rationale = data.get("rationale")
    missing = [c for c in CRITERIA if not isinstance(rationale, dict) or not is_text(rationale.get(c))]
    if missing:
        problems.append(f"rationale needs text for {', '.join(missing)}")
    seat = data.get("seat")
    if (not isinstance(seat, dict) or not is_text(seat.get("providerInstanceId")) or not is_text(seat.get("model"))):
        problems.append("seat must name the scorer's providerInstanceId and model")
    elif (seat["providerInstanceId"] != scorer["providerInstanceId"]
          or gate.model_identity(seat["model"]) != gate.model_identity(scorer["model"])):
        problems.append(f"seat is {seat['providerInstanceId']} {seat['model']}, not the scorer prepare.json "
                        f"names ({scorer['providerInstanceId']} {scorer['model']})")
    return problems


def check(work_dir):
    """Every problem with candidates.json and scores/<id>.json; empty when all is well."""
    work_dir = Path(work_dir)
    try:
        prepared = read_json(work_dir / "prepare.json")
        limit, scorer = prepared["max_candidates"], prepared["scorer"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        return [f"cannot read prepare.json: {error!r}"]
    try:
        candidates = read_json(work_dir / "candidates.json")
    except (OSError, ValueError) as error:
        return [f"cannot read candidates.json: {error}"]
    if not isinstance(candidates, list):
        return ["candidates.json must be a list of candidates"]
    problems = []
    if len(candidates) > limit:
        problems.append(f"candidates.json holds {len(candidates)} candidates; max_candidates is {limit}")
    seen = set()
    for number, candidate in enumerate(candidates, 1):
        cid = candidate.get("id") if isinstance(candidate, dict) else None
        if not isinstance(candidate, dict):
            problems.append(f"candidate {number}: must be a JSON object")
            continue
        if not isinstance(cid, str) or not SAFE_ID.match(cid):
            problems.append(f"candidate {number}: id {cid!r} must be letters, digits, - or _")
            continue
        if cid in seen:
            problems.append(f"{cid}: the id appears twice in candidates.json")
            continue
        seen.add(cid)
        problems += [f"{cid}: {p}" for p in candidate_problems(candidate) + score_problems(work_dir, cid, candidate.get("title"), scorer)]
    return problems


# Scoring and selecting

def value_score(scores, weights):
    """Σ weight × score / 10, rounded half up (82.5 is 83)."""
    return math.floor(sum(weights[c] * scores[c] for c in weights) / 10 + 0.5)


def band(score, bands):
    for name in BANDS:
        if score >= bands[name]:
            return name.capitalize()
    return None


def rank(candidates, scores_by_id, policy, room):
    """Every candidate scored, best Value score first (ties in candidate order), each with its
    `outcome`: "below the bar" (no band), "selected" (the first `room` banded ones) or "past the room"."""
    weights, items = policy["weights"], []
    for candidate in candidates:
        scored = scores_by_id[candidate["id"]]
        value = value_score(scored["scores"], weights)
        found = band(value, policy["bands"])
        items.append({**candidate, "value_score": value, "band": found, "effort": scored["effort"],
                      "quick_win": found == "High" and scored["effort"] == "S",
                      "breakdown": [{"criterion": c, "weight": weights[c], "score": scored["scores"][c],
                                     "rationale": scored["rationale"][c]} for c in CRITERIA]})
    items.sort(key=lambda item: -item["value_score"])
    banded = 0
    for item in items:
        if item["band"] is None:
            item["outcome"] = "below the bar"
        else:
            banded += 1
            item["outcome"] = "selected" if banded <= room else "past the room"
    return items


def select(candidates, scores_by_id, policy, room):
    """The candidates that clear the Low band, best Value score first (ties in candidate order), at most room."""
    return [{k: v for k, v in item.items() if k != "outcome"}
            for item in rank(candidates, scores_by_id, policy, room) if item["outcome"] == "selected"]


def bullet(text):
    return "- " + text.strip().replace("\n", "\n  ")


def cell(text):
    return " ".join(text.replace("|", "\\|").split())


def render_description(item):
    """The Discovered ticket's description: the public part, then the Factory notes that stay in Linear."""
    closest = item["closest"]
    lines = ["## Problem", "", item["problem"].strip(), "",
             "## Why it matters", "", item["why"].strip(), "",
             "## Acceptance criteria", "", *map(bullet, item["acceptance_criteria"]), "",
             NOTES_HEADING, "",
             f"**Lens:** {item.get('lens')}", "",
             "**Evidence:**", "", *map(bullet, item["evidence"]), "",
             f"**Value score:** {item['value_score']}/100 ({item['band']})", "",
             "| Criterion | Weight | Score | Rationale |", "|---|---|---|---|",
             *(f"| {b['criterion']} | {b['weight']} | {b['score']} | {cell(b['rationale'])} |"
               for b in item["breakdown"]), "",
             f"**Effort:** {item['effort']}", "",
             f"**Closest ticket:** {closest.get('identifier') or 'none'}: {closest['why_different'].strip()}"]
    if item.get("regression_of"):
        lines += ["", f"**Regression of:** {item['regression_of']}"]
    return "\n".join(lines) + "\n"


def labels_for(item):
    return [DISCOVERED] + ([QUICK_WIN] if item["quick_win"] else [])


def read_input(path):
    try:
        return read_json(path)
    except (OSError, ValueError) as error:
        raise DiscoveryError(f"cannot read {path}: {error}") from error


SCORED_FIELDS = ("id", "title", "value_score", "band", "effort", "quick_win", "outcome")


def score_work_dir(work_dir):
    """Return (problems, {"selected", "dropped"}); scored.json and selected.json are written only
    when there are no problems."""
    problems = check(work_dir)
    if problems:
        return problems, None
    prepared = read_input(work_dir / "prepare.json")
    candidates = read_input(work_dir / "candidates.json")
    scores = {c["id"]: read_input(work_dir / "scores" / f"{c['id']}.json") for c in candidates}
    ranked = rank(candidates, scores, prepared["policy"], max(0, prepared["room"]))
    selected = [{**{k: v for k, v in item.items() if k != "outcome"}, "lens": prepared["lens"]}
                for item in ranked if item["outcome"] == "selected"]
    scored = [{field: item[field] for field in SCORED_FIELDS} for item in ranked]
    write_json(work_dir / "scored.json", scored)
    write_json(work_dir / "selected.json", selected)
    return [], {"selected": [s for s in scored if s["outcome"] == "selected"],
                "dropped": [s for s in scored if s["outcome"] != "selected"]}


def read_filed(work_dir):
    """{number: identifier} of the items an earlier `file` of this pass created."""
    path = work_dir / "filed.json"
    if not path.exists():
        return {}
    filed = read_input(path)
    if not isinstance(filed, list) or any(not isinstance(f, dict) or not {"number", "identifier", "title"} <= f.keys()
                                          for f in filed):
        raise DiscoveryError(f"{path} must be a list of {{number, identifier, title}}")
    return {(f["number"], f["title"]): f["identifier"] for f in filed}


def file_selected(work_dir, linear, dry_run):
    """File each selected item as a Discovered ticket in Backlog, once (a dry run writes record/NN-ticket.md).

    After each create, filed.json records it, so a rerun after a failure skips what was filed.
    The one gap: Linear.create creates, then re-reads the issue; if that read fails, the ticket
    exists but is not recorded, and a rerun files it again."""
    prepared = read_input(work_dir / "prepare.json")
    selected = read_input(work_dir / "selected.json")
    done = {} if dry_run else read_filed(work_dir)
    records = [{"number": n, "identifier": i, "title": t} for (n, t), i in done.items()]
    printed = []
    for number, item in enumerate(selected, 1):
        labels, priority, description = labels_for(item), PRIORITY[item["band"]], render_description(item)
        if dry_run:
            record = work_dir / "record" / f"{number:02d}-ticket.md"
            record.parent.mkdir(parents=True, exist_ok=True)
            record.write_text(f"# {item['title']}\n\n"
                              f"- **Status:** {BACKLOG}\n"
                              f"- **Project:** {prepared['linear_project']}\n"
                              f"- **Labels:** {', '.join(labels)}\n"
                              f"- **Priority:** {priority} ({item['band']})\n\n"
                              f"---\n\n{description}", encoding="utf-8")
            identifier = None
        elif (number, item["title"]) in done:
            identifier = done[(number, item["title"])]
        else:
            try:
                identifier = linear.create(prepared["team"], item["title"], state=BACKLOG,
                                           project=prepared["linear_project"], description=description,
                                           labels=labels, priority=priority)["identifier"]
            except linear_mod.LinearError as error:
                filed = ", ".join(r["identifier"] for r in records) or "none"
                raise linear_mod.LinearError(f"{error} (filed before it: {filed}; rerun `file`: it skips "
                                             "what filed.json records)") from error
            records.append({"number": number, "identifier": identifier, "title": item["title"]})
            write_json(work_dir / "filed.json", records)
        printed.append({"identifier": identifier, "title": item["title"], "value_score": item["value_score"],
                        "band": item["band"], "effort": item["effort"]})
    return printed


def clear_pass(work_dir):
    """Delete the previous pass's outputs from the work dir, and only those."""
    for name in PASS_FILES:
        path = work_dir / name
        if path.is_file() or path.is_symlink():
            path.unlink()
    for name in PASS_DIRS:
        path = work_dir / name
        if path.is_symlink() or path.is_file():
            path.unlink()
        elif path.is_dir():
            shutil.rmtree(path)


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def local_now():
    return datetime.now().astimezone()


def main(argv=None, linear=None, clock=local_now):
    parser = argparse.ArgumentParser(description="The deterministic steps of a Discovery pass.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare", help="settings, Lens, room and scorer seat for today's pass")
    p.add_argument("--linear-project", required=True, help="the repo's Linear project")
    p.add_argument("--discoverer-model", required=True, help="the Discovery agent's own model id")
    p.add_argument("--date", required=True, help="today, as YYYY-MM-DD")
    p.add_argument("--out", required=True, type=Path, help="the pass's work dir")
    p.add_argument("--config", default=str(factory_home() / "projects.json"))
    sub.add_parser("check", help="check candidates.json and scores/<id>.json").add_argument("work_dir", type=Path)
    sub.add_parser("score", help="rank the scored candidates into scored.json and selected.json").add_argument("work_dir", type=Path)
    p = sub.add_parser("file", help="file selected.json as Discovered tickets in Backlog")
    p.add_argument("work_dir", type=Path)
    p.add_argument("--dry-run", action="store_true", help="write record/NN-ticket.md instead of filing")
    args = parser.parse_args(argv)
    for name in ("out", "work_dir", "config"):
        if getattr(args, name, None) is not None:
            setattr(args, name, Path(getattr(args, name)).expanduser())

    try:
        if args.command in ("check", "score"):
            problems, result = (check(args.work_dir), None) if args.command == "check" else score_work_dir(args.work_dir)
            if problems:
                print("\n".join(problems))
                return 1
            if args.command == "check":
                print("ok")
                return 0
        elif args.command == "file":
            result = file_selected(args.work_dir, linear or linear_mod.Linear(), args.dry_run)
        else:
            try:
                day = date.fromisoformat(args.date)
            except ValueError as error:
                raise DiscoveryError(f"--date must be YYYY-MM-DD: {error}") from error
            config = project_mod.read_config(args.config)
            result, tickets = prepare(config, args.linear_project, args.discoverer_model, day,
                                      linear or linear_mod.Linear(), clock)
            clear_pass(args.out)
            write_json(args.out / "tickets.json", tickets)
            write_json(args.out / "prepare.json", result)
    except (DiscoveryError, project_mod.ProjectError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (linear_mod.LinearError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
