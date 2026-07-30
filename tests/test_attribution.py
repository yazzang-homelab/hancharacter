import ast

import os
import unittest

from hancharacter import attribution, cli, config, segment


PROFILE_PATH = os.path.join(config.repo_root(), "profiles", "crimson_fixture.json")


def _profile_data():
    return {
        "work": "attribution-fixture",
        "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
        "evidence_lang": "en",
        "pivot_lang": "en",
        "target_lang": "ko",
        "speaker_roles": {
            "speaker1": config.ROLE_SPEAKER,
            "keyword1": config.ROLE_TERM,
            "default": config.ROLE_CLOSE,
            "dead": config.ROLE_SYSTEM,
        },
        "delimiters": {
            "en": {"speech": [['"', '"']], "term": []},
            "ko": {"speech": [['"', '"']], "term": []},
        },
    }


class _CsvProfile:
    """Supply the future closed CSV declaration without changing config ownership."""

    def __init__(self, profile):
        self._profile = profile
        self.data = dict(profile.data, csv_speaker_column="speaker")

    def __getattr__(self, name):
        return getattr(self._profile, name)


class _EmptyRoleProfile:
    def __init__(self, profile):
        self._profile = profile

    @property
    def speaker_roles(self):
        return {}

    def role(self, label):
        return None

    def is_speaker(self, label):
        return False

    def __getattr__(self, name):
        return getattr(self._profile, name)



def _emitted_hard_codes():
    path = os.path.join(config.repo_root(), "hancharacter", "attribution.py")
    with open(path, encoding="utf-8") as handle:
        tree = ast.parse(handle.read(), filename=path)
    return {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "findings"
        and node.func.attr == "hard"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    }


class AttributionTests(unittest.TestCase):
    def setUp(self):
        self.profile = config.Profile(_profile_data())

    def row(self, key, evidence='<color=speaker1>source', pivot='"source"', target='"target"'):
        return segment.Row(
            key=key,
            evidence=evidence,
            pivot=pivot,
            evidence_lang=self.profile.evidence_lang,
            pivot_lang=self.profile.pivot_lang,
            target=target,
        )

    def test_undeclared_label_is_never_attributed_and_is_ineligible(self):
        row = self.row("unknown", evidence="<color=unlisted>source")
        report = attribution.attribution_report([row], self.profile)

        self.assertEqual(1, report["eligibility"][config.INELIGIBLE_UNDECLARED])
        self.assertEqual((), attribution.attributions([row], self.profile))
        self.assertEqual((), attribution.attributed_for_gating([row], self.profile))
        undeclared = [
            finding for finding in report["findings"]
            if finding["code"] == "attribution_undeclared_label"
        ]
        self.assertEqual(1, len(undeclared))
        self.assertEqual("hard", undeclared[0]["severity"])

    def test_t2_candidate_stays_pending_and_cannot_reach_a_gate(self):
        row = self.row("candidate", evidence="unmarked source")
        row.attribution_tier = attribution.T2
        row.candidate_speaker = "speaker1"

        records = attribution.attributions([row], self.profile)
        self.assertEqual(1, len(records))
        self.assertEqual(attribution.T2, records[0].evidence_tier)
        self.assertEqual(attribution.T2, records[0].target_tier)
        self.assertEqual("pending", records[0].status)
        self.assertEqual((), attribution.attributed_for_gating([row], self.profile))

        report = attribution.attribution_report([row], self.profile)
        self.assertEqual(1, report["eligibility"][config.INELIGIBLE_PENDING])
        self.assertEqual(1, report["by_tier"][attribution.T2])

    def test_t3_confirmation_promotes_target_tier_and_records_identity_and_time(self):
        row = self.row("confirmed")
        confirmation = {
            "row_key": "confirmed",
            "speaker": "speaker1",
            "confirmed_by": "fixture reviewer",
            "confirmed_at": "2026-07-29T00:00:00Z",
        }

        records = attribution.attributions([row], self.profile, confirmations=[confirmation])
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual(attribution.T1, record.evidence_tier)
        self.assertEqual(attribution.T3, record.target_tier)
        self.assertEqual("confirmed", record.status)
        self.assertEqual("fixture reviewer", record.confirmed_by)
        self.assertEqual("2026-07-29T00:00:00Z", record.confirmed_at)

        units = attribution.attributed_for_gating([row], self.profile, confirmations=[confirmation])
        self.assertEqual(1, len(units))
        self.assertFalse(hasattr(units[0], "target_tier"))
        self.assertTrue(units[0].eligible)

    def test_declared_adapter_structures_are_t1_not_heuristics(self):
        rows = (
            {
                "key": "srt",
                "adapter": "srt",
                "speaker_prefix": "speaker1:",
                "evidence": "source srt",
                "pivot": '"source srt"',
                "target": '"target srt"',
            },
            {
                "key": "ass",
                "adapter": "ass",
                "speaker": "speaker1",
                "evidence": "source ass",
                "pivot": '"source ass"',
                "target": '"target ass"',
            },
            {
                "key": "po",
                "adapter": "po",
                "msgctxt": "speaker:speaker1",
                "evidence": "source po",
                "pivot": '"source po"',
                "target": '"target po"',
            },
        )
        records = attribution.attributions(rows, self.profile)
        self.assertEqual([attribution.T1] * 3, [record.evidence_tier for record in records])
        self.assertEqual([attribution.T1] * 3, [record.target_tier for record in records])
        self.assertEqual(3, len(attribution.attributed_for_gating(rows, self.profile)))
    def test_csv_speaker_column_requires_and_uses_a_declaration(self):
        row = {
            "key": "csv",
            "adapter": "csv",
            "speaker_column": "speaker",
            "csv_speaker": "speaker1",
            "evidence": "source",
            "pivot": '"source"',
            "target": '"target"',
        }
        profile = _CsvProfile(self.profile)
        records = attribution.attributions([row], profile)
        self.assertEqual(1, len(records))
        self.assertEqual(attribution.T1, records[0].target_tier)
        self.assertEqual(1, len(attribution.attributed_for_gating([row], profile)))


    def test_undeclared_structural_adapter_label_is_hard_and_not_attributed(self):
        row = {
            "key": "unknown-srt",
            "adapter": "srt",
            "speaker_prefix": "unlisted:",
            "evidence": "source",
            "pivot": '"source"',
            "target": '"target"',
        }
        found = attribution.lint_speaker_roles([row], self.profile)
        self.assertEqual(
            ["attribution_undeclared_label"],
            [finding.code for finding in found if finding.severity == "hard"],
        )
        self.assertEqual((), attribution.attributions([row], self.profile))

    def test_empty_speaker_role_map_is_hard_when_labels_are_present(self):
        row = self.row("empty-map", evidence="<color=speaker1>source")
        found = attribution.lint_speaker_roles([row], _EmptyRoleProfile(self.profile))
        self.assertEqual(["hard"], [finding.severity for finding in found])
        self.assertEqual(["attribution_undeclared_label"], [finding.code for finding in found])

    def test_lint_hard_for_present_undeclared_and_reports_dead_declaration(self):
        row = self.row("labels", evidence="<color=speaker1>one<color=unlisted>two")
        found = attribution.lint_speaker_roles([row], self.profile)

        hard = [finding for finding in found if finding.severity == "hard"]
        reports = [finding for finding in found if finding.severity == "report"]
        self.assertEqual(["attribution_undeclared_label"], [finding.code for finding in hard])
        self.assertIn("dead", [finding.scope for finding in reports])
        self.assertIn("attribution_dead_speaker_role", [finding.code for finding in reports])

    def test_eligibility_publishes_all_keys_including_checked_zeroes(self):
        report = attribution.attribution_report([self.row("clean")], self.profile)
        expected_keys = {
            config.INELIGIBLE_MIXED_SPAN,
            config.INELIGIBLE_DUPLICATE_SOURCE,
            config.INELIGIBLE_PENDING,
            config.INELIGIBLE_UNDECLARED,
            config.INELIGIBLE_UNSPLITTABLE,
            config.COUNTER_SCOPE_UNREALISED,
        }
        self.assertEqual(expected_keys, set(report["eligibility"]))
        self.assertTrue(all(value == 0 for value in report["eligibility"].values()))

    def test_duplicate_source_detail_explicitly_states_the_deferral(self):
        rows = [
            self.row("one", pivot='"first pivot"'),
            self.row("two", pivot='"second pivot"'),
        ]
        report = attribution.attribution_report(rows, self.profile)

        self.assertEqual(2, report["eligibility"][config.INELIGIBLE_DUPLICATE_SOURCE])
        details = [
            finding["detail"] for finding in report["findings"]
            if finding["code"] == "attribution_duplicate_source_deferred"
        ]
        self.assertEqual(2, len(details))
        self.assertTrue(all(
            "host TM keys on the source (evidence) string, so two rows sharing it cannot be attributed apart" in detail
            for detail in details
        ))

    def test_t1_rate_is_exact_from_the_published_report_not_a_caller_argument(self):
        report = {
            "by_tier": {
                attribution.T1: 19,
                attribution.T2: 57,
                attribution.T3: 1,
            }
        }
        self.assertEqual(0.95, attribution.t1_rate(report))

    def test_empty_rows_produce_a_hard_finding(self):
        report = attribution.attribution_report([], self.profile)
        empty = [
            finding for finding in report["findings"]
            if finding["code"] == "attribution_rows_empty"
        ]
        self.assertEqual(1, len(empty))
        self.assertEqual("hard", empty[0]["severity"])
        self.assertIsNone(attribution.t1_rate(report))

    def test_every_hard_finding_has_a_reachability_case(self):
        unknown = self.row("unknown", evidence="<color=unlisted>source")
        lint_codes = {finding.code for finding in attribution.lint_speaker_roles([unknown], self.profile)}
        empty_codes = {
            finding["code"]
            for finding in attribution.attribution_report([], self.profile)["findings"]
            if finding["severity"] == "hard"
        }
        self.assertEqual(
            {"attribution_undeclared_label", "attribution_rows_empty"},
            _emitted_hard_codes(),
        )
        self.assertIn("attribution_undeclared_label", lint_codes)
        self.assertIn("attribution_rows_empty", empty_codes)


class ExternalFixtureAttributionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = config.fixture_path()
        if not os.path.exists(fixture):
            raise unittest.SkipTest("read-only fixture is unavailable")
        cls.profile = config.load_profile(PROFILE_PATH)
        cls.rows = cli._load_rows(fixture, cls.profile)

    def test_keyword_otherline_and_narration_rows_create_zero_phantom_speaker_scopes(self):
        report = attribution.attribution_report(self.rows, self.profile)
        gate_units = attribution.attributed_for_gating(self.rows, self.profile)
        declared_speakers = {
            label for label, role in self.profile.speaker_roles.items()
            if role == config.ROLE_SPEAKER
        }
        nonvoice_rows = set()
        for row in self.rows:
            state = segment.eligibility(row, self.profile)
            labels = attribution._tag_labels(row, self.profile)
            has_nonvoice_label = any(
                label in {"keyword1", "otherline1", "otherline2", "secondperson1"}
                for label in labels
            )
            if not state.scopes and (has_nonvoice_label or not labels):
                nonvoice_rows.add(row.key)

        phantom = [unit for unit in gate_units if unit.row_key in nonvoice_rows]
        self.assertEqual(set(report["scopes"]), declared_speakers)
        self.assertEqual([], phantom)
        self.assertEqual(0, len(phantom))
        self.assertGreater(len(nonvoice_rows), 0)


if __name__ == "__main__":
    unittest.main()
