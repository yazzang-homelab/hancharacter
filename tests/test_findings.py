import unittest

from hancharacter import findings
from hancharacter.findings import FindingSet, hard, report


class FindingSetTests(unittest.TestCase):
    def test_severity_is_the_single_authority(self):
        finding_set = FindingSet()
        finding_set.add(report("DENSITY_NOTE", "informational density warning"))

        self.assertTrue(finding_set.is_clean())
        self.assertEqual({"DENSITY_NOTE": 1}, finding_set.by_code())
        self.assertEqual("report", finding_set.reported[0].severity)

        finding_set.add(hard("DENSITY_NOTE", "blocking density failure"))
        self.assertFalse(finding_set.is_clean())
        self.assertEqual({"DENSITY_NOTE": 2}, finding_set.by_code())
        self.assertEqual("hard", finding_set.hard[0].severity)

    def test_module_has_no_hard_code_blocklist(self):
        self.assertFalse(
            any(
                isinstance(value, (set, frozenset)) and "hard" in name.lower()
                for name, value in vars(findings).items()
            )
        )

    def test_json_preserves_severity_and_optional_location(self):
        finding = hard(
            "DENSITY_RANGE",
            "target lies outside the permitted range",
            scope="speaker:iris",
            row_key="scene-4",
            axis="sentence_final",
        )
        self.assertEqual(
            {
                "code": "DENSITY_RANGE",
                "severity": "hard",
                "detail": "target lies outside the permitted range",
                "scope": "speaker:iris",
                "row_key": "scene-4",
                "axis": "sentence_final",
            },
            finding.to_json(),
        )


if __name__ == "__main__":
    unittest.main()
