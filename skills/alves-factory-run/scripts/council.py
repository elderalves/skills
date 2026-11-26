"""Resolve Council targets from bundled defaults, owner settings and one project.

    python council.py --project PCS- [--config ~/.alves-factory/projects.json] [--policy FILE ...] [--out FILE]

Layers, each replacing whole lenses: the bundled default Council, the top-level
`council`, then the project entry's `council` (an inline object, or the name of
an entry in the top-level `councils`). Every seat names its connection and exact
model. Each --policy file is a gate policy layer, as passed to the review: when
the effective `min_models` is above 1 and the Council seats fewer distinct
models, the run cannot pass, so this exits 2 before any review is paid for.

Exit 2 on unusable config. Provider availability and model options are checked
by the orchestrator at dispatch. An OpenCode model outside opencode-go/ is
allowed, but it bills OpenCode Models credits rather than the Go subscription,
so it prints a warning on stderr.
"""

import argparse
import copy
import json
import sys
from pathlib import Path

REVIEW_SKILL = Path(__file__).resolve().parents[2] / "alves-factory-review"
sys.path.insert(0, str(REVIEW_SKILL / "scripts"))
import gate  # noqa: E402  (shares the gate's policy loading and model identity)
from factory_home import factory_home  # noqa: E402

DEFAULT_COUNCIL = REVIEW_SKILL / "assets" / "default-council.json"
LENSES = {"requirements", "architecture", "testing-risk"}
TARGET_FIELDS = {"providerInstanceId", "model", "options"}
GO_PREFIX = "opencode-go/"


class ConfigError(Exception):
    pass


def read_object(path):
    try:
        value = json.loads(gate.read_text(path))
    except (OSError, ValueError) as error:
        raise ConfigError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ConfigError(f"{path} must contain a JSON object")
    return value


def validate_council(value, source):
    if not isinstance(value, dict):
        raise ConfigError(f"{source} must be an object keyed by reviewer lens")
    if value.keys() - LENSES:
        raise ConfigError(f"{source}: unknown lenses {sorted(value.keys() - LENSES)}")
    for lens, seat in value.items():
        name = f"{source}.{lens}"
        if isinstance(seat, dict) and "provider" in seat:
            raise ConfigError(f"{name}.provider was removed; the connection is target.providerInstanceId")
        if not isinstance(seat, dict) or seat.keys() != {"target"}:
            raise ConfigError(f"{name} needs exactly a target")
        target = seat["target"]
        if not isinstance(target, dict) or target.keys() - TARGET_FIELDS:
            raise ConfigError(f"{name}.target accepts providerInstanceId, model and options")
        for field in ("providerInstanceId", "model"):
            if not isinstance(target.get(field), str) or not target[field].strip():
                raise ConfigError(f"{name}.target.{field} must be a non-empty string")
        if "options" in target:
            options = target["options"]
            if (not isinstance(options, dict)
                    or any(not key.strip() or not isinstance(item, (str, bool))
                           for key, item in options.items())):
                raise ConfigError(f"{name}.target.options must map option IDs to strings or booleans")


def project_council(config, entry, project_match):
    """Return (source, council) for the entry's own layer: inline, named or absent."""
    chosen = entry.get("council", {})
    if not isinstance(chosen, str):
        return f"projects[{project_match}].council", chosen
    councils = config.get("councils", {})
    if not isinstance(councils, dict):
        raise ConfigError("councils must be an object of named Councils")
    if chosen not in councils:
        raise ConfigError(f"projects[{project_match}].council names {chosen!r}, "
                          f"which is not in councils ({sorted(councils) or 'none defined'})")
    return f"councils.{chosen}", councils[chosen]


def resolve(config, project_match, policy=None, warnings=None, linear_project=None):
    """Merge the Council layers; check them against `policy`; append billing warnings.

    Entries sharing one match are told apart by `linear_project` (compared ignoring case)."""
    projects = config.get("projects")
    if not isinstance(projects, list) or any(not isinstance(p, dict) for p in projects):
        raise ConfigError("projects must be a list of objects")
    matches = [p for p in projects if p.get("match") == project_match]
    if linear_project is not None:
        matches = [p for p in matches if isinstance(p.get("linear_project"), str)
                   and p["linear_project"].casefold() == linear_project.casefold()]
    if len(matches) != 1:
        which = f"{project_match!r}" + (f" in Linear project {linear_project!r}" if linear_project else "")
        raise ConfigError(f"project match {which} must select exactly one entry; found {len(matches)}")
    council = read_object(DEFAULT_COUNCIL)
    sources = {}
    for source, layer in (("defaults", council), ("council", config.get("council", {})),
                          project_council(config, matches[0], project_match)):
        validate_council(layer, source)
        council = {**council, **copy.deepcopy(layer)}
        sources.update(dict.fromkeys(layer, source))
    if policy is not None:
        check_model_floor(council, sources, policy["min_models"])
    if warnings is not None:
        warnings.extend(billing_warnings(council, sources))
    return council


def check_model_floor(council, sources, floor):
    models = {gate.model_identity(seat["target"]["model"]) for seat in council.values()}
    if len(models) < floor:
        seated = ", ".join(f"{lens}={council[lens]['target']['model']} ({sources[lens]})"
                           for lens in sorted(council))
        raise ConfigError(f"policy min_models is {floor}, but the Council seats {len(models)} "
                          f"distinct model(s): {seated}. Change the Council or lower min_models "
                          f"in the project's policy file")


def billing_warnings(council, sources):
    """Name each OpenCode seat whose model is not on the Go subscription."""
    found = []
    for lens in sorted(council):
        target = council[lens]["target"]
        model = target["model"]
        if target["providerInstanceId"] == "opencode" and not model.startswith(GO_PREFIX):
            found.append(f"{sources[lens]}.{lens} uses {model}, which bills OpenCode Models "
                         f"credits, not OpenCode Go (Go models start with {GO_PREFIX})")
    return found


def main(argv=None):
    parser = argparse.ArgumentParser(description="Resolve the Council targets for one factory project.")
    parser.add_argument("--project", required=True, help="the selected projects.json entry's exact match value")
    parser.add_argument("--linear-project",
                        help="the selected entry's linear_project, when several entries share its match")
    parser.add_argument("--config", type=Path, default=factory_home() / "projects.json")
    parser.add_argument("--policy", action="append", default=[],
                        help="a gate policy layer, as passed to the review; repeat to layer several")
    parser.add_argument("--out", type=Path, help="write the resolved config into the run's work dir")
    args = parser.parse_args(argv)
    try:
        policy = gate.load_policy(args.policy)
        warnings = []
        result = resolve(read_object(args.config), args.project, policy, warnings, args.linear_project)
        output = json.dumps(result, indent=2) + "\n"
        if args.out:
            args.out.write_text(output, encoding="utf-8")
    except (ConfigError, gate.PolicyError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(output, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
