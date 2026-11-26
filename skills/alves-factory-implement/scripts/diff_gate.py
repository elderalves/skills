"""Decide one pass of the independent diff review from the Council's diff reviews.

Usage:
    python diff_gate.py <reviews-dir> --council FILE --pass N [--out FILE]
    python diff_gate.py <reviews-dir> --check

Every *.json file in <reviews-dir> is one diff review (format in
references/diff-reviewer-brief.md). --council is the seats the pass dispatched: every
lens in it must have a review, written by that lens's connection and model. The result
is written to --out (default: diff-review.json next to <reviews-dir>) and printed:

    {"result": "clean" | "fix" | "unresolved" | "incomplete", "pass", "reasons",
     "reviews", "majors", "minors"}

- clean: every seat reviewed and no review holds a major finding.
- fix: a major finding on pass 0; the run fixes it and runs pass 1.
- unresolved: a major finding on the last pass; the PR stays a draft with it listed.
- incomplete: a review is missing, malformed or off its seat; nothing independent
  vouches for the diff, so the PR stays a draft.

Exit codes: 0 when a result was written (whatever it is), 1 in --check mode when any
review has a problem, 2 when the arguments or the Council are unusable.
"""

import argparse
import json
import sys
from pathlib import Path

REVIEW_SCRIPTS = Path(__file__).resolve().parents[2] / "alves-factory-review" / "scripts"
sys.path.insert(0, str(REVIEW_SCRIPTS))
import gate  # noqa: E402  (shares the Council loading and seat check)

MAX_FIX_PASSES = 1
VERDICTS = {"approve", "changes"}
SEVERITIES = {"major", "minor"}
FINDING_TEXT = ("file", "problem", "evidence", "fix")


def read_json(path):
    return json.loads(gate.read_text(path))


def load_reviews(reviews_dir):
    """Return (reviews, problems). Unreadable files become problems, never exceptions."""
    reviews, problems = [], []
    for path in sorted(Path(reviews_dir).glob("*.json")):
        try:
            review = read_json(path)
        except (OSError, ValueError) as error:
            problems.append(f"{path.name}: unreadable ({error})")
            continue
        if isinstance(review, dict):
            review.setdefault("reviewer", path.stem)
        reviews.append(review)
    return reviews, problems


def validate_review(review):
    """Return a list of problems with one diff review."""
    if not isinstance(review, dict):
        return ["review is not a JSON object"]
    name = review.get("reviewer", "?")
    problems = []
    for field in ("provider_instance", "model"):
        if not isinstance(review.get(field), str) or not review[field].strip():
            problems.append(f"{name}: {field} is missing")
    if review.get("verdict") not in VERDICTS:
        problems.append(f"{name}: verdict must be one of {sorted(VERDICTS)}")
    findings = review.get("findings")
    if not isinstance(findings, list):
        return problems + [f"{name}: findings must be a list"]
    for index, finding in enumerate(findings):
        where = f"{name}: findings[{index}]"
        if not isinstance(finding, dict):
            problems.append(f"{where} is not an object")
            continue
        if finding.get("severity") not in SEVERITIES:
            problems.append(f"{where}.severity must be one of {sorted(SEVERITIES)}")
        for field in FINDING_TEXT:
            if not isinstance(finding.get(field), str) or not finding[field].strip():
                problems.append(f"{where}.{field} is missing")
        line = finding.get("line")
        if line is not None and (not isinstance(line, int) or isinstance(line, bool) or line < 1):
            problems.append(f"{where}.line must be a line number or null")
    if not isinstance(review.get("previous_findings", []), list):
        problems.append(f"{name}: previous_findings must be a list")
    if problems:
        return problems
    majors = [f for f in findings if f["severity"] == "major"]
    if review["verdict"] == "approve" and majors:
        problems.append(f"{name}: approve allows only minor findings")
    if review["verdict"] == "changes" and not majors:
        problems.append(f"{name}: changes needs at least one major finding")
    return problems


def evaluate(reviews, council, pass_number, load_problems=()):
    """Return the pass's result record."""
    problems = list(load_problems)
    for review in reviews:
        problems.extend(validate_review(review))

    def record(result, reasons, summaries=(), majors=(), minors=()):
        return {"result": result, "pass": pass_number, "reasons": reasons,
                "reviews": list(summaries), "majors": list(majors), "minors": list(minors)}

    if problems:
        return record("incomplete", problems)
    mismatches = gate.council_mismatches(reviews, council)
    reviewed = {r["reviewer"] for r in reviews}
    missing = [f"{lens}: no review" for lens in council if lens not in reviewed]
    if mismatches or missing:
        return record("incomplete", missing + mismatches)

    summaries, majors, minors = [], [], []
    for review in reviews:
        name = review["reviewer"]
        mine = [{"reviewer": name, **f} for f in review["findings"]]
        summaries.append({
            "reviewer": name,
            "provider_instance": review["provider_instance"],
            "model": review["model"],
            "verdict": review["verdict"],
            "majors": sum(f["severity"] == "major" for f in mine),
            "minors": sum(f["severity"] == "minor" for f in mine),
        })
        majors += [f for f in mine if f["severity"] == "major"]
        minors += [f for f in mine if f["severity"] == "minor"]

    if not majors:
        return record("clean", [f"{len(reviews)} reviews, no major finding"], summaries, majors, minors)
    reasons = [f"{f['reviewer']}: {f['problem']} ({f['file']}"
               + (f":{f['line']})" if f.get("line") else ")") for f in majors]
    if pass_number < MAX_FIX_PASSES:
        return record("fix", reasons, summaries, majors, minors)
    return record("unresolved", reasons, summaries, majors, minors)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Decide one pass of the independent diff review.")
    parser.add_argument("reviews_dir", type=Path)
    parser.add_argument("--council", type=Path, help="the seats this pass dispatched; required unless --check")
    parser.add_argument("--pass", type=int, dest="pass_number", help="0 for the first pass, 1 after the fix")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--check", action="store_true",
                        help="only validate the reviews: print each problem, exit 1 when there is any")
    args = parser.parse_args(argv)

    if not args.reviews_dir.is_dir():
        parser.error(f"{args.reviews_dir} is not a directory")
    reviews, problems = load_reviews(args.reviews_dir)
    if args.check:
        for review in reviews:
            problems.extend(validate_review(review))
        print("\n".join(problems) or "ok")
        return 1 if problems else 0

    if args.council is None or args.pass_number is None:
        parser.error("--council and --pass are required unless --check is given")
    if args.pass_number < 0:
        parser.error("--pass must be 0 or more")
    try:
        council = gate.load_council(args.council)
    except gate.PolicyError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    result = evaluate(reviews, council, args.pass_number, problems)
    out = args.out or args.reviews_dir.resolve().parent / "diff-review.json"
    out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("result", "pass", "reasons")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
