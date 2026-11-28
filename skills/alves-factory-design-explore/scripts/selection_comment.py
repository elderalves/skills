"""Build the Selection comment for one Exploration round from its decision alone.

    python selection_comment.py <round-dir> --round N --figma-url <url> --page-id <id>
                                --uploads <uploads.json> [--ledger <cost.json>] [--arm ARM] [--now ISO] [--out FILE]

<round-dir> holds the design Council's decision.json (mode explore) and designs.json.
--uploads maps each design id to its screenshot's Linear asset URL (`linear.py upload`); a
design with no upload says so and the comment is still built. --ledger adds the run's cost
line (run_cost.py). The comment ends with the design record, a JSON block a later
Refinement run reads to find each Variation's frame. Prints the Markdown (without the
[alves-factory] marker, which linear.py comment adds).

Exit 2 when the decision is not a ranked Exploration decision or an input is unreadable.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_cost  # noqa: E402

TOP_FINDINGS = 3


def read(path):
    data = Path(path).read_bytes()
    return json.loads(data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"))


def label(criterion):
    return criterion.replace("_", " ")


def one_line(text):
    return " ".join(str(text).split())


def build(decision, designs, uploads, round_no, figma_url, page_id, cost_line=None, arm=None):
    if decision.get("mode") != "explore" or decision.get("decision") != "ranked":
        raise ValueError(f"expected a ranked Exploration decision, got {decision.get('mode')}/{decision.get('decision')}")
    policy = decision["policy"]
    criteria = [c for seat in policy["seats"].values() for c in seat]
    by_id = {d["id"]: d for d in decision["designs"]}
    meta = {d["id"]: d for d in designs}
    order = decision["ranking"]
    best = decision.get("recommendation")
    lines = [f"## Selection: Exploration {round_no}", "",
             f"{len(order)} Variations, one per Design hypothesis, each scored by the design Council from its "
             "screenshot and the Design brief. **The Selection is yours**: the Council's recommendation is advice.", ""]
    if arm:
        lines += [f"**Calibration arm:** `{arm}`", ""]
    header = "| Criterion (weight) | " + " | ".join(order) + " |"
    lines += [header, "|---" * (len(order) + 1) + "|"]
    score_cells = []
    for did in order:
        d = by_id[did]
        cell = f"{d['score']:.2f}"
        if did == best:
            cell = f"**{cell}**"
        if d["vetoed"]:
            cell += " ⛔ veto"
        score_cells.append(cell)
    lines.append("| **Score (0–10)** | " + " | ".join(score_cells) + " |")
    for c in criteria:
        lines.append(f"| {label(c)} ({policy['weights'][c]}) | "
                     + " | ".join(str(by_id[did]["criteria"][c]["score"]) for did in order) + " |")
    lines.append("")
    for did in order:
        d, m = by_id[did], meta.get(did, {})
        name, _, premise = (m.get("hypothesis") or d.get("hypothesis") or "").partition(": ")
        lines += [f"### {did} — {name or 'Variation ' + did}", ""]
        lines.append(f"![{did} — desktop]({uploads[did]})" if uploads.get(did)
                     else "_The screenshot did not upload; open the Variation in Figma._")
        lines += ["", f"**Hypothesis:** {one_line(premise or name)}", ""]
        findings = [f for f in d["findings"] if f["severity"] == "major"][:TOP_FINDINGS] or d["findings"][:TOP_FINDINGS]
        if d["critical_defects"]:
            lines.append("**Critical defects:**")
            lines += [f"- ⛔ **{x['category']}**: {one_line(x['problem'])} _({one_line(x['element'])})_"
                      for x in d["critical_defects"]]
            lines.append("")
        lines.append("**Top findings:**" if findings else "**Top findings:** none")
        lines += [f"{i}. **{f['severity']} · {label(f['criterion'])}**: {one_line(f['problem'])} "
                  f"_({one_line(f['element'])})_ → {one_line(f['fix'])}" for i, f in enumerate(findings, 1)]
        lines += ["", "**Strengths:**" if d["strengths"] else "**Strengths:** none named"]
        lines += [f"- {one_line(s['strength'])}" for s in d["strengths"]]
        weakest = min(criteria, key=lambda c: (d["criteria"][c]["score"], -policy["weights"][c]))
        tradeoffs = [one_line(m["tradeoff"]) if m.get("tradeoff") else None,
                     f"Weakest criterion: {label(weakest)} ({d['criteria'][weakest]['score']})."]
        tradeoffs += [f"Vetoed: {one_line(r)}." for r in d["veto_reasons"]]
        lines += ["", "**Trade-offs:** " + " ".join(t for t in tradeoffs if t), ""]
    lines += ["### Council recommendation", ""]
    if best:
        lines.append(f"**{best}**. " + " ".join(one_line(r) for r in decision["reasons"]))
    else:
        lines.append("**None.** " + " ".join(one_line(r) for r in decision["reasons"]))
    lines += ["", "The Council recommends; it never selects.", "",
              f"**Figma:** [the ticket's page in the Factory Figma file]({figma_url})", "",
              "**To continue:** reply with your Selection (\"B\", or \"B, with C's side panel\"), then move the ticket to "
              "**Refining** to refine it, to **Ready for Design** to explore again (say in your reply what to change), "
              "or to **Canceled** to reject every Variation.", ""]
    if cost_line:
        lines += [cost_line, ""]
    record = {"exploration": round_no, "page_id": page_id, "recommendation": best, "arm": arm,
              "designs": [{"id": did, "file_key": meta.get(did, {}).get("file_key"),
                           "node_id": (meta.get(did, {}).get("screens") or [{}])[0].get("node_id"),
                           "score": by_id[did]["score"], "vetoed": by_id[did]["vetoed"]} for did in order]}
    lines += ["**Design record**", "", "```json", json.dumps(record, ensure_ascii=False), "```", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build an Exploration round's Selection comment.")
    parser.add_argument("round_dir", type=Path)
    parser.add_argument("--round", type=int, required=True, dest="round_no")
    parser.add_argument("--figma-url", required=True)
    parser.add_argument("--page-id", required=True)
    parser.add_argument("--uploads", type=Path, required=True)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--arm", help="the Calibration arm, shown on a calibration ticket")
    parser.add_argument("--now")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    try:
        decision = read(args.round_dir / "decision.json")
        designs = read(args.round_dir / "designs.json")["designs"]
        uploads = read(args.uploads)
        cost = run_cost.render(run_cost.read(args.ledger), args.now) if args.ledger else None
        text = build(decision, designs, uploads, args.round_no, args.figma_url, args.page_id, cost, args.arm)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    if args.out:
        args.out.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
