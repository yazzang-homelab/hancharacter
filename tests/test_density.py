import unittest

from hancharacter import config
from hancharacter.density import (
    band,
    density,
    saturation_findings,
    scope_report,
    verdict,
    to_finding,
    wilson_interval,

)


class DensityTests(unittest.TestCase):
    SOURCE_BAND = (0.5, 0.5)

    def _verdict(self, d_tgt, matched, total, **overrides):
        arguments = {
            "n_units": total,
            "n_scenes": config.MIN_SCENES_PER_BAND,
            "dual_standard": False,
            "mode": config.MODE_VOICE_CRITICAL,
            "matched": matched,
            "total": total,
        }
        arguments.update(overrides)
        return verdict(d_tgt, self.SOURCE_BAND, **arguments)

    def test_canonical_density_returns_none_without_eligible_units(self):
        self.assertIsNone(density(0, 0))
        self.assertEqual(0.25, density(3, 12))

    def test_band_uses_documented_linear_interpolation(self):
        self.assertEqual((0.1, 0.9), band([0.0, 0.5, 1.0]))
        self.assertEqual((0.42, 0.42), band([0.42]))


    def test_numeric_entry_points_reject_hostile_density_values(self):
        invalid_values = (float("nan"), float("inf"), float("-inf"), -0.1, 1.1, "bad")
        for value in invalid_values:
            with self.subTest(entry_point="band", value=value):
                with self.assertRaises(ValueError) as error:
                    band([0.2, value])
                self.assertIn(repr(value), str(error.exception))
            with self.subTest(entry_point="density", value=value):
                with self.assertRaises(ValueError) as error:
                    density(value, 1)
                self.assertIn(repr(value), str(error.exception))
            with self.subTest(entry_point="wilson_interval", value=value):
                with self.assertRaises(ValueError) as error:
                    wilson_interval(value, 1)
                self.assertIn(repr(value), str(error.exception))
            with self.subTest(entry_point="verdict", value=value):
                with self.assertRaises(ValueError) as error:
                    self._verdict(value, 0, 100)
                self.assertIn(repr(value), str(error.exception))

    def test_verdict_rejects_invalid_bands_before_classifying_loss(self):
        invalid_bands = ((float("nan"), 0.2), (0.2, float("inf")), (0.9, 0.2))
        for source_band in invalid_bands:
            with self.subTest(source_band=source_band):
                with self.assertRaises(ValueError):
                    verdict(
                        0.0,
                        source_band,
                        n_units=100,
                        n_scenes=5,
                        dual_standard=False,
                        mode=config.MODE_VOICE_CRITICAL,
                        matched=0,
                        total=100,
                    )

    def test_b13_nan_band_composition_raises_instead_of_passing_total_loss(self):
        with self.assertRaises(ValueError):
            verdict(
                0.0,
                band([0.2, float("nan")]),
                n_units=100,
                n_scenes=5,
                dual_standard=False,
                mode=config.MODE_VOICE_CRITICAL,
                matched=0,
                total=100,
            )
    def test_scope_report_publishes_each_derived_quantity(self):
        row = scope_report(
            "speaker:iris",
            "sentence_final",
            0.5,
            0.2,
            [0.5] * config.MIN_SCENES_PER_BAND,
            n_units=1000,
            n_scenes=config.MIN_SCENES_PER_BAND,
            dual_standard=False,
            mode=config.MODE_VOICE_CRITICAL,
            matched=200,
            total=1000,
            target_scene_densities=[0.1, 0.2, 0.3, 0.4, 0.5],
        )
        self.assertEqual(0.2, row["point_estimate"])
        self.assertEqual(-0.3, row["delta"])
        self.assertEqual([0.5, 0.5], row["band"])
        self.assertEqual([0.5, 0.5], row["effective_band"])
        self.assertEqual("hard", row["status"])
        self.assertIsInstance(row["wilson"], list)
        self.assertFalse(row["under_sampled"])

    def test_loss_and_over_application_are_both_hard(self):
        loss = self._verdict(0.2, 200, 1000)
        over_application = self._verdict(0.8, 800, 1000)

        self.assertEqual("hard", loss.status)
        self.assertIn("below p10", loss.reason)
        self.assertEqual("hard", over_application.status)
        self.assertIn("above p90", over_application.reason)

    def test_near_band_miss_is_report_not_hard(self):
        result = self._verdict(0.4, 400, 1000)

        self.assertEqual("report", result.status)
        self.assertIn("OUTER_TOL", result.reason)

    def test_in_band_target_passes(self):
        # A pass is the sole verdict that permits release, so this must not drift.
        result = self._verdict(0.5, 500, 1000)

        self.assertEqual("pass", result.status)
        self.assertFalse(result.under_sampled)

    def test_in_band_under_sampled_is_report_not_pass(self):
        # The sampling cap applies before an in-band result can become a pass.
        result = self._verdict(0.5, 5, 10, n_units=10)

        self.assertEqual("report", result.status)
        self.assertTrue(result.under_sampled)
        self.assertIn("MIN_UNITS_PER_SCOPE", result.reason)

    def test_wilson_precedence_requires_the_interval_to_clear_tolerance(self):
        noisy = self._verdict(0.2, 4, 20)
        precise = self._verdict(0.2, 200, 1000)

        self.assertEqual("report", noisy.status)
        self.assertIn("wilson upper", noisy.reason)
        self.assertIn("does not clear", noisy.reason)
        self.assertEqual("hard", precise.status)
        self.assertIn("wilson upper", precise.reason)
        self.assertIn("clears", precise.reason)

    def test_minimum_units_and_scenes_force_report_only(self):
        few_units = self._verdict(
            0.0,
            0,
            10,
            n_units=10,
        )
        few_scenes = self._verdict(
            0.0,
            0,
            100,
            n_units=100,
            n_scenes=3,
        )

        self.assertEqual("report", few_units.status)
        self.assertTrue(few_units.under_sampled)
        self.assertEqual("report", few_scenes.status)
        self.assertTrue(few_scenes.under_sampled)

    def test_prose_fidelity_caps_an_otherwise_hard_density_verdict(self):
        critical = self._verdict(0.2, 200, 1000)
        prose = self._verdict(
            0.2,
            200,
            1000,
            mode=config.MODE_PROSE_FIDELITY,
        )

        self.assertEqual("hard", critical.status)
        self.assertEqual("report", prose.status)
        self.assertIn("MODE_PROSE_FIDELITY caps", prose.reason)

    def test_to_finding_maps_each_density_status_and_preserves_reason(self):
        passing = self._verdict(0.5, 500, 1000)
        reported = self._verdict(0.4, 400, 1000)
        blocking = self._verdict(0.2, 200, 1000)

        # Density status is not a finding severity until this single conversion.
        self.assertIsNone(to_finding(passing, scope="speaker:iris", axis="ending_transform"))
        for result, severity in ((reported, "report"), (blocking, "hard")):
            with self.subTest(status=result.status):
                finding = to_finding(
                    result,
                    scope="speaker:iris",
                    axis="ending_transform",
                    row_key="row-7",
                )
                self.assertIsNotNone(finding)
                self.assertEqual(severity, finding.severity)
                self.assertEqual(result.reason, finding.detail)
                self.assertEqual("speaker:iris", finding.scope)
                self.assertEqual("ending_transform", finding.axis)
                self.assertEqual("row-7", finding.row_key)

    def test_dual_standard_widens_both_band_edges(self):
        source_band = (0.4, 0.4)
        ordinary = verdict(
            0.16,
            source_band,
            n_units=10000,
            n_scenes=config.MIN_SCENES_PER_BAND,
            dual_standard=False,
            mode=config.MODE_VOICE_CRITICAL,
            matched=1600,
            total=10000,
        )
        dual = verdict(
            0.16,
            source_band,
            n_units=10000,
            n_scenes=config.MIN_SCENES_PER_BAND,
            dual_standard=True,
            mode=config.MODE_VOICE_CRITICAL,
            matched=1600,
            total=10000,
        )

        self.assertEqual("hard", ordinary.status)
        self.assertEqual("report", dual.status)
        self.assertIn("OUTER_TOL", dual.reason)
        self.assertEqual(
            (
                source_band[0] - config.DUAL_STD_WIDEN,
                source_band[1] + config.DUAL_STD_WIDEN,
            ),
            dual.effective_band,
        )

    def test_saturation_lints_constant_and_band_max_pinning(self):
        constant_row = {
            "scope": "speaker:iris",
            "axis": "sentence_final",
            "d_tgt": 0.5,
            "effective_band": [0.2, 0.5],
            "per_scene_densities": [0.5, 0.5, 0.5, 0.5, 0.5],
        }
        healthy_row = {
            "scope": "speaker:jo",
            "axis": "sentence_final",
            "d_tgt": 0.3,
            "effective_band": [0.2, 0.5],
            "per_scene_densities": [0.1, 0.2, 0.3, 0.4, 0.5],
        }
        self.assertEqual([], saturation_findings([healthy_row]))

        constant_findings = saturation_findings([constant_row])
        self.assertTrue(
            any(finding.code == "DENSITY_SATURATION" for finding in constant_findings)
        )
        self.assertTrue(all(finding.severity == "report" for finding in constant_findings))

        pinned_rows = [
            {
                "scope": "speaker:" + name,
                "axis": "sentence_final",
                "d_tgt": 0.5,
                "effective_band": [0.2, 0.5],
                "per_scene_densities": [0.1, 0.3, 0.5, 0.2, 0.4],
            }
            for name in ("iris", "jo", "kai")
        ]
        pinning_findings = saturation_findings(pinned_rows)
        self.assertTrue(
            any(
                finding.code == "DENSITY_BAND_MAX_PINNING"
                and finding.severity == "report"
                for finding in pinning_findings
            )
        )


if __name__ == "__main__":
    unittest.main()
