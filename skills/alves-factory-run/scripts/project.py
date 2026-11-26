"""Find the projects.json entry a factory run works on, with its repo path made absolute.

    python project.py --ref <upstream-ref> [--config FILE]
    python project.py --linear-project <name> [--config FILE]
    python project.py --match <match> [--config FILE]

--ref applies the match rules of references/config.md: entries are tried in order, and the
first whose `match` is a prefix of the ref wins (`linear-project:` entries never match by
prefix). --linear-project finds the Native entry `linear-project:<name>`. --match finds the
entry with exactly that `match`.

Prints the entry as JSON with `repo` absolute: a leading `~/` becomes this machine's home
directory, so one projects.json serves Windows, Linux and macOS. Exit 2, with the reason on
stderr, when the config cannot be read, no entry matches, or the repo is not a directory here.
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


def find(config, ref=None, linear_project=None, match=None):
    projects = [e for e in config["projects"] if isinstance(e, dict) and isinstance(e.get("match"), str)]
    if match is not None:
        found = [e for e in projects if e["match"] == match]
        what = f"match {match!r}"
    elif linear_project is not None:
        found = [e for e in projects if e["match"] == NATIVE + linear_project]
        what = f"Linear project {linear_project!r}"
    else:
        found = [e for e in projects if not e["match"].startswith(NATIVE) and ref.startswith(e["match"])]
        what = f"upstream ref {ref!r}"
    if not found:
        raise ProjectError(f"no projects.json entry matches {what}")
    return resolve_entry(found[0])


def main(argv=None):
    parser = argparse.ArgumentParser(description="Find the projects.json entry for a factory run.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--ref", help="an upstream ref, such as PCS-6137 or github:owner/repo#12")
    which.add_argument("--linear-project", help="the Linear project of a Native ticket")
    which.add_argument("--match", help="an entry's exact match value")
    parser.add_argument("--config", default=str(factory_home() / "projects.json"))
    args = parser.parse_args(argv)
    try:
        entry = find(read_config(args.config), args.ref, args.linear_project, args.match)
    except ProjectError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(entry, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
