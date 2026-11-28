"""A design run's cost ledger: time, tokens and Figma MCP calls, and its Figma limit handling.

    python run_cost.py start <ledger.json> [--now ISO]
    python run_cost.py add <ledger.json> --label <what> [--figma N] [--tokens N]
    python run_cost.py summary <ledger.json> [--now ISO]
    python run_cost.py render <ledger.json> [--now ISO]
    python run_cost.py is-limit --error-file <file>
    python run_cost.py limit-comment <ledger.json> --step <step> --error-file <file> [--per-day N] [--per-minute N] [--now ISO]

start opens the ledger with the run's start time (a ledger that exists is reset). add records
one piece of work: its Figma MCP calls (whoami, create_new_file and generate_figma_design are
free: count only the others) and the tokens it reported; leave --tokens out when the tool
reported none, and the summary names it as unreported. summary prints the totals as JSON;
render prints the one-line **Run cost** for a factory comment.

is-limit reads a failed Figma call's error text and prints {"limit": true|false}: whether the
plan's MCP rate limit stopped it. limit-comment prints the "## Figma limit" comment that ends
the run Blocked.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

LIMIT_PATTERNS = [r"rate[\s_-]?limit", r"\b429\b", r"too many requests", r"quota", r"limit (?:exceeded|reached)",
                  r"daily (?:call )?limit", r"exceeded .*limit"]
DEFAULT_PER_DAY, DEFAULT_PER_MINUTE = 200, 15


def now_iso(value=None):
    return value or datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def read_text(path):
    """A file's text, honouring a UTF-8 or UTF-16 byte-order mark (PowerShell's `>` writes UTF-16)."""
    data = Path(path).read_bytes()
    return data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig", errors="replace")


def read(path):
    return json.loads(read_text(path))


def write(path, ledger):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def start(path, now=None):
    ledger = {"started_at": now_iso(now), "entries": []}
    write(path, ledger)
    return ledger


def add(path, label, figma=0, tokens=None, now=None):
    if figma < 0 or (tokens is not None and tokens < 0):
        raise ValueError("--figma and --tokens must not be negative")
    ledger = read(path)
    ledger["entries"].append({"label": label, "figma_calls": figma, "tokens": tokens, "at": now_iso(now)})
    write(path, ledger)
    return ledger


def summary(ledger, now=None):
    elapsed = parse_time(now_iso(now)) - parse_time(ledger["started_at"])
    entries = ledger["entries"]
    return {
        "started_at": ledger["started_at"],
        "elapsed_minutes": max(0, round(elapsed.total_seconds() / 60)),
        "figma_calls": sum(e["figma_calls"] for e in entries),
        "tokens": sum(e["tokens"] for e in entries if e["tokens"] is not None),
        "tokens_unreported": [e["label"] for e in entries if e["tokens"] is None],
        "entries": entries,
    }


def render(ledger, now=None):
    s = summary(ledger, now)
    tokens = f"{s['tokens']:,} tokens"
    if s["tokens_unreported"]:
        tokens += f" (not reported by: {', '.join(s['tokens_unreported'])})"
    return f"**Run cost:** {s['elapsed_minutes']} min · {tokens} · {s['figma_calls']} Figma calls"


def is_limit(text):
    return any(re.search(p, text, re.I) for p in LIMIT_PATTERNS)


def limit_comment(ledger, step, error, per_day=DEFAULT_PER_DAY, per_minute=DEFAULT_PER_MINUTE, now=None):
    first = next((line.strip() for line in error.splitlines() if line.strip()), "no error text")
    return "\n".join([
        "## Figma limit",
        "",
        f"The Figma MCP limit stopped this run at **{step}**: `{first[:300]}`",
        "",
        f"- The plan allows {per_day} Figma MCP calls a day and {per_minute} a minute.",
        "- No Selection comment was posted. Variations already built stay in their sections of the ticket's Figma page.",
        f"- {render(ledger, now)}",
        "",
        "**To continue:** after the limit resets, move the ticket back to **Ready for Design**. "
        "The sweep does not retry a Figma limit.",
        "",
    ])


def main(argv=None):
    parser = argparse.ArgumentParser(description="A design run's cost ledger.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("start", "summary", "render"):
        p = sub.add_parser(name)
        p.add_argument("ledger", type=Path)
        p.add_argument("--now")
    p = sub.add_parser("add")
    p.add_argument("ledger", type=Path)
    p.add_argument("--label", required=True)
    p.add_argument("--figma", type=int, default=0)
    p.add_argument("--tokens", type=int)
    p.add_argument("--now")
    sub.add_parser("is-limit").add_argument("--error-file", type=Path, required=True)
    p = sub.add_parser("limit-comment")
    p.add_argument("ledger", type=Path)
    p.add_argument("--step", required=True)
    p.add_argument("--error-file", type=Path, required=True)
    p.add_argument("--per-day", type=int, default=DEFAULT_PER_DAY)
    p.add_argument("--per-minute", type=int, default=DEFAULT_PER_MINUTE)
    p.add_argument("--now")
    args = parser.parse_args(argv)
    try:
        if args.command == "start":
            print(json.dumps(start(args.ledger, args.now), indent=2))
        elif args.command == "add":
            print(json.dumps(summary(add(args.ledger, args.label, args.figma, args.tokens, args.now), args.now), indent=2))
        elif args.command == "summary":
            print(json.dumps(summary(read(args.ledger), args.now), indent=2))
        elif args.command == "render":
            print(render(read(args.ledger), args.now))
        elif args.command == "is-limit":
            print(json.dumps({"limit": is_limit(read_text(args.error_file))}))
        else:
            error = read_text(args.error_file)
            print(limit_comment(read(args.ledger), args.step, error, args.per_day, args.per_minute, args.now), end="")
    except (OSError, ValueError, KeyError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
