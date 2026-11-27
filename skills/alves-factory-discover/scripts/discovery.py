"""Run one Discovery pass's deterministic steps: what to look at, how much room, who scores.

    python discovery.py prepare --linear-project <name> --discoverer-model <model> --date YYYY-MM-DD --out <dir> [--config FILE]

`prepare` finds the projects.json entry of the Linear project (project.py --linear-project),
which must carry a `discovery` object, and layers the entry's `discovery.policy` file over the
bundled assets/default-policy.json. It reads every Factory ticket of the project (any status)
into <dir>/tickets.json and writes <dir>/prepare.json, which it also prints:

    {"match", "linear_project", "team", "repo", "base_branch", "lens", "room", "open_backlog",
     "max_candidates", "since", "scorer", "policy", "upstream_type"}

- lens: lenses[date.toordinal() % len(lenses)]; `discovery.lenses` replaces the policy's list.
- room: max(0, min(max_new, max_open - open_backlog)), where open_backlog counts the tickets in
  Backlog labelled `discovered`; room 0 ends the pass before it looks.
- since: the date at the current local clock time, less 24 hours (ISO 8601 with offset).
- scorer: the seat that scores every candidate: `discovery.scorer.target`, else the entry's
  resolved Council testing-risk seat. It is never the Discovery agent's own model.

An entry with an Upstream tracker (jira, github) needs `upstream.file`, and Jira its
`project_key`, so an approved Discovered ticket can be filed there.

Exit codes: 0 ok, 1 on a Linear or file error, 2 on unusable config or arguments, with
`error: ...` on stderr.
"""

import argparse
import json
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

DEFAULT_POLICY = Path(__file__).resolve().parents[1] / "assets" / "default-policy.json"
CRITERIA = ("impact", "engineering", "reach", "evidence", "urgency")
BANDS = ("high", "medium", "low")
DEFAULT_CAPS = {"max_new": 3, "max_open": 10}
NATIVE = project_mod.NATIVE
DISCOVERED = "discovered"
BACKLOG = "Backlog"
FILED_UPSTREAM = {"jira", "github"}


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
            raise DiscoveryError(f"{match!r} has a {kind} Upstream tracker but no upstream.file, so an "
                                 "approved Discovered ticket could not be filed there")
        if kind == "jira" and (not isinstance(filing.get("project_key"), str) or not filing["project_key"].strip()):
            raise DiscoveryError(f"{match!r}: upstream.file needs the Jira project_key to file tickets in")
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
        "lens": lens_for(day, found["lenses"]),
        "room": room(found["max_new"], found["max_open"], backlog),
        "open_backlog": backlog,
        "max_candidates": policy["max_candidates"],
        "since": since(day, clock),
        "scorer": scorer,
        "policy": policy,
        "upstream_type": (entry.get("upstream") or {}).get("type"),
    }, tickets


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
    args = parser.parse_args(argv)

    try:
        try:
            day = date.fromisoformat(args.date)
        except ValueError as error:
            raise DiscoveryError(f"--date must be YYYY-MM-DD: {error}") from error
        config = project_mod.read_config(args.config)
        result, tickets = prepare(config, args.linear_project, args.discoverer_model, day,
                                  linear or linear_mod.Linear(), clock)
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
