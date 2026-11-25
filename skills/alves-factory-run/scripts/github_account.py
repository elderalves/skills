"""Find the GitHub account a factory run uses for one repo, without switching the active gh account.

    python github_account.py <repo-dir> [--account <pinned-account>]

Prints JSON {"account", "source", "host"}: source is "pinned" when --account was given and
can reach the repo, "detected" when found by trying every account `gh auth status` lists.
Use the account per command, never through `gh auth switch`:

    GH_TOKEN=$(gh auth token --hostname <host> --user <account>) git push ...

Exit 1, naming every account tried, when none can reach the repo's origin.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from urllib.parse import urlparse


ACCOUNT_LINE = re.compile(r"Logged in to (\S+) account (\S+)")


def run(args, env=None, cwd=None):
    """Return (exit code, stdout). Never raises for a failing command."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, env=env, cwd=cwd, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return done.returncode, done.stdout + done.stderr


class AccountError(Exception):
    pass


def origin_host(repo, runner=run):
    code, out = runner(["git", "-C", repo, "remote", "get-url", "origin"])
    if code != 0:
        raise AccountError(f"{repo} has no origin remote")
    url = out.strip()
    if url.startswith("git@"):
        return url.split("@", 1)[1].split(":", 1)[0]
    return urlparse(url).hostname or ""


def accounts(host, runner=run):
    _, out = runner(["gh", "auth", "status", "--hostname", host])
    return [user for h, user in ACCOUNT_LINE.findall(out) if h == host]


def can_reach(repo, host, account, runner=run):
    code, token = runner(["gh", "auth", "token", "--hostname", host, "--user", account])
    if code != 0 or not token.strip():
        return False
    env = {**os.environ, "GH_TOKEN": token.strip(), "GIT_TERMINAL_PROMPT": "0"}
    code, _ = runner(["git", "-C", repo, "ls-remote", "--heads", "origin"], env=env)
    return code == 0


def resolve(repo, pinned=None, runner=run):
    host = origin_host(repo, runner)
    if pinned:
        if can_reach(repo, host, pinned, runner):
            return {"account": pinned, "source": "pinned", "host": host}
        raise AccountError(f"pinned account {pinned!r} cannot reach {repo}'s origin on {host}")
    tried = accounts(host, runner)
    for account in tried:
        if can_reach(repo, host, account, runner):
            return {"account": account, "source": "detected", "host": host}
    raise AccountError(f"no gh account can reach {repo}'s origin on {host}; tried: {', '.join(tried) or 'none'}")


def main(argv=None, runner=run):
    parser = argparse.ArgumentParser(description="Find the GitHub account for one repo.")
    parser.add_argument("repo")
    parser.add_argument("--account", help="the project's pinned github_account")
    args = parser.parse_args(argv)
    try:
        result = resolve(args.repo, args.account, runner)
    except AccountError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
