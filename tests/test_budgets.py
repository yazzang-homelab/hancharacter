import unittest

from hancharacter import budgets


class BudgetCheckTests(unittest.TestCase):
    def subtitle_budget(self, *, cpl=42, cps=20):
        return {
            "edition_medium": "subtitle",
            "subtitle": {"class": "subtitle", "cpl": cpl, "cps": cps},
        }

    def codes(self, finding_set):
        return [finding["code"] for finding in finding_set.to_json()]

    def assert_report_finding_set(self, finding_set, report):
        self.assertEqual(finding_set.to_json(), report["findings"])

    def test_cps_violation_is_hard_for_timed_overlong_subtitle(self):
        found, report = budgets.check(
            [
                {
                    "key": "timed-overlong",
                    "edition_medium": "subtitle",
                    "target": "abcdef",
                    "start": 0.0,
                    "end": 0.1,
                }
            ],
            budgets=self.subtitle_budget(),
        )

        self.assertIn("budget_subtitle_cps_exceeded", self.codes(found))
        self.assertEqual("hard", found.hard[0].severity)
        self.assertEqual(1, report["measured"])
        self.assertEqual(60.0, report["worst"]["cps"])
        self.assertEqual("cps", report["violations"][0]["metric"])

    def test_subtitle_that_fits_is_not_flagged(self):
        found, report = budgets.check(
            [
                {
                    "key": "timed-fit",
                    "target": "short line",
                    "start": 0.0,
                    "end": 2.0,
                }
            ],
            budgets={"class": "subtitle", "cpl": 42, "cps": 20},
        )

        self.assertTrue(found.is_clean())
        self.assertEqual([], report["violations"])
        self.assertEqual(1, report["measured"])
        self.assertEqual(0, report["unmeasurable"])

    def test_missing_timing_is_report_only_unmeasurable_not_a_pass(self):
        found, report = budgets.check(
            [
                {
                    "key": "untimed",
                    "edition_medium": "subtitle",
                    "target": "fits",
                }
            ],
            budgets=self.subtitle_budget(),
        )

        self.assertEqual([], found.hard)
        self.assertEqual(["budget_subtitle_timing_absent"], self.codes(found))
        self.assertEqual(0, report["measured"])
        self.assertEqual(1, report["unmeasurable"])
        self.assertIsNone(report["measurements"][0]["cps"])

    def test_display_width_counts_latin_hangul_and_kana_exactly(self):
        self.assertEqual(6, budgets.display_width("A한あB"))

    def test_display_width_ignores_combining_marks_and_preserves_cjk_widths(self):
        self.assertEqual(2, budgets.display_width("한"))
        self.assertEqual(2, budgets.display_width("あ"))
        self.assertEqual(2, budgets.display_width("漢"))
        self.assertEqual(1, budgets.display_width("ｶ"))
        self.assertEqual(2, budgets.display_width("ｶﾞ"))
        self.assertEqual(1, budgets.display_width("e\u0301"))
        self.assertEqual(3, budgets.display_width("가〮"))

    def test_hangul_exactly_at_cpl_limit_is_not_flagged(self):
        found, report = budgets.check(
            [{"key": "hangul-boundary", "target": "한" * 21, "start": 0, "end": 100}],
            budgets=self.subtitle_budget(cpl=42, cps=20),
        )
        self.assertEqual([], self.codes(found))
        self.assertEqual(42.0, report["measurements"][0]["cpl"])
        self.assert_report_finding_set(found, report)

    def test_cpl_uses_east_asian_display_width_not_codepoint_length(self):
        found, report = budgets.check(
            [
                {
                    "key": "wide-subtitle",
                    "edition_medium": "subtitle",
                    "target": "한" * 22,
                    "start": 0,
                    "end": 100,
                }
            ],
            budgets=self.subtitle_budget(cpl=42, cps=20),
        )
        self.assertEqual(["budget_subtitle_cpl_exceeded"], self.codes(found))
        self.assertEqual(44.0, report["measurements"][0]["cpl"])
        self.assert_report_finding_set(found, report)

    def test_append_multiply_and_split_project_lengths_and_split_changes_cpl_denominator(self):
        realisations = {
            "append": {"length_cost": {"model": "append", "value": 3}},
            "multiply": {"length_cost": {"model": "multiply", "value": 1.5}},
            "split": {"length_cost": {"model": "split", "value": 2}},
        }
        rows = [
            {
                "key": "append",
                "edition_medium": "subtitle",
                "target": "abcdefghij",
                "start": 0,
                "end": 10,
                "realisation_id": "append",
            },
            {
                "key": "multiply",
                "edition_medium": "subtitle",
                "target": "abcdefghij",
                "start": 0,
                "end": 10,
                "realisation_id": "multiply",
            },
            {
                "key": "split",
                "edition_medium": "subtitle",
                "target": "abcdefghij",
                "start": 0,
                "end": 10,
                "realisation_id": "split",
            },
        ]

        found, report = budgets.check(
            rows,
            budgets=self.subtitle_budget(cpl=20, cps=20),
            realisations=realisations,
        )

        self.assertTrue(found.is_clean())
        measured = {entry["row_key"]: entry for entry in report["measurements"]}
        self.assertEqual((13.0, 13.0, 1, 3.0), (
            measured["append"]["chars"],
            measured["append"]["cpl"],
            measured["append"]["lines"],
            measured["append"]["marker_length"],
        ))
        self.assertEqual((15.0, 15.0, 1, 5.0), (
            measured["multiply"]["chars"],
            measured["multiply"]["cpl"],
            measured["multiply"]["lines"],
            measured["multiply"]["marker_length"],
        ))
        self.assertEqual((10.0, 5.0, 2, 0.0), (
            measured["split"]["chars"],
            measured["split"]["cpl"],
            measured["split"]["lines"],
            measured["split"]["marker_length"],
        ))

    def test_violation_uses_declared_budget_without_widening(self):
        declared = self.subtitle_budget(cpl=42, cps=100)
        found, report = budgets.check(
            [
                {
                    "key": "exact-budget",
                    "edition_medium": "subtitle",
                    "target": "x" * 43,
                    "start": 0,
                    "end": 1,
                }
            ],
            budgets=declared,
        )

        self.assertIn("budget_subtitle_cpl_exceeded", self.codes(found))
        cpl_violation = next(
            item for item in report["violations"] if item["metric"] == "cpl"
        )
        self.assertEqual(declared["subtitle"]["cpl"], cpl_violation["budget"])
        self.assertEqual(42, cpl_violation["budget"])

    def test_unmodelled_edition_medium_is_a_limitation_not_a_measured_verdict(self):
        found, report = budgets.check(
            [
                {
                    "key": "game-row",
                    "edition_medium": "game/3ds",
                    "target": "anything",
                    "start": 0,
                    "end": 1,
                }
            ],
            budgets=self.subtitle_budget(),
        )

        self.assertEqual([], found.hard)
        self.assertEqual(["budget_edition_medium_unmodelled"], self.codes(found))
        self.assertEqual(0, report["measured"])
        self.assertEqual(1, report["unmeasurable"])
        self.assertEqual([], report["violations"])

    def test_advisory_rows_publish_marker_length_without_hard_bound(self):
        found, report = budgets.check(
            [
                {
                    "key": "advisory-row",
                    "edition_medium": "po",
                    "target": "plain",
                    "length_cost": {"model": "append", "value": 3},
                }
            ],
            budgets={
                "edition_medium": "po",
                "po": {"class": "advisory"},
            },
        )

        self.assertTrue(found.is_clean())
        self.assertEqual([], report["violations"])
        self.assertEqual(1, report["measured"])
        self.assertEqual(3.0, report["measurements"][0]["marker_length"])
        self.assertEqual(8.0, report["measurements"][0]["chars"])

    def test_balloon_checks_character_count_and_area(self):
        found, report = budgets.check(
            [
                {
                    "key": "balloon-row",
                    "edition_medium": "balloon",
                    "target": "abcd\nef",
                }
            ],
            budgets={
                "edition_medium": "balloon",
                "balloon": {"class": "balloon", "chars": 5, "area": 8},
            },
        )

        self.assertEqual(["budget_balloon_chars_exceeded"], self.codes(found))
        self.assertEqual(6.0, report["measurements"][0]["chars"])
        self.assertEqual(8.0, report["measurements"][0]["area"])

    def test_reports_publish_every_hard_and_report_finding(self):
        valid = {
            "key": "row",
            "edition_medium": "subtitle",
            "target": "fits",
            "start": 0,
            "end": 10,
        }
        cases = (
            (None, self.subtitle_budget()),
            ([valid], None),
            ([valid], {"edition_medium": "subtitle", "subtitle": {"class": "subtitle", "cps": 20}}),
            ([dict(valid, key="untimed", start=None, end=None)], self.subtitle_budget()),
            ([dict(valid, key="unknown-medium", edition_medium="game/3ds")], self.subtitle_budget()),
            ([dict(valid, key="surface-absent", target=None)], self.subtitle_budget()),
            (
                [dict(valid, key="unknown-cost", length_cost={"model": "unknown", "value": 1})],
                self.subtitle_budget(),
            ),
            ([dict(valid, key="cpl-exceeded", target="x" * 43)], self.subtitle_budget(cps=100)),
        )
        codes = set()
        for rows, declared in cases:
            found, report = budgets.check(rows, budgets=declared)
            self.assert_report_finding_set(found, report)
            codes.update(self.codes(found))
        self.assertEqual(
            {
                "budget_rows_invalid",
                "budget_rows_absent",
                "budget_declaration_invalid",
                "budget_subtitle_timing_absent",
                "budget_edition_medium_unmodelled",
                "budget_surface_absent",
                "budget_realisation_unmodelled",
                "budget_subtitle_cpl_exceeded",
            },
            codes,
        )

    def test_zero_rows_is_hard_not_a_clean_report(self):
        found, report = budgets.check([], budgets=self.subtitle_budget())

        self.assertFalse(found.is_clean())
        self.assertEqual(["budget_rows_absent"], self.codes(found))
        self.assertEqual(
            {
                "class": "subtitle",
                "rows": 0,
                "measured": 0,
                "unmeasurable": 0,
                "worst": {
                    "cpl": 0.0,
                    "cps": 0.0,
                    "chars": 0.0,
                    "area": 0.0,
                    "marker_length": 0.0,
                },
                "violations": [],
                "measurements": [],
                "findings": found.to_json(),
            },
            report,
        )


if __name__ == "__main__":
    unittest.main()
