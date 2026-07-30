import unittest

from hancharacter.measure import pattern_match
from hancharacter.tag_grammar import grammar_for, strip_tags


class AssLayoutSubstitutionTests(unittest.TestCase):
    """ASS layout syntax is not markup and must not be deleted.

    Deleting "\\N" welded two display lines into one token, which both
    destroyed a marker anchored to the end of line one and fabricated a word
    ("명이오" + "그러니" -> "명이오그러니") that nobody wrote.
    """

    def _surface(self, text):
        return strip_tags(text, grammar_for("ass"))

    def test_hard_break_becomes_a_real_line_break(self):
        self.assertEqual(
            self._surface(r"これは主命でござる。\Nそれゆえ従え。"),
            "これは主命でござる。\nそれゆえ従え。",
        )

    def test_soft_break_becomes_a_real_line_break(self):
        self.assertEqual(self._surface(r"あい\nうえ"), "あい\nうえ")

    def test_hard_space_does_not_fuse_words(self):
        self.assertEqual(self._surface(r"강조\h여기"), "강조\u00a0여기")

    def test_override_blocks_are_still_stripped_as_markup(self):
        self.assertEqual(self._surface(r"{\i1}強調{\i0}あり"), "強調あり")

    def test_a_single_line_cue_is_unchanged(self):
        self.assertEqual(self._surface("これは主命でござる。"), "これは主命でござる。")

    def test_a_marker_ending_line_one_survives_the_adapter(self):
        surface = self._surface(r"これは主命でござる。\Nそれゆえ従え。")
        self.assertTrue(pattern_match(surface, [r"でござる[。！？!?…]*$"]))

    def test_no_layout_grammar_is_unaffected(self):
        self.assertEqual(strip_tags(r"a\Nb", grammar_for("plain_text")), r"a\Nb")
