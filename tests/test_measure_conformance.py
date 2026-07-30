import copy
import json
import unittest

from hancharacter.measure import (
    conformance,
    get_plugin,
    golden_digest,
    measurable_axes,
    display_line_anchored,
    pattern_match,
    unit_surface,
)
from hancharacter.segment import Unit


GOLDEN_LANGUAGES = ("ja", "en", "ko")


def golden_data(plugin):
    fixture = plugin.GOLDEN
    if isinstance(fixture, dict):
        return copy.deepcopy(fixture)
    with open(fixture, "r", encoding="utf-8") as handle:
        return json.load(handle)


class PluginSurfaceTests(unittest.TestCase):
    def test_unknown_language_raises(self):
        with self.assertRaises(LookupError):
            get_plugin("xx")

    def test_english_measurable_axes_are_honest(self):
        axes = measurable_axes("en")
        self.assertNotIn("ending_transform", axes)
        self.assertIn("orthographic_distortion", axes)

    def test_plugins_expose_only_the_declared_classifier_contract(self):
        """The plugin surface stays closed; only declared names may appear.

        `BASE_REGISTER` is optional and target-side. It is the ordinary
        sentence-final inventory of the target language, which the invention gate
        subtracts before deciding that a recurring form was fabricated. It lives on
        the adapter because it is a fact about a language rather than about any one
        character's contract: a copy inside the gate would be unreachable for a
        second target language, and ordinary casual speech in that language would
        then be eligible to be called an invention.

        It is data, not a callable, so it cannot become the competing segmenter this
        closed surface exists to prevent.
        """
        required = {"VERSION", "AXES", "match", "GOLDEN"}
        optional = {"BASE_REGISTER"}
        for lang in GOLDEN_LANGUAGES:
            with self.subTest(lang=lang):
                public = {
                    name for name in vars(get_plugin(lang)) if not name.startswith("_")
                }
                self.assertEqual(required, public & required)
                self.assertEqual(
                    set(),
                    public - required - optional,
                    "an undeclared public name could create a competing segmenter",
                )
                for name in sorted(public & optional):
                    self.assertFalse(
                        callable(getattr(get_plugin(lang), name)),
                        "%s must be data, not a callable" % name,
                    )

    def test_file_backed_golden_digest_matches_fixture_bytes(self):
        for lang in ("ja", "en"):
            with self.subTest(lang=lang):
                with open(get_plugin(lang).GOLDEN, "rb") as handle:
                    import hashlib

                    self.assertEqual(hashlib.sha256(handle.read()).hexdigest(), golden_digest(lang))

    def test_pattern_match_rejects_malformed_patterns(self):
        with self.assertRaisesRegex(ValueError, "invalid pattern"):
            pattern_match("marker", ["("])
        with self.assertRaises(TypeError):
            pattern_match("marker", 1)
        with self.assertRaises(TypeError):
            pattern_match("marker", ["marker", 1])
        with self.assertRaisesRegex(
            ValueError, r"patterns list: \{'pattern': \['marker'\]\}"
        ):
            pattern_match("marker", {"pattern": ["marker"]})

    def test_empty_pattern_set_matches_nothing(self):
        self.assertFalse(pattern_match("marker", []))
        self.assertFalse(pattern_match("marker", {"patterns": []}))

    def test_unit_surface_rejects_missing_or_invalid_surfaces(self):
        with self.assertRaisesRegex(TypeError, "base nor reading"):
            unit_surface(object(), "ending_transform")
        with self.assertRaisesRegex(TypeError, "base nor reading"):
            unit_surface({}, "ending_transform")
        with self.assertRaisesRegex(TypeError, "base surface"):
            unit_surface({"base": None}, "ending_transform")

    def test_unit_surface_uses_axis_appropriate_segment_unit_surface(self):
        unit = Unit("row", "speaker", "evidence", "base", "reading")
        self.assertEqual("reading", unit_surface(unit, "lexical_register"))
        self.assertEqual("base", unit_surface(unit, "ending_transform"))



class ConformanceTests(unittest.TestCase):
    def test_every_registered_plugin_has_a_non_vacuous_passing_fixture(self):
        for lang in GOLDEN_LANGUAGES:
            with self.subTest(lang=lang):
                fixture = golden_data(get_plugin(lang))
                self.assertGreaterEqual(len(fixture["units"]), 20)
                self.assertEqual([], conformance(lang))

    def test_sabotaged_fixture_produces_hard_findings(self):
        plugin = get_plugin("ja")
        original = plugin.GOLDEN
        try:
            fixture = golden_data(plugin)
            fixture["units"][0]["matches"]["ending_transform"] = False
            plugin.GOLDEN = fixture
            failures = conformance("ja")
        finally:
            plugin.GOLDEN = original
        self.assertTrue(failures)
        self.assertTrue(all(finding.severity == "hard" for finding in failures))
        self.assertTrue(any(finding.code == "golden_mismatch" for finding in failures))

    def test_axis_declaration_typos_hard_fail_before_fixture_measurement(self):
        plugin = get_plugin("ja")
        original = plugin.AXES
        cases = (
            ("extra axis", "plugin_axes", "unexpected_axis"),
            ("missing axis", "plugin_axes", "ending_transform"),
            ("misspelled axis", "plugin_axes", "ending_transfrom"),
            ("bad status", "plugin_axis_status", "aplicable"),
        )
        try:
            for name, code, detail in cases:
                with self.subTest(case=name):
                    axes = dict(original)
                    if name == "extra axis":
                        axes["unexpected_axis"] = "applicable"
                    elif name == "missing axis":
                        del axes["ending_transform"]
                    elif name == "misspelled axis":
                        del axes["ending_transform"]
                        axes["ending_transfrom"] = "applicable"
                    else:
                        axes["ending_transform"] = "aplicable"
                    plugin.AXES = axes
                    failures = conformance("ja")

                    # Declarations must fail before an unmeasured axis can read clean.
                    self.assertTrue(failures)
                    self.assertTrue(all(finding.severity == "hard" for finding in failures))
                    self.assertTrue(any(finding.code == code for finding in failures))
                    self.assertTrue(any(detail in finding.detail for finding in failures))
        finally:
            plugin.AXES = original

    def test_all_false_fixture_is_vacuous(self):
        plugin = get_plugin("ja")
        original = plugin.GOLDEN
        axes = measurable_axes("ja")
        try:
            plugin.GOLDEN = {
                "language": "ja",
                "units": [
                    {"text": "plain", "matches": {axis: False for axis in axes}}
                    for _ in range(20)
                ],
                "densities": {axis: 0.0 for axis in axes},
            }
            failures = conformance("ja")
        finally:
            plugin.GOLDEN = original
        self.assertTrue(failures)
        self.assertTrue(all(finding.severity == "hard" for finding in failures))
        vacuous = [
            finding
            for finding in failures
            if finding.code == "golden_fixture_vacuous"
        ]
        self.assertEqual(len(axes), len(vacuous))
        self.assertEqual(set(axes), {finding.axis for finding in vacuous})


class DisplayLineAnchorTests(unittest.TestCase):
    """Instance seven of the $-anchor-versus-structural-artifact class.

    A marker ending line one of a two-line cue was unmatchable because ``$``
    anchors at end of string.  That made the flattening gate unreachable for
    the most common subtitle shape while also mis-reading faithful work.
    """

    PATTERN = r"でござる[。！？!?…]*$"
    KO_PATTERN = r"이오[.!?…]*$"

    def _match(self, text, pattern=None):
        return pattern_match(text, [pattern or self.PATTERN])

    def test_marker_ending_line_one_of_a_two_line_cue_is_matched(self):
        self.assertTrue(self._match("これは主命でござる。\nそれゆえ従え。"))

    def test_marker_ending_the_final_line_is_still_matched(self):
        self.assertTrue(self._match("それゆえ従え。\nこれは主命でござる。"))

    def test_single_line_marker_is_unchanged(self):
        self.assertTrue(self._match("これは主命でござる。"))

    def test_unmarked_speech_does_not_match_on_any_line(self):
        self.assertFalse(self._match("これは主命である。\nそれゆえ従え。"))
        self.assertFalse(self._match("이것이 주인의 뜻이다.\n따르라.", self.KO_PATTERN))

    def test_a_marker_split_across_the_line_break_does_not_match(self):
        self.assertFalse(self._match("これは主命でござ\nる。"))

    def test_fused_lines_do_not_match_which_is_why_adapters_must_keep_breaks(self):
        self.assertFalse(self._match("これは主命でござるそれゆえ従え。"))

    def test_caret_anchored_utterance_frames_are_not_widened(self):
        frame = r"^我が名は"
        self.assertTrue(pattern_match("我が名は闇の者。", [frame]))
        self.assertFalse(pattern_match("そして\n我が名は闇の者。", [frame]))

    def test_an_escaped_dollar_is_left_anchored_as_written(self):
        self.assertEqual(display_line_anchored(r"cost\$"), r"cost\$")
        self.assertEqual(display_line_anchored(r"end$"), r"end(?=\n|\Z)")

    def test_rewrite_is_confined_to_a_trailing_anchor(self):
        self.assertEqual(display_line_anchored(r"a$b"), r"a$b")

    def test_golden_fixtures_stay_single_line_so_the_digest_is_unaffected(self):
        for lang in GOLDEN_LANGUAGES:
            blob = json.dumps(golden_data(get_plugin(lang)), ensure_ascii=False)
            self.assertNotIn("\\n", blob)
