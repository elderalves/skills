"""The decidable parts of an Exploration run: ticket settings, the claim, the brief and designs.json.

    python design_ticket.py settings --issue <issue.json> --comments <comments.json>
    python design_ticket.py claim --state <status name>
    python design_ticket.py check-brief <brief.md> --variations N
    python design_ticket.py designs <round-dir> --brief <brief.md> --file-key <key>

settings reads the Factory ticket (`linear.py get`) and its comments (`linear.py comments`)
and prints the run's settings: the number of Variations (label `variations:<n>`, default 3),
the Calibration arm (label `arm:direct` or `arm:browser-first`, default direct; a
`calibration` ticket must name one), the Exploration round (one more than the highest
Exploration number in the factory's Selection comments), the owner's feedback for this round (owner comments after the
latest Selection comment, or every owner comment before the first) and the previous
Selection's design record.

claim prints what the run does with a ticket in that status: claim it (Ready for Design,
set Exploring), or exit without writes (another run owns it, or there is no trigger).

check-brief checks the Design brief's sections and its Design hypotheses (exactly N, lettered
A, B, C...) and prints the hypotheses; exit 1 with one problem per line when it is malformed.

designs builds <round-dir>/designs.json from the brief's hypotheses and each Variation
agent's <round-dir>/variations/<id>.json, keeping the Variations that returned a frame.
Exit 1 when fewer than MIN_VARIATIONS did.

Every command prints JSON. Exit 2 when an input is unreadable or a setting is contradictory.
"""

import argparse
import json
import re
import sys
from pathlib import Path

MARKER = "[alves-factory]"
SELECTION_HEADING = re.compile(r"^##\s+Selection:\s+Exploration\s+(\d+)\s*$", re.M)
RECORD_BLOCK = re.compile(r"```json\s*\n(\{.*?\})\s*\n```", re.S)
ARMS = {"direct", "browser-first"}
DEFAULT_VARIATIONS, MIN_VARIATIONS, MAX_VARIATIONS = 3, 2, 5
CLAIM_FROM, RUNNING = "Ready for Design", "Exploring"
BRIEF_SECTIONS = ["User goal", "Requirements", "Design system", "States and breakpoints", "Design hypotheses"]
HYPOTHESIS = re.compile(r"^###\s+([A-Z])\s+[—-]\s+(.+?)\s*$", re.M)
FIELD = re.compile(r"^\*\*(Premise|Optimizes for|Trade-off):\*\*\s*(.+?)\s*$", re.M)


class SettingsError(Exception):
    pass


def read_json(path):
    data = Path(path).read_bytes()
    text = data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
    return json.loads(text)


def is_factory(comment):
    return comment.get("from_factory", comment.get("body", "").lstrip().startswith(MARKER))


def settings(issue, comments):
    labels = [l["name"] for l in (issue.get("labels") or {}).get("nodes", [])]
    arm_labels = [l.split(":", 1)[1] for l in labels if l.startswith("arm:")]
    if len(arm_labels) > 1:
        raise SettingsError(f"the ticket has {len(arm_labels)} arm labels; keep one of arm:direct or arm:browser-first")
    if arm_labels and arm_labels[0] not in ARMS:
        raise SettingsError(f"unknown arm label arm:{arm_labels[0]}; use arm:direct or arm:browser-first")
    calibration = "calibration" in labels
    if calibration and not arm_labels:
        raise SettingsError("a calibration ticket must name its arm with arm:direct or arm:browser-first")
    counts = [l.split(":", 1)[1] for l in labels if l.startswith("variations:")]
    if len(counts) > 1:
        raise SettingsError("the ticket has more than one variations: label")
    variations = DEFAULT_VARIATIONS
    if counts:
        if not counts[0].isdigit() or not MIN_VARIATIONS <= int(counts[0]) <= MAX_VARIATIONS:
            raise SettingsError(f"variations:{counts[0]} must be a number from {MIN_VARIATIONS} to {MAX_VARIATIONS}")
        variations = int(counts[0])
    ordered = sorted(comments, key=lambda c: c.get("created_at", ""))
    selections = [(c, m) for c in ordered if is_factory(c) for m in [SELECTION_HEADING.search(c["body"])] if m]
    last = selections[-1][0] if selections else None
    feedback = [{"created_at": c["created_at"], "author": c.get("author"), "body": c["body"].strip()}
                for c in ordered if not is_factory(c) and (last is None or c["created_at"] > last["created_at"])]
    record = None
    if last:
        block = RECORD_BLOCK.search(last["body"])
        if block:
            try:
                record = json.loads(block.group(1))
            except json.JSONDecodeError:
                record = None
    return {
        "identifier": issue.get("identifier"),
        "status": (issue.get("state") or {}).get("name"),
        "calibration": calibration,
        "arm": arm_labels[0] if arm_labels else "direct",
        "arm_source": "label" if arm_labels else "default",
        "variations": variations,
        "round": max((int(m.group(1)) for _, m in selections), default=0) + 1,
        "re_entry": bool(selections),
        "feedback": feedback,
        "previous_selection": record,
    }


def claim(state):
    if state == CLAIM_FROM:
        return {"action": "claim", "set": RUNNING, "reason": f"{CLAIM_FROM} starts an Exploration run"}
    if state == RUNNING:
        return {"action": "exit", "reason": f"another Exploration run owns the ticket ({RUNNING})"}
    return {"action": "exit", "reason": f"{state!r} is not {CLAIM_FROM!r}: this run has no trigger"}


def parse_hypotheses(text):
    """The Design hypotheses under the brief's ## Design hypotheses heading, in order."""
    hypotheses = []
    part = text.split("## Design hypotheses", 1)[1] if "## Design hypotheses" in text else ""
    part = re.split(r"^##\s", part, maxsplit=1, flags=re.M)[0]
    matches = list(HYPOTHESIS.finditer(part))
    for i, m in enumerate(matches):
        body = part[m.end(): matches[i + 1].start() if i + 1 < len(matches) else len(part)]
        fields = dict(FIELD.findall(body))
        hypotheses.append({"id": m.group(1), "name": m.group(2), "premise": fields.get("Premise", ""),
                           "optimizes_for": fields.get("Optimizes for", ""), "tradeoff": fields.get("Trade-off", "")})
    return hypotheses


def check_brief(text, variations):
    """Return (hypotheses, problems) for a Design brief."""
    headings = re.findall(r"^##\s+(.+?)\s*$", text, re.M)
    problems = [f"missing section: ## {s}" for s in BRIEF_SECTIONS if s not in headings]
    hypotheses = parse_hypotheses(text)
    if len(hypotheses) != variations:
        problems.append(f"{len(hypotheses)} Design hypotheses, the run asks for {variations}")
    expected = [chr(ord("A") + i) for i in range(len(hypotheses))]
    if [h["id"] for h in hypotheses] != expected:
        problems.append(f"hypotheses must be lettered {', '.join(expected) or 'A, B, C'} in order")
    for h in hypotheses:
        for field, key in (("Premise", "premise"), ("Optimizes for", "optimizes_for"), ("Trade-off", "tradeoff")):
            if not h[key]:
                problems.append(f"hypothesis {h['id']} has no **{field}:** line")
    return hypotheses, problems


def build_designs(round_dir, hypotheses, file_key):
    """Return (designs, missing): one design per Variation whose agent returned a frame."""
    designs, missing = [], []
    for h in hypotheses:
        path = Path(round_dir) / "variations" / f"{h['id']}.json"
        try:
            result = read_json(path)
        except (OSError, ValueError):
            missing.append({"id": h["id"], "reason": f"no readable {path.name}"})
            continue
        frame = result.get("frame_node_id") if isinstance(result, dict) else None
        if not isinstance(frame, str) or not re.fullmatch(r"\d+[:-]\d+", frame):
            missing.append({"id": h["id"], "reason": result.get("error") if isinstance(result, dict) and result.get("error")
                            else "no frame_node_id"})
            continue
        designs.append({"id": h["id"], "hypothesis": f"{h['name']}: {h['premise']}", "tradeoff": h["tradeoff"],
                        "file_key": file_key, "arm": result.get("arm"),
                        "screens": [{"node_id": frame.replace("-", ":"), "label": "desktop",
                                     "path": f"screens/{h['id']}/desktop.png"}]})
    return designs, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description="Decidable parts of an Exploration run.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("settings")
    p.add_argument("--issue", type=Path, required=True)
    p.add_argument("--comments", type=Path, required=True)
    sub.add_parser("claim").add_argument("--state", required=True)
    p = sub.add_parser("check-brief")
    p.add_argument("brief", type=Path)
    p.add_argument("--variations", type=int, required=True)
    p = sub.add_parser("designs")
    p.add_argument("round_dir", type=Path)
    p.add_argument("--brief", type=Path, required=True)
    p.add_argument("--file-key", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "settings":
            result, code = settings(read_json(args.issue), read_json(args.comments)), 0
        elif args.command == "claim":
            result, code = claim(args.state), 0
        elif args.command == "check-brief":
            hypotheses, problems = check_brief(args.brief.read_text(encoding="utf-8-sig"), args.variations)
            if problems:
                print("\n".join(problems))
                return 1
            result, code = {"hypotheses": hypotheses}, 0
        else:
            hypotheses = parse_hypotheses(args.brief.read_text(encoding="utf-8-sig"))
            designs, missing = build_designs(args.round_dir, hypotheses, args.file_key)
            (args.round_dir / "designs.json").write_text(json.dumps({"designs": designs}, indent=2, ensure_ascii=False) + "\n",
                                                         encoding="utf-8")
            code = 0 if len(designs) >= MIN_VARIATIONS else 1
            result = {"designs": [d["id"] for d in designs], "missing": missing,
                      "enough": code == 0, "min_variations": MIN_VARIATIONS}
    except SettingsError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except (OSError, ValueError) as error:
        print(f"error: cannot read input: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
