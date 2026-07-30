import contextlib
import io
import json
import os
import tempfile
import unittest

from hancharacter import cli, config
from hancharacter import segment



PROFILE_PATH = os.path.join(config.repo_root(), "profiles", "crimson_fixture.json")


def grouped_count(row, profile, side):
    if side == "evidence":
        units = segment.evidence_units(row, profile)
    else:
        units = segment.side_units(row, profile, side)
    return segment.group_units(units)

class _ProfileWithDelimiters:
    """Exercise segmentation's boundary guard without weakening Profile immutability."""

    def __init__(self, profile, delimiters):
        self._profile = profile
        self._delimiters = delimiters

    def delimiters(self, lang):
        return self._delimiters.get(lang)

    def __getattr__(self, name):
        return getattr(self._profile, name)


def _run_segment_cli(profile_data, rows, keys=()):
    with tempfile.TemporaryDirectory() as directory:
        profile_path = os.path.join(directory, "profile.json")
        rows_path = os.path.join(directory, "rows.json")
        with open(profile_path, "w", encoding="utf-8") as handle:
            json.dump(profile_data, handle)
        with open(rows_path, "w", encoding="utf-8") as handle:
            json.dump(rows, handle)
        stdout = io.StringIO()
        stderr = io.StringIO()
        arguments = ["segment", "--profile", profile_path, "--rows", rows_path]
        for key in keys:
            arguments.extend(["--key", key])
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = cli.main(arguments)
    return rc, stdout.getvalue(), stderr.getvalue()


class SyntheticSegmentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = config.load_profile(PROFILE_PATH)

    def row(self, key, evidence, pivot, target=None):
        return segment.Row(
            key=key,
            evidence=evidence,
            pivot=pivot,
            evidence_lang=self.profile.evidence_lang,
            pivot_lang=self.profile.pivot_lang,
            target=target,
        )

    def profile_with_delimiters(self, mutate):
        payload = json.loads(self.profile.to_json())
        mutate(payload["delimiters"])
        return _ProfileWithDelimiters(self.profile, payload["delimiters"])

    def test_newline_and_sentence_boundaries_do_not_split_a_quote(self):
        wrapped = self.row(
            "wrapped",
            "<color=frea1>source<color=default>",
            '"First line.\nSecond line."',
        )
        two_sentences = self.row(
            "two-sentences",
            "<color=frea1>source<color=default>",
            '"First sentence. Second sentence."',
        )
        self.assertEqual(len(grouped_count(wrapped, self.profile, "pivot")), 1)
        self.assertEqual(len(grouped_count(two_sentences, self.profile, "pivot")), 1)

    def test_layout_tag_does_not_create_a_stretch_initial_quote(self):
        payload = json.loads(self.profile.to_json())
        payload["layout_tags"] = ["<lineheight=8>"]
        profile = config.Profile(payload)
        spans = segment.speech_spans(
            '"Speech." said<lineheight=8>"Title."', profile, profile.pivot_lang
        )
        self.assertEqual(["speech", "term"], [span.kind for span in spans])

    def test_role_change_close_makes_a_single_standard_ja_row_eligible(self):
        payload = json.loads(self.profile.to_json())
        payload.update({"evidence_lang": "ja", "pivot_lang": "ja", "target_lang": "ja"})
        profile = config.Profile(payload)
        row = segment.Row(
            key="implicit-ja-close",
            evidence="<color=frea1>「source<color=default>",
            pivot="<color=frea1>「speech<color=default>",
            evidence_lang="ja",
            pivot_lang="ja",
        )
        state = segment.eligibility(row, profile)
        self.assertTrue(state.eligible)
        self.assertEqual(
            ["speech"],
            [span.kind for span in segment.speech_spans(row.pivot, profile, "ja")],
        )
        self.assertEqual(1, len(grouped_count(row, profile, "pivot")))

    def test_ruby_exposes_base_and_reading_surfaces(self):
        row = self.row(
            "ruby",
            "<color=frea1><ruby>字<rt>じ</rt></ruby><color=default>",
            '"Speech."',
        )
        unit = segment.evidence_units(row, self.profile)[0]
        self.assertEqual(unit.base, "字")
        self.assertEqual(unit.reading, "字じ")

    def test_non_speaker_roles_do_not_create_attribution(self):
        for label in ("keyword1", "otherline2"):
            with self.subTest(label=label):
                row = self.row(
                    "non-speaker-" + label,
                    "<color=%s>metadata<color=default>" % label,
                    '"Speech."',
                )
                state = segment.eligibility(row, self.profile)
                self.assertEqual(segment.evidence_units(row, self.profile), [])
                self.assertEqual(state.scopes, [])
                self.assertFalse(state.eligible and bool(state.scopes))

    def test_eligibility_reports_each_attribution_blocker(self):
        cases = (
            (
                self.row(
                    "unknown-label",
                    "<color=unlisted>source<color=default>",
                    '"Speech."',
                ),
                {},
                config.INELIGIBLE_UNDECLARED,
            ),
            (
                self.row(
                    "mixed-speakers",
                    "<color=frea1>one<color=giauque1>two<color=default>",
                    '"Speech."',
                ),
                {},
                config.INELIGIBLE_MIXED_SPAN,
            ),
            (
                self.row(
                    "unpaired-quote",
                    "<color=frea1>source<color=default>",
                    '"unfinished',
                ),
                {},
                config.INELIGIBLE_UNSPLITTABLE,
            ),
            (
                self.row(
                    "duplicate-source",
                    "<color=frea1>source<color=default>",
                    '"Speech."',
                ),
                {"duplicate_source": True},
                config.INELIGIBLE_DUPLICATE_SOURCE,
            ),
        )
        for row, kwargs, reason in cases:
            with self.subTest(row=row.key):
                state = segment.eligibility(row, self.profile, **kwargs)
                self.assertFalse(state.eligible)
                self.assertIn(reason, state.reasons)


    def test_profile_data_is_immutable_after_validation(self):
        with self.assertRaises(TypeError):
            self.profile.data["coverage_floor"] = 0.8
        with self.assertRaises(TypeError):
            self.profile.data["speaker_roles"]["frea1"] = config.ROLE_TERM
        with self.assertRaises(TypeError):
            self.profile.data["delimiters"]["en"]["speech"][0][0] = "["

        payload = json.loads(self.profile.to_json())
        payload["speaker_roles"]["frea1"] = config.ROLE_TERM
        fresh_profile = config.Profile(payload)
        self.assertFalse(fresh_profile.is_speaker("frea1"))
        row = self.row(
            "fresh-role-declaration",
            "<color=frea1>source<color=default>",
            '"Speech."',
        )
        self.assertEqual([], segment.eligibility(row, fresh_profile).scopes)
    def test_missing_pivot_delimiters_raises(self):
        """The segmentation boundary guard also protects duck-typed profiles."""
        profile = self.profile_with_delimiters(
            lambda delimiters: delimiters.pop(self.profile.pivot_lang)
        )
        row = self.row(
            "missing-pivot-delimiters",
            "<color=frea1>source<color=default>",
            '"Speech."',
        )
        with self.assertRaisesRegex(ValueError, self.profile.pivot_lang):
            segment.side_units(row, profile, "pivot")

    def test_malformed_delimiter_pair_raises(self):
        profile = self.profile_with_delimiters(
            lambda delimiters: delimiters[self.profile.pivot_lang].update(
                {"speech": [["「"]]}
            )
        )
        row = self.row(
            "malformed-pivot-delimiters",
            "<color=frea1>source<color=default>",
            '"Speech."',
        )
        with self.assertRaisesRegex(ValueError, "「"):
            segment.side_units(row, profile, "pivot")

    def test_empty_speech_declaration_raises_instead_of_measuring_zero(self):
        """An empty declaration must never quietly return zero speech spans."""
        profile = self.profile_with_delimiters(
            lambda delimiters: delimiters[self.profile.pivot_lang].update({"speech": []})
        )
        row = self.row(
            "empty-speech-declaration",
            "<color=frea1>source<color=default>",
            '"Speech."',
        )
        with self.assertRaisesRegex(ValueError, "speech"):
            segment.side_units(row, profile, "pivot")

    def test_h2_parity_reports_a_dropped_quotation_mark_rather_than_failing(self):
        """Losing the quote marks is a typographic choice, not a lost utterance."""
        matching = self.row(
            "h2-matching",
            "<color=frea1>source<color=default>",
            '"Voice." a title called "Term."',
            '"목소리." 설명 「용어」',
        )
        unquoted = self.row(
            "h2-unquoted",
            "<color=frea1>source<color=default>",
            '"Voice." a title called "Term."',
            "설명 「용어」",
        )
        self.assertIsNone(segment.quote_parity(matching, self.profile))
        finding = segment.quote_parity(unquoted, self.profile)
        self.assertIsNotNone(finding)
        self.assertEqual(finding.code, "voice-quote-parity")
        self.assertEqual(finding.severity, "report")

    def test_h2_parity_fails_hard_only_when_the_target_has_no_visible_text(self):
        emptied = self.row(
            "h2-emptied",
            "<color=frea1>source<color=default>",
            '"Voice."',
            "<ctrl>   ",
        )
        finding = segment.quote_parity(emptied, self.profile)
        self.assertIsNotNone(finding)
        self.assertEqual("hard", finding.severity)
        self.assertIn("no visible text", finding.detail)

    def test_h2_parity_never_fails_a_faithful_attribution_first_rendering(self):
        """Pivot and target are permitted to classify quotes by different rules.

        An attribution-first pivot puts its quote mid-stretch, where the positional
        policy reads it as terminology and counts zero speech spans, while the
        Korean target declares terminology delimiters of its own and counts one.
        Both renderings are faithful, so neither direction may be a hard failure.
        """
        rows = (
            self.row(
                "faithful-attribution-first",
                "<color=frea1>source<color=default>",
                'Frea says, "Lovely."',
                '프레아가 말했다, "좋네."',
            ),
            self.row(
                "faithful-quote-first",
                "<color=frea1>source<color=default>",
                '"Lovely," Frea says.',
                '프레아가 말했다, "좋네."',
            ),
        )
        for row in rows:
            with self.subTest(row=row.key):
                finding = segment.quote_parity(row, self.profile)
                if finding is not None:
                    self.assertEqual(
                        "report",
                        finding.severity,
                        "a faithful rendering must never be a hard failure",
                    )

    def test_report_keeps_a_two_reason_row_separate_from_pure_narration(self):
        ineligible = self.row(
            "two-reasons",
            "<color=frea1>one<color=giauque1>two<color=default>",
            '"unfinished',
        )
        narration = self.row(
            "narration",
            "<color=keyword1>metadata<color=default>",
            '"speech"',
        )
        report = segment.segment_report([ineligible, narration], self.profile)
        self.assertEqual(1, report["ineligible_rows"])
        self.assertEqual(1, report["ineligible"][config.INELIGIBLE_MIXED_SPAN])
        self.assertEqual(1, report["ineligible"][config.INELIGIBLE_UNSPLITTABLE])
        self.assertEqual(1, report["pure_narration_rows"])

    def test_segment_report_publishes_quote_parity_findings_by_severity(self):
        cases = (
            (
                "pivot_dropped_a_line",
                self.row(
                    "pivot-dropped-a-line",
                    "<color=frea1>source<color=default>",
                    "narration",
                    '"one"',
                ),
                0,
                "report",
            ),
            (
                "split",
                self.row(
                    "split",
                    "<color=frea1>source<color=default>",
                    '"one"<ctrl>"two"',
                    '"one"',
                ),
                0,
                "report",
            ),
            (
                "emptied",
                self.row(
                    "emptied",
                    "<color=frea1>source<color=default>",
                    '"one"',
                    "   ",
                ),
                1,
                "hard",
            ),
            (
                "clean",
                self.row(
                    "clean",
                    "<color=frea1>source<color=default>",
                    '"one"',
                    '"one"',
                ),
                0,
                None,
            ),
        )
        for direction, row, expected_hard_findings, severity in cases:
            with self.subTest(direction=direction):
                report = segment.segment_report([row], self.profile)
                self.assertEqual(expected_hard_findings, report["hard_findings"])
                self.assertEqual(0 if severity is None else 1, len(report["findings"]))
                if severity is not None:
                    self.assertEqual("voice-quote-parity", report["findings"][0]["code"])
                    self.assertEqual(severity, report["findings"][0]["severity"])


class SegmentCliTests(unittest.TestCase):
    @staticmethod
    def profile(coverage_floor=0.70, pivot_speech=None):
        if pivot_speech is None:
            pivot_speech = [['"', '"']]
        return {
            "work": "cli-test",
            "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
            "evidence_lang": "en",
            "pivot_lang": "en",
            "target_lang": "ko",
            "speaker_roles": {
                "speaker1": config.ROLE_SPEAKER,
                "metadata": config.ROLE_TERM,
                "close": config.ROLE_CLOSE,
            },
            "delimiters": {
                "en": {"speech": pivot_speech, "term": []},
                "ko": {"speech": [['"', '"']], "term": []},
            },
            "coverage_floor": coverage_floor,
        }

    def test_hard_quote_parity_is_printed_and_returns_nonzero(self):
        """Only an emptied utterance is unambiguous enough to fail the command."""
        rc, stdout, stderr = _run_segment_cli(
            self.profile(),
            [
                {
                    "key": "emptied",
                    "evidence": "<color=speaker1>source<color=close>",
                    "pivot": '"one"',
                    "target": "   ",
                }
            ],
        )
        self.assertEqual(1, rc)
        self.assertEqual("", stderr)
        self.assertIn("HARD voice-quote-parity", stdout)
        self.assertIn("hard finding", stdout)


    def test_non_speaker_profile_is_rejected_before_segmenting(self):
        profile = self.profile()
        profile["speaker_roles"] = {
            "metadata": config.ROLE_TERM,
            "system": config.ROLE_SYSTEM,
            "close": config.ROLE_CLOSE,
        }
        rc, stdout, stderr = _run_segment_cli(
            profile,
            [
                {
                    "key": "suppressed",
                    "evidence": "<color=metadata>metadata<color=close>",
                    "pivot": '"speech"',
                }
            ],
        )
        self.assertEqual(2, rc)
        self.assertEqual("", stdout)
        self.assertIn("at least one speaker role", stderr)
    def test_rows_without_speaker_scopes_return_nonzero(self):
        rc, stdout, stderr = _run_segment_cli(
            self.profile(),
            [
                {
                    "key": "unscoped",
                    "evidence": "<color=metadata>metadata<color=close>",
                    "pivot": '"speech"',
                }
            ],
        )
        self.assertEqual(1, rc)
        self.assertEqual("", stderr)
        self.assertIn("none carries a speaker scope", stdout)

    def test_unrealised_pivot_scope_returns_nonzero(self):
        rc, stdout, stderr = _run_segment_cli(
            self.profile(pivot_speech=[["[", "]"]]),
            [
                {
                    "key": "unrealised",
                    "evidence": "<color=speaker1>source<color=close>",
                    "pivot": '"speech"',
                }
            ],
        )
        self.assertEqual(1, rc)
        self.assertEqual("", stderr)
        self.assertIn("no realised pivot spans", stdout)

    def test_low_coverage_returns_nonzero(self):
        rc, stdout, stderr = _run_segment_cli(
            self.profile(coverage_floor=0.80),
            [
                {
                    "key": "realised",
                    "evidence": "<color=speaker1>source<color=close>",
                    "pivot": '"speech"',
                },
                {
                    "key": "unrealised",
                    "evidence": "<color=speaker1>source<color=close>",
                    "pivot": "narration",
                },
            ],
        )
        self.assertEqual(1, rc)
        self.assertEqual("", stderr)
        self.assertIn("coverage 0.500 is below declared floor 0.80", stdout)


    def test_unmeasured_declared_scope_returns_nonzero(self):
        profile = self.profile()
        profile["speaker_roles"]["speaker2"] = config.ROLE_SPEAKER
        rows = [
            {
                "key": "realised",
                "evidence": "<color=speaker1>source<color=close>",
                "pivot": '"speech"',
            }
        ]
        rc, stdout, stderr = _run_segment_cli(profile, rows)
        self.assertEqual(1, rc)
        self.assertEqual("", stderr)
        self.assertIn("speaker2", stdout)
        self.assertIn("no attributed unit", stdout)

    def test_key_slice_suppresses_unmeasured_scope_failure(self):
        profile = self.profile()
        profile["speaker_roles"]["speaker2"] = config.ROLE_SPEAKER
        rows = [
            {
                "key": "realised",
                "evidence": "<color=speaker1>source<color=close>",
                "pivot": '"speech"',
            }
        ]
        rc, stdout, stderr = _run_segment_cli(profile, rows, keys=("realised",))
        self.assertEqual(0, rc)
        self.assertEqual("", stderr)
        self.assertNotIn("FAIL declared speaker scope", stdout)

    def test_scene_pattern_falls_back_to_explicit_row_scene(self):
        profile_data = self.profile()
        profile_data["scene_pattern"] = r"^(scene-\d+)"
        profile = config.Profile(profile_data)
        with tempfile.TemporaryDirectory() as directory:
            rows_path = os.path.join(directory, "rows.json")
            with open(rows_path, "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "host-family": [
                            {
                                "key": "unmatched",
                                "scene": "explicit-scene",
                                "en": '"speech"',
                            }
                        ]
                    },
                    handle,
                )
            rows = cli._load_rows(rows_path, profile)
        self.assertEqual("explicit-scene", rows[0].scene)

class FixtureSegmentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = config.fixture_path()
        if not os.path.exists(fixture):
            raise unittest.SkipTest("read-only fixture is unavailable")
        cls.profile = config.load_profile(PROFILE_PATH)
        with open(fixture, encoding="utf-8") as handle:
            data = json.load(handle)
        cls.records = {record["key"]: record for record in data["dialogue"]}

    def row(self, key):
        record = self.records[key]
        return segment.Row(
            key=record["key"],
            evidence=record["jp"],
            pivot=record["en"],
            evidence_lang=self.profile.evidence_lang,
            pivot_lang=self.profile.pivot_lang,
        )

    def test_hand_table(self):
        table = (
            ("mes10_FM_008", "lippi1", 1, 1, "yes"),
            ("mes08_FM_004", "frea1", 1, 1, "yes"),
            ("mes08_FM_002", "frea1", 1, 1, "yes"),
            ("mes08_FM_005", "giauque1", 1, 0, "no"),
            ("mes13_FM_004", "frea1", 1, 1, "yes"),
            ("mes14_FM_002", "lippi1", 1, 1, "yes"),
            ("mes15_FM_001", "lippi1", 1, 1, "yes"),
            ("mes16_FM_002", "frea1+giauque1", None, None, "ineligible"),
            ("mes16_FM_001", "", 0, 0, "n/a"),
        )
        for key, scope_text, evidence_expected, pivot_expected, both in table:
            with self.subTest(key=key):
                row = self.row(key)
                state = segment.eligibility(row, self.profile)
                evidence = grouped_count(row, self.profile, "evidence")
                pivot = grouped_count(row, self.profile, "pivot")
                if both == "ineligible":
                    self.assertFalse(state.eligible)
                    self.assertEqual(
                        state.reasons, [config.INELIGIBLE_MIXED_SPAN]
                    )
                    self.assertEqual(state.scopes, scope_text.split("+"))
                    actual_both = None
                else:
                    self.assertTrue(state.eligible)
                    self.assertEqual(len(evidence), evidence_expected)
                    self.assertEqual(len(pivot), pivot_expected)
                    actual_both = None if not state.scopes else (
                        len(evidence) > 0 and len(pivot) > 0
                    )
                if both == "yes":
                    self.assertTrue(actual_both)
                elif both == "no":
                    self.assertFalse(actual_both)
                else:
                    self.assertIsNone(actual_both)

    def test_h1_scope_extent_and_mid_stretch_term(self):
        lippi = self.row("mes10_FM_008")
        lippi_units = grouped_count(lippi, self.profile, "pivot")
        self.assertEqual(len(lippi_units), 1)
        unit = lippi_units[(lippi.key, "lippi1")]
        self.assertNotIn("Lippi says", unit.base)

        term_row = self.row("mes15_FM_001")
        spans = segment.speech_spans(
            term_row.pivot, self.profile, term_row.pivot_lang
        )
        terms = [span for span in spans if span.kind == "term"]
        self.assertTrue(
            any("Defense of Heresy" in segment.strip_tags(
                span.text, self.profile, keep_ruby_reading=False
            ) for span in terms)
        )
        self.assertEqual(len(grouped_count(term_row, self.profile, "evidence")), 1)
        self.assertEqual(len(grouped_count(term_row, self.profile, "pivot")), 1)

    def test_m3_unrealised_scope_is_excluded_from_coverage_numerator(self):
        row = self.row("mes08_FM_005")
        evidence = grouped_count(row, self.profile, "evidence")
        pivot = grouped_count(row, self.profile, "pivot")
        self.assertEqual(len(evidence), 1)
        self.assertEqual(len(pivot), 0)

        report = segment.segment_report([row], self.profile)
        self.assertEqual(report["counters"][config.COUNTER_SCOPE_UNREALISED], 1)
        self.assertEqual(
            report["scopes"]["giauque1"],
            {
                "evidence_units": 1,
                "pivot_units": 0,
                "target_units": 0,
                "unrealised": 1,
                "rows": ["mes08_FM_005"],
                "scene_counts": {"mes08": 1},
                "units_without_scene": 0,
                "n_scenes": 1,
            },
        )
        self.assertEqual(
            report["coverage"]["giauque1"],
            {"eligible_units": 0, "attributed_units": 1, "ratio": 0.0},
        )

    def test_fixture_scene_pattern_resolves_36_scenes_for_best_covered_speaker(self):
        report = segment.segment_report(
            cli._load_rows(config.fixture_path(), self.profile), self.profile
        )
        self.assertEqual(36, report["scopes"]["lippi1"]["n_scenes"])
        self.assertGreater(
            report["scopes"]["lippi1"]["n_scenes"], config.MIN_SCENES_PER_BAND
        )

    def test_shipped_fixture_segment_command_exits_zero(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            rc = cli.main(
                [
                    "segment",
                    "--profile",
                    PROFILE_PATH,
                    "--rows",
                    config.fixture_path(),
                ]
            )
        self.assertEqual(0, rc)
        self.assertEqual("", stderr.getvalue())
        self.assertIn("rows                       4052", stdout.getvalue())
        self.assertIn("rows with a speaker scope  208", stdout.getvalue())
        self.assertIn("ineligible rows            37", stdout.getvalue())
        self.assertIn("ineligibility reasons      38", stdout.getvalue())
        self.assertIn("mixed_speaker_span         36", stdout.getvalue())
        self.assertIn("unsplittable_payload       2", stdout.getvalue())
        self.assertIn("counter voice_scope_unrealised 24", stdout.getvalue())
        self.assertIn("counter units_without_scene 0", stdout.getvalue())
        for ratio in ("0.818", "0.915", "0.774", "0.918"):
            self.assertIn("ratio=" + ratio, stdout.getvalue())


class DeclaredPositionalityTests(unittest.TestCase):
    """Whether stretch position discriminates speech from terminology is declared.

    English reuses the straight quote for both speech and terminology, so position
    is the only available discriminator there and a mid-stretch quote is a term.
    Korean gives terminology its own brackets, so a straight-quoted span is speech
    wherever it sits — applying the positional rule there would read a second
    consecutive utterance as a term and hide an invented line.
    """

    def setUp(self):
        self.profile = config.load_profile(
            os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "profiles", "crimson_fixture.json")
        )

    def test_positional_language_reads_a_mid_stretch_quote_as_a_term(self):
        pivot = '"Where is it?"<br><key>He came for the "Defense of Heresy," nothing else.'
        kinds = [span.kind for span in segment.speech_spans(pivot, self.profile, "en")]
        self.assertEqual(["speech", "term"], kinds)

    def test_declared_non_positional_language_keeps_consecutive_utterances(self):
        target = '"갔어." "또 갔어."'
        kinds = [span.kind for span in segment.speech_spans(target, self.profile, "ko")]
        self.assertEqual(["speech", "speech"], kinds)

    def test_pivot_dropped_line_is_reported_not_failed(self):
        """A quoted target against an unquoted pivot means the pivot dropped a line.

        On an eligible row the evidence side always carries a speaker scope, so this
        shape cannot mean the target fabricated a voice; it is already published as
        `voice_scope_unrealised`, and a translator restoring a line the pivot lost is
        faithful to the source. Detecting a fabricated voice belongs to the
        catalogue-anchored invention scan, not to a span count.
        """
        row = segment.Row(
            key="pivot-dropped-a-line",
            evidence="<color=lippi1>「いった。」<color=default>",
            pivot="narration",
            target='"갔어."',
            evidence_lang=self.profile.evidence_lang,
            pivot_lang=self.profile.pivot_lang,
            scene="scene1",
        )
        report = segment.segment_report([row], self.profile)
        self.assertEqual(0, report["hard_findings"])
        self.assertEqual(
            ["voice-quote-parity"], [f["code"] for f in report["findings"]]
        )
        self.assertEqual("report", report["findings"][0]["severity"])

    def test_faithful_split_quote_is_report_only_when_rules_differ(self):
        row = segment.Row(
            key="faithful-split",
            evidence="<color=lippi1>「いった。」<color=default>",
            pivot='"A," he said, "B."',
            target='"A," 그가 말했다, "B."',
            evidence_lang=self.profile.evidence_lang,
            pivot_lang=self.profile.pivot_lang,
            scene="scene1",
        )
        report = segment.segment_report([row], self.profile)
        self.assertEqual(0, report["hard_findings"])
        self.assertEqual(1, len(report["findings"]))
        self.assertEqual("report", report["findings"][0]["severity"])
        self.assertIn("split or merged quotation", report["findings"][0]["detail"])

    def test_non_boolean_positional_declaration_raises(self):
        profile = config.Profile(json.loads(self.profile.to_json()))
        data = json.loads(profile.to_json())
        data["delimiters"]["ko"]["speech_is_positional"] = "yes"
        with self.assertRaisesRegex(ValueError, "speech_is_positional"):
            config.Profile(data)


class EmptyTargetTests(unittest.TestCase):
    """An absent target is untranslated work; an empty one is a deleted utterance.

    Collapsing the second into the first would hide exactly the loss the parity
    check exists to catch, so the two must stay distinguishable through both
    supported row shapes.
    """

    def setUp(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.profile = config.load_profile(
            os.path.join(root, "profiles", "crimson_fixture.json")
        )
        self.row_fields = {
            "key": "deleted",
            "evidence": "<color=lippi1>「いった。」<color=default>",
            "pivot": '"He went."',
            "evidence_lang": self.profile.evidence_lang,
            "pivot_lang": self.profile.pivot_lang,
            "scene": "scene1",
        }

    def test_missing_target_has_nothing_to_compare(self):
        row = segment.Row(**self.row_fields)
        self.assertIsNone(segment.quote_parity(row, self.profile))

    def test_empty_target_is_a_hard_parity_loss(self):
        row = segment.Row(target="", **self.row_fields)
        finding = segment.quote_parity(row, self.profile)
        self.assertIsNotNone(finding)
        self.assertEqual("hard", finding.severity)
        self.assertEqual("voice-quote-parity", finding.code)

    def test_zero_width_and_bom_only_targets_are_hard_parity_losses(self):
        for target in ("\u200b", "\ufeff"):
            with self.subTest(target=target):
                finding = segment.quote_parity(
                    segment.Row(target=target, **self.row_fields), self.profile
                )
                self.assertIsNotNone(finding)
                self.assertEqual("hard", finding.severity)

    def test_term_substitution_target_is_visible_but_control_markup_is_not(self):
        substitution = segment.quote_parity(
            segment.Row(target="<player>", **self.row_fields), self.profile
        )
        self.assertIsNotNone(substitution)
        self.assertEqual("report", substitution.severity)

        control = segment.quote_parity(
            segment.Row(target="<ctrl>   ", **self.row_fields), self.profile
        )
        self.assertIsNotNone(control)
        self.assertEqual("hard", control.severity)

    def test_cli_preserves_empty_target_in_both_row_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = os.path.join(tmp, "profile.json")
            with open(profile_path, "w", encoding="utf-8") as handle:
                handle.write(self.profile.to_json())

            listed = os.path.join(tmp, "listed.json")
            with open(listed, "w", encoding="utf-8") as handle:
                json.dump([dict(self.row_fields, target="")], handle, ensure_ascii=False)

            host_shaped = os.path.join(tmp, "host.json")
            with open(host_shaped, "w", encoding="utf-8") as handle:
                json.dump(
                    {"dialogue": [{"key": "deleted",
                                   "jp": self.row_fields["evidence"],
                                   "en": self.row_fields["pivot"],
                                   "ko": ""}]},
                    handle,
                    ensure_ascii=False,
                )

            for rows_path in (listed, host_shaped):
                with self.subTest(rows=os.path.basename(rows_path)):
                    buffer = io.StringIO()
                    with contextlib.redirect_stdout(buffer):
                        code = cli.main(
                            ["segment", "--profile", profile_path, "--rows", rows_path]
                        )
                    self.assertNotEqual(0, code)
                    self.assertIn("voice-quote-parity", buffer.getvalue())


class SceneAndKeyFilterTests(unittest.TestCase):
    """Two silencing routes the architect review found, pinned closed.

    A unit with no resolvable scene is invisible to the per-scene band and caps the
    density verdict at `report`; a `--key` filter that selects nothing suppresses
    every coverage check. Both used to be silent.
    """

    def setUp(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.profile = config.load_profile(
            os.path.join(root, "profiles", "crimson_fixture.json")
        )

    def _row(self, key, scene=None):
        return segment.Row(
            key=key,
            evidence="<color=lippi1>「あ。」<color=default>",
            pivot='"Ah."',
            evidence_lang=self.profile.evidence_lang,
            pivot_lang=self.profile.pivot_lang,
            scene=scene,
        )

    def test_declared_key_rule_resolves_scenes_for_a_direct_caller(self):
        report = segment.segment_report([self._row("dialogue/mes08_FM_005")], self.profile)
        self.assertEqual({"mes08": 1}, report["scopes"]["lippi1"]["scene_counts"])
        self.assertEqual(1, report["scopes"]["lippi1"]["n_scenes"])
        self.assertEqual(0, report["counters"][config.COUNTER_UNITS_WITHOUT_SCENE])

    def test_blank_scene_metadata_is_absent_not_a_scene_bucket(self):
        for scene in ("", " \t"):
            with self.subTest(scene=repr(scene)):
                report = segment.segment_report([self._row("no-scene-here", scene)], self.profile)
                scope = report["scopes"]["lippi1"]
                self.assertEqual({}, scope["scene_counts"])
                self.assertEqual(0, scope["n_scenes"])
                self.assertEqual(1, scope["units_without_scene"])
                self.assertEqual(1, report["counters"][config.COUNTER_UNITS_WITHOUT_SCENE])

    def test_unresolvable_scene_is_published_not_silently_dropped(self):
        report = segment.segment_report([self._row("no-scene-here")], self.profile)
        self.assertEqual(1, report["scopes"]["lippi1"]["units_without_scene"])
        self.assertEqual(1, report["counters"][config.COUNTER_UNITS_WITHOUT_SCENE])
        self.assertEqual(0, report["scopes"]["lippi1"]["n_scenes"])

    def test_key_filter_matching_nothing_is_an_error_not_a_clean_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = os.path.join(tmp, "profile.json")
            with open(profile_path, "w", encoding="utf-8") as handle:
                handle.write(self.profile.to_json())
            rows_path = os.path.join(tmp, "rows.json")
            with open(rows_path, "w", encoding="utf-8") as handle:
                json.dump(
                    [{"key": "mes08_FM_005",
                      "evidence": "<color=lippi1>「あ。」<color=default>",
                      "pivot": '"Ah."'}],
                    handle,
                    ensure_ascii=False,
                )
            buffer = io.StringIO()
            with contextlib.redirect_stderr(buffer):
                code = cli.main(
                    ["segment", "--profile", profile_path, "--rows", rows_path,
                     "--key", "typo_key"]
                )
            self.assertEqual(2, code)
            self.assertIn("selected no rows", buffer.getvalue())


class TargetVisibilityTests(unittest.TestCase):
    """The emptied-utterance gate is the spine's only hard verdict.

    Anything that makes an empty target look non-empty silences it, so the two
    routes the review found are pinned here: a colour tag whose declared label
    happens to carry a glyph-bearing role, and the wider family of invisible
    characters.
    """

    def setUp(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.profile = config.load_profile(
            os.path.join(root, "profiles", "crimson_fixture.json")
        )

    def _parity(self, target):
        row = segment.Row(
            key="dialogue/mes08_FM_001",
            evidence="<color=lippi1>「いった。」<color=default>",
            pivot='"He went."',
            target=target,
            evidence_lang=self.profile.evidence_lang,
            pivot_lang=self.profile.pivot_lang,
        )
        return segment.quote_parity(row, self.profile)

    def test_colour_markup_only_target_is_emptied_even_for_a_term_role_label(self):
        finding = self._parity("<color=keyword1><color=default>")
        self.assertIsNotNone(finding, "a colour-only target renders nothing")
        self.assertEqual("hard", finding.severity)

    def test_substitution_placeholder_only_target_is_not_emptied(self):
        finding = self._parity("<player>")
        if finding is not None:
            self.assertEqual("report", finding.severity)

    def test_invisible_character_only_targets_are_emptied(self):
        for name, char in (
            ("zero width space", "\u200b"),
            ("zero width non-joiner", "\u200c"),
            ("zero width joiner", "\u200d"),
            ("word joiner", "\u2060"),
            ("bom", "\ufeff"),
            ("soft hyphen", "\u00ad"),
        ):
            with self.subTest(char=name):
                finding = self._parity(char * 3)
                self.assertIsNotNone(finding, "%s renders nothing" % name)
                self.assertEqual("hard", finding.severity)
