"""Apply the factory's design policy to one design Council round and write its decision.

Usage:
    python design_gate.py <round-dir> --mode explore|refine --council FILE [--previous FILE ...] [--policy FILE ...] [--out FILE]
    python design_gate.py <round-dir> --check [--policy FILE ...]
    python design_gate.py --check-council FILE [--policy FILE ...]

<round-dir> holds designs.json (the designs under review, with their screens) and
one review per design and seat at reviews/<design>/<seat>.json. --council is the
round's resolved design Council: each review must come from its seat's configured
connection and model. Each --policy file is merged over the bundled default
policy, in the order given.

explore ranks every design by its weighted score, puts vetoed designs last and
recommends the best design that is not vetoed. refine reviews one design and
applies the Refinement stop rule; --previous lists the earlier Refinement rounds'
decision.json files, oldest first.

--check validates the reviews only. --check-council validates a Council against
the policy before any reviewer is paid for.

Exit codes: 0 when a decision was written (including "invalid") or a check passed,
1 when --check found problems, 2 when the arguments, policy, Council, designs.json
or previous decisions are unusable, so the caller should stop as blocked.
"""

import argparse
import json
import math
import re
import sys
from pathlib import Path

PLAN_GATE = Path(__file__).resolve().parents[2] / "alves-factory-review" / "scripts"
sys.path.insert(0, str(PLAN_GATE))
import gate as plan_gate  # noqa: E402  (shares tolerant JSON reading and model identity)

DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "assets" / "default-policy.json"
SEVERITIES = {"major", "minor"}
DESIGN_ID = re.compile(r"^[A-Za-z0-9_-]+$")
read_text = plan_gate.read_text
model_identity = plan_gate.model_identity


class PolicyError(Exception):
    pass


def merge(base, override):
    """Deep-merge objects; lists and scalars in the override replace the base."""
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def is_text(value):
    return isinstance(value, str) and bool(value.strip())


def read_json(path, what):
    try:
        return json.loads(read_text(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise PolicyError(f"cannot read {what} {path}: {error}") from error


# ---------- policy ----------

def load_policy(paths):
    policy = read_json(DEFAULT_POLICY, "default policy")
    for path in paths:
        override = read_json(path, "policy")
        if not isinstance(override, dict):
            raise PolicyError(f"policy {path} must be a JSON object")
        policy = merge(policy, override)
    check_policy(policy)
    return policy


def check_policy(policy):
    seats, weights = policy.get("seats"), policy.get("weights")
    if not isinstance(seats, dict) or not seats:
        raise PolicyError("policy.seats must be a non-empty object of seat -> criteria")
    if any(not isinstance(c, list) or not c or not all(is_text(x) for x in c) for c in seats.values()):
        raise PolicyError("each policy.seats entry must be a non-empty list of criterion names")
    owned = [c for criteria in seats.values() for c in criteria]
    if len(owned) != len(set(owned)):
        raise PolicyError("each criterion must belong to exactly one seat")
    if not isinstance(weights, dict) or set(weights) != set(owned):
        raise PolicyError("policy.weights must have exactly one weight per seat criterion")
    if any(not is_number(w) or w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise PolicyError("policy.weights must be non-negative numbers with a positive sum")
    veto = policy.get("veto_categories")
    if not isinstance(veto, list) or not set(veto) <= set(owned):
        raise PolicyError("policy.veto_categories must be a list of seat criteria")
    if not is_number(policy.get("finding_below")) or not 0 <= policy["finding_below"] <= 10:
        raise PolicyError("policy.finding_below must be a number from 0 to 10")
    if not is_int(policy.get("min_models")) or policy["min_models"] < 1:
        raise PolicyError("policy.min_models must be an integer of at least 1")
    excluded = policy.get("excluded_connections", [])
    if not isinstance(excluded, list) or not all(isinstance(x, str) for x in excluded):
        raise PolicyError("policy.excluded_connections must be a list of connection IDs")
    refine = policy.get("refine")
    if not isinstance(refine, dict):
        raise PolicyError("policy.refine must be an object")
    if not is_int(refine.get("max_rounds")) or refine["max_rounds"] < 1:
        raise PolicyError("policy.refine.max_rounds must be an integer of at least 1")
    if not is_int(refine.get("plateau_rounds")) or refine["plateau_rounds"] < 1:
        raise PolicyError("policy.refine.plateau_rounds must be an integer of at least 1")
    if not is_number(refine.get("plateau_delta")) or refine["plateau_delta"] < 0:
        raise PolicyError("policy.refine.plateau_delta must be a non-negative number")
    mark = refine.get("pass_mark")
    if mark is not None and (not is_number(mark) or not 0 <= mark <= 10):
        raise PolicyError("policy.refine.pass_mark must be null or a number from 0 to 10")


# ---------- Council ----------

def check_council(council, policy, source="council"):
    """Validate a resolved design Council against the policy; raise PolicyError on any problem."""
    if not isinstance(council, dict):
        raise PolicyError(f"{source} must be a JSON object keyed by seat")
    seats = set(policy["seats"])
    if set(council) != seats:
        raise PolicyError(f"{source} must seat exactly {sorted(seats)}, got {sorted(council)}")
    models = set()
    for seat, entry in council.items():
        target = entry.get("target") if isinstance(entry, dict) else None
        if not isinstance(target, dict) or not is_text(target.get("providerInstanceId")) or not is_text(target.get("model")):
            raise PolicyError(f"{source}.{seat} needs a target with providerInstanceId and model")
        if target["providerInstanceId"] in policy.get("excluded_connections", []):
            raise PolicyError(f"{source}.{seat}: connection {target['providerInstanceId']} is excluded from design review")
        models.add(model_identity(target["model"]))
    if len(models) < policy["min_models"]:
        raise PolicyError(f"{source} seats {len(models)} distinct model(s), policy needs {policy['min_models']}")


def load_council(path, policy):
    council = read_json(path, "council")
    check_council(council, policy, str(path))
    return council


# ---------- designs and reviews ----------

def load_designs(round_dir):
    """Return the designs list from <round-dir>/designs.json; raise PolicyError when unusable."""
    data = read_json(Path(round_dir) / "designs.json", "designs")
    designs = data.get("designs") if isinstance(data, dict) else None
    if not isinstance(designs, list) or not designs:
        raise PolicyError("designs.json must hold a non-empty designs list")
    seen = set()
    for design in designs:
        did = design.get("id") if isinstance(design, dict) else None
        if not isinstance(did, str) or not DESIGN_ID.match(did) or did in seen:
            raise PolicyError(f"designs.json: every design needs a unique id of letters, digits, - or _ (got {did!r})")
        seen.add(did)
        screens = design.get("screens")
        if not isinstance(screens, list) or not screens or not all(isinstance(s, dict) and is_text(s.get("path")) for s in screens):
            raise PolicyError(f"designs.json: design {did} needs at least one screen with a path")
    return designs


def norm(path):
    return str(path).replace("\\", "/").strip().lstrip("./")


def load_reviews(round_dir, designs, policy):
    """Return ({design: {seat: review}}, problems). Unreadable or stray files become problems."""
    reviews = {d["id"]: {} for d in designs}
    problems = []
    root = Path(round_dir) / "reviews"
    for path in sorted(root.glob("*/*.json")) if root.is_dir() else []:
        design, seat = path.parent.name, path.stem
        if design not in reviews:
            problems.append(f"reviews/{design}: no such design in designs.json")
            continue
        if seat not in policy["seats"]:
            problems.append(f"reviews/{design}/{path.name}: no such seat in the policy")
            continue
        try:
            reviews[design][seat] = json.loads(read_text(path))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            problems.append(f"reviews/{design}/{path.name}: unreadable ({error})")
    for d in designs:
        for seat in policy["seats"]:
            if seat not in reviews[d["id"]] and not any(p.startswith(f"reviews/{d['id']}/{seat}.json") for p in problems):
                problems.append(f"{d['id']}: no review from {seat}")
    return reviews, problems


def validate_review(review, design, seat, policy):
    """Return the problems with one design review (seat and design come from its path)."""
    name = f"{design['id']}/{seat}"
    if not isinstance(review, dict):
        return [f"{name}: review is not a JSON object"]
    problems = []
    if review.get("seat", seat) != seat:
        problems.append(f"{name}: seat field says {review.get('seat')!r}")
    if review.get("design", design["id"]) != design["id"]:
        problems.append(f"{name}: design field says {review.get('design')!r}")
    for field in ("provider_instance", "model"):
        if not is_text(review.get(field)):
            problems.append(f"{name}: {field} is missing")
    own = policy["seats"][seat]
    viewed = review.get("screens_viewed")
    if not isinstance(viewed, list):
        problems.append(f"{name}: screens_viewed must be a list")
    else:
        seen = {norm(v) for v in viewed if isinstance(v, str)}
        problems += [f"{name}: did not view {s['path']}" for s in design["screens"] if norm(s["path"]) not in seen]
    scores, rationale = review.get("scores"), review.get("rationale")
    if not isinstance(scores, dict) or set(scores) != set(own):
        problems.append(f"{name}: scores must cover exactly {own}")
    elif any(not is_int(scores[c]) or not 0 <= scores[c] <= 10 for c in own):
        problems.append(f"{name}: every score must be an integer from 0 to 10")
    if not isinstance(rationale, dict) or any(not is_text(rationale.get(c)) for c in own):
        problems.append(f"{name}: rationale needs a visible element and reason for each of {own}")
    defects, findings = review.get("critical_defects"), review.get("findings")
    categories = set(policy["veto_categories"]) | {"other"}
    if not isinstance(defects, list) or any(
            not isinstance(d, dict) or d.get("category") not in categories
            or not is_text(d.get("element")) or not is_text(d.get("problem")) for d in defects):
        problems.append(f"{name}: each critical defect needs a category in {sorted(categories)}, an element and a problem")
    if not isinstance(findings, list) or any(
            not isinstance(f, dict) or f.get("criterion") not in policy["weights"] or f.get("severity") not in SEVERITIES
            or not all(is_text(f.get(k)) for k in ("element", "problem", "fix")) for f in findings):
        problems.append(f"{name}: each finding needs a rubric criterion, a severity of major or minor, an element, a problem and a fix")
    strengths = review.get("strengths", [])
    if not isinstance(strengths, list) or not all(is_text(s) for s in strengths):
        problems.append(f"{name}: strengths must be a list of sentences")
    if problems:
        return problems
    for criterion in own:
        backed = any(f["criterion"] == criterion and f["severity"] == "major" for f in findings) or \
            any(d["category"] == criterion for d in defects)
        if scores[criterion] < policy["finding_below"] and not backed:
            problems.append(f"{name}: {criterion} scored {scores[criterion]}, below {policy['finding_below']}, "
                            f"with no major finding or critical defect under it")
    return problems


def validate_round(round_dir, designs, policy):
    reviews, problems = load_reviews(round_dir, designs, policy)
    for d in designs:
        for seat, review in reviews[d["id"]].items():
            problems += validate_review(review, d, seat, policy)
    return reviews, problems


def council_mismatches(reviews, council):
    found = []
    for design, by_seat in reviews.items():
        for seat, review in by_seat.items():
            target = council[seat]["target"]
            expected = (target["providerInstanceId"], target["model"])
            actual = (review["provider_instance"].strip(), review["model"].strip())
            if actual != expected:
                found.append(f"{design}/{seat}: written by {actual[1]} via {actual[0]}, "
                             f"Council seats {expected[1]} via {expected[0]}")
    return found


# ---------- scoring ----------

def summarise(design, by_seat, policy):
    """One design's score, veto and evidence, drawn only from its reviews."""
    weights = policy["weights"]
    criteria, defects, findings, strengths = {}, [], [], []
    for seat, review in by_seat.items():
        for c in policy["seats"][seat]:
            criteria[c] = {"score": review["scores"][c], "seat": seat, "model": review["model"],
                           "rationale": review["rationale"][c]}
        defects += [{"seat": seat, **d} for d in review["critical_defects"]]
        findings += [{"seat": seat, **f} for f in review["findings"]]
        strengths += [{"seat": seat, "strength": s} for s in review.get("strengths", [])]
    score = round(sum(criteria[c]["score"] * w for c, w in weights.items()) / sum(weights.values()), 2)
    vetoes = [d for d in defects if d["category"] in policy["veto_categories"]]
    findings.sort(key=lambda f: (f["severity"] != "major", -weights[f["criterion"]]))
    return {
        "id": design["id"],
        "hypothesis": design.get("hypothesis"),
        "score": score,
        "vetoed": bool(vetoes),
        "veto_reasons": [f"critical {d['category']} defect: {d['problem']} ({d['element']})" for d in vetoes],
        "major_findings": sum(f["severity"] == "major" for f in findings),
        "criteria": criteria,
        "critical_defects": defects,
        "findings": findings,
        "strengths": strengths,
    }


def explore(summaries):
    ranked = sorted(summaries, key=lambda s: (s["vetoed"], -s["score"], s["id"]))
    eligible = [s for s in ranked if not s["vetoed"]]
    if not eligible:
        return {"decision": "ranked", "rule": "all-vetoed", "recommendation": None,
                "reasons": ["every design has a critical usability or accessibility defect"],
                "ranking": [s["id"] for s in ranked]}
    best = eligible[0]
    reasons = [f"{best['id']} scores {best['score']}, the highest of the designs without a veto"]
    reasons += [f"{s['id']} is vetoed: {'; '.join(s['veto_reasons'])}" for s in ranked if s["vetoed"]]
    return {"decision": "ranked", "rule": "recommend", "recommendation": best["id"],
            "reasons": reasons, "ranking": [s["id"] for s in ranked]}


def refine(summary, history, policy):
    """Apply the Refinement stop rule to this round, given earlier rounds' scores (oldest first)."""
    rules = policy["refine"]
    scores = [h["score"] for h in history] + [summary["score"]]
    round_no = len(scores)
    trail = [{"round": i + 1, "score": s} for i, s in enumerate(scores)]

    def decide(decision, rule, reasons):
        return {"decision": decision, "rule": rule, "reasons": reasons, "round": round_no, "history": trail}

    if not summary["critical_defects"] and summary["major_findings"] == 0:
        return decide("stop", "clean", [f"score {summary['score']} with no critical defect or major finding left"])
    mark = rules["pass_mark"]
    if mark is not None and not summary["vetoed"] and summary["score"] >= mark:
        return decide("stop", "meets-pass-mark", [f"score {summary['score']} reaches the pass mark {mark}"])
    if round_no >= rules["max_rounds"]:
        return decide("stop", "round-cap", [f"round {round_no} reached the cap of {rules['max_rounds']}"])
    window = rules["plateau_rounds"]
    if round_no > window:
        gains = [round(scores[i] - scores[i - 1], 2) for i in range(round_no - window, round_no)]
        if all(g < rules["plateau_delta"] for g in gains):
            return decide("stop", "plateau", [f"gains {gains} over the last {window} rounds are each below {rules['plateau_delta']}"])
    reasons = [f"score {summary['score']}, {len(summary['critical_defects'])} critical defect(s), "
               f"{summary['major_findings']} major finding(s)"]
    return decide("continue", "below-stop", reasons)


def load_history(paths, policy):
    history = []
    for i, path in enumerate(paths):
        record = read_json(path, "previous decision")
        design = record.get("design") if isinstance(record, dict) else None
        if not isinstance(record, dict) or record.get("mode") != "refine" or record.get("decision") == "invalid" \
                or not isinstance(design, dict) or not is_number(design.get("score")):
            raise PolicyError(f"previous decision {path} is not a valid Refinement round")
        if record.get("round") != i + 1:
            raise PolicyError(f"previous decision {path} is round {record.get('round')}, expected round {i + 1}")
        history.append({"round": i + 1, "score": design["score"]})
    return history


def evaluate(mode, designs, reviews, problems, council, policy, history=()):
    base = {"mode": mode, "models": sorted({model_identity(t["target"]["model"]) for t in council.values()})}
    if problems:
        return {**base, "decision": "invalid", "rule": "invalid-reviews", "reasons": problems}
    mismatches = council_mismatches(reviews, council)
    if mismatches:
        return {**base, "decision": "invalid", "rule": "council-mismatch", "reasons": mismatches}
    summaries = [summarise(d, reviews[d["id"]], policy) for d in designs]
    if mode == "explore":
        return {**base, **explore(summaries), "designs": summaries}
    return {**base, **refine(summaries[0], list(history), policy), "design": summaries[0]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply the design policy to one design Council round.")
    parser.add_argument("round_dir", type=Path, nargs="?")
    parser.add_argument("--mode", choices=["explore", "refine"])
    parser.add_argument("--council", type=Path, help="the round's resolved design Council (council.json)")
    parser.add_argument("--previous", action="append", default=[], type=Path,
                        help="an earlier Refinement round's decision.json; repeat, oldest first")
    parser.add_argument("--policy", action="append", default=[], help="a design policy override; repeat to layer")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true", help="only validate the reviews")
    parser.add_argument("--check-council", type=Path, metavar="FILE", help="only validate a Council against the policy")
    args = parser.parse_args(argv)

    try:
        policy = load_policy(args.policy)
        if args.check_council:
            load_council(args.check_council, policy)
            print("ok")
            return 0
        if args.round_dir is None or not args.round_dir.is_dir():
            parser.error("a round directory is required")
        designs = load_designs(args.round_dir)
        if args.check:
            _, problems = validate_round(args.round_dir, designs, policy)
            print("\n".join(problems) or "ok")
            return 1 if problems else 0
        if args.mode is None or args.council is None:
            parser.error("--mode and --council are required unless --check or --check-council is given")
        if args.mode == "refine" and len(designs) != 1:
            raise PolicyError("a Refinement round reviews exactly one design")
        if args.mode == "explore" and args.previous:
            raise PolicyError("--previous applies only to Refinement rounds")
        council = load_council(args.council, policy)
        history = load_history(args.previous, policy) if args.mode == "refine" else []
    except PolicyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    reviews, problems = validate_round(args.round_dir, designs, policy)
    record = evaluate(args.mode, designs, reviews, problems, council, policy, history)
    record["policy"] = policy
    out = args.out or args.round_dir / "decision.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    line = record["decision"]
    if record.get("recommendation"):
        line += f" {record['recommendation']}"
    print(f"{line} ({record['rule']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
