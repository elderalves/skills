"""Run with: python -m unittest discover <this-dir>."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import project


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        (self.home / "Projects" / "pcs").mkdir(parents=True)
        (self.home / "Projects" / "side").mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        self.env.start()
        self.config = {"projects": [
            {"match": "linear-project:Side", "repo": "~/Projects/side"},
            {"match": "PCS-", "repo": "~/Projects/pcs", "base_branch": "master"},
            {"match": "PC", "repo": str(self.home / "Projects" / "side")},
            {"match": "GONE-", "repo": "~/Projects/gone"},
            {"match": "REL-", "repo": "Projects/pcs"},
        ]}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_ref_takes_first_prefix_match_and_expands_home(self):
        entry = project.find(self.config, ref="PCS-6137")
        self.assertEqual(entry["match"], "PCS-")
        self.assertEqual(Path(entry["repo"]), self.home / "Projects" / "pcs")
        self.assertEqual(entry["base_branch"], "master")

    def test_ref_never_matches_a_native_entry_by_prefix(self):
        config = {"projects": [{"match": "linear-project:Side", "repo": "~/Projects/side"}]}
        with self.assertRaisesRegex(project.ProjectError, "no projects.json entry"):
            project.find(config, ref="linear-project:Side-1")

    def test_linear_project_finds_the_native_entry(self):
        entry = project.find(self.config, linear_project="Side")
        self.assertEqual(Path(entry["repo"]), self.home / "Projects" / "side")

    def test_match_is_exact_and_keeps_an_absolute_repo(self):
        entry = project.find(self.config, match="PC")
        self.assertEqual(entry["match"], "PC")
        self.assertEqual(Path(entry["repo"]), self.home / "Projects" / "side")

    def test_missing_directory_is_an_error(self):
        with self.assertRaisesRegex(project.ProjectError, "not a directory on this machine"):
            project.find(self.config, ref="GONE-1")

    def test_relative_repo_is_an_error(self):
        with self.assertRaisesRegex(project.ProjectError, "must be absolute"):
            project.find(self.config, ref="REL-1")

    def test_main_prints_entry_and_exits_2_on_no_match(self):
        path = self.home / "projects.json"
        path.write_text(json.dumps(self.config), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(project.main(["--ref", "PCS-1", "--config", str(path)]), 0)
        self.assertEqual(json.loads(out.getvalue())["match"], "PCS-")
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertEqual(project.main(["--ref", "NOPE-1", "--config", str(path)]), 2)
        self.assertIn("no projects.json entry matches", err.getvalue())

    def test_unreadable_config_exits_2(self):
        with redirect_stderr(io.StringIO()):
            self.assertEqual(project.main(["--ref", "PCS-1", "--config", str(self.home / "none.json")]), 2)


if __name__ == "__main__":
    unittest.main()
