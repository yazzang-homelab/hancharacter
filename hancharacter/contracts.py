"""Per-character voice contracts and their seal-time prerequisites.

This module deliberately keeps evidence-producing joins outside itself.  The caller
supplies graduation stages, coverage, glyph availability, precedent results and
dialect results because those are reports over distinct artifacts.  Recomputing any
one of them here would make a seal depend on a hidden, potentially different view
of the evidence.
"""
import copy
import hashlib
import json
import math
import re
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from . import config, findings, schemas, typology


_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SCOPE_KEY_RE = re.compile(
    r"mode=(?P<mode>[^|=]+)\|state=(?P<state>[^|=]+)\|"
    r"form=(?P<form>[^|=]+)\|arc=(?P<arc>[^|=]+)"
)
_SEAL_ALGORITHM = "sha256"


class ContractError(ValueError):
    """A contract input is structurally incomplete or unsafe to seal."""


def _copy_json(value: Any) -> Any:
    """Copy a JSON-shaped value without retaining caller-owned containers."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ContractError("contract value must be JSON-serialisable: %s" % exc)


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and bool(_SHA256_RE.fullmatch(value))


def _pattern_list_errors(label: str, value: Any) -> List[str]:
    errors = []
    if not isinstance(value, list) or not value:
        return ["%s: expected a non-empty regex list" % label]
    for index, pattern in enumerate(value):
        if not isinstance(pattern, str) or not pattern:
            errors.append("%s[%d]: expected a non-empty regex" % (label, index))
            continue
        try:
            re.compile(pattern)
        except re.error as exc:
            errors.append("%s[%d]: invalid regex: %s" % (label, index, exc))
    return errors


def _band_errors(label: str, value: Any) -> List[str]:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(_is_number(item) for item in value)
    ):
        return ["%s: expected a two-element numeric density band" % label]
    if not 0.0 <= float(value[0]) <= float(value[1]) <= 1.0:
        return ["%s: expected 0 <= lo <= hi <= 1" % label]
    return []



def _scope_override_errors(value: Any, axis_names: Sequence[str]) -> List[str]:
    """Validate reusable state keys, never opaque scene labels.

    An override key has exactly this durable shape::

        mode=<mode>|state=<state>|form=<form>|arc=<arc>

    It is intentionally not a scene id.  A scene number describes placement, not a
    character condition, and silently becomes wrong after a scene renumbering.
    """
    errors = []
    if not isinstance(value, dict):
        return ["contract.scope_overrides: expected an object"]
    for key, override in value.items():
        if not isinstance(key, str) or not _SCOPE_KEY_RE.fullmatch(key):
            errors.append(
                "contract.scope_overrides key %r must be "
                "mode=<mode>|state=<state>|form=<form>|arc=<arc>, not a scene id"
                % (key,)
            )
        if not isinstance(override, dict) or set(override) != {"bands"}:
            errors.append(
                "contract.scope_overrides[%r]: expected exactly {'bands'}" % (key,)
            )
            continue
        bands = override["bands"]
        if not isinstance(bands, dict) or not bands:
            errors.append(
                "contract.scope_overrides[%r].bands: expected a non-empty object" % key
            )
            continue
        for axis, band in bands.items():
            if not isinstance(axis, str) or axis not in axis_names:
                errors.append(
                    "contract.scope_overrides[%r].bands: undeclared axis %r" % (key, axis)
                )
            errors.extend(
                _band_errors(
                    "contract.scope_overrides[%r].bands[%r]" % (key, axis), band
                )
            )
    return errors
def _enforcement_input_errors(
    contract: Mapping[str, Any], axis_names: Sequence[str]
) -> List[str]:
    """Validate sealed gate inputs whose caller overrides would be unsafe."""
    errors = []
    marker_sets = contract.get("marker_sets")
    if not isinstance(marker_sets, dict) or set(marker_sets) != set(axis_names):
        errors.append("contract.marker_sets: expected one non-empty regex list per resolved axis")
    elif any(
        _pattern_list_errors("contract.marker_sets[%r]" % axis, patterns)
        for axis, patterns in marker_sets.items()
    ):
        for axis, patterns in marker_sets.items():
            errors.extend(_pattern_list_errors("contract.marker_sets[%r]" % axis, patterns))

    catalogue_markers = contract.get("catalogue_markers")
    if not isinstance(catalogue_markers, dict) or not catalogue_markers:
        errors.append("contract.catalogue_markers: expected a non-empty marker map")
    else:
        for marker, patterns in catalogue_markers.items():
            if not isinstance(marker, str) or not marker:
                errors.append("contract.catalogue_markers: marker ids must be non-empty strings")
            errors.extend(
                _pattern_list_errors("contract.catalogue_markers[%r]" % marker, patterns)
            )

    review_decisions = contract.get("review_decisions")
    if not isinstance(review_decisions, dict):
        errors.append("contract.review_decisions: expected a decision map")
    else:
        for key, decision in review_decisions.items():
            if not isinstance(key, str) or not key or not isinstance(decision, str) or not decision.strip():
                errors.append(
                    "contract.review_decisions: keys and decisions must be non-empty strings"
                )
    return errors




def validate_contract(contract: Any) -> List[str]:
    """Validate the local closed contract shape until the shared schema owns it.

    The shared ``schemas.contract`` shape is intentionally not used here yet: P2
    extends it, and accepting the old minimal shape would reject every meaningful
    contract or tempt callers to omit enforcement state.  The leader can replace
    this helper with the same closed rules in ``schemas`` without changing callers.
    """
    if not isinstance(contract, dict):
        return ["contract: expected object"]

    required = (
        "work",
        "speaker",
        "declared_speakers",
        "type_ids",
        "source_lang",
        "target_lang",
        "axes",
        "attribution",
        "required_markers",
        "forbidden_markers",
        "measured_source_density",
        "bands",
        "scope_overrides",
        "exclusivity",
        "edition_medium",
        "voice_enforcement_mode",
        "authority",
        "coverage_floor",

        "catalogue_version",
        "required_glyphs",
        "marker_sets",
        "catalogue_markers",
        "review_decisions",
    )
    optional = ("plugin_version", "golden_digest", "measurable_axes", "seal")

    errors = []
    for key in required:
        if key not in contract:
            errors.append("contract: missing required key %r" % key)
    for key in contract:
        if key not in required + optional:
            errors.append("contract: unknown key %r" % key)

    for key in ("work", "speaker", "source_lang", "target_lang", "edition_medium", "catalogue_version"):
        if key in contract and (not isinstance(contract[key], str) or not contract[key]):
            errors.append("contract.%s: expected a non-empty string" % key)
    if (
        "voice_enforcement_mode" in contract
        and contract["voice_enforcement_mode"] not in config.ENFORCEMENT_MODES
    ):
        errors.append(
            "contract.voice_enforcement_mode: expected one of %s"
            % list(config.ENFORCEMENT_MODES)
        )
    # No default. A contract that declares no authority is refused rather than
    # silently treated as the weaker route, because a guard that defaults to off is
    # not a guard.
    if contract.get("authority") not in config.CONTRACT_AUTHORITIES:
        errors.append(
            "contract.authority: expected one of %s"
            % list(config.CONTRACT_AUTHORITIES)
        )
    coverage_floor = contract.get("coverage_floor")
    if (
        not _is_number(coverage_floor)
        or not 0.0 <= float(coverage_floor) <= 1.0
    ):
        errors.append("contract.coverage_floor: expected a number from 0 through 1")


    speakers = contract.get("declared_speakers")
    if not isinstance(speakers, list) or not speakers or any(
        not isinstance(speaker, str) or not speaker for speaker in speakers
    ):
        errors.append("contract.declared_speakers: expected a non-empty speaker list")
    elif len(set(speakers)) != len(speakers):
        errors.append("contract.declared_speakers: duplicate speaker")
    elif contract.get("speaker") not in speakers:
        errors.append("contract.speaker: must appear in declared_speakers")

    type_ids = contract.get("type_ids")
    if not isinstance(type_ids, list) or not type_ids or any(
        not isinstance(type_id, str) or not type_id for type_id in type_ids
    ):
        errors.append("contract.type_ids: expected a non-empty type-id list")
    elif len(set(type_ids)) != len(type_ids):
        errors.append("contract.type_ids: duplicate type id")

    axes = contract.get("axes")
    if not isinstance(axes, list) or not axes:
        errors.append("contract.axes: expected a non-empty resolved-axis list")
    else:
        if isinstance(type_ids, list) and len(axes) != len(type_ids):
            errors.append("contract.axes: must have one entry per type_id")
        for index, axis in enumerate(axes):
            label = "contract.axes[%d]" % index
            if not isinstance(axis, dict) or set(axis) != {
                "axis", "marker", "pattern_set", "corpus_digest"
            }:
                errors.append(
                    "%s: expected exactly axis, marker, pattern_set, corpus_digest" % label
                )
                continue
            if axis["axis"] not in schemas.AXES:
                errors.append("%s.axis: undeclared axis" % label)
            if not isinstance(axis["marker"], str) or not axis["marker"]:
                errors.append("%s.marker: expected a non-empty string" % label)
            errors.extend(_pattern_list_errors("%s.pattern_set" % label, axis["pattern_set"]))
            if not _sha256(axis["corpus_digest"]):
                errors.append("%s.corpus_digest: expected a SHA-256 digest" % label)

    attribution = contract.get("attribution")
    if not isinstance(attribution, dict) or set(attribution) != {
        "evidence_tier", "target_tier", "status"
    }:
        errors.append(
            "contract.attribution: expected exactly evidence_tier, target_tier, status"
        )
    elif any(not isinstance(value, str) or not value for value in attribution.values()):
        errors.append("contract.attribution: all values must be non-empty strings")

    errors.extend(_pattern_list_errors("contract.required_markers", contract.get("required_markers")))
    errors.extend(_pattern_list_errors("contract.forbidden_markers", contract.get("forbidden_markers")))

    axis_names = set()
    if isinstance(axes, list):
        axis_names = {
            axis.get("axis") for axis in axes if isinstance(axis, dict) and isinstance(axis.get("axis"), str)
        }
    measured = contract.get("measured_source_density")
    if not isinstance(measured, dict) or set(measured) != axis_names:
        errors.append(
            "contract.measured_source_density: expected one finite density per resolved axis"
        )
    elif any(
        not _is_number(value) or not 0.0 <= float(value) <= 1.0
        for value in measured.values()
    ):
        errors.append("contract.measured_source_density: expected densities from 0 through 1")

    bands = contract.get("bands")
    if not isinstance(bands, dict) or not bands:
        errors.append("contract.bands: expected a non-empty scope object")
    else:
        for scope, per_axis in bands.items():
            if not isinstance(scope, str) or not scope:
                errors.append("contract.bands: invalid scope key")
            if not isinstance(per_axis, dict) or set(per_axis) != axis_names:
                errors.append(
                    "contract.bands[%r]: expected one band per resolved axis" % scope
                )
                continue
            for axis, band in per_axis.items():
                errors.extend(_band_errors("contract.bands[%r][%r]" % (scope, axis), band))

    errors.extend(_scope_override_errors(contract.get("scope_overrides"), sorted(axis_names)))
    exclusivity = contract.get("exclusivity")
    if not isinstance(exclusivity, dict) or set(exclusivity) != {"exclusive_with"}:
        errors.append("contract.exclusivity: expected exactly exclusive_with")
    elif not isinstance(exclusivity["exclusive_with"], list) or any(
        not isinstance(speaker, str) or not speaker
        for speaker in exclusivity["exclusive_with"]
    ):
        errors.append("contract.exclusivity.exclusive_with: expected a speaker list")
    elif len(set(exclusivity["exclusive_with"])) != len(exclusivity["exclusive_with"]):
        errors.append("contract.exclusivity.exclusive_with: duplicate speaker")

    errors.extend(_enforcement_input_errors(contract, sorted(axis_names)))

    glyphs = contract.get("required_glyphs")
    if not isinstance(glyphs, list) or any(
        not isinstance(glyph, str) or not glyph for glyph in glyphs
    ):
        errors.append("contract.required_glyphs: expected a glyph list")
    elif len(set(glyphs)) != len(glyphs):
        errors.append("contract.required_glyphs: duplicate glyph")

    if "plugin_version" in contract and (
        not isinstance(contract["plugin_version"], str) or not contract["plugin_version"]
    ):
        errors.append("contract.plugin_version: expected a non-empty string")
    if "golden_digest" in contract and not _sha256(contract["golden_digest"]):
        errors.append("contract.golden_digest: expected a SHA-256 digest")
    dynamic_keys = ("plugin_version", "golden_digest", "measurable_axes", "seal")
    if any(key in contract for key in dynamic_keys) and "measurable_axes" not in contract:
        errors.append("contract.measurable_axes: sealed contract must pin plugin axes")
    if "measurable_axes" in contract:
        measurable_axes = contract["measurable_axes"]
        if (
            not isinstance(measurable_axes, list)
            or not measurable_axes
            or any(not isinstance(axis, str) or not axis for axis in measurable_axes)
            or len(set(measurable_axes)) != len(measurable_axes)
        ):
            errors.append("contract.measurable_axes: expected a unique non-empty axis list")
        elif not axis_names.issubset(set(measurable_axes)):
            errors.append("contract.measurable_axes: must include every resolved axis")

    if "seal" in contract:
        seal = contract["seal"]
        if not isinstance(seal, dict) or set(seal) != {"algorithm", "hash"}:
            errors.append("contract.seal: expected exactly algorithm and hash")
        elif seal["algorithm"] != _SEAL_ALGORITHM or not _sha256(seal["hash"]):
            errors.append("contract.seal: invalid algorithm or hash")
    return errors


def build(
    work: str,
    speaker: str,
    type_ids: Sequence[str],
    source_lang: str,
    target_lang: str,
    *,
    attribution: Mapping[str, str],
    required_markers: Sequence[str],
    forbidden_markers: Sequence[str],
    measured_source_density: Mapping[str, float],
    bands: Mapping[str, Mapping[str, Sequence[float]]],
    scope_overrides: Mapping[str, Mapping[str, Any]],
    exclusivity: Mapping[str, Any],
    edition_medium: str,
    voice_enforcement_mode: str,
    authority: str,
    coverage_floor: float = config.COVERAGE_FLOOR_X,

    declared_speakers: Sequence[str],
    corpus_digests: Mapping[str, str],
    marker_sets: Mapping[str, Sequence[str]],
    catalogue_markers: Mapping[str, Sequence[str]],
    review_decisions: Mapping[str, str],
    required_glyphs: Sequence[str],
    axis_status: Callable[[str], Dict[str, str]],
    measurable: Sequence[str],
    root: Optional[str] = None,
) -> Dict[str, Any]:
    """Build an unsealed, self-contained contract from catalogue resolution.

    ``axis_status`` and ``measurable`` are deliberately required forwards to
    :func:`typology.resolve_axis_set`; omitting them used to turn the measurement
    guard into an opt-in check.  ``corpus_digests`` is injected because only the
    caller that assembled the reviewed corpus can state which rows support a marker.
    """
    resolved = typology.resolve_axis_set(
        type_ids,
        target_lang,
        root=root,
        axis_status=axis_status,
        measurable=measurable,
    )
    source_types = typology.load_types(root)
    mismatched_sources = [
        type_id
        for type_id in type_ids
        if source_types[type_id]["source_lang"] != source_lang
    ]
    if mismatched_sources:
        raise ContractError(
            "type(s) %s declare a source language different from contract source_lang %r"
            % (mismatched_sources, source_lang)
        )
    axes = []
    for type_id, axis in zip(type_ids, resolved):
        digest = corpus_digests.get(type_id)
        if not _sha256(digest):
            raise ContractError(
                "corpus_digests[%r] must be a SHA-256 digest for every resolved marker"
                % type_id
            )
        entry = dict(axis)
        entry["corpus_digest"] = digest
        axes.append(entry)

    contract = {
        "work": work,
        "speaker": speaker,
        "declared_speakers": list(declared_speakers),
        "type_ids": list(type_ids),
        "source_lang": source_lang,
        "target_lang": target_lang,
        "axes": axes,
        "attribution": dict(attribution),
        "required_markers": list(required_markers),
        "forbidden_markers": list(forbidden_markers),
        "measured_source_density": dict(measured_source_density),
        "bands": _copy_json(bands),
        "scope_overrides": _copy_json(scope_overrides),
        "exclusivity": _copy_json(exclusivity),
        "edition_medium": edition_medium,
        "voice_enforcement_mode": voice_enforcement_mode,
        "authority": authority,
        "coverage_floor": coverage_floor,

        "catalogue_version": typology.catalogue_version(root),
        "required_glyphs": list(required_glyphs),
        "marker_sets": _copy_json(marker_sets),
        "catalogue_markers": _copy_json(catalogue_markers),
        "review_decisions": _copy_json(review_decisions),
    }
    errors = validate_contract(contract)
    if errors:
        raise ContractError("; ".join(errors))
    return contract


def _as_findings(value: Any, label: str) -> List[findings.Finding]:
    """Normalise a complete finding artifact without inventing a clean result."""
    if isinstance(value, findings.FindingSet):
        return list(value.hard) + list(value.reported)
    if isinstance(value, findings.Finding):
        return [value]
    if value is None or isinstance(value, (str, bytes, Mapping)):
        raise ContractError("%s must be a finding artifact" % label)
    try:
        items = list(value)
    except TypeError as exc:
        raise ContractError("%s must be a finding artifact" % label) from exc
    if not all(isinstance(item, findings.Finding) for item in items):
        raise ContractError("%s must contain only Finding objects" % label)
    return items


def _rejected_precedent_hit(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return any(
        finding.severity == "hard"
        for finding in _as_findings(value, "rejected_precedent_match")
    )


def _dialect_undecided(value: Any) -> bool:
    return any(
        finding.code == "dialect_pair_undecided"
        for finding in _as_findings(value, "dialect_findings")
    )


def _seal_payload(contract: Mapping[str, Any]) -> bytes:
    """Canonical serialisation for a seal, excluding its self-reference."""
    payload = _copy_json(contract)
    payload.pop("seal", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _seal_is_current(contract: Mapping[str, Any]) -> bool:
    seal = contract.get("seal") if isinstance(contract, Mapping) else None
    return bool(
        isinstance(seal, Mapping)
        and seal.get("algorithm") == _SEAL_ALGORITHM
        and _sha256(seal.get("hash"))
        and seal.get("hash") == hashlib.sha256(_seal_payload(contract)).hexdigest()
    )


def seal(
    contract: Mapping[str, Any],
    *,
    schema_validate: Callable[[Mapping[str, Any]], Sequence[str]],
    graduation_stages: Mapping[str, str],
    source_evidence_ok: Callable[[str], Any] = lambda type_id: (
        "no source-side evidence join was supplied"
    ),
    length_ok: bool,
    plugin_for: Callable[[str], Any],
    plugin_measurable_axes: Callable[[str], Sequence[str]],
    plugin_golden_digest: Callable[[str], str],
    rejected_precedent_match: Any,
    glyph_available: Callable[[str], bool],
    coverage: Mapping[str, float],
    dialect_findings: Any,
) -> Tuple[Optional[Dict[str, Any]], findings.FindingSet]:
    """Seal a contract only after every independently-derived prerequisite passes.

    The injected inputs are evidence joins rather than convenience hooks: graduation
    must come from the caller's corpus report; rejected-precedent and dialect
    results come from their own audited gates; glyph availability belongs to the
    renderer; and coverage belongs to attribution.  This keeps the sealed claim
    re-derivable from published artifacts rather than a second hidden computation.
    """
    result = findings.FindingSet()
    candidate = _copy_json(contract)
    prior_measurable_axes = candidate.pop("measurable_axes", None)
    candidate.pop("seal", None)
    candidate.pop("plugin_version", None)
    candidate.pop("golden_digest", None)


    errors = validate_contract(candidate)
    external_errors = schema_validate(candidate)
    if isinstance(external_errors, str):
        external_errors = [external_errors]
    elif external_errors is None:
        external_errors = ["schema validator returned no result"]
    else:
        try:
            external_errors = list(external_errors)
        except TypeError:
            external_errors = ["schema validator returned a non-iterable result"]
    errors.extend(str(error) for error in external_errors if error)
    if errors:
        result.add(
            findings.hard(
                "contract_schema_invalid",
                "contract fails its closed schema: %s" % "; ".join(errors),
            )
        )

    measured_source_density = candidate.get("measured_source_density")
    for axis_entry in candidate.get("axes", []):
        if not isinstance(axis_entry, Mapping):
            continue
        axis = axis_entry.get("axis")
        value = (
            measured_source_density.get(axis)
            if isinstance(measured_source_density, Mapping) and isinstance(axis, str)
            else None
        )
        if _is_number(value) and float(value) == 0.0:
            result.add(
                findings.hard(
                    "contract_source_density_zero",
                    "axis %s requires a marker but its measured source density is zero; "
                    "refuse a seal whose LOSS gate could never fire" % axis,
                    scope=candidate.get("speaker"),
                    axis=axis,
                )
            )


    # The two authorities require different evidence, and each is checked against
    # exactly what it claims.
    #
    # `precedent_backed` asserts the rendering is the established convention, so it
    # needs a canonical type: source-side evidence AND a cited published edition.
    #
    # `translator_declared` asserts only that the translator's own declared
    # rendering is applied faithfully, so it needs the source-side evidence alone.
    # It must never be read as blessing the rendering, which is why the authority is
    # sealed into the contract and carried through every report.
    authority = candidate.get("authority")
    for type_id in candidate.get("type_ids", []):
        stage = graduation_stages.get(type_id)
        if authority == config.AUTHORITY_TRANSLATOR_DECLARED:
            source_ok = source_evidence_ok(type_id)
            if source_ok is not True:
                result.add(
                    findings.hard(
                        "contract_source_evidence_incomplete",
                        "type %s does not yet have complete source-side evidence, so even a "
                        "translator-declared contract cannot enforce it: %s"
                        % (type_id, source_ok),
                        scope=type_id,
                    )
                )
        elif stage != config.STAGE_CANONICAL:
            result.add(
                findings.hard(
                    "contract_type_not_canonical",
                    "type %s is at graduation stage %r, not canonical" % (type_id, stage),
                    scope=type_id,
                )
            )

    if length_ok is not True:
        result.add(
            findings.hard(
                "contract_length_infeasible",
                "the longest required realisation does not fit the declared layout budget",
                scope=candidate.get("speaker"),
            )
        )

    measurable_axes = []
    plugin_version = None
    golden_digest = None
    source_lang = candidate.get("source_lang")
    try:
        plugin = plugin_for(source_lang)
        measurable_axes = list(plugin_measurable_axes(source_lang))
        plugin_version = getattr(plugin, "VERSION")
        golden_digest = plugin_golden_digest(source_lang)
    except (LookupError, ImportError, AttributeError, TypeError, ValueError) as exc:
        result.add(
            findings.hard(
                "contract_source_measurement_unavailable",
                "source language %r has no usable measurement plugin: %s"
                % (source_lang, exc),
            )
        )
    else:
        axis_names = {
            axis["axis"]
            for axis in candidate.get("axes", [])
            if isinstance(axis, dict) and isinstance(axis.get("axis"), str)
        }
        valid_measurable_axes = (
            bool(measurable_axes)
            and all(isinstance(axis, str) and axis for axis in measurable_axes)
            and len(set(measurable_axes)) == len(measurable_axes)
        )
        measurable_axis_detail = (
            sorted(measurable_axes)
            if all(isinstance(axis, str) for axis in measurable_axes)
            else ["<invalid>"]
        )

        if (
            not valid_measurable_axes
            or not isinstance(plugin_version, str)
            or not plugin_version
            or not _sha256(golden_digest)
            or not axis_names.issubset(set(measurable_axes))
        ):
            result.add(
                findings.hard(
                    "contract_source_measurement_unavailable",
                    "source plugin must expose a unique non-empty axis list, version, golden digest, "
                    "and every required measurable axis (declared=%s, measurable=%s)"
                    % (sorted(axis_names), measurable_axis_detail),

                )
            )
        elif prior_measurable_axes is not None:
            if (
                not isinstance(prior_measurable_axes, list)
                or not prior_measurable_axes
                or any(
                    not isinstance(axis, str) or not axis
                    for axis in prior_measurable_axes
                )
                or len(set(prior_measurable_axes)) != len(prior_measurable_axes)
            ):
                result.add(
                    findings.hard(
                        "contract_schema_invalid",
                        "sealed contract has an invalid measurable_axes pin",
                        scope=candidate.get("speaker"),
                    )
                )
            elif set(prior_measurable_axes) != set(measurable_axes):
                result.add(
                    findings.hard(
                        "contract_source_measurement_changed",
                        "source plugin measurable axes changed from %s to %s; rebuild and review the contract"
                        % (sorted(prior_measurable_axes), sorted(measurable_axes)),
                        scope=candidate.get("speaker"),
                    )
                )


    precedent_value = (
        rejected_precedent_match(candidate)
        if callable(rejected_precedent_match)
        else rejected_precedent_match
    )
    precedent_detail = "a selected realisation matches a rejected precedent"
    if _rejected_precedent_hit(precedent_value):
        result.add(findings.hard("contract_rejected_precedent_match", precedent_detail))

    unavailable = []
    for glyph in candidate.get("required_glyphs", []):
        if glyph_available(glyph) is not True:
            unavailable.append(glyph)
    if unavailable:
        result.add(
            findings.hard(
                "contract_required_glyph_unavailable",
                "required glyph(s) unavailable: %s" % ", ".join(unavailable),
            )
        )

    coverage_floor = candidate.get("coverage_floor", config.COVERAGE_FLOOR_X)
    if float(coverage_floor) < config.COVERAGE_FLOOR_X:
        result.add(
            findings.hard(
                "contract_coverage_floor_below_frozen",
                "declared coverage floor %.2f is below frozen coverage floor %.2f; "
                "the lower declared floor requires a hash-bound coverage waiver"
                % (float(coverage_floor), config.COVERAGE_FLOOR_X),
                scope=candidate.get("work"),
            )
        )
    for speaker in candidate.get("declared_speakers", []):
        value = coverage.get(speaker)
        if not _is_number(value) or float(value) < float(coverage_floor):
            result.add(
                findings.hard(
                    "contract_speaker_coverage_below_floor",
                    "speaker %s coverage %r is below the declared %.2f floor"
                    % (speaker, value, float(coverage_floor)),
                    scope=speaker,
                )
            )

    if _dialect_undecided(dialect_findings):
        result.add(
            findings.hard(
                "contract_dialect_pair_undecided",
                "the declared dialect pair has no human ruling",
                scope=candidate.get("work"),
            )
        )

    if not result.is_clean():
        return None, result

    candidate["plugin_version"] = plugin_version
    candidate["golden_digest"] = golden_digest
    candidate["measurable_axes"] = sorted(measurable_axes)
    candidate["seal"] = {
        "algorithm": _SEAL_ALGORITHM,
        "hash": hashlib.sha256(_seal_payload(candidate)).hexdigest(),
    }
    return candidate, result


def _flat_realisations(realisations: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Accept either the typology id map or a type-id-to-variant map."""
    out = []
    for value in realisations.values():
        if isinstance(value, dict) and "type_id" in value:
            out.append(value)
        elif isinstance(value, (list, tuple)):
            out.extend(item for item in value if isinstance(item, dict) and "type_id" in item)
    return out


def _length_after_cost(chars: float, parts: int, cost: Mapping[str, Any]) -> Tuple[float, int]:
    model = cost.get("model")
    value = cost.get("value")
    if not _is_number(value) or float(value) < 0:
        raise ContractError("realisation length_cost must contain a non-negative number")
    value = float(value)
    if model == "append":
        return chars + value, parts
    if model == "multiply":
        return chars * value, parts
    if model == "split":
        if value < 1 or not value.is_integer():
            raise ContractError("split length_cost.value must be a positive whole number")
        return chars, parts * int(value)
    raise ContractError("unknown length_cost.model %r" % model)


def _longest_variant(
    variants: Sequence[Mapping[str, Any]], chars: float, parts: int, axis: str
) -> Tuple[Optional[Mapping[str, Any]], Optional[Tuple[float, int]], Optional[str]]:
    if not variants:
        return None, None, "no_realisation"
    projected = []
    for variant in variants:
        cost = variant.get("length_cost")
        if not isinstance(cost, dict):
            return None, None, "missing_length_cost"
        if axis == "utterance_frame" and cost.get("model") == "append":
            return None, None, "utterance_frame_append_forbidden"
        try:
            result = _length_after_cost(chars, parts, cost)
        except ContractError as exc:
            return None, None, str(exc)
        # The maximum total character projection is conservative; part count is a
        # tie-breaker because a split consumes additional layout capacity.
        projected.append((result[0], result[1], str(variant.get("id", "")), variant))
    projected.sort(key=lambda item: (item[0], item[1], item[2]))
    chars_after, parts_after, _identifier, variant = projected[-1]
    return variant, (chars_after, parts_after), None


def _row_medium(row: Mapping[str, Any], contract: Mapping[str, Any]) -> str:
    medium = row.get("medium", contract.get("edition_medium"))
    if not isinstance(medium, str) or not medium:
        raise ContractError("row medium must be declared")
    return medium.lower()


def _budget_failure(
    medium: str,
    budget: Mapping[str, Any],
    projected: Mapping[str, Any],
    *,
    timing_present: bool,
) -> bool:
    if medium in ("plain", "po"):
        return False
    if medium == "subtitle":
        if not _is_number(budget.get("cpl")):
            return True
        if float(projected["cpl"]) > float(budget["cpl"]):
            return True
        if timing_present:
            if not _is_number(budget.get("cps")):
                return True
            if float(projected["cps"]) > float(budget["cps"]):
                return True
        return False
    if medium == "balloon":
        if not _is_number(budget.get("chars")) or not _is_number(budget.get("area")):
            return True
        return (
            float(projected["chars"]) > float(budget["chars"])
            or float(projected["area"]) > float(budget["area"])
        )
    return True


def length_feasible(
    rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
    realisations: Mapping[str, Any],
    *,
    eligible_segments: Callable[[Mapping[str, Any]], Sequence[Mapping[str, Any]]],
    budgets: Mapping[str, Mapping[str, Any]],
) -> Tuple[bool, List[Tuple[str, str, str, Dict[str, Any], Dict[str, Any]]]]:
    """Project every required axis through every eligible row segment.

    For a type with several target variants, the conservative projection selects the
    variant producing the greatest character requirement for that segment.  Costs
    are applied cumulatively: ``append`` adds characters, ``multiply`` scales them,
    and ``split`` retains the total but multiplies rendered parts.  Plain and PO
    media are advisory-only.  No tolerance or altered budget is introduced here.
    """
    if not rows:
        raise ContractError("length check requires at least one eligible row")
    failures = []
    variants = _flat_realisations(realisations)
    axes = contract.get("axes", [])
    type_ids = contract.get("type_ids", [])
    if (
        not isinstance(axes, list)
        or not axes
        or not isinstance(type_ids, list)
        or not type_ids
        or len(axes) != len(type_ids)
    ):
        raise ContractError("length check requires one resolved axis per type id")
    checked_segments = 0

    for row in rows:
        if not isinstance(row, Mapping):
            raise ContractError("length row must be an object")
        row_key = row.get("key", row.get("row_key"))
        if not isinstance(row_key, str) or not row_key:
            raise ContractError("length row must declare key or row_key")
        medium = _row_medium(row, contract)
        declared_budget = budgets.get(medium)
        if declared_budget is None:
            declared_budget = budgets.get(row.get("medium"))
        if not isinstance(declared_budget, Mapping):
            declared_budget = {}
        budget = _copy_json(dict(declared_budget))
        segments = eligible_segments(row)
        if segments is None:
            raise ContractError("eligible_segments must return a sequence, not None")
        for segment in segments:
            if isinstance(segment, str):
                segment = {"text": segment}
            if not isinstance(segment, Mapping) or not isinstance(segment.get("text"), str):
                raise ContractError("each eligible segment must provide text")
            checked_segments += 1
            chars = float(len(segment["text"]))
            parts = int(segment.get("parts", 1))
            if parts < 1:
                raise ContractError("segment.parts must be positive")
            start = segment.get("start", row.get("start"))
            end = segment.get("end", row.get("end"))
            timing_present = start is not None or end is not None
            duration = None
            if timing_present:
                if not _is_number(start) or not _is_number(end) or float(end) <= float(start):
                    duration = 0.0
                else:
                    duration = float(end) - float(start)
            area_per_char = segment.get("area_per_char", 1.0)
            if not _is_number(area_per_char) or float(area_per_char) < 0:
                raise ContractError("segment.area_per_char must be a non-negative number")

            for type_id, axis_entry in zip(type_ids, axes):
                if not isinstance(axis_entry, Mapping) or not isinstance(axis_entry.get("axis"), str):
                    raise ContractError("resolved axis entries must declare axis")
                axis = axis_entry["axis"]
                choices = [item for item in variants if item.get("type_id") == type_id]
                selected, result, error = _longest_variant(choices, chars, parts, axis)
                projected = {
                    "chars": chars,
                    "parts": parts,
                    "cpl": chars / parts,
                    "area": chars * float(area_per_char),
                }
                if duration is not None:
                    projected["cps"] = math.inf if duration == 0 else chars / duration
                if error is not None:
                    projected["reason"] = error
                    failures.append((row_key, axis, medium, budget, projected))
                    continue
                assert result is not None and selected is not None
                chars, parts = result
                projected = {
                    "chars": chars,
                    "parts": parts,
                    "cpl": chars / parts,
                    "area": chars * float(area_per_char),
                    "realisation": selected.get("id"),
                }
                if duration is not None:
                    projected["cps"] = math.inf if duration == 0 else chars / duration
                if _budget_failure(
                    medium, budget, projected, timing_present=timing_present
                ):
                    failures.append((row_key, axis, medium, budget, projected))
    if checked_segments == 0:
        raise ContractError("length check requires at least one eligible segment")
    return (not failures), failures


def create_waiver(
    contract: Mapping[str, Any],
    category: str,
    *,
    waiver_id: str,
    reason: str,
    waived_codes: Sequence[str],
    granted_by: str,
    granted_at: str,
) -> Dict[str, Any]:
    """Create one schema-valid waiver bound to exactly one current seal.

    Application belongs to :mod:`hancharacter.gates`; this function records the
    approved artifact and its contract binding without deciding which findings a
    category may clear.
    """
    if category not in config.WAIVER_CATEGORIES:
        raise ContractError(
            "waiver category %r is not one of %s" % (category, list(config.WAIVER_CATEGORIES))
        )
    if not _seal_is_current(contract):
        raise ContractError("a waiver can bind only to a current sealed contract")
    if not isinstance(waived_codes, Sequence) or isinstance(waived_codes, (str, bytes)):
        raise ContractError("waived_codes must be a sequence of finding codes")
    codes = list(waived_codes)
    if any(not isinstance(code, str) or not code for code in codes):
        raise ContractError("waived_codes must contain non-empty strings")
    if len(set(codes)) != len(codes):
        raise ContractError("waived_codes must not repeat a finding code")
    waiver = {
        "id": waiver_id,
        "category": category,
        "contract_hash": contract["seal"]["hash"],
        "reason": reason,
        "waived_codes": codes,
        "granted_by": granted_by,
        "granted_at": granted_at,
        "stale": False,
    }
    try:
        schemas.require("waiver", waiver)
    except ValueError as exc:
        raise ContractError("invalid waiver artifact: %s" % exc) from exc
    return waiver


def waiver_is_current(waiver: Mapping[str, Any], contract: Mapping[str, Any]) -> bool:
    """A waiver cannot outlive an edit to the contract it named."""
    if not isinstance(waiver, Mapping):
        return False
    if schemas.validate("waiver", dict(waiver)):
        return False
    return bool(
        waiver.get("stale") is False
        and _seal_is_current(contract)
        and waiver.get("contract_hash") == contract["seal"]["hash"]
    )


def ladder_ledger_check(
    contract: Mapping[str, Any], ledger: Optional[Sequence[Mapping[str, Any]]]
) -> findings.FindingSet:
    """Reject an absent priority-ladder ledger and any resulting marker under-run.

    A waiver is deliberately not an argument to this function.  A priority ladder is
    allowed only while it preserves the contract; once it drops a required marker,
    that is a non-waivable defect, not an editorial exception.
    """
    result = findings.FindingSet()
    if ledger is None:
        result.add(
            findings.hard(
                "contract_voice_drop_ledger_absent",
                "no voice-drop ledger was supplied; dropped markers would otherwise look clean",
                scope=contract.get("speaker"),
            )
        )
        return result
    for index, entry in enumerate(ledger):
        if not isinstance(entry, Mapping):
            result.add(
                findings.hard(
                    "contract_voice_drop_ledger_invalid",
                    "voice-drop ledger entry %d is not an object" % index,
                    scope=contract.get("speaker"),
                )
            )
            continue
        if entry.get("event") != "voice-drop":
            continue
        if entry.get("reason") not in ("priority_ladder", "ladder"):
            continue
        if not isinstance(entry.get("under_run"), bool):
            result.add(
                findings.hard(
                    "contract_voice_drop_ledger_invalid",
                    "voice-drop ledger entry %d must declare boolean under_run" % index,
                    scope=contract.get("speaker"),
                )
            )
        elif entry["under_run"]:
            result.add(
                findings.hard(
                    "contract_ladder_marker_underrun",
                    "priority ladder dropped a required marker on row %r; this is non-waivable"
                    % entry.get("row_key"),
                    scope=contract.get("speaker"),
                    row_key=entry.get("row_key"),
                    axis=entry.get("axis"),
                )
            )
    return result


def rebase(
    contract: Mapping[str, Any],
    *,
    corpus_digests: Mapping[str, str],
    axis_status: Callable[[str], Dict[str, str]],
    measurable: Sequence[str],
    schema_validate: Callable[[Mapping[str, Any]], Sequence[str]],
    graduation_stages: Mapping[str, str],
    source_evidence_ok: Callable[[str], Any] = lambda type_id: (
        "no source-side evidence join was supplied"
    ),
    length_ok: bool,
    plugin_for: Callable[[str], Any],
    plugin_measurable_axes: Callable[[str], Sequence[str]],
    plugin_golden_digest: Callable[[str], str],
    rejected_precedent_match: Any,
    glyph_available: Callable[[str], bool],
    coverage: Mapping[str, float],
    dialect_findings: Any,
    waivers: Sequence[Mapping[str, Any]],
    root: Optional[str] = None,
) -> Tuple[Optional[Dict[str, Any]], findings.FindingSet, List[Dict[str, Any]]]:
    """Resolve against a newer catalogue, reseal, and stale changed bindings."""
    rebuilt = build(
        contract["work"],
        contract["speaker"],
        contract["type_ids"],
        contract["source_lang"],
        contract["target_lang"],
        attribution=contract["attribution"],
        required_markers=contract["required_markers"],
        forbidden_markers=contract["forbidden_markers"],
        measured_source_density=contract["measured_source_density"],
        bands=contract["bands"],
        scope_overrides=contract["scope_overrides"],
        exclusivity=contract["exclusivity"],
        edition_medium=contract["edition_medium"],
        voice_enforcement_mode=contract["voice_enforcement_mode"],
        authority=contract["authority"],
        declared_speakers=contract["declared_speakers"],
        corpus_digests=corpus_digests,
        marker_sets=contract["marker_sets"],
        catalogue_markers=contract["catalogue_markers"],
        review_decisions=contract["review_decisions"],
        required_glyphs=contract["required_glyphs"],
        axis_status=axis_status,
        measurable=measurable,
        root=root,
    )
    resealed, result = seal(
        rebuilt,
        schema_validate=schema_validate,
        graduation_stages=graduation_stages,
        length_ok=length_ok,
        plugin_for=plugin_for,
        plugin_measurable_axes=plugin_measurable_axes,
        plugin_golden_digest=plugin_golden_digest,
        rejected_precedent_match=rejected_precedent_match,
        glyph_available=glyph_available,
        coverage=coverage,
        dialect_findings=dialect_findings,
    )
    current_hash = None if resealed is None else resealed["seal"]["hash"]
    rebased_waivers = []
    for waiver in waivers:
        copied = _copy_json(waiver)
        copied["stale"] = copied.get("contract_hash") != current_hash
        rebased_waivers.append(copied)
    return resealed, result, rebased_waivers
