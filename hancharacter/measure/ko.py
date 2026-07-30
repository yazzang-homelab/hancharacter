"""Korean target-side marker classification."""
import re as _re
from typing import Any as _Any

from hancharacter.config import MEASURABLE_AXIS_STATUSES as _MEASURABLE_AXIS_STATUSES

from . import pattern_match as _pattern_match, unit_surface as _unit_surface


VERSION = "1.0"
AXES = {
    "speech_level": "not_applicable",
    "pronouns": "not_applicable",
    "ending_transform": "applicable",
    "interjection_laugh": "not_applicable",
    "lexical_register": "not_applicable",
    "sentence_habit": "not_applicable",
    "dialect_policy": "not_applicable",
    "orthographic_distortion": "not_applicable",
    "punctuation_policy": "applicable",
    "utterance_frame": "applicable",
    "phoneme_substitution": "applicable",
}

GOLDEN = {
    "language": "ko",
    "units": [
        {"text": "나는 여기 있다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": True, "phoneme_substitution": False}},
        {"text": "이제 가겠다냥.", "matches": {"ending_transform": True, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "정말 기쁘다!!", "matches": {"ending_transform": False, "punctuation_policy": True, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "그 말은 긔묘하다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": True}},
        {"text": "저는 약속을 지킨다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": True, "phoneme_substitution": False}},
        {"text": "오늘은 맑다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "소인은 길을 안다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": True, "phoneme_substitution": False}},
        {"text": "그렇슴다.", "matches": {"ending_transform": True, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "왜 이래??", "matches": {"ending_transform": False, "punctuation_policy": True, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "쥬스는 차갑다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": True}},
        {"text": "본인은 기록한다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": True, "phoneme_substitution": False}},
        {"text": "그만하거든.", "matches": {"ending_transform": True, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "정말이다...", "matches": {"ending_transform": False, "punctuation_policy": True, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "평범한 문장이다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "이 몸은 물러난다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": True, "phoneme_substitution": False}},
        {"text": "그렇긔.", "matches": {"ending_transform": True, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": True}},
        {"text": "알겠냥!", "matches": {"ending_transform": True, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "조용하다.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "그만이지요.", "matches": {"ending_transform": False, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": False}},
        {"text": "말하쥬.", "matches": {"ending_transform": True, "punctuation_policy": False, "utterance_frame": False, "phoneme_substitution": True}}
    ],
    "densities": {
        "ending_transform": 0.3,
        "punctuation_policy": 0.15,
        "utterance_frame": 0.25,
        "phoneme_substitution": 0.2
    }
}


# The ordinary Korean sentence-final inventory: polite, formal and casual/banmal.
# Owned here because it is a property of the TARGET LANGUAGE, not of any one
# character's contract. The invention gate subtracts it before deciding that a
# recurring form was fabricated, so without it ordinary casual Korean appearing
# three times in a scene is reported as an invented marker -- a gate firing on
# faithful translation.
#
# An earlier pass deleted a `BASE_REGISTER` constant here as dead code, correctly:
# nothing read it. It returns now because the invention gate does read it, and a
# whitelist living in the gate would put a target-language fact inside per-work
# enforcement where a second target language could not reach it.
BASE_REGISTER = (
    r"(?:요|죠|군요|네요|습니다|ㅂ니다|니다|습니까|ㅂ니까|세요|십시오|시죠|지요"
    r"|아요|어요|여요|다|라|자|게|고|네|군|지|까|야|아|어|해|했어|했지|거든|구나"
    r"|잖아|지마)[.。!?！？…]*$",
)


_ENDING_RE = _re.compile(
    r"(?:거든요|나이다|슴다|지롱|라구|구먼|구려|거든|냥|당|긔|슴|쥬|죵|노|하오|소|게)(?:[.。！？!?…]*)$"
)
_PHONEME_RE = _re.compile(r"(?:긔|쥬|죵|댜|랴|쟈|뎌|뎨|뫄)")
_PUNCTUATION_RE = _re.compile(r"(?:[!?]{2,}|…{2,}|\.{3,}|~)")
_FRAME_RE = _re.compile(
    r"^\s*(?:나는|내가|저는|제가|소인은|본인은|이 몸은|우리는|우리가)"
)



def match(unit: _Any, axis: str, pattern_set: _Any) -> bool:
    """Classify Korean target-side marker surfaces, not quote segmentation."""

    if AXES.get(axis) not in _MEASURABLE_AXIS_STATUSES:
        return False
    surface = _unit_surface(unit, axis)
    configured = _pattern_match(surface, pattern_set)
    if configured is not None:
        return configured
    if axis == "ending_transform":
        return bool(_ENDING_RE.search(surface))
    if axis == "phoneme_substitution":
        return bool(_PHONEME_RE.search(surface))
    if axis == "punctuation_policy":
        return bool(_PUNCTUATION_RE.search(surface))
    if axis == "utterance_frame":
        return bool(_FRAME_RE.search(surface))
    return False
