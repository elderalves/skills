"""Find the projects.json entry a factory run works on, with its repo path made absolute.

    python project.py --ref <upstream-ref> [--linear-project <name>] [--config FILE]
    python project.py --ref <upstream-ref> --candidates [--config FILE]
    python project.py --linear-project <name> [--config FILE]
    python project.py --match <match> [--config FILE]

--ref applies the match rules of references/config.md: entries are tried in order, and the
first whose `match` is a prefix of the ref selects that prefix (`linear-project:` entries never
match by prefix). Several entries may share one prefix when one Upstream tracker feeds several
repos; each then names a distinct `linear_project`, and --linear-project picks among them (the
Factory ticket's Linear project, once triage has filed it). --ref alone refuses to guess
between shared entries. --candidates prints every entry of the prefix, for triage to choose
from. --linear-project alone finds the Native entry `linear-project:<name>`. --match finds
the one entry with exactly that `match`.

Prints the entry (a list of entries for --candidates) as JSON with `repo` absolute: a leading
`~/` becomes this machine's home directory, so one projects.json serves Windows, Linux and
macOS. Exit 2, with the reason on stderr, when the config cannot be read, no entry matches,
the choice is ambiguous, or the repo is not a directory here. --candidates skips an entry
whose repo is missing here with a `warning:` line on stderr, and fails only when none is left.
"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from factory_home import factory_home  # noqa: E402

NATIVE = "linear-project:"


class ProjectError(Exception):
    pass


def read_config(path):
    try:
        data = Path(path).expanduser().read_bytes()
        text = data.decode("utf-16" if data[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig")
        config = json.loads(text)
    except (OSError, ValueError) as error:
        raise ProjectError(f"cannot read {path}: {error}") from error
    if not isinstance(config, dict) or not isinstance(config.get("projects"), list):
        raise ProjectError(f"{path} needs a projects list")
    return config


def expand_repo(value):
    """The repo path with a leading ~ expanded; it must then be absolute."""
    if not isinstance(value, str) or not value.strip():
        raise ProjectError("the entry has no repo")
    path = Path(os.path.expanduser(value.strip()))
    if not path.is_absolute():
        raise ProjectError(f"repo {value!r} must be absolute or start with ~/")
    return path


def resolve_entry(entry):
    """A copy of entry with repo absolute, after checking it is a directory on this machine."""
    path = expand_repo(entry.get("repo"))
    if not path.is_dir():
        raise ProjectError(f"{entry.get('match')!r}: repo {entry['repo']!r} is not a directory "
                           f"on this machine ({path})")
    return {**entry, "repo": str(path)}


def entries(config):
    return [e for e in config["projects"] if isinstance(e, dict) and isinstance(e.get("match"), str)]


def same_name(a, b):
    return isinstance(a, str) and isinstance(b, str) and a.casefold() == b.casefold()


def prefix_entries(config, ref):
    """Every entry sharing the first prefix that matches ref, in config order (unresolved)."""
    upstream = [e for e in entries(config) if not e["match"].startswith(NATIVE)]
    first = next((e for e in upstream if ref.startswith(e["match"])), None)
    if first is None:
        raise ProjectError(f"no projects.json entry matches upstream ref {ref!r}")
    group = [e for e in upstream if e["match"] == first["match"]]
    if len(group) > 1:
        names = [e.get("linear_project") for e in group]
        for i, name in enumerate(names):
            if not isinstance(name, str) or not name.strip() or any(same_name(name, n) for n in names[:i]):
                raise ProjectError(f"entries sharing match {first['match']!r} each need a distinct "
                                   f"linear_project; found {names}")
    return group


def candidates(config, ref, skipped=None):
    """The entries triage chooses among for ref, with repos absolute; a repo missing here is skipped."""
    found, errors = [], []
    for entry in prefix_entries(config, ref):
        try:
            found.append(resolve_entry(entry))
        except ProjectError as error:
            errors.append(f"{entry.get('linear_project') or entry['match']}: {error}")
    if not found:
        raise ProjectError("; ".join(errors))
    if skipped is not None:
        skipped.extend(errors)
    return found


def find(config, ref=None, linear_project=None, match=None):
    if match is not None:
        found = [e for e in entries(config) if e["match"] == match]
        if len(found) > 1:
            raise ProjectError(f"{len(found)} entries have match {match!r}; pick one by ref and Linear project")
        what = f"match {match!r}"
    elif ref is not None:
        group = prefix_entries(config, ref)
        if linear_project is not None:
            found = [e for e in group if same_name(e.get("linear_project"), linear_project)]
            if not found:
                raise ProjectError(f"no entry for {ref!r} files tickets in Linear project {linear_project!r}; "
                                   f"its entries use {[e.get('linear_project') for e in group]}")
        elif len(group) > 1:
            raise ProjectError(f"{ref!r} matches {len(group)} entries "
                               f"({', '.join(e['linear_project'] for e in group)}); "
                               "pass --linear-project, the Factory ticket's Linear project")
        else:
            found = group
        what = f"upstream ref {ref!r}"
    else:
        found = [e for e in entries(config) if e["match"] == NATIVE + linear_project]
        what = f"Linear project {linear_project!r}"
    if not found:
        raise ProjectError(f"no projects.json entry matches {what}")
    return resolve_entry(found[0])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find the projects.json entry for a factory run.")
    parser.add_argument("--ref", help="an upstream ref, such as PCS-6137 or github:owner/repo#12")
    parser.add_argument("--linear-project",
                        help="with --ref, the Factory ticket's Linear project; alone, a Native ticket's")
    parser.add_argument("--candidates", action="store_true", help="with --ref, every entry triage chooses among")
    parser.add_argument("--match", help="an entry's exact match value")
    parser.add_argument("--config", default=str(factory_home() / "projects.json"))
    args = parser.parse_args(argv)
    try:
        if args.match is not None and (args.ref or args.linear_project or args.candidates):
            raise ProjectError("--match takes no other selector")
        if args.candidates and (not args.ref or args.linear_project):
            raise ProjectError("--candidates needs --ref and no --linear-project")
        if args.match is None and args.ref is None and args.linear_project is None:
            raise ProjectError("pass --ref, --linear-project or --match")
        config = read_config(args.config)
        if args.candidates:
            skipped = []
            result = candidates(config, args.ref, skipped)
            for line in skipped:
                print(f"warning: skipped {line}", file=sys.stderr)
        else:
            result = find(config, args.ref, args.linear_project, args.match)
    except ProjectError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
