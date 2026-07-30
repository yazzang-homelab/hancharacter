from hancharacter import config
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
PROFILE = os.path.join(ROOT, "profiles", "crimson_fixture.json")
CRIMSON_ROWS = config.fixture_path()


class CliAdapterTests(unittest.TestCase):
    def run_cli(self, *arguments):
        return subprocess.run(
            [sys.executable, "-m", "hancharacter.cli", *arguments],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_authored_srt_loads_rows_via_segment(self):
        result = self.run_cli(
            "segment", "--profile", PROFILE, "--rows", os.path.join(FIXTURES, "sample.srt")
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("rows                       2", result.stdout)
        self.assertNotIn("error:", result.stderr)

    def test_authored_po_loads_rows_via_segment(self):
        result = self.run_cli(
            "segment", "--profile", PROFILE, "--rows", os.path.join(FIXTURES, "sample.po")
        )
        self.assertEqual(1, result.returncode)
        self.assertIn("rows                       1", result.stdout)
        self.assertNotIn("error:", result.stderr)

    def test_unknown_extension_fails_loudly(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = os.path.join(directory, "rows.unknown")
            shutil.copyfile(os.path.join(FIXTURES, "sample.srt"), rows)
            result = self.run_cli("segment", "--profile", PROFILE, "--rows", rows)
        self.assertEqual(2, result.returncode)
        self.assertIn("adapter_format_undeclared", result.stderr)

    def test_format_overrides_extension(self):
        with tempfile.TemporaryDirectory() as directory:
            rows = os.path.join(directory, "subtitle.json")
            shutil.copyfile(os.path.join(FIXTURES, "sample.srt"), rows)
            result = self.run_cli(
                "segment", "--profile", PROFILE, "--rows", rows, "--format", "srt"
            )
        self.assertEqual(1, result.returncode)
        self.assertIn("rows                       2", result.stdout)
        self.assertNotIn("error:", result.stderr)

    def test_host_shaped_crimson_fixture_keeps_4052_rows(self):
        if not os.path.isfile(CRIMSON_ROWS):
            self.skipTest(
                "external corpus %s is unavailable; a clone without the pinned "
                "fixture cannot check the 4052-row baseline" % CRIMSON_ROWS
            )
        result = self.run_cli(
            "segment", "--profile", PROFILE, "--rows", CRIMSON_ROWS
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("rows                       4052", result.stdout)

    def test_budget_command_consumes_declared_profile_budget_and_publishes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            profile_path = os.path.join(directory, "subtitle-profile.json")
            with open(PROFILE, encoding="utf-8") as handle:
                profile = json.load(handle)
            profile["edition_medium"] = "subtitle"
            profile["budgets"] = {
                "edition_medium": "subtitle",
                "subtitle": {"class": "subtitle", "cpl": 1, "cps": 1},
            }
            with open(profile_path, "w", encoding="utf-8") as handle:
                json.dump(profile, handle)
            result = self.run_cli(
                "budget",
                "--profile",
                profile_path,
                "--rows",
                os.path.join(FIXTURES, "sample.srt"),
                "--json",
            )
        self.assertEqual(1, result.returncode)
        published = json.loads(result.stdout)
        self.assertEqual("subtitle", published["budget_declaration"]["edition_medium"])
        self.assertEqual(2, published["budget"]["rows"])
        self.assertEqual(2, published["budget"]["measured"])
        self.assertTrue(published["budget"]["violations"])
        self.assertTrue(any(item["severity"] == "hard" for item in published["budget"]["findings"]))


if __name__ == "__main__":
    unittest.main()
