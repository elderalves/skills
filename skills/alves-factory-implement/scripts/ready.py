"""Decide whether a finished implementation run may promote its draft PR (the ready check).

Usage:
    python ready.py --pr-ready auto|draft --decision FILE --verification FILE
                    [--diff-review FILE] [--checks FILE --pr-body FILE [--evidence FILE]]
                    [--risk-flag ID ...] [--out FILE]

--decision is the last Council round's decision.json; --verification is the run's
verification.json (format in references/ready-check.md); --diff-review is the last pass
of the independent diff review (diff_gate.py's output), a missing one keeping the draft;
--checks is the output of `gh pr checks <pr> --json name,bucket`, left out in a dry run;
--pr-body is the body the PR was opened with, required with --checks, and --evidence is
publish_evidence.py's output, left out when no screenshot was published: every image the body
shows must be one that script verified on GitHub. Each --risk-flag is one the Plan declares.
Prints and writes (to --out, when given) {"ready", "reasons"}: when
ready is false, reasons names every condition that failed, in plain words.

Exit codes: 0 when a result was written (ready or not), 2 when an input is unusable,
so the PR stays a draft and the caller names the error.
"""

import argparse
import json
import re
import sys
from pathlib import Path


MODES = {"auto", "draft"}
PASSING = {"pass", "skipping"}
RESULTS = {"pass", "fail"}
DIFF_RESULTS = {"clean", "fix", "unresolved", "incomplete"}
IMAGE = re.compile(r"""!\[[^\]]*\]\(\s*<?([^)\s>]+)>?[^)]*\)|<img\b[^>]*\bsrc=["']([^"']+)["']""", re.IGNORECASE)


class InputError(Exception):
    pass


def read_text(path):
    """A file's text, honouring a UTF-8 or UTF-16 byte-order mark (PowerShell's `>` writes UTF-16)."""
    data = Path(path).read_bytes()
    return data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")


def read_json(path, what):
    try:
        return json.loads(read_text(path))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InputError(f"cannot read {what} {path}: {error}") from error


def check_verification(verification):
    if not isinstance(verification, dict):
        raise InputError("verification must be a JSON object")
    checks = verification.get("checks")
    if not isinstance(checks, list) or not checks:
        raise InputError("verification.checks must be a non-empty list")
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("command"), str):
            raise InputError("each verification check needs a command")
        if check.get("result") not in RESULTS:
            raise InputError(f"check {check['command']!r}: result must be one of {sorted(RESULTS)}")
        if check.get("baseline") not in RESULTS | {None}:
            raise InputError(f"check {check['command']!r}: baseline must be pass, fail or null")
    fixes = verification.get("ci_fixes", 0)
    if not isinstance(fixes, int) or isinstance(fixes, bool) or fixes < 0:
        raise InputError("verification.ci_fixes must be a whole number, 0 or more")
    evidence = verification.get("evidence", {"required": False, "missing": []})
    if (not isinstance(evidence, dict) or not isinstance(evidence.get("required"), bool)
            or not isinstance(evidence.get("missing", []), list)):
        raise InputError("verification.evidence must be {required: bool, missing: [reason, ...]}")
    if "process_deviations" not in verification:
        raise InputError("verification.process_deviations is required: one sentence for each time the "
                         "harness forced the run off its process (such as a task written in-session because "
                         "its subagent could not start), or [] when there was none")
    process = verification["process_deviations"]
    if not isinstance(process, list) or not all(isinstance(p, str) and p.strip() for p in process):
        raise InputError("verification.process_deviations must be a list of sentences")


def check_diff_review(review):
    if not isinstance(review, dict) or review.get("result") not in DIFF_RESULTS:
        raise InputError(f"diff review must be diff_gate.py's output, with result one of {sorted(DIFF_RESULTS)}")
    if not isinstance(review.get("reasons", []), list):
        raise InputError("diff review reasons must be a list")


def check_evidence(published):
    images = published.get("images") if isinstance(published, dict) else None
    if not isinstance(images, dict) or not all(isinstance(u, str) for u in images.values()):
        raise InputError("evidence must be publish_evidence.py's output, with images {file: url}")


def body_images(body):
    return [a or b for a, b in IMAGE.findall(body)]


def check_ci(checks):
    if not isinstance(checks, list) or any(
            not isinstance(c, dict) or not isinstance(c.get("name"), str) or not isinstance(c.get("bucket"), str)
            for c in checks):
        raise InputError("checks must be the list `gh pr checks --json name,bucket` prints")


def evaluate(pr_ready, decision, verification, checks, plan_risk_flags=(), diff_review=None,
             pr_body=None, published=None):
    """Return {"ready", "reasons"}. Every condition is evaluated, so reasons lists all failures."""
    reasons = []

    if pr_ready != "auto":
        reasons.append("this project opens every PR as a draft (pr_ready: draft)")

    if decision.get("decision") != "implement":
        reasons.append(f"the Council did not approve the Plan on its own (Gate decision: "
                       f"{decision.get('decision', 'missing')}); the owner approved it")

    flags = list(dict.fromkeys(list(plan_risk_flags) + list(decision.get("risk_flags") or [])))
    reasons += [f"the Plan carries the Risk flag {flag}" for flag in flags]

    if checks is None:
        reasons.append("no CI result (a dry run opens no PR)")
    elif not checks:
        reasons.append("the repo runs no CI checks on the PR, so nothing outside the factory verified it")
    else:
        reasons += [f"CI check {c['name']} is {c['bucket']}" for c in checks if c["bucket"] not in PASSING]
        if not any(c["bucket"] == "pass" for c in checks):
            reasons.append("no CI check passed")

    fixes = verification.get("ci_fixes", 0)
    if fixes:
        reasons.append(f"CI went green only after {fixes} fix commit(s)")

    evidence = verification.get("evidence", {"required": False, "missing": []})
    if evidence["required"]:
        reasons += [f"screenshot missing: {m}" for m in evidence.get("missing", [])]

    if pr_body is not None:
        verified = set((published or {}).get("images", {}).values())
        reasons += [f"screenshot link not verified: {url}" for url in body_images(pr_body) if url not in verified]

    for check in verification["checks"]:
        if check["result"] == "fail":
            base = ", as it did on the base branch" if check.get("baseline") == "fail" else ""
            reasons.append(f"`{check['command']}` fails on the branch{base}")

    if diff_review is None:
        reasons.append("no independent diff review ran")
    elif diff_review["result"] != "clean":
        detail = "; ".join(str(r) for r in diff_review.get("reasons", [])) or "no reason given"
        reasons.append(f"the independent diff review is {diff_review['result']}: {detail}")

    reasons += [f"process deviation: {p}" for p in verification.get("process_deviations", [])]

    return {"ready": not reasons, "reasons": reasons or ["all conditions met"]}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Decide whether the factory may promote its draft PR.")
    parser.add_argument("--pr-ready", required=True, help="the project's pr_ready setting: auto or draft")
    parser.add_argument("--decision", type=Path, required=True)
    parser.add_argument("--verification", type=Path, required=True)
    parser.add_argument("--diff-review", type=Path, help="the last diff review pass; omit only when none ran")
    parser.add_argument("--checks", type=Path, help="`gh pr checks --json name,bucket` output; omit in a dry run")
    parser.add_argument("--pr-body", type=Path, help="the body the PR was opened with; required with --checks")
    parser.add_argument("--evidence", type=Path, help="publish_evidence.py's output; omit when none was published")
    parser.add_argument("--risk-flag", action="append", default=[], dest="risk_flags")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)

    try:
        if args.pr_ready not in MODES:
            raise InputError(f"--pr-ready must be one of {sorted(MODES)}")
        decision = read_json(args.decision, "decision")
        if not isinstance(decision, dict):
            raise InputError("decision must be a JSON object")
        verification = read_json(args.verification, "verification")
        check_verification(verification)
        diff_review = read_json(args.diff_review, "diff review") if args.diff_review else None
        if diff_review is not None:
            check_diff_review(diff_review)
        checks = read_json(args.checks, "checks") if args.checks else None
        if checks is not None:
            check_ci(checks)
            if not args.pr_body:
                raise InputError("--pr-body is required with --checks: the screenshot links are checked against it")
        try:
            pr_body = read_text(args.pr_body) if args.pr_body else None
        except (OSError, UnicodeDecodeError) as error:
            raise InputError(f"cannot read PR body {args.pr_body}: {error}") from error
        published = read_json(args.evidence, "evidence") if args.evidence else None
        if published is not None:
            check_evidence(published)
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    result = evaluate(args.pr_ready, decision, verification, checks, args.risk_flags, diff_review,
                      pr_body, published)
    text = json.dumps(result, indent=2)
    if args.out:
        args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
