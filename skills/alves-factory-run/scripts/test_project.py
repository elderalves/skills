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


class SharedPrefixTest(unittest.TestCase):
    """One Upstream tracker prefix feeding several repos, told apart by their Linear project."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        for name in ("empower", "explore", "pcs"):
            (self.home / "Projects" / name).mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"HOME": str(self.home), "USERPROFILE": str(self.home)})
        self.env.start()
        self.config = {"projects": [
            {"match": "PCS-", "repo": "~/Projects/pcs", "linear_project": "AgileKit"},
            {"match": "RTP-", "repo": "~/Projects/empower", "linear_project": "Empower Widgets"},
            {"match": "RTP-", "repo": "~/Projects/explore", "linear_project": "Explore Frontend"},
            {"match": "RT", "repo": "~/Projects/pcs", "linear_project": "Other"},
        ]}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_candidates_are_every_entry_of_the_first_matching_prefix_in_order(self):
        found = project.candidates(self.config, "RTP-49498")
        self.assertEqual([e["linear_project"] for e in found], ["Empower Widgets", "Explore Frontend"])
        self.assertEqual(Path(found[1]["repo"]), self.home / "Projects" / "explore")

    def test_a_single_entry_prefix_has_one_candidate(self):
        self.assertEqual([e["linear_project"] for e in project.candidates(self.config, "PCS-1")], ["AgileKit"])

    def test_candidates_skip_a_repo_missing_here_and_say_so(self):
        (self.home / "Projects" / "explore").rmdir()
        skipped = []
        found = project.candidates(self.config, "RTP-1", skipped)
        self.assertEqual([e["linear_project"] for e in found], ["Empower Widgets"])
        self.assertEqual(len(skipped), 1)
        self.assertIn("Explore Frontend", skipped[0])

    def test_candidates_with_no_repo_here_is_an_error(self):
        (self.home / "Projects" / "empower").rmdir()
        (self.home / "Projects" / "explore").rmdir()
        with self.assertRaisesRegex(project.ProjectError, "not a directory on this machine"):
            project.candidates(self.config, "RTP-1")

    def test_ref_alone_refuses_to_guess_between_shared_entries(self):
        with self.assertRaisesRegex(project.ProjectError, "Empower Widgets.*Explore Frontend"):
            project.find(self.config, ref="RTP-1")

    def test_ref_and_linear_project_pick_one_entry_ignoring_case(self):
        entry = project.find(self.config, ref="RTP-1", linear_project="explore frontend")
        self.assertEqual(Path(entry["repo"]), self.home / "Projects" / "explore")

    def test_linear_project_outside_the_prefix_is_an_error(self):
        with self.assertRaisesRegex(project.ProjectError, "AgileKit"):
            project.find(self.config, ref="RTP-1", linear_project="AgileKit")

    def test_single_entry_prefix_still_checks_the_linear_project(self):
        self.assertEqual(project.find(self.config, ref="PCS-1", linear_project="AgileKit")["match"], "PCS-")
        with self.assertRaises(project.ProjectError):
            project.find(self.config, ref="PCS-1", linear_project="Empower Widgets")

    def test_shared_prefix_needs_a_distinct_linear_project_per_entry(self):
        for second in ({"match": "RTP-", "repo": "~/Projects/explore"},
                       {"match": "RTP-", "repo": "~/Projects/explore", "linear_project": "empower widgets"}):
            config = {"projects": [self.config["projects"][1], second]}
            with self.assertRaisesRegex(project.ProjectError, "RTP-.*linear_project"):
                project.candidates(config, "RTP-1")

    def test_main_prints_candidates_and_picks_with_linear_project(self):
        path = self.home / "projects.json"
        path.write_text(json.dumps(self.config), encoding="utf-8")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(project.main(["--ref", "RTP-7", "--candidates", "--config", str(path)]), 0)
        self.assertEqual(len(json.loads(out.getvalue())), 2)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(project.main(["--ref", "RTP-7", "--linear-project", "Empower Widgets",
                                           "--config", str(path)]), 0)
        self.assertEqual(json.loads(out.getvalue())["linear_project"], "Empower Widgets")
        with redirect_stderr(io.StringIO()):
            self.assertEqual(project.main(["--ref", "RTP-7", "--config", str(path)]), 2)
            self.assertEqual(project.main(["--candidates", "--linear-project", "X", "--config", str(path)]), 2)


if __name__ == "__main__":
    unittest.main()
