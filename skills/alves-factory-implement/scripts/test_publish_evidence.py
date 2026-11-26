"""Run with: python -m unittest discover <this-dir>"""

import io
import json
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import publish_evidence as pe


# PNG signature plus CR, LF and NUL bytes, so any line-ending conversion would show.
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\r\n" * 8


def sh(*args, cwd=None):
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Repo:
    """A checkout whose origin is a local bare repo, standing in for GitHub."""

    def __init__(self, root):
        self.origin = root / "origin.git"
        self.checkout = root / "checkout"
        self.evidence = root / "evidence"
        sh("git", "init", "--bare", "-q", str(self.origin))
        sh("git", "init", "-q", str(self.checkout))
        sh("git", "-C", str(self.checkout), "config", "core.autocrlf", "true")
        sh("git", "-C", str(self.checkout), "config", "user.name", "Factory")
        sh("git", "-C", str(self.checkout), "config", "user.email", "factory@example.com")
        sh("git", "-C", str(self.checkout), "remote", "add", "origin", str(self.origin))
        self.evidence.mkdir()

    def shoot(self, **pngs):
        for name, extra in pngs.items():
            (self.evidence / f"{name.replace('_', '-')}.png").write_bytes(PNG + extra.encode())

    def served(self, repo, commit, host, env):
        """What the origin holds at the commit, read the way GitHub's tree API reports it."""
        out = sh("git", "--git-dir", str(self.origin), "ls-tree", "-l", "-z", commit)
        tree = {}
        for entry in filter(None, out.split("\0")):
            meta, _, path = entry.partition("\t")
            tree[path] = int(meta.split()[3])
        return tree

    def publish(self, read_tree=None, runner=pe.run, branch="factory/PCS-1"):
        return pe.publish(self.checkout, self.evidence, branch, "PCS-1: evidence screenshots",
                          "acme/widgets", "github.com", dict(os.environ), read_tree or self.served, runner)

    def head(self, ref="refs/heads/factory/PCS-1-evidence"):
        return sh("git", "--git-dir", str(self.origin), "rev-parse", ref)


class Publish(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_names_and_bytes_arrive_exactly(self):
        self.repo.shoot(composed_list_after="a", api_guidance_after="b")
        result = self.repo.publish()
        self.assertEqual(result["branch"], "factory/PCS-1-evidence")
        self.assertEqual(result["commit"], self.repo.head())
        names = sh("git", "--git-dir", str(self.repo.origin), "ls-tree", "--name-only", "-z", result["commit"])
        self.assertEqual([n for n in names.split("\0") if n], ["api-guidance-after.png", "composed-list-after.png"])
        blob = subprocess.run(["git", "--git-dir", str(self.repo.origin), "cat-file", "blob",
                               f"{result['commit']}:composed-list-after.png"], capture_output=True, check=True).stdout
        self.assertEqual(blob, PNG + b"a")

    def test_urls_pin_the_commit(self):
        self.repo.shoot(composed_list_after="a")
        result = self.repo.publish()
        self.assertEqual(result["images"], {"composed-list-after.png":
                         f"https://github.com/acme/widgets/blob/{result['commit']}/composed-list-after.png?raw=true"})

    def test_evidence_commit_is_an_orphan_and_leaves_the_checkout_alone(self):
        self.repo.shoot(composed_list_after="a")
        result = self.repo.publish()
        parents = sh("git", "--git-dir", str(self.repo.origin), "rev-list", "--parents", "-n1", result["commit"])
        self.assertEqual(parents, result["commit"])
        self.assertEqual(sh("git", "-C", str(self.repo.checkout), "status", "--porcelain"), "")

    def test_a_retry_stacks_on_the_earlier_commit(self):
        self.repo.shoot(composed_list_after="a")
        first = self.repo.publish()["commit"]
        self.repo.shoot(composed_list_after="b")
        second = self.repo.publish()["commit"]
        self.assertNotEqual(first, second)
        parents = sh("git", "--git-dir", str(self.repo.origin), "rev-list", "--parents", "-n1", second)
        self.assertEqual(parents, f"{second} {first}")

    def test_a_retry_with_the_same_screenshots_reuses_the_commit(self):
        self.repo.shoot(composed_list_after="a")
        first = self.repo.publish()["commit"]
        self.assertEqual(self.repo.publish()["commit"], first)

    def test_a_tree_github_serves_differently_fails(self):
        self.repo.shoot(composed_list_after="a")

        def carriage_returns(repo, commit, host, env):
            return {f"{name}\r": size for name, size in self.repo.served(repo, commit, host, env).items()}

        with self.assertRaisesRegex(pe.PublishError, "missing \\['composed-list-after.png'\\]"):
            self.repo.publish(read_tree=carriage_returns)

    def test_no_commit_sha_means_no_push(self):
        self.repo.shoot(composed_list_after="a")
        calls = []

        def broken_commit_tree(args, cwd=None, env=None, stdin=None):
            calls.append(args)
            if "commit-tree" in args:
                return 0, "", ""
            return pe.run(args, cwd, env, stdin)

        with self.assertRaisesRegex(pe.PublishError, "nothing was pushed"):
            self.repo.publish(runner=broken_commit_tree)
        self.assertFalse(any("push" in a for a in calls))

    def test_an_unreachable_origin_fails_without_touching_the_branch(self):
        self.repo.shoot(composed_list_after="a")
        first = self.repo.publish()["commit"]
        sh("git", "-C", str(self.repo.checkout), "remote", "set-url", "origin", str(Path(self.tmp.name) / "gone.git"))
        self.repo.shoot(composed_list_after="b")
        with self.assertRaises(pe.PublishError):
            self.repo.publish()
        self.assertEqual(self.repo.head(), first)

    def test_no_screenshots_is_an_input_error(self):
        with self.assertRaisesRegex(pe.InputError, "no PNG"):
            self.repo.publish()

    def test_a_name_that_is_not_a_slug_is_an_input_error(self):
        (self.repo.evidence / "composed list.png").write_bytes(PNG)
        with self.assertRaisesRegex(pe.InputError, "slug"):
            self.repo.publish()


class Main(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repo(Path(self.tmp.name))
        self.out = Path(self.tmp.name) / "evidence.json"

    def tearDown(self):
        self.tmp.cleanup()

    def main(self, runner):
        argv = ["--checkout", str(self.repo.checkout), "--evidence-dir", str(self.repo.evidence),
                "--branch", "factory/PCS-1", "--message", "PCS-1: evidence screenshots",
                "--repo", "acme/widgets", "--account", "bot", "--out", str(self.out)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = pe.main(argv, runner=runner, read_tree=self.repo.served)
        return code, stdout.getvalue(), stderr.getvalue()

    @staticmethod
    def with_token(token="t0ken"):
        seen = {}

        def runner(args, cwd=None, env=None, stdin=None):
            if args[:3] == ["gh", "auth", "token"]:
                return (0, token + "\n", "") if token else (1, "", "no account")
            if args[0] == "git" and "push" in args:
                seen["token"] = env.get("GH_TOKEN")
            return pe.run(args, cwd, env, stdin)

        return runner, seen

    def test_publishes_writes_out_and_scopes_the_token(self):
        self.repo.shoot(composed_list_after="a")
        runner, seen = self.with_token()
        code, stdout, _ = self.main(runner)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.out.read_text(encoding="utf-8")), json.loads(stdout))
        self.assertEqual(seen["token"], "t0ken")
        self.assertNotEqual(os.environ.get("GH_TOKEN"), "t0ken")

    def test_no_token_exits_1(self):
        self.repo.shoot(composed_list_after="a")
        runner, _ = self.with_token(token="")
        code, _, stderr = self.main(runner)
        self.assertEqual(code, 1)
        self.assertIn("no gh token", stderr)
        self.assertFalse(self.out.exists())

    def test_unusable_input_exits_2(self):
        runner, _ = self.with_token()
        code, _, stderr = self.main(runner)
        self.assertEqual(code, 2)
        self.assertIn("no PNG", stderr)


if __name__ == "__main__":
    unittest.main()
