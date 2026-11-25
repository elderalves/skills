"""Run with: python -m unittest discover <this-dir>. No network: a fake runner plays gh and git."""

import unittest

from github_account import AccountError, main, resolve

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


if __name__ == "__main__":
    unittest.main()
