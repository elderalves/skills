"""Run with: python -m unittest discover <this-dir>. No network: a fake runner plays gh and git."""

import io
import json
import unittest
import unittest.mock

from github_account import PIN_KEY, AccountError, helper_command, main, pin, pin_status, resolve

STATUS = """github.com
  ✓ Logged in to github.com account work-user (keyring)
  - Active account: true
  ✓ Logged in to github.com account personal-user (keyring)
  - Active account: false
"""


def fake(reachable, remote="https://github.com/me/repo.git"):
    """reachable: the accounts whose token can ls-remote the repo."""
    def runner(args, env=None, cwd=None):
        if args[:2] == ["git", "-C"] and args[3:5] == ["remote", "get-url"]:
            return 0, remote + "\n"
        if args[:3] == ["gh", "auth", "status"]:
            return 0, STATUS
        if args[:3] == ["gh", "auth", "token"]:
            return 0, f"token-{args[-1]}\n"
        if "ls-remote" in args:
            user = env["GH_TOKEN"].removeprefix("token-")
            return (0, "") if user in reachable else (128, "Repository not found")
        raise AssertionError(args)
    return runner


class Resolve(unittest.TestCase):
    def test_detects_first_account_that_reaches(self):
        self.assertEqual(resolve("r", runner=fake({"personal-user"})),
                         {"account": "personal-user", "source": "detected", "host": "github.com"})

    def test_pinned_account_wins_without_trying_others(self):
        self.assertEqual(resolve("r", "work-user", fake({"work-user", "personal-user"}))["source"], "pinned")

    def test_pinned_account_without_access_is_an_error(self):
        with self.assertRaisesRegex(AccountError, "pinned"):
            resolve("r", "work-user", fake({"personal-user"}))

    def test_no_account_names_the_ones_tried(self):
        with self.assertRaisesRegex(AccountError, "work-user, personal-user"):
            resolve("r", runner=fake(set()))

    def test_ssh_remote_host(self):
        result = resolve("r", runner=fake({"work-user"}, remote="git@github.com:me/repo.git"))
        self.assertEqual(result["host"], "github.com")

    def test_cli_exit_codes(self):
        self.assertEqual(main(["r"], runner=fake({"work-user"})), 0)
        self.assertEqual(main(["r"], runner=fake(set())), 1)


KEY = "credential.https://github.com.helper"
GH = "C:/Program Files/GitHub CLI/gh.exe"


def which(name):
    return r"C:\Program Files\GitHub CLI\gh.exe"


class Repo:
    """A fake repo: its local git config, and whether a plain ls-remote can authenticate."""

    def __init__(self, config=None, remote="https://github.com/me/repo.git", reachable=True):
        self.config, self.remote, self.reachable, self.envs = dict(config or {}), remote, reachable, []

    def __call__(self, args, env=None, cwd=None):
        rest = args[3:]
        if rest[:2] == ["remote", "get-url"]:
            return 0, self.remote + "\n"
        if rest[:2] == ["config", "--local"]:
            op = rest[2:]
            if op[0] == "--get-all":
                values = self.config.get(op[1])
                return (0, "\n".join(values) + "\n") if values else (1, "")
            if op[0] == "--unset-all":
                return (0, "") if self.config.pop(op[1], None) else (5, "")
            if op[0] == "--add":
                self.config.setdefault(op[1], []).append(op[2])
                return 0, ""
            self.config[op[0]] = [op[1]]
            return 0, ""
        if rest[:1] == ["ls-remote"]:
            self.envs.append(env)
            return (0, "") if self.reachable else (128, "Authentication failed")
        raise AssertionError(args)


PINNED = {KEY: ["", helper_command("github.com", "work-user", GH)], PIN_KEY: ["work-user"]}


class Pin(unittest.TestCase):
    def test_writes_a_reset_then_the_account_helper_and_the_mark(self):
        repo = Repo()
        self.assertEqual(pin("r", "work-user", repo, which)["written"], True)
        self.assertEqual(repo.config, PINNED)
        self.assertIn('"C:/Program Files/GitHub CLI/gh.exe" auth token --hostname github.com --user work-user',
                      repo.config[KEY][1])

    def test_proves_plain_git_works_without_any_token_in_the_environment(self):
        repo = Repo()
        with unittest.mock.patch.dict("os.environ", {"GH_TOKEN": "t", "GITHUB_TOKEN": "t"}):
            pin("r", "work-user", repo, which)
        self.assertNotIn("GH_TOKEN", repo.envs[0])
        self.assertNotIn("GITHUB_TOKEN", repo.envs[0])
        self.assertEqual(repo.envs[0]["GIT_TERMINAL_PROMPT"], "0")

    def test_a_correct_pin_is_left_as_it_is(self):
        repo = Repo(PINNED)
        self.assertEqual(pin_status("r", "work-user", repo, which)["state"], "ok")
        self.assertEqual(pin("r", "work-user", repo, which)["written"], False)
        self.assertEqual(repo.envs, [])

    def test_a_pin_for_another_account_is_stale_and_replaced(self):
        repo = Repo(PINNED)
        self.assertEqual(pin_status("r", "personal-user", repo, which)["state"], "stale")
        pin("r", "personal-user", repo, which)
        self.assertEqual(repo.config[PIN_KEY], ["personal-user"])
        self.assertEqual(len(repo.config[KEY]), 2)
        self.assertIn("--user personal-user", repo.config[KEY][1])

    def test_a_pin_naming_a_moved_gh_is_stale(self):
        moved = {**PINNED, KEY: ["", helper_command("github.com", "work-user", "/old/gh")]}
        self.assertEqual(pin_status("r", "work-user", Repo(moved), which)["state"], "stale")

    def test_the_owners_own_helper_is_left_alone(self):
        for config in ({KEY: ["store"]}, {"credential.helper": ["manager"]}):
            repo = Repo(config)
            self.assertEqual(pin_status("r", "work-user", repo, which)["state"], "foreign")
            with self.assertRaisesRegex(AccountError, "did not write"):
                pin("r", "work-user", repo, which)
            self.assertEqual(repo.config, config)

    def test_an_ssh_origin_needs_no_pin(self):
        repo = Repo(remote="git@github.com:me/repo.git")
        self.assertEqual(pin_status("r", "work-user", repo, which)["state"], "ssh")
        with self.assertRaisesRegex(AccountError, "SSH"):
            pin("r", "work-user", repo, which)
        self.assertEqual(repo.config, {})

    def test_a_pin_that_still_cannot_reach_the_repo_is_an_error(self):
        with self.assertRaisesRegex(AccountError, "still fails"):
            pin("r", "work-user", Repo(reachable=False), which)

    def test_missing_gh_is_an_error(self):
        with self.assertRaisesRegex(AccountError, "not on PATH"):
            pin("r", "work-user", Repo(), lambda name: None)

    def test_cli_pins_the_resolved_account(self):
        repo, accounts = Repo(), fake({"work-user"})

        def runner(args, env=None, cwd=None):
            if args[:1] == ["gh"] or (env and "GH_TOKEN" in env):
                return accounts(args, env, cwd)
            return repo(args, env, cwd)
        with unittest.mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.assertEqual(main(["r", "--account", "work-user", "--pin"], runner, which), 0)
        self.assertEqual(json.loads(out.getvalue())["pin"], {"state": "ok", "written": True})
        self.assertEqual(repo.config[PIN_KEY], ["work-user"])


if __name__ == "__main__":
    unittest.main()
