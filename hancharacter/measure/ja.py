"""Japanese source-side marker classification."""
import os as _os
import re as _re
from typing import Any as _Any

from hancharacter.config import MEASURABLE_AXIS_STATUSES as _MEASURABLE_AXIS_STATUSES

from . import pattern_match as _pattern_match, unit_surface as _unit_surface


VERSION = "1.0"
AXES = {
    "speech_level": "applicable",
    "pronouns": "lexical",
    "ending_transform": "applicable",
    "interjection_laugh": "applicable",
    "lexical_register": "lexical",
    "sentence_habit": "not_applicable",
    "dialect_policy": "not_applicable",
    "orthographic_distortion": "not_applicable",
    "punctuation_policy": "not_applicable",
    "utterance_frame": "not_applicable",
    "phoneme_substitution": "not_applicable",
}
GOLDEN = _os.path.join(_os.path.dirname(__file__), "golden", "ja.json")


_ENDING_RE = _re.compile(
    r"(?:のだ|んだ|なのだ|です|ます|じゃ|っす|ござる|にゃ|だ)(?:[。！？!?…]*)$"
)
_SPEECH_LEVEL_RE = _re.compile(
    r"(?:でございます|ございます|です|ます|じゃ|っす|ござる|にゃ|だ)(?:[。！？!?…]*)$"
)
_PRONOUN_RE = _re.compile(r"(?:私|わたし|僕|ぼく|俺|おれ|わし|あたし|うち|拙者|おぬし)")
_LAUGH_RE = _re.compile(r"(?:あはは|ははは|ふふふ|えへへ|へへ|くくく|ククク|ｗ{2,}|笑)")
_REGISTER_RE = _re.compile(r"(?:拙者|おぬし|貴様|恐れ入ります|承知|候|ござる|である)")



def match(unit: _Any, axis: str, pattern_set: _Any) -> bool:
    """Classify Japanese morphology without constructing segmentation units."""

    if AXES.get(axis) not in _MEASURABLE_AXIS_STATUSES:
        return False
    surface = _unit_surface(unit, axis)
    configured = _pattern_match(surface, pattern_set)
    if configured is not None:
        return configured
    if axis == "ending_transform":
        return bool(_ENDING_RE.search(surface))
    if axis == "speech_level":
        return bool(_SPEECH_LEVEL_RE.search(surface))
    if axis == "pronouns":
        return bool(_PRONOUN_RE.search(surface))
    if axis == "interjection_laugh":
        return bool(_LAUGH_RE.search(surface))
    if axis == "lexical_register":
        return bool(_REGISTER_RE.search(surface))
    return False
