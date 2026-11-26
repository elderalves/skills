"""Publish a run's evidence screenshots to its evidence branch, then prove GitHub serves them.

Usage:
    python publish_evidence.py --checkout DIR --evidence-dir DIR --branch FACTORY_BRANCH
                               --message TEXT --repo OWNER/REPO --account GH_ACCOUNT
                               [--host github.com] --out FILE

Commits every PNG in --evidence-dir to `<FACTORY_BRANCH>-evidence` with git plumbing, which
leaves the checkout's working tree, index and branch untouched. A retried run stacks a commit
on the branch's head; nothing is force-pushed, and nothing is pushed unless the new commit is a
full SHA. After the push it reads the commit's tree back from GitHub and checks every file
is there under its exact name and size. Only then does it write (to --out) and print:

    {"commit": SHA, "branch": NAME, "images": {"<file>": "<url to render in the PR>"}}

The gh account's token is fetched here and passed only to this script's own git and gh
commands, so the caller never sets GH_TOKEN.

Exit codes: 0 when published and verified; 1 when the push or the read-back failed (the PR
then says "Screenshots unavailable" and the run goes on); 2 when an input is unusable.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path


SHA = re.compile(r"^[0-9a-f]{40}$")
NAME = re.compile(r"^[A-Za-z0-9._-]+\.png$")
REPO = re.compile(r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$")


class InputError(Exception):
    pass


class PublishError(Exception):
    pass


def run(args, cwd=None, env=None, stdin=None):
    """Return (exit code, stdout, stderr) as text. stdin is bytes, passed through unchanged."""
    try:
        done = subprocess.run(args, cwd=cwd, env=env, input=stdin, capture_output=True, timeout=300)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, "", str(error)
    return done.returncode, done.stdout.decode("utf-8", "replace"), done.stderr.decode("utf-8", "replace")


def screenshots(evidence_dir):
    files = sorted(Path(evidence_dir).glob("*.png"))
    if not files:
        raise InputError(f"no PNG in {evidence_dir}")
    for f in files:
        if not NAME.match(f.name):
            raise InputError(f"screenshot name {f.name!r} must be a slug: letters, digits, '.', '_', '-'")
    return files


def git(checkout, args, env, runner, stdin=None, what=None):
    code, out, err = runner(["git", "-C", str(checkout), *args], env=env, stdin=stdin)
    if code != 0:
        raise PublishError(f"{what or 'git ' + args[0]} failed: {(err or out).strip()}")
    return out.strip()


def full_sha(value, what):
    if not SHA.match(value):
        raise PublishError(f"{what} did not print a commit SHA (got {value!r}); nothing was pushed")
    return value


def remote_head(checkout, ref, env, runner):
    """The evidence branch's head on origin, or None when the branch does not exist yet."""
    out = git(checkout, ["ls-remote", "--heads", "origin", ref], env, runner, what="reading the evidence branch")
    for line in out.splitlines():
        sha, _, name = line.partition("\t")
        if name.strip() == ref:
            return full_sha(sha.strip(), "ls-remote")
    return None


def github_tree(repo, commit, host, env, runner=run):
    """{path: size} of the commit's tree, as GitHub serves it."""
    code, out, err = runner(["gh", "api", "--hostname", host, f"repos/{repo}/git/trees/{commit}"], env=env)
    if code != 0:
        raise PublishError(f"reading the pushed tree back from GitHub failed: {(err or out).strip()}")
    tree = json.loads(out)
    if tree.get("truncated"):
        raise PublishError("GitHub returned a truncated tree for the evidence commit")
    return {e["path"]: e.get("size") for e in tree.get("tree", []) if e.get("type") == "blob"}


def publish(checkout, evidence_dir, branch, message, repo, host, env, read_tree=github_tree, runner=run):
    if not REPO.match(repo):
        raise InputError(f"--repo must be OWNER/REPO, got {repo!r}")
    files = screenshots(evidence_dir)
    evidence_branch = f"{branch}-evidence"
    ref = f"refs/heads/{evidence_branch}"

    entries = b""
    for f in files:
        blob = git(checkout, ["hash-object", "-w", "--no-filters", "--", str(f)], env, runner)
        full_sha(blob, f"hash-object for {f.name}")
        entries += f"100644 blob {blob}\t{f.name}".encode("utf-8") + b"\0"
    tree = full_sha(git(checkout, ["mktree", "-z"], env, runner, stdin=entries), "mktree")

    parent = remote_head(checkout, ref, env, runner)
    parents = []
    if parent:
        git(checkout, ["fetch", "--no-tags", "origin", ref], env, runner, what="fetching the evidence branch")
        fetched = full_sha(git(checkout, ["rev-parse", "--verify", "FETCH_HEAD^{commit}"], env, runner), "rev-parse")
        if fetched != parent:
            raise PublishError(f"the evidence branch moved while publishing ({parent} -> {fetched})")
        parents = ["-p", parent]

    if parent and git(checkout, ["rev-parse", f"{parent}^{{tree}}"], env, runner) == tree:
        commit = parent  # a retry with the same screenshots: the branch already holds them
    else:
        commit = full_sha(git(checkout, ["commit-tree", tree, *parents, "-m", message], env, runner), "commit-tree")
        git(checkout, ["push", "origin", f"{commit}:{ref}"], env, runner, what="pushing the evidence branch")

    served = read_tree(repo, commit, host, env)
    expected = {f.name: f.stat().st_size for f in files}
    if served != expected:
        missing = sorted(set(expected) - set(served))
        extra = sorted(set(served) - set(expected))
        resized = sorted(n for n in set(expected) & set(served) if expected[n] != served[n])
        raise PublishError("GitHub serves a different evidence tree than was published: "
                           f"missing {missing!r}, unexpected {extra!r}, wrong size {resized!r}")

    images = {name: f"https://{host}/{repo}/blob/{commit}/{name}?raw=true" for name in expected}
    return {"commit": commit, "branch": evidence_branch, "images": images}


def main(argv=None, runner=run, read_tree=github_tree):
    parser = argparse.ArgumentParser(description="Publish evidence screenshots to the evidence branch.")
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--branch", required=True, help="the factory branch; the evidence branch adds -evidence")
    parser.add_argument("--message", required=True)
    parser.add_argument("--repo", required=True, help="OWNER/REPO on the git host")
    parser.add_argument("--account", required=True, help="the run's gh account (config.md#github-account)")
    parser.add_argument("--host", default="github.com")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        code, token, err = runner(["gh", "auth", "token", "--hostname", args.host, "--user", args.account])
        if code != 0 or not token.strip():
            raise PublishError(f"no gh token for {args.account} on {args.host}: {err.strip()}")
        env = {**os.environ, "GH_TOKEN": token.strip(), "GIT_TERMINAL_PROMPT": "0"}
        result = publish(args.checkout, args.evidence_dir, args.branch, args.message,
                         args.repo, args.host, env, read_tree, runner)
    except InputError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except PublishError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    text = json.dumps(result, indent=2)
    args.out.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
