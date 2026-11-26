"""Find the GitHub account a factory run uses for one repo, without switching the active gh account.

    python github_account.py <repo-dir> [--account <pinned-account>] [--pin]

Prints JSON {"account", "source", "host"}: source is "pinned" when --account was given and
can reach the repo, "detected" when found by trying every account `gh auth status` lists.
Use the account per command, never through `gh auth switch`:

    GH_TOKEN=$(gh auth token --hostname <host> --user <account>) git push ...

--pin also writes the account into the repo's own git config, so a plain `git fetch` (T3's
worktree preparation, before any skill runs) uses it instead of gh's active account: an empty
`credential.https://<host>.helper` resets the global helpers, then a helper that prints
`gh auth token --user <account>`. The mark `alves-factory.githubaccount` says the factory wrote
it; a local helper without the mark is the owner's and is left alone. Worktrees share the
repo's config, so one pin covers them all. The JSON gains "pin": {"state", "written"}.

Exit 1, naming every account tried, when none can reach the repo's origin, or when --pin
cannot write a working pin.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import urlparse


ACCOUNT_LINE = re.compile(r"Logged in to (\S+) account (\S+)")
PIN_KEY = "alves-factory.githubaccount"
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


def run(args, env=None, cwd=None):
    """Return (exit code, stdout). Never raises for a failing command."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, env=env, cwd=cwd, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        return 1, str(error)
    return done.returncode, done.stdout + done.stderr


class AccountError(Exception):
    pass


def origin_url(repo, runner=run):
    code, out = runner(["git", "-C", repo, "remote", "get-url", "origin"])
    if code != 0:
        raise AccountError(f"{repo} has no origin remote")
    return out.strip()


def host_of(url):
    if url.startswith("git@"):
        return url.split("@", 1)[1].split(":", 1)[0]
    return urlparse(url).hostname or ""


def origin_host(repo, runner=run):
    return host_of(origin_url(repo, runner))


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


# Pinning the account in the repo's git config

def helper_key(host):
    return f"credential.https://{host}.helper"


def helper_command(host, account, gh):
    """The credential helper git runs (through sh, also on Windows) to get the account's token.
    `gh auth token --user` reads the keyring and ignores GH_TOKEN, so the pin holds in any shell."""
    return (f'!f() {{ test "$1" = get || exit 0; echo username={account}; '
            f'echo "password=$("{gh}" auth token --hostname {host} --user {account})"; }}; f')


def gh_path(which=shutil.which):
    path = which("gh")
    if not path:
        raise AccountError("gh is not on PATH")
    return path.replace("\\", "/")


def local_values(repo, key, runner):
    code, out = runner(["git", "-C", repo, "config", "--local", "--get-all", key])
    return out.splitlines() if code == 0 else []


def pin_status(repo, account, runner=run, which=shutil.which):
    """Read-only. state: ok | missing | stale (the factory's pin names another account or gh path)
    | foreign (a local helper the factory did not write) | ssh (origin uses SSH, no helper runs)."""
    url = origin_url(repo, runner)
    host = host_of(url)
    status = {"repo": repo, "host": host, "account": account, "pinned": None}
    if url.startswith(("git@", "ssh://")):
        return {**status, "state": "ssh"}
    mark = local_values(repo, PIN_KEY, runner)
    helpers = local_values(repo, helper_key(host), runner)
    status["pinned"] = mark[0] if mark else None
    if not mark:
        foreign = helpers or local_values(repo, "credential.helper", runner)
        return {**status, "state": "foreign" if foreign else "missing"}
    want = ["", helper_command(host, account, gh_path(which))]
    return {**status, "state": "ok" if mark == [account] and helpers == want else "stale"}


def pin(repo, account, runner=run, which=shutil.which):
    """Write the pin when it is missing or stale, then prove a plain `git ls-remote` works."""
    status = pin_status(repo, account, runner, which)
    if status["state"] == "ssh":
        raise AccountError(f"{repo}'s origin uses SSH, so git uses SSH keys, not a gh account: nothing to pin")
    if status["state"] == "foreign":
        raise AccountError(f"{repo} has a local credential helper the factory did not write; "
                           f"left alone (remove it, or pin {account} yourself)")
    if status["state"] == "ok":
        return {**status, "written": False}
    host, key = status["host"], helper_key(status["host"])
    runner(["git", "-C", repo, "config", "--local", "--unset-all", key])  # exit 5 when there is none
    for args in (["--add", key, ""], ["--add", key, helper_command(host, account, gh_path(which))],
                 [PIN_KEY, account]):
        code, out = runner(["git", "-C", repo, "config", "--local", *args])
        if code != 0:
            raise AccountError(f"cannot write {repo}'s git config: {out.strip()}")
    env = {k: v for k, v in os.environ.items() if k not in TOKEN_VARS} | {"GIT_TERMINAL_PROMPT": "0"}
    code, out = runner(["git", "-C", repo, "ls-remote", "--heads", "origin"], env=env)
    if code != 0:
        raise AccountError(f"pinned {account} in {repo}, but a plain git ls-remote still fails: {out.strip()[:300]}")
    return {**status, "state": "ok", "written": True}


def main(argv=None, runner=run, which=shutil.which):
    parser = argparse.ArgumentParser(description="Find the GitHub account for one repo.")
    parser.add_argument("repo")
    parser.add_argument("--account", help="the project's pinned github_account")
    parser.add_argument("--pin", action="store_true", help="also pin the account in the repo's git config")
    args = parser.parse_args(argv)
    try:
        result = resolve(args.repo, args.account, runner)
        if args.pin:
            pinned = pin(args.repo, result["account"], runner, which)
            result["pin"] = {"state": pinned["state"], "written": pinned["written"]}
    except AccountError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
