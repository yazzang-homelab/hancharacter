import copy
import subprocess
import sys

import hashlib

import contextlib
import io
import json
import os
import tempfile
import unittest

from hancharacter import cli, config, e2e, findings, gates, schemas, segment

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))



ROOT = config.repo_root()
PROFILE = os.path.join(ROOT, "profiles", "crimson_fixture.json")
ROWS = config.fixture_path()
STAMP = "2026-07-30T00:00:00Z"


def _load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class E2ETests(unittest.TestCase):
    def test_crimson_records_the_honest_preseal_stop_and_policy(self):
        if not os.path.isfile(ROWS):
            self.skipTest(
                "external corpus %s is unavailable; a clone without the pinned "
                "fixture cannot run the crimson path" % ROWS
            )
        with tempfile.TemporaryDirectory(prefix="hc-e2e-crimson-") as directory:
            report, rc = e2e.run_real_fixture(PROFILE, ROWS, directory, STAMP)
            self.assertEqual(1, rc)
            self.assertEqual("blocked_at_contract_seal", report["status"])
            self.assertEqual("crimson", report["fixture"])
            self.assertTrue(report["contracts"]["preseal_findings"])

            self.assertEqual("prose_fidelity", report["profile"]["mode"])
            self.assertTrue(report["profile"]["dual_standard"])
            self.assertEqual("report_only_in_prose_fidelity", report["gates"]["density_policy"])
            self.assertEqual("hard_when_a_sealed_contract_exists", report["gates"]["presence_policy"])
            self.assertFalse(report["gates"]["executed"])
            self.assertEqual(0, report["contracts"]["sealed_count"])
            self.assertFalse(report["contracts"]["all_types_canonical"])
            self.assertTrue(report["contracts"]["stop_reason"])
            self.assertEqual(0.70, report["profile"]["coverage_floor"])
            self.assertEqual(1.0, report["attribution"]["t1_rate"])
            self.assertEqual(
                {"frea1", "lippi1", "giauque1", "flint1"},
                set(report["segmentation"]["coverage"]),
            )
            self.assertEqual(
                {
                    config.INELIGIBLE_MIXED_SPAN,
                    config.INELIGIBLE_DUPLICATE_SOURCE,
                    config.INELIGIBLE_PENDING,
                    config.INELIGIBLE_UNDECLARED,
                    config.INELIGIBLE_UNSPLITTABLE,
                },
                set(report["segmentation"]["ineligible_by_reason"]),
            )
            self.assertTrue(report["density"]["under_sampled_scopes"])
            self.assertFalse(report["intermittent_band"]["measured"])
            graduation = report["contracts"]["graduation"]
            self.assertEqual([], schemas.validate("graduation_report", graduation))
            canonical = sorted(
                row["type_id"] for row in graduation["types"] if row["stage"] == "canonical"
            )
            self.assertEqual([], canonical)
            self.assertTrue(all(row["unmet"] for row in graduation["types"]))
            # Crimson stops because every type is ungraduated, and separately
            # because its speakers carry no catalogue type at all.
            blocked_types = sorted(
                finding["scope"]
                for finding in report["contracts"]["preseal_findings"]
                if finding["code"] == "contract_type_not_canonical"
            )
            self.assertIn("ja_hao_gozaru", blocked_types)
            self.assertEqual(
                set(),
                {
                    type_id
                    for entry in report["contracts"]["speaker_marker_types"]
                    for type_id in entry["type_ids"]
                },
            )
            self.assertEqual([], e2e.validate_report(_load(os.path.join(directory, "report.json"))))
            self.assertFalse(os.path.commonpath((ROOT, directory)) == ROOT)

    def test_voice_critical_seals_loss_fails_and_faithful_intermittent_passes(self):
        with tempfile.TemporaryDirectory(prefix="hc-e2e-voice-") as directory:
            suite, rc = e2e.run_voice_critical(directory, STAMP)
            self.assertEqual(0, rc)
            synthetic = os.path.join(directory, "synthetic-artifacts")
            self.assertEqual("synthetic-voice-critical", suite["run"])
            self.assertEqual("synthetic", suite["fixture"])

            self.assertEqual("passed", suite["status"])
            self.assertTrue(suite["contracts"]["sealed"])
            self.assertEqual("canonical", suite["contracts"]["graduation"]["types"][0]["stage"])
            self.assertEqual(1, suite["runs"]["seeded_loss"]["exit_code"])
            self.assertIn("voice_required_marker_absent", suite["runs"]["seeded_loss"]["hard_codes"])
            self.assertEqual(0, suite["runs"]["faithful_intermittent"]["exit_code"])
            loss = _load(os.path.join(synthetic, "seeded-loss-report.json"))
            faithful = _load(os.path.join(synthetic, "faithful-intermittent-report.json"))

            self.assertEqual("failed_as_expected", loss["status"])
            self.assertTrue(loss["gates"]["hard_findings"])
            self.assertEqual("passed", faithful["status"])
            self.assertEqual([], faithful["gates"]["hard_findings"])
            self.assertEqual("pass", faithful["density"]["scope_verdicts"][0]["status"])
            self.assertTrue(faithful["intermittent_band"]["source_has_marker_free_scene"])
            self.assertTrue(faithful["intermittent_band"]["target_has_marker_free_scene"])
            self.assertEqual(
                [], schemas.validate("graduation_report", faithful["contracts"]["graduation"])
            )
            self.assertEqual([], e2e.validate_report(loss))
            self.assertEqual([], e2e.validate_report(faithful))
            self.assertEqual([], e2e.validate_suite(_load(os.path.join(synthetic, "report.json"))))
            self.assertFalse(os.path.exists(os.path.join(directory, "report.json")))
            for artifact in (suite, loss, faithful, _load(os.path.join(synthetic, "seal-report.json"))):
                self.assertEqual("synthetic", artifact["fixture"])
                self.assertNotEqual("crimson", artifact.get("run"))
            with open(os.path.join(synthetic, "summary.txt"), encoding="utf-8") as handle:
                self.assertIn(
                    "This synthetic suite proves the seal and gate paths on authored data; it is not a result about any real work.",
                    handle.read(),
                )


    def test_cli_returns_nonzero_for_the_seeded_loss(self):
        with tempfile.TemporaryDirectory(prefix="hc-e2e-cli-") as directory:
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                rc = cli.main(
                    [
                        "e2e",
                        "--scenario",
                        "seeded-loss",
                        "--out",
                        directory,
                        "--generated-at",
                        STAMP,
                    ]
                )
            self.assertEqual(1, rc)
            self.assertIn("voice-critical suite: passed", stdout.getvalue())
            printed_path = os.path.join(directory, "synthetic-artifacts", "report.json")
            self.assertIn("wrote %s" % printed_path, stdout.getvalue())
            self.assertTrue(os.path.isfile(printed_path))
            report = _load(os.path.join(directory, "synthetic-artifacts", "seeded-loss-report.json"))

            self.assertIn(
                "voice_required_marker_absent",
                [finding["code"] for finding in report["gates"]["hard_findings"]],
            )


    def test_delimited_source_flattening_regression_is_hard(self):
        profile = config.Profile(
            {
                "work": "delimited-source-regression",
                "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
                "evidence_lang": "ja",
                "pivot_lang": "ja",
                "target_lang": "ko",
                "speaker_roles": {"hero": config.ROLE_SPEAKER, "close": config.ROLE_CLOSE},
                "delimiters": {
                    "ja": {"speech": [["「", "」"]], "term": []},
                    "ko": {"speech": [['"', '"']], "term": []},
                },
            }
        )
        source = segment.Row(
            key="source-row",
            evidence="<color=hero>「これは主命でござる。」<color=close>",
            pivot="「これは主命でござる。」",
            target='"이것은 주인의 명이다."',
            evidence_lang="ja",
            pivot_lang="ja",
            scene="scene-0",
        )
        units, source_hits, source_scenes = e2e._source_scene_densities(
            [source], profile, "ending_transform", [r"ござる[。！？!?…]*$"]
        )
        self.assertEqual(1, source_hits)
        marker_patterns = [r"이오[.。！？!?…]*$"]
        contract = {
            "speaker": "hero",
            "axes": [{"axis": "ending_transform"}],
            "required_markers": marker_patterns,
            "forbidden_markers": [],
            "measured_source_density": {"ending_transform": source_hits / len(units)},
            "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
            "exclusivity": {"exclusive_with": []},
            "bands": {"all": {"ending_transform": [1.0, 1.0]}},
            "scope_overrides": {},
            "marker_sets": {"ending_transform": marker_patterns},
            "catalogue_markers": {"fixture": marker_patterns},
            "review_decisions": {},
            "seal": {"hash": hashlib.sha256(b"delimited-source").hexdigest()},
            "measurable_axes": ["ending_transform"],
        }
        found, _report = gates.corpus(
            [
                {
                    "row_key": unit.row_key,
                    "scope": unit.scope,
                    "text": unit.target_text,
                    "scene": unit.scene,
                    "eligible": True,
                    "pending": False,
                    "attributed_spans": 1,
                }
                for unit in units
            ],
            [contract],
            catalogue_markers={"fixture": marker_patterns},
            target_lang="ko",
            source_scene_densities={("hero", "ending_transform"): source_scenes},
            measurable_axes={"hero": ["ending_transform"]},
            quote_parity_findings=findings.FindingSet(),
            ladder_findings=findings.FindingSet(),
            profile=profile,
        )
        self.assertFalse(found.is_clean())
        self.assertIn("voice_required_marker_absent", [finding.code for finding in found.hard])

    def test_e2e_capacity_gate_uses_profile_budgets(self):
        profile_data = copy.deepcopy(e2e._synthetic_profile())
        profile_data.update({"edition_medium": "subtitle", "budgets": {"subtitle": {"cpl": 1}}})
        profile = config.Profile(profile_data)
        with tempfile.TemporaryDirectory() as directory:
            e2e._synthetic_catalogue(directory)
            candidate = e2e._contract_candidate(
                profile,
                directory,
                {"synthetic_nyan": config.STAGE_CANONICAL},
                0.5,
                (0.2, 0.8),
                hashlib.sha256(b"profile-budget").hexdigest(),
            )
            check = e2e._length_check(
                [segment.Row(key="row", evidence="", pivot="", target="긴 대사")],
                profile,
                directory,
            )
            feasible, failures = check(candidate)
        self.assertFalse(feasible)
        self.assertEqual("subtitle", failures[0][2])
        self.assertEqual({"cpl": 1}, failures[0][3])
    def test_reports_are_reproducible_and_reject_repository_output(self):
        with tempfile.TemporaryDirectory(prefix="hc-e2e-repro-") as directory:
            e2e.run_voice_critical(directory, STAMP)
            with open(os.path.join(directory, "synthetic-artifacts", "report.json"), "rb") as handle:

                first = handle.read()
            e2e.run_voice_critical(directory, STAMP)
            with open(os.path.join(directory, "synthetic-artifacts", "report.json"), "rb") as handle:
                self.assertEqual(first, handle.read())
        with self.assertRaisesRegex(ValueError, "outside the repository"):
            e2e.run_voice_critical(os.path.join(ROOT, "e2e-out"), STAMP)


if __name__ == "__main__":
    unittest.main()


class E2EFormatReachabilityTests(unittest.TestCase):
    """e2e is the only command that produces a verdict, so every declared
    format must reach it.  It previously accepted JSON and host-shaped JSON
    only, which left seven adapter formats unable to be judged at all."""

    PROFILE = os.path.join(_REPO_ROOT, "profiles", "crimson_fixture.json")

    def _run(self, rows_path, out, extra=()):
        cmd = [
            sys.executable, "-m", "hancharacter.cli", "e2e",
            "--profile", self.PROFILE, "--rows", rows_path, "--out", out,
        ]
        return subprocess.run(
            list(cmd) + list(extra), cwd=_REPO_ROOT,
            capture_output=True, text=True,
        )

    def _srt(self, directory):
        path = os.path.join(directory, "cue.srt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                "1\n00:00:01,000 --> 00:00:03,000\n\u3053\u308c\u306f\u4e3b\u547d"
                "\u3067\u3054\u3056\u308b\u3002\n"
            )
        return path

    def test_a_subtitle_file_reaches_a_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            result = self._run(self._srt(tmp), out)
            self.assertIn("real fixture:", result.stdout, msg=result.stderr)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual("e2e_report", report["kind"])

    def test_an_undeclared_extension_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rows.zzz")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("x")
            result = self._run(path, os.path.join(tmp, "out"))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("adapter_format_undeclared", result.stdout + result.stderr)

    def test_format_flag_overrides_the_extension(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "rows.dat")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "1\n00:00:01,000 --> 00:00:03,000\n\u3054\u3056\u308b\u3002\n"
                )
            out = os.path.join(tmp, "out")
            result = self._run(path, out, extra=("--format", "srt"))
            self.assertIn("real fixture:", result.stdout, msg=result.stderr)

    def test_an_operator_input_is_not_labelled_as_the_pinned_crimson_fixture(self):
        # A hard-coded label put an untrue provenance into the evidence tree.
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "out")
            self._run(self._srt(tmp), out)
            with open(os.path.join(out, "report.json"), encoding="utf-8") as handle:
                report = json.load(handle)
            self.assertEqual("operator_input", report["fixture"])
            self.assertEqual("operator_input", report["run"])


class PresealStopReasonTests(unittest.TestCase):
    """Two generations of this string were false. Every clause is now pinned.

    The first was a hardcoded claim that no type was canonical, which broke the
    moment one graduated. The second asserted that the canonical types did not
    cover what the speakers require *without computing the set difference*, which
    was false on the only fixture it describes because those speakers require
    nothing at all.
    """

    def _reason(self, canonical, ungraduated, required, target_units=0):
        graduation = {
            "types": [{"type_id": t, "stage": "canonical"} for t in canonical]
            + [{"type_id": t, "stage": "observed"} for t in ungraduated]
        }
        scope_types = [{"speaker": "s", "type_ids": list(required)}]
        return e2e._preseal_stop_reason(
            graduation, scope_types, target_units=target_units
        )

    def test_an_empty_requirement_set_is_not_called_uncovered(self):
        reason = self._reason(["a"], ["b"], [])
        self.assertIn("no per-speaker type requirement to satisfy", reason)
        self.assertNotIn("do not cover", reason)
        self.assertNotIn("are not canonical.", reason.split(";")[1])

    def test_a_genuinely_missing_requirement_names_only_what_is_missing(self):
        reason = self._reason(["a"], ["b", "c"], ["a", "b"])
        self.assertIn("require a, b, of which b are not canonical", reason)

    def test_a_satisfied_requirement_says_so(self):
        reason = self._reason(["a"], [], ["a"])
        self.assertIn("Every type the declared speakers require (a) is canonical", reason)

    def test_no_canonical_type_is_still_reported_plainly(self):
        self.assertIn(
            "has no canonical type", self._reason([], ["a"], [])
        )

    def test_target_unit_count_is_derived_not_asserted(self):
        self.assertIn("No target-language unit is present", self._reason(["a"], [], []))
        self.assertIn(
            "7 target-language unit(s) are present",
            self._reason(["a"], [], [], target_units=7),
        )

    def test_the_crimson_reason_is_true_of_the_crimson_fixture(self):
        if not os.path.isfile(ROWS):
            self.skipTest(
                "external corpus %s is unavailable; a clone without the pinned "
                "fixture cannot run the crimson path" % ROWS
            )
        with tempfile.TemporaryDirectory(prefix="hc-e2e-reason-") as directory:
            report, _ = e2e.run_real_fixture(PROFILE, ROWS, directory, STAMP)
            reason = report["contracts"]["stop_reason"]
            graduation = report["contracts"]["graduation"]
            canonical = [
                row["type_id"] for row in graduation["types"] if row["stage"] == "canonical"
            ]
            # Every factual clause must match the report it accompanies.
            if canonical:
                self.assertIn("%d canonical type(s)" % len(canonical), reason)
                for type_id in canonical:
                    self.assertIn(type_id, reason)
            else:
                self.assertIn("has no canonical type", reason)
            required = {
                type_id
                for entry in report["contracts"]["speaker_marker_types"]
                for type_id in entry["type_ids"]
            }
            if required:
                self.assertIn("declared speakers require", reason)
            else:
                self.assertIn("no per-speaker type requirement to satisfy", reason)
