"""Language-specific marker measurement.

Segmentation belongs exclusively to :mod:`hancharacter.segment`.  Plugins only
classify the canonical units it supplies; they must never construct a competing
set of units because every density comparison depends on a shared denominator.
"""
import hashlib
import importlib
import json
import re
from typing import Any, Dict, List, Optional, Protocol

from hancharacter import config, findings, schemas


class MeasurePlugin(Protocol):
    """A language classifier over canonical segmenter units.

    ``AXES`` maps every name in ``schemas.AXES`` to a status from
    ``config.AXIS_STATUSES``.  ``GOLDEN`` supplies the non-vacuous fixture that
    conformance recomputes before the plugin can be trusted.
    """

    VERSION: str
    AXES: Dict[str, str]
    GOLDEN: Any

    def match(self, unit: Any, axis: str, pattern_set: Any) -> bool:
        """Return whether *unit* has the requested marker."""


_MODULES = {
    "ja": "hancharacter.measure.ja",
    "en": "hancharacter.measure.en",
    "ko": "hancharacter.measure.ko",
}


def get_plugin(lang: str) -> MeasurePlugin:
    """Return the declared plugin for an exact language code."""

    if not isinstance(lang, str):
        raise LookupError("undeclared measurement language %r" % (lang,))
    module_name = _MODULES.get(lang.lower())
    if module_name is None:
        raise LookupError("undeclared measurement language %r" % (lang,))
    return importlib.import_module(module_name)  # type: ignore[return-value]


def languages() -> List[str]:
    """Declared measurement languages, in stable order.

    Public so callers never reach into the private registry: whether a language
    has a plugin at all is part of the seal (a declared source language with no
    plugin is a hard failure at contract seal), so it needs a supported accessor.
    """
    return sorted(_MODULES)

def measurable_axes(lang: str) -> List[str]:
    """Return only axes the language can actually measure."""

    plugin = get_plugin(lang)
    return [
        axis
        for axis, status in plugin.AXES.items()
        if status in config.MEASURABLE_AXIS_STATUSES
    ]


def unit_surface(unit: Any, axis: str) -> str:
    """Select a canonical surface without creating or splitting units.

    Lexical axes use ruby-aware ``reading`` when it is available.  Morphology
    and punctuation use the canonical base surface.  Plain strings and mapping
    inputs make golden fixtures and small callers convenient without changing
    the segmenter contract.
    """

    lexical = axis in {
        "pronouns",
        "lexical_register",
        "sentence_habit",
        "dialect_policy",
    }
    preferred = "reading" if lexical else "base"
    fallback = "base" if lexical else "reading"
    if isinstance(unit, str):
        return unit
    missing = object()
    if isinstance(unit, dict):
        value = unit.get(preferred, missing)
        if value is missing:
            value = unit.get(fallback, missing)
    else:
        value = getattr(unit, preferred, missing)
        if value is missing:
            value = getattr(unit, fallback, missing)
    if value is missing:
        raise TypeError("unit has neither base nor reading surface")
    if not isinstance(value, str):
        raise TypeError("unit %s surface must be a string" % preferred)
    return value


_TRAILING_DOLLAR = re.compile(r"(?<!\\)((?:\\\\)*)\$\Z")


def display_line_anchored(pattern: str) -> str:
    """Rewrite a trailing ``$`` to mean "end of a display line or end of text".

    A sentence-final marker is the dominant realisation shape in this
    catalogue: 51 of the 55 anchored shipped patterns end in ``$``.  Python
    anchors a bare ``$`` at the end of the whole string, so in a two-line
    subtitle cue or a wrapped text box a marker that ends *line one* was
    unmatchable::

        これは主命でござる。\\nそれゆえ従え。   ->  'でござる$' did not match

    A display line break is a layout artifact, not an utterance boundary, so
    refusing to see the marker there made the flattening gate unreachable for
    the most common subtitle shape while also flagging faithful work.

    ``re.MULTILINE`` is deliberately **not** used.  It would also loosen ``^``,
    and the four shipped ``^`` patterns are utterance frames (``^我が名は``)
    whose anchoring to the start of the utterance is intended and has no
    demonstrated defect.  Widening them would be an unjustified bound change,
    so only a trailing ``$`` is rewritten.

    The even-backslash guard keeps a literal ``\\$`` (an escaped dollar sign)
    anchored as written.

    Known limitation: a marker immediately followed by a line break *inside* a
    continuing sentence now matches, e.g. ``「ござる\\n」と書いた。``.  This is a
    pathological wrap and is recorded rather than papered over.
    """

    # A lambda replacement keeps the emitted text literal; a string template
    # would interpret the "\n" and reject the "\Z" as a bad escape.
    return _TRAILING_DOLLAR.sub(lambda m: m.group(1) + r"(?=\n|\Z)", pattern)


def pattern_match(surface: str, pattern_set: Any) -> Optional[bool]:
    """Apply an optional caller-supplied pattern set.

    ``None`` delegates to the language plugin's built-in morphology.  An empty
    set deliberately matches nothing, which keeps a declared but empty marker
    set observable rather than silently falling back to broad heuristics.
    """

    if pattern_set is None:
        return None
    if isinstance(pattern_set, dict):
        if "patterns" not in pattern_set or not isinstance(pattern_set["patterns"], list):
            raise ValueError(
                "pattern_set object requires a patterns list: %r" % (pattern_set,)
            )
        pattern_set = pattern_set["patterns"]
    if isinstance(pattern_set, str):
        patterns = (pattern_set,)
    else:
        try:
            patterns = tuple(pattern_set)
        except TypeError as error:
            raise TypeError("pattern_set must be a string or iterable of strings") from error
    compiled = []
    for pattern in patterns:
        if not isinstance(pattern, str):
            raise TypeError("pattern_set contains non-string pattern %r" % (pattern,))
        try:
            compiled.append(re.compile(display_line_anchored(pattern), re.IGNORECASE))
        except re.error as error:
            raise ValueError("invalid pattern %r: %s" % (pattern, error)) from error
    return any(pattern.search(surface) for pattern in compiled)


def _fixture_data(plugin: MeasurePlugin) -> Dict[str, Any]:
    fixture = getattr(plugin, "GOLDEN", None)
    if isinstance(fixture, dict):
        return fixture
    if not isinstance(fixture, str):
        raise LookupError("plugin has no golden fixture")
    with open(fixture, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _fixture_bytes(plugin: MeasurePlugin) -> bytes:
    fixture = getattr(plugin, "GOLDEN", None)
    if isinstance(fixture, dict):
        return json.dumps(
            fixture, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    if not isinstance(fixture, str):
        raise LookupError("plugin has no golden fixture")
    with open(fixture, "rb") as handle:
        return handle.read()


def _hard(code: str, detail: str, **values: Any) -> Any:
    language = values.pop("language", None)
    if language is not None and "scope" not in values:
        values["scope"] = language
    return findings.hard(code, detail, **values)


def _plugin_contract_failures(lang: str, plugin: MeasurePlugin) -> List[Any]:
    """Return hard findings for declarations that could hide an unmeasured axis."""
    axes = getattr(plugin, "AXES", None)
    if not isinstance(axes, dict):
        return [
            _hard(
                "plugin_axes",
                "plugin AXES must be a dictionary covering canonical axes",
                language=lang,
            )
        ]

    declared = set(axes)
    missing = sorted(schemas.AXES - declared)
    unexpected = sorted(declared - schemas.AXES, key=repr)
    failures: List[Any] = []
    if missing or unexpected:
        detail = "plugin AXES differs from canonical axes"
        if missing:
            detail += "; missing: %s" % ", ".join(missing)
        if unexpected:
            detail += "; unexpected: %s" % ", ".join(repr(axis) for axis in unexpected)
        failures.append(_hard("plugin_axes", detail, language=lang))

    invalid_statuses = [
        (axis, status)
        for axis, status in axes.items()
        if status not in config.AXIS_STATUSES
    ]
    if invalid_statuses:
        details = ", ".join(
            "%s=%r" % (axis, status)
            for axis, status in sorted(invalid_statuses, key=lambda item: repr(item[0]))
        )
        failures.append(
            _hard(
                "plugin_axis_status",
                "plugin AXES has statuses outside AXIS_STATUSES: %s" % details,
                language=lang,
            )
        )
    return failures


def conformance(lang: str) -> List[Any]:
    """Run a plugin's non-vacuous golden fixture and return hard mismatches."""

    plugin = get_plugin(lang)
    contract_failures = _plugin_contract_failures(lang, plugin)
    if contract_failures:
        return contract_failures
    try:
        fixture = _fixture_data(plugin)
    except (LookupError, OSError, ValueError, json.JSONDecodeError) as error:
        return [_hard("golden_fixture", str(error), language=lang)]

    axes = measurable_axes(lang)
    units = fixture.get("units") if isinstance(fixture, dict) else None
    expected_densities = fixture.get("densities") if isinstance(fixture, dict) else None
    failures: List[Any] = []
    if not axes:
        failures.append(
            _hard(
                "empty_measurable_axes",
                "plugin declares no measurable axes",
                language=lang,
            )
        )
    if not isinstance(units, list):
        return failures + [
            _hard("golden_fixture", "golden fixture has no units list", language=lang)
        ]
    if len(units) < 20:
        failures.append(
            _hard(
                "golden_fixture_too_small",
                "golden fixture has %d units; at least 20 are required" % len(units),
                language=lang,
            )
        )
    if not isinstance(expected_densities, dict):
        failures.append(
            _hard(
                "golden_fixture",
                "golden fixture has no densities object",
                language=lang,
            )
        )
        expected_densities = {}

    counts = {axis: 0 for axis in axes}
    expected_matches = {axis: 0 for axis in axes}
    for index, row in enumerate(units):
        if not isinstance(row, dict):
            failures.append(
                _hard(
                    "golden_fixture",
                    "unit %d is not an object" % index,
                    language=lang,
                )
            )
            continue
        expected = row.get("matches")
        text = row.get("text")
        if not isinstance(text, str) or not isinstance(expected, dict):
            failures.append(
                _hard(
                    "golden_fixture",
                    "unit %d requires text and matches" % index,
                    language=lang,
                )
            )
            continue
        for axis in axes:
            if axis not in expected or not isinstance(expected[axis], bool):
                failures.append(
                    _hard(
                        "golden_fixture",
                        "unit %d has no boolean expectation for %s" % (index, axis),
                        language=lang,
                        axis=axis,
                    )
                )
                continue
            if expected[axis]:
                expected_matches[axis] += 1
            actual = bool(plugin.match(text, axis, row.get("pattern_set")))
            if actual:
                counts[axis] += 1
            if actual != expected[axis]:
                failures.append(
                    _hard(
                        "golden_mismatch",
                        "unit %d axis %s expected %s, got %s"
                        % (index, axis, expected[axis], actual),
                        language=lang,
                        axis=axis,
                    )
                )

    for axis in axes:
        expected_density = expected_densities.get(axis)
        if not (
            expected_matches[axis] > 0
            and counts[axis] > 0
            and isinstance(expected_density, (int, float))
            and not isinstance(expected_density, bool)
            and expected_density > 0
        ):
            failures.append(
                _hard(
                    "golden_fixture_vacuous",
                    "axis %s requires a true expectation, observed match, and positive density"
                    % axis,
                    language=lang,
                    axis=axis,
                )
            )

    denominator = len(units)
    if denominator:
        for axis in axes:
            expected_density = expected_densities.get(axis)
            if not isinstance(expected_density, (int, float)) or isinstance(
                expected_density, bool
            ):
                failures.append(
                    _hard(
                        "golden_fixture",
                        "axis %s has no numeric expected density" % axis,
                        language=lang,
                        axis=axis,
                    )
                )
                continue
            actual_density = counts[axis] / denominator
            if abs(actual_density - float(expected_density)) > 1e-12:
                failures.append(
                    _hard(
                        "golden_density_mismatch",
                        "axis %s expected density %.12g, got %.12g"
                        % (axis, expected_density, actual_density),
                        language=lang,
                        axis=axis,
                    )
                )
    return failures


def golden_digest(lang: str) -> str:
    """Return the SHA-256 digest of the golden fixture's exact bytes."""

    return hashlib.sha256(_fixture_bytes(get_plugin(lang))).hexdigest()
