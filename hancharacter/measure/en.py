"""English pivot-side marker classification.

English has no sentence-final particle slot comparable to Japanese or Korean;
ending transforms are therefore deliberately not applicable here.
"""
import os as _os
import re as _re
from typing import Any as _Any

from hancharacter.config import MEASURABLE_AXIS_STATUSES as _MEASURABLE_AXIS_STATUSES

from . import pattern_match as _pattern_match, unit_surface as _unit_surface


VERSION = "1.0"
AXES = {
    "speech_level": "not_applicable",
    "pronouns": "not_applicable",
    "ending_transform": "not_applicable",
    "interjection_laugh": "not_applicable",
    "lexical_register": "lexical",
    "sentence_habit": "lexical",
    "dialect_policy": "not_applicable",
    "orthographic_distortion": "applicable",
    "punctuation_policy": "not_applicable",
    "utterance_frame": "not_applicable",
    "phoneme_substitution": "not_applicable",
}
GOLDEN = _os.path.join(_os.path.dirname(__file__), "golden", "en.json")


_EYE_DIALECT_RE = _re.compile(
    r"(?:\b[A-Za-z]+in'(?=\W|$)|\b(?:ain't|gonna|wanna|lemme|ya|wuz|sez|c'mon|ol')(?=\W|$))",
    _re.IGNORECASE,
)
_REGISTER_RE = _re.compile(
    r"(?:\bpal\b|\bmate\b|\bsir\b|\bmadam\b|\bbucko\b|\bchap\b|\bmy dear\b|\breckon\b|\bindeed\b|\bproper\b)",
    _re.IGNORECASE,
)
_HABIT_RE = _re.compile(
    r"(?:^\s*(?:well|listen|mark my words|i reckon)\b|\b(?:you hear|isn't it|right)\?\s*$)",
    _re.IGNORECASE,
)



def match(unit: _Any, axis: str, pattern_set: _Any) -> bool:
    """Classify load-bearing English lexical and orthographic markers."""

    if AXES.get(axis) not in _MEASURABLE_AXIS_STATUSES:
        return False
    surface = _unit_surface(unit, axis)
    configured = _pattern_match(surface, pattern_set)
    if configured is not None:
        return configured
    if axis == "orthographic_distortion":
        return bool(_EYE_DIALECT_RE.search(surface))
    if axis == "lexical_register":
        return bool(_REGISTER_RE.search(surface))
    if axis == "sentence_habit":
        return bool(_HABIT_RE.search(surface))
    return False
