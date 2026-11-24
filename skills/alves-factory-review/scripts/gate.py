"""Apply the factory's policy to one Council round and write the Gate decision.

Usage:
    python gate.py <reviews-dir> --revision N [--risk-flag ID ...] [--policy FILE ...] [--out FILE]

Every *.json file in <reviews-dir> is one Plan review. Each --policy file is
merged over the bundled default policy, in the order given. The decision is
written to --out (default: decision.json next to <reviews-dir>) and printed.

Exit codes: 0 when a decision was written (including escalate), 2 when the
arguments or the policy are unusable, so the caller should mark the run Blocked.
"""

import argparse
import json
import math
import sys
from pathlib import Path


DEFAULT_POLICY = Path(__file__).resolve().parent.parent / "assets" / "default-policy.json"
VERDICTS = {"approve", "revise", "escalate"}


class PolicyError(Exception):
    pass


def merge(base, override):
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_policy(paths):
    policy = json.loads(DEFAULT_POLICY.read_text(encoding="utf-8"))
    for path in paths:
        try:
            override = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PolicyError(f"cannot read policy {path}: {error}") from error
        if not isinstance(override, dict):
            raise PolicyError(f"policy {path} must be a JSON object")
        policy = merge(policy, override)
    check_policy(policy)
    return policy


def check_policy(policy):
    weights = policy.get("weights")
    if not isinstance(weights, dict) or not weights:
        raise PolicyError("policy.weights must be a non-empty object")
    if any(not is_number(w) or w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise PolicyError("policy.weights must be non-negative numbers with a positive sum")
    implement = policy.get("implement", {})
    numbers = [
        policy.get("min_reviews"),
        policy.get("min_providers"),
        policy.get("escalate_below_average"),
        policy.get("max_revisions"),
        implement.get("min_average"),
        implement.get("min_lowest"),
        implement.get("max_spread"),
    ]
    if any(not is_number(n) for n in numbers):
        raise PolicyError("policy is missing a numeric threshold")


def is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_reviews(reviews_dir):
    """Return (reviews, problems). Unreadable files become problems, never exceptions."""
    reviews, problems = [], []
    for path in sorted(Path(reviews_dir).glob("*.json")):
        try:
            review = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            problems.append(f"{path.name}: unreadable ({error})")
            continue
        if isinstance(review, dict):
            review.setdefault("reviewer", path.stem)
        reviews.append(review)
    return reviews, problems


def validate_review(review, weights):
    """Return a list of problems with one Plan review."""
    if not isinstance(review, dict):
        return ["review is not a JSON object"]
    name = review.get("reviewer", "?")
    problems = []
    if not isinstance(review.get("provider"), str) or not review["provider"].strip():
        problems.append(f"{name}: provider is missing")
    if review.get("verdict") not in VERDICTS:
        problems.append(f"{name}: verdict must be one of {sorted(VERDICTS)}")
    scores = review.get("scores")
    if not isinstance(scores, dict):
        problems.append(f"{name}: scores must be an object")
    else:
        for criterion in weights:
            score = scores.get(criterion)
            if not is_number(score) or not 0 <= score <= 100:
                problems.append(f"{name}: scores.{criterion} must be a number from 0 to 100")
    for field in ("blockers", "issues", "risk_flags"):
        if not isinstance(review.get(field, []), list):
            problems.append(f"{name}: {field} must be a list")
    return problems


def weighted_score(scores, weights):
    total = sum(weights.values())
    return sum(scores[c] * w for c, w in weights.items()) / total


def evaluate(reviews, revision, plan_risk_flags, policy, load_problems=()):
    """Apply the gate rules in order and return the decision record."""
    weights = policy["weights"]
    problems = list(load_problems)
    for review in reviews:
        problems.extend(validate_review(review, weights))

    valid = not problems
    summaries = []
    blockers, issues, risk_flags = [], [], list(plan_risk_flags)
    for review in reviews:
        if not isinstance(review, dict):
            continue
        name = review.get("reviewer", "?")
        if valid:
            summaries.append({
                "reviewer": name,
                "provider": review["provider"],
                "verdict": review["verdict"],
                "score": round(weighted_score(review["scores"], weights), 1),
            })
        blockers += [{"reviewer": name, "blocker": b} for b in review.get("blockers", []) if valid]
        issues += [{"reviewer": name, "issue": i} for i in review.get("issues", []) if valid]
        risk_flags += [f for f in review.get("risk_flags", []) if valid and f not in risk_flags]

    scores = [s["score"] for s in summaries]
    average = round(sum(scores) / len(scores), 1) if scores else None
    lowest = min(scores) if scores else None
    spread = round(max(scores) - min(scores), 1) if scores else None
    providers = {s["provider"].strip().lower() for s in summaries}
    unknown_flags = [f for f in risk_flags if f not in policy.get("risk_flags", {})]

    def decide(decision, rule, reasons):
        return {
            "decision": decision,
            "rule": rule,
            "reasons": reasons,
            "revision": revision,
            "plan_score": average,
            "lowest": lowest,
            "spread": spread,
            "providers": sorted(providers),
            "reviews": summaries,
            "blockers": blockers,
            "issues": issues,
            "risk_flags": risk_flags,
            "unknown_risk_flags": unknown_flags,
        }

    # Rule 1: anything that makes the round untrustworthy or needs the owner.
    if problems:
        return decide("escalate", "invalid-reviews", problems)
    if len(reviews) < policy["min_reviews"]:
        return decide("escalate", "too-few-reviews",
                      [f"{len(reviews)} reviews, policy needs {policy['min_reviews']}"])
    if len(providers) < policy["min_providers"]:
        return decide("escalate", "single-provider",
                      [f"{len(providers)} providers, policy needs {policy['min_providers']}"])
    if blockers:
        return decide("escalate", "blockers", [f"{len(blockers)} Blocker(s) need the owner"])
    if risk_flags:
        return decide("escalate", "risk-flags", [f"Risk flag: {f}" for f in risk_flags])
    escalating = [s["reviewer"] for s in summaries if s["verdict"] == "escalate"]
    if escalating:
        return decide("escalate", "reviewer-escalated", [f"{r} voted escalate" for r in escalating])

    # Rule 2: a strong, consistent, unanimous round.
    bar = policy["implement"]
    if (average >= bar["min_average"] and lowest >= bar["min_lowest"]
            and spread <= bar["max_spread"] and all(s["verdict"] == "approve" for s in summaries)):
        return decide("implement", "meets-bar",
                      [f"Plan score {average}, lowest {lowest}, spread {spread}, all approve"])

    # Rule 3: too weak to revise, or out of revisions.
    if average < policy["escalate_below_average"]:
        return decide("escalate", "score-too-low",
                      [f"Plan score {average} is below {policy['escalate_below_average']}"])
    if revision >= policy["max_revisions"]:
        return decide("escalate", "revision-cap",
                      [f"Revision {revision} reached the cap of {policy['max_revisions']}"])

    # Rule 4: close enough to fix.
    reasons = [f"Plan score {average}, lowest {lowest}, spread {spread}"]
    reasons += [f"{s['reviewer']} voted {s['verdict']}" for s in summaries if s["verdict"] != "approve"]
    return decide("revise", "below-bar", reasons)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Apply the factory policy to one Council round.")
    parser.add_argument("reviews_dir", type=Path)
    parser.add_argument("--revision", type=int, required=True,
                        help="0 for the first Plan, 1 after the first Revise, and so on")
    parser.add_argument("--risk-flag", action="append", default=[], dest="risk_flags",
                        help="a Risk flag the Plan declares; repeat for several")
    parser.add_argument("--policy", action="append", default=[],
                        help="a policy override file; repeat to layer several")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    if args.revision < 0:
        parser.error("--revision must be 0 or more")
    if not args.reviews_dir.is_dir():
        parser.error(f"{args.reviews_dir} is not a directory")
    try:
        policy = load_policy(args.policy)
    except PolicyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    reviews, problems = load_reviews(args.reviews_dir)
    record = evaluate(reviews, args.revision, args.risk_flags, policy, problems)
    record["policy"] = policy

    out = args.out or args.reviews_dir.resolve().parent / "decision.json"
    out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    print(record["decision"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
