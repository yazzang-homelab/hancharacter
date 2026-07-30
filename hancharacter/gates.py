"""Ordered, artifact-derived character voice gates.

This module deliberately owns no attribution, contract, or renderer policy.  Those
artifacts and the functions that derive them are supplied at the boundary.  The
gates only join published artifacts, run the canonical density metric, and make
any skipped or rejected decision visible.

``run`` accepts injected ``attribution_gate``, ``seal_contract``, ``length_check``
and ``ladder_check`` callables so importing this module cannot accidentally select
a different peer implementation.  Its corpus observations are plain artifacts;
model-labelled fields are deliberately ignored.
"""
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
import hashlib
import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from . import config, density, findings, io_adapters, measure, schemas




_GATE_ORDER = (
    "character-attribution",
    "contract-seal",
    "capacity/length",
    "character-corpus",
)
_BINDING_RE = re.compile(r"\s*\[waiver-bind:sha256=([0-9a-f]{64})\]$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Retained only as the fallback for a target adapter that publishes no
# BASE_REGISTER. `measure/ko.py` is the canonical owner and is consulted first by
# `_base_register_for`; a target language whose adapter declares nothing gets this
# conservative Korean list, which is wrong for any non-Korean target and is
# therefore reported rather than relied on.
_LOCAL_KO_BASE_REGISTER_WHITELIST = (
    r"(?:요|죠|군요|네요|습니다|ㅂ니다|니다|습니까|ㅂ니까|세요|십시오|시죠|지요|아요|어요|여요|다|라|자|게|고|네|군|지|까|야|아|어|해|했어|했지|거든|구나|잖아|지마)[.。!?！？…]*$",
)

# Waiver categories are closed by config.  This table closes the second half of
# the rule: a known category cannot be used to clear an unrelated finding.
_WAIVABLE_BY_CATEGORY = {
    "policy_density": frozenset(("DENSITY_VERDICT",)),
    "arc_scope": frozenset(("DENSITY_VERDICT",)),
    "edition_variant": frozenset(("DENSITY_VERDICT",)),
    "dialect_ruling": frozenset(("DENSITY_VERDICT",)),
    "coverage": frozenset(
        (
            "contract_speaker_coverage_below_floor",
            "contract_coverage_floor_below_frozen",
        )
    ),
    # A glyph fallback may document renderer work, but never erase a voice
    # presence, corpus, or ladder result.
    "glyph_fallback": frozenset(),
}

# These classifications intentionally dominate any future category expansion.
# A marker is present, absent, fabricated, forbidden, or dropped by the ladder;
# none is a policy preference a waiver may erase.
_NON_WAIVABLE_CODES = frozenset(
    (
        "voice_required_marker_absent",
        "voice_forbidden_marker_present",
        "voice_exclusivity",
        "voice_invention_catalogue",
        "voice_invention_review_untriaged",
        "contract_ladder_marker_underrun",
        "contract_voice_drop_ledger_absent",
        "contract_voice_drop_ledger_invalid",
        "gate_not_run",
        "contract_source_density_zero",
        "voice_source_density_zero",


    )
)


class GateError(ValueError):
    """Raised for an incomplete artifact boundary rather than guessed input."""


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _as_list(value: Any, label: str) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (str, bytes, Mapping)):
        raise GateError("%s must be a sequence" % label)
    try:
        return list(value)
    except TypeError as exc:
        raise GateError("%s must be a sequence" % label) from exc


def _finding_set(value: Any, label: str) -> findings.FindingSet:
    """Normalise only actual findings; truthy booleans never authorise a pass."""
    result = findings.FindingSet()
    if value is None:
        raise GateError("%s finding artifact is absent" % label)
    if isinstance(value, findings.FindingSet):
        result.extend(list(value.hard) + list(value.reported))
        return result
    if isinstance(value, findings.Finding):
        result.add(value)
        return result
    if isinstance(value, Mapping) and "findings" in value:
        value = value["findings"]
    if isinstance(value, (str, bytes, Mapping)):
        raise GateError("%s must contain Finding objects, not a model verdict" % label)
    try:
        values = list(value)
    except TypeError as exc:
        raise GateError("%s must contain Finding objects" % label) from exc
    for index, item in enumerate(values):
        if isinstance(item, findings.Finding):
            result.add(item)
        elif isinstance(item, Mapping):
            try:
                result.add(findings.Finding(**item))
            except TypeError as exc:
                raise GateError("%s[%d] is not a finding artifact" % (label, index)) from exc
        else:
            raise GateError("%s[%d] is not a finding artifact" % (label, index))
    return result


def _copy_finding(finding: findings.Finding, *, detail: Optional[str] = None) -> findings.Finding:
    return findings.Finding(
        code=finding.code,
        severity=finding.severity,
        detail=finding.detail if detail is None else detail,
        scope=finding.scope,
        row_key=finding.row_key,
        axis=finding.axis,
    )


def contract_hash(contract: Mapping[str, Any]) -> str:
    """Return the binding hash for a gate finding.

    A current contract's own seal is the shared binding with a persisted waiver.
    The serialised fallback only labels findings emitted while an unsealed contract
    is being refused; such a candidate cannot create a valid waiver.
    """
    seal = contract.get("seal") if isinstance(contract, Mapping) else None
    if isinstance(seal, Mapping) and isinstance(seal.get("hash"), str) and _SHA256_RE.fullmatch(seal["hash"]):
        return seal["hash"]
    try:
        payload = json.dumps(
            contract, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise GateError("contract must be JSON-shaped to bind a waiver: %s" % exc)
    return hashlib.sha256(payload).hexdigest()



def bind_finding(finding: findings.Finding, contract: Mapping[str, Any]) -> findings.Finding:
    """Bind a finding to one exact contract without widening ``Finding``'s schema."""
    digest = contract_hash(contract)
    if _BINDING_RE.search(finding.detail):
        return finding
    return _copy_finding(finding, detail="%s [waiver-bind:sha256=%s]" % (finding.detail, digest))


def _binding(finding: findings.Finding) -> Optional[str]:
    match = _BINDING_RE.search(finding.detail)
    return None if match is None else match.group(1)


def _waived_codes(waiver: Any) -> Tuple[str, ...]:
    """Return a waiver's declared codes without treating malformed data as a match."""
    codes = _value(waiver, "waived_codes")
    if isinstance(codes, (str, bytes, Mapping)) or not isinstance(codes, Sequence):
        return ()
    return tuple(code for code in codes if isinstance(code, str))


def _rejected_waiver(detail: str, waiver: Any) -> findings.Finding:
    category = _value(waiver, "category", "?")
    codes = _waived_codes(waiver)
    return findings.hard(
        "waiver_rejected",
        "waiver category %r for %r rejected: %s" % (category, list(codes) or "?", detail),
    )

def _obsolete_waiver(waiver: Any) -> findings.Finding:
    category = _value(waiver, "category", "?")
    codes = _waived_codes(waiver)
    return findings.report(
        "waiver_obsolete",
        "waiver category %r for %r no longer names a finding and can be retired"
        % (category, list(codes) or "?"),
    )


def apply_waivers(
    source: Any,
    waivers: Iterable[Mapping[str, Any]],
    *,
    current_contract_hashes: Iterable[str] = (),
) -> Tuple[findings.FindingSet, List[Dict[str, Any]], List[findings.Finding]]:
    """Apply only current, closed, contract-bound waiver artifacts.

    A valid waiver that no longer names any finding is report-only obsolete and
    explicitly says it can be retired.  Malformed, stale, unknown-category, and
    non-waivable records remain hard failures.
    """
    source_findings = _finding_set(source, "findings")
    original = list(source_findings.hard) + list(source_findings.reported)
    known_hashes = {value for value in current_contract_hashes if isinstance(value, str)}

    applied: List[Dict[str, Any]] = []
    rejected: List[findings.Finding] = []
    seen = set()

    for waiver in _as_list(waivers, "waivers"):
        if not isinstance(waiver, Mapping):
            rejected.append(_rejected_waiver("artifact is not an object", waiver))
            continue
        schema_errors = schemas.validate("waiver", dict(waiver))
        if schema_errors:
            rejected.append(_rejected_waiver("invalid artifact: %s" % "; ".join(schema_errors), waiver))
            continue
        waiver_id = waiver["id"]
        if waiver_id in seen:
            rejected.append(_rejected_waiver("duplicate waiver id", waiver))
            continue
        seen.add(waiver_id)
        if waiver.get("stale") is True:
            rejected.append(_rejected_waiver("stale after contract rebase", waiver))
            continue

        category = waiver["category"]
        codes = _waived_codes(waiver)
        forbidden = [
            code
            for code in codes
            if code not in _WAIVABLE_BY_CATEGORY.get(category, frozenset())
            or code in _NON_WAIVABLE_CODES
        ]
        if forbidden:
            rejected.append(
                _rejected_waiver(
                    "category may not waive code(s) %s" % sorted(forbidden), waiver
                )
            )
            continue

        bound_hash = waiver["contract_hash"]
        if known_hashes and bound_hash not in known_hashes:
            rejected.append(_rejected_waiver("stale against every current contract seal", waiver))
            continue
        matched = []
        stale = False
        missing = []
        for code in codes:
            candidates = [finding for finding in original if finding.code == code]
            current = [
                finding for finding in candidates if _binding(finding) == bound_hash
            ]
            if not current:
                stale = stale or bool(candidates)
                missing.append(code)
                continue
            matched.extend(current)
        if missing:
            rejected.append(
                _rejected_waiver("stale after contract/finding edit", waiver)
                if stale
                else _obsolete_waiver(waiver)
            )
            continue

        for finding in matched:
            applied.append(
                {
                    "id": waiver_id,
                    "category": category,
                    "code": finding.code,
                    "contract_hash": bound_hash,
                    "reason": waiver["reason"],
                }
            )
        original = [finding for finding in original if finding not in matched]

    remaining = findings.FindingSet()
    remaining.extend(original)
    return remaining, applied, rejected


def _patterns(value: Any, label: str) -> Tuple[re.Pattern, ...]:
    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, Sequence) or isinstance(value, (bytes, Mapping)):
        raise GateError("%s must be a sequence of regex strings" % label)
    compiled = []
    for pattern in value:
        if not isinstance(pattern, str) or not pattern:
            raise GateError("%s contains an invalid regex" % label)
        try:
            compiled.append(re.compile(pattern, re.IGNORECASE))
        except re.error as exc:
            raise GateError("%s contains invalid regex %r: %s" % (label, pattern, exc))
    return tuple(compiled)


def _matches(text: str, patterns: Sequence[re.Pattern]) -> bool:
    return any(pattern.search(text) is not None for pattern in patterns)


def _normalise_raw_surface(text: str, profile: Any, target_lang: str) -> str:
    """Recover the declared measurement surface for a raw observation.

    Legacy plain strings without markup or delimiters are already usable without a
    profile. Raw delimited strings require the same adapter-owned normalisation as
    loaded rows so a delimiter cannot defeat an anchored marker pattern.
    """
    if profile is None:
        if text[:1] in ('"', "'", "「", "『") or text[-1:] in ('"', "'", "」", "』"):
            raise ValueError("raw delimited observation has no declared profile")
        return text
    return io_adapters.normalise_measurement_surface(text, profile, target_lang)



def _surface(
    observation: Mapping[str, Any], axis: str, profile: Any, target_lang: str
) -> str:
    if observation["raw_surface"]:
        return _normalise_raw_surface(observation["text"], profile, target_lang)
    return measure.unit_surface(observation["unit"], axis)


def _matches_observation(
    observation: Mapping[str, Any],
    patterns: Sequence[re.Pattern],
    axis: str,
    profile: Any,
    target_lang: str,
    result: findings.FindingSet,
    failures: set,
) -> bool:
    try:
        surface = _surface(observation, axis, profile, target_lang)
    except (AttributeError, LookupError, TypeError, ValueError) as exc:
        key = (observation["scope"], observation["row_key"], axis)
        if key not in failures:
            failures.add(key)
            result.add(
                findings.hard(
                    "voice_observation_unnormalisable",
                    "scope %s row %s axis %s cannot be normalised to the measurement surface: %s"
                    % (observation["scope"], observation["row_key"], axis, exc),
                    scope=observation["scope"],
                    row_key=observation["row_key"],
                    axis=axis,
                )
            )
        return False
    return _matches(surface, patterns)


def _observation(observation: Any, index: int) -> Dict[str, Any]:
    missing = object()
    text = _value(observation, "text", _value(observation, "target_text", missing))
    base = _value(observation, "base", missing)
    reading = _value(observation, "reading", missing)
    if text is missing:
        text = base if isinstance(base, str) else reading
    scope = _value(observation, "scope", _value(observation, "speaker"))
    row_key = _value(observation, "row_key", _value(observation, "key"))
    if not isinstance(text, str):
        raise GateError("observation %d requires target text or a canonical unit surface" % index)
    if not isinstance(scope, str) or not scope:
        raise GateError("observation %d requires a scope, including ineligible/pending rows" % index)
    if not isinstance(row_key, str) or not row_key:
        raise GateError("observation %d requires a row_key" % index)
    scene = _value(observation, "scene")
    if scene is not None and not isinstance(scene, str):
        raise GateError("observation %d scene must be a string or null" % index)
    eligible = _value(observation, "eligible", True)
    pending = _value(observation, "pending", False)
    attributed_spans = _value(observation, "attributed_spans", 1)
    if not isinstance(eligible, bool) or not isinstance(pending, bool):
        raise GateError("observation %d eligibility flags must be booleans" % index)
    if not isinstance(attributed_spans, int) or attributed_spans < 0:
        raise GateError("observation %d attributed_spans must be a non-negative integer" % index)
    return {
        "text": text,
        "unit": observation,
        "raw_surface": base is missing and reading is missing,
        "scope": scope,
        "row_key": row_key,
        "scene": scene,
        "eligible": eligible,
        "pending": pending,
        "attributed_spans": attributed_spans,
        "sentence_final": _value(observation, "sentence_final"),
        "narration_text": _value(observation, "narration_text"),
        "mode": _value(observation, "mode"),
        "state": _value(observation, "state"),
        "form": _value(observation, "form"),
        "arc": _value(observation, "arc"),
    }


def _normalise_contracts(contracts: Iterable[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    by_scope: Dict[str, Mapping[str, Any]] = {}
    for index, contract in enumerate(_as_list(contracts, "contracts")):
        if not isinstance(contract, Mapping):
            raise GateError("contracts[%d] is not an object" % index)
        scope = contract.get("speaker", contract.get("scope"))
        if not isinstance(scope, str) or not scope:
            raise GateError("contracts[%d] requires speaker" % index)
        if scope in by_scope:
            raise GateError("multiple contracts declare speaker %r" % scope)
        by_scope[scope] = contract
    return by_scope


def _required_patterns(contract: Mapping[str, Any], axis: Optional[str] = None) -> Tuple[re.Pattern, ...]:
    per_axis = contract.get("required_markers_by_axis")
    if axis is not None and isinstance(per_axis, Mapping) and axis in per_axis:
        return _patterns(per_axis[axis], "required_markers_by_axis[%r]" % axis)
    return _patterns(contract.get("required_markers", ()), "required_markers")


def _forbidden_patterns(contract: Mapping[str, Any]) -> Tuple[re.Pattern, ...]:
    return _patterns(contract.get("forbidden_markers", ()), "forbidden_markers")


def _contract_axes(contract: Mapping[str, Any]) -> List[str]:
    axes = contract.get("axes")
    if not isinstance(axes, Sequence) or isinstance(axes, (str, bytes, Mapping)):
        return []
    result = []
    for entry in axes:
        axis = _value(entry, "axis")
        if isinstance(axis, str) and axis:
            result.append(axis)
    return result
def _caller_value(
    values: Optional[Mapping[Any, Any]], scope: str, axis: str
) -> Any:
    if values is None:
        return None
    if not isinstance(values, Mapping):
        raise GateError("caller gate input must be a mapping when supplied")
    return values.get(
        (scope, axis), values.get("%s:%s" % (scope, axis), values.get(axis))
    )


def _input_contradiction(
    result: findings.FindingSet, field: str, scope: Optional[str] = None
) -> None:
    result.add(
        findings.hard(
            "gate_input_contradicts_seal",
            "caller-supplied %s contradicts the sealed contract" % field,
            scope=scope,
        )
    )


def _sealed_marker_patterns(
    contract: Mapping[str, Any],
    scope: str,
    axis: str,
    supplied: Optional[Mapping[Any, Sequence[str]]],
    result: findings.FindingSet,
) -> Tuple[re.Pattern, ...]:
    caller_value = _caller_value(supplied, scope, axis)
    sealed_sets = contract.get("marker_sets")
    if isinstance(sealed_sets, Mapping) and axis in sealed_sets:
        sealed_value = sealed_sets[axis]
        if caller_value is not None and caller_value != sealed_value:
            _input_contradiction(result, "marker_sets", scope)
        return _patterns(sealed_value, "sealed marker_sets[%r]" % axis)
    if caller_value is not None:
        return _patterns(caller_value, "marker_sets[%r]" % ((scope, axis),))
    return _required_patterns(contract, axis)


def _authoritative_catalogue_markers(
    contracts: Mapping[str, Mapping[str, Any]],
    supplied: Optional[Mapping[str, Any]],
    result: findings.FindingSet,
) -> Mapping[str, Any]:
    sealed = [
        contract["catalogue_markers"]
        for contract in contracts.values()
        if isinstance(contract.get("catalogue_markers"), Mapping)
    ]
    if not sealed:
        if not isinstance(supplied, Mapping):
            raise GateError("catalogue_markers must be supplied when no contract seals them")
        return supplied
    authoritative = sealed[0]
    for candidate in sealed[1:]:
        if candidate != authoritative:
            _input_contradiction(result, "catalogue_markers")
    if supplied is not None and supplied != authoritative:
        _input_contradiction(result, "catalogue_markers")
    return authoritative


def _authoritative_review_decisions(
    contracts: Mapping[str, Mapping[str, Any]],
    supplied: Optional[Mapping[str, Any]],
    result: findings.FindingSet,
) -> Mapping[str, Any]:
    sealed = [
        contract["review_decisions"]
        for contract in contracts.values()
        if isinstance(contract.get("review_decisions"), Mapping)
    ]
    if not sealed:
        if supplied is None:
            return {}
        if not isinstance(supplied, Mapping):
            raise GateError("review_decisions must be a mapping when supplied")
        return supplied
    authoritative = {}
    for decisions in sealed:
        for key, decision in decisions.items():
            if key in authoritative and authoritative[key] != decision:
                _input_contradiction(result, "review_decisions")
            authoritative[key] = decision
    if supplied is not None and supplied != authoritative:
        _input_contradiction(result, "review_decisions")
    return authoritative


def _observation_scope_key(observation: Mapping[str, Any]) -> Optional[str]:
    values = tuple(observation[name] for name in ("mode", "state", "form", "arc"))
    if not all(isinstance(value, str) and value for value in values):
        return None
    return "mode=%s|state=%s|form=%s|arc=%s" % values


def _sealed_band(
    contract: Mapping[str, Any],
    scope: str,
    axis: str,
    observations: Sequence[Mapping[str, Any]],
    supplied: Optional[Mapping[Any, Sequence[float]]],
    source_scenes: Sequence[float],
) -> Tuple[Tuple[float, float], bool]:
    """Return the sealed band and whether legacy caller fallback was required."""
    bands = contract.get("bands")
    if isinstance(bands, Mapping):
        selected = bands.get(scope, bands.get("all"))
        if isinstance(selected, Mapping) and axis in selected:
            band = selected[axis]
            keys = {_observation_scope_key(item) for item in observations}
            keys.discard(None)
            if len(keys) == 1:
                override = contract.get("scope_overrides")
                if isinstance(override, Mapping):
                    override_row = override.get(next(iter(keys)))
                    if isinstance(override_row, Mapping):
                        override_bands = override_row.get("bands")
                        if isinstance(override_bands, Mapping) and axis in override_bands:
                            band = override_bands[axis]
            try:
                lower, upper = band
                return (float(lower), float(upper)), False
            except (TypeError, ValueError) as exc:
                raise GateError("sealed band for %s/%s is invalid: %s" % (scope, axis, exc)) from exc
    caller_band = _caller_value(supplied, scope, axis)
    if caller_band is None:
        caller_band = density.band(source_scenes)
    try:
        lower, upper = caller_band
        return (float(lower), float(upper)), True
    except (TypeError, ValueError) as exc:
        raise GateError("unsealed band for %s/%s is invalid: %s" % (scope, axis, exc)) from exc



def _catalogue_patterns(catalogue_markers: Mapping[str, Any]) -> Dict[str, Tuple[re.Pattern, ...]]:
    if not isinstance(catalogue_markers, Mapping):
        raise GateError("catalogue_markers must map marker ids to regex sequences")
    return {
        str(marker): _patterns(patterns, "catalogue_markers[%r]" % marker)
        for marker, patterns in catalogue_markers.items()
    }


def _final_form(
    observation: Mapping[str, Any],
    axis: str,
    profile: Any,
    target_lang: str,
    result: findings.FindingSet,
    failures: set,
    *,
    surface: Optional[str] = None,
) -> Optional[str]:
    declared = observation.get("sentence_final")
    if isinstance(declared, str) and declared:
        return declared
    if surface is None:
        try:
            surface = _surface(observation, axis, profile, target_lang)
        except (AttributeError, LookupError, TypeError, ValueError):
            _matches_observation(observation, (), axis, profile, target_lang, result, failures)
            return None
    # A declared form is preferable, but one Hangul final syllable is a bounded,
    # reproducible local fallback for the current Korean adapter.  We never use a
    # language-model label or infer a character from prose.
    text = surface.rstrip(".。!?！？… \t\r\n")
    match = re.search(r"([가-힣])$", text)
    return None if match is None else match.group(1)


def _base_whitelist(target_lang: str, supplied: Optional[Sequence[str]]) -> Tuple[re.Pattern, ...]:
    """The target language's ordinary sentence-final inventory.

    Consulted in this order: an explicit caller list, then the target adapter's own
    ``BASE_REGISTER``, then the bounded local Korean fallback. The adapter is the
    right owner because this is a fact about a language, not about one character's
    contract, and a whitelist living here would be unreachable for a second target
    language.

    An empty tuple for a target whose adapter declares nothing is deliberate: with
    no base register subtracted, ordinary speech in that language becomes eligible
    to be called an invention, so the caller must treat an empty whitelist as a
    recorded gap rather than as a clean result.
    """
    if supplied is not None:
        return _patterns(supplied, "base_register_whitelist")
    try:
        from . import measure

        declared = getattr(measure.get_plugin(target_lang), "BASE_REGISTER", None)
    except LookupError:
        declared = None
    if declared:
        return _patterns(declared, "%s adapter BASE_REGISTER" % target_lang)
    if target_lang.lower() == "ko":
        return _patterns(_LOCAL_KO_BASE_REGISTER_WHITELIST, "local Korean base-register whitelist")
    return ()


def invention(
    observations: Iterable[Any],
    contracts: Iterable[Mapping[str, Any]],
    *,
    catalogue_markers: Optional[Mapping[str, Any]],
    target_lang: str,
    base_register_whitelist: Optional[Sequence[str]] = None,
    review_decisions: Optional[Mapping[str, Any]] = None,
    profile: Any = None,
) -> Tuple[findings.FindingSet, List[Dict[str, Any]], Dict[str, int]]:
    """Detect catalogue over-application and recurring novel final forms.

    ``catalogue_markers`` and ``review_decisions`` are caller fallbacks only: a
    sealed contract wins and a differing caller value is hard.  The base-register
    whitelist is intentionally target-adapter policy, not character-contract
    policy, so it has no per-character sealed override.
    """
    scope_contracts = _normalise_contracts(contracts)
    result = findings.FindingSet()
    authoritative_markers = _authoritative_catalogue_markers(
        scope_contracts, catalogue_markers, result
    )
    decisions = _authoritative_review_decisions(scope_contracts, review_decisions, result)
    markers = _catalogue_patterns(authoritative_markers)
    if not markers:
        raise GateError("catalogue_markers must not be empty; invention cannot pass without a marker artifact")
    whitelist = _base_whitelist(target_lang, base_register_whitelist)
    normalized = [_observation(item, index) for index, item in enumerate(_as_list(observations, "observations"))]
    if not scope_contracts:
        result.add(
            findings.hard(
                "contracts_empty",
                "no character contracts were supplied; invention enforcement would be inert",
            )
        )
    if not normalized:
        result.add(
            findings.hard(
                "voice_observations_empty",
                "no target observations were supplied; invention cannot pass with no units to check",
            )
        )
    counts = {"eligible": 0, "ineligible": 0, "pending": 0, "total": len(normalized)}
    novel = defaultdict(list)
    failures = set()

    for item in normalized:
        if item["pending"]:
            counts["pending"] += 1
        elif item["eligible"]:
            counts["eligible"] += 1
        else:
            counts["ineligible"] += 1
        contract = scope_contracts.get(item["scope"])
        axes = _contract_axes(contract) if contract is not None else []
        axis = axes[0] if axes else "ending_transform"
        required = _required_patterns(contract, axis) if contract is not None else ()
        marker_matches = {
            marker_id
            for marker_id, marker_patterns in markers.items()
            if _matches_observation(
                item, marker_patterns, axis, profile, target_lang, result, failures
            )
        }
        for marker_id in marker_matches:
            if not required or not _matches_observation(
                item, required, axis, profile, target_lang, result, failures
            ):
                result.add(
                    findings.hard(
                        "voice_invention_catalogue",
                        "catalogue marker %s appears in scope %s without a contract requirement"
                        % (marker_id, item["scope"]),
                        scope=item["scope"],
                        row_key=item["row_key"],
                    )
                )
        try:
            surface = _surface(item, axis, profile, target_lang)
        except (AttributeError, LookupError, TypeError, ValueError):
            _matches_observation(item, (), axis, profile, target_lang, result, failures)
            continue
        form = _final_form(
            item, axis, profile, target_lang, result, failures, surface=surface
        )
        if form is None or _matches(surface, whitelist):
            continue
        # A known catalogue marker is an over-application decision above, not a
        # novel-form guess. This prevents conflicting hard/report classifications.
        if marker_matches:
            continue
        novel[(item["scope"], form)].append(item)

    queue: List[Dict[str, Any]] = []
    for (scope, form), rows in sorted(novel.items()):
        if len(rows) < config.NOVELTY_RECURRENCE_K:
            continue
        key = "%s:%s" % (scope, form)
        queue_entry = {
            "key": key,
            "scope": scope,
            "form": form,
            "count": len(rows),
            "row_keys": [row["row_key"] for row in rows],
            "status": "pending",
        }
        decision = decisions.get(key)
        if isinstance(decision, str) and decision.strip():
            queue_entry["status"] = "triaged"
            queue_entry["decision"] = decision
        queue.append(queue_entry)
        result.add(
            findings.report(
                "voice_invention_novel_recurring",
                "novel sentence-final form %r recurs %d times in scope %s"
                % (form, len(rows), scope),
                scope=scope,
                row_key=rows[0]["row_key"],
            )
        )
        if queue_entry["status"] != "triaged":
            result.add(
                findings.hard(
                    "voice_invention_review_untriaged",
                    "novel-form review queue entry %s is pending; corpus cannot pass with decorative review"
                    % key,
                    scope=scope,
                    row_key=rows[0]["row_key"],
                )
            )
    return result, queue, counts


def _density_rows(
    observations: Sequence[Mapping[str, Any]],
    contracts: Mapping[str, Mapping[str, Any]],
    *,
    source_scene_densities: Mapping[Any, Sequence[float]],
    marker_sets: Optional[Mapping[Any, Sequence[str]]] = None,
    bands: Optional[Mapping[Any, Sequence[float]]] = None,
    profile: Any = None,
    target_lang: str,
) -> findings.FindingSet:
    """Measure canonical target surfaces and classify against sealed bands."""
    result = findings.FindingSet()
    if not isinstance(source_scene_densities, Mapping):
        raise GateError("source_scene_densities must be an artifact mapping")
    failures = set()
    for scope, contract in sorted(contracts.items()):
        axes = _contract_axes(contract)
        if not axes:
            continue
        per_scope = [
            item
            for item in observations
            if item["scope"] == scope and item["eligible"] and not item["pending"]
        ]
        for axis in axes:
            total = len(per_scope)
            if total == 0:
                result.add(
                    findings.hard(
                        "voice_enforcement_inert",
                        "scope %s has a contract axis %s but zero eligible canonical units" % (scope, axis),
                        scope=scope,
                        axis=axis,
                    )
                )
                continue
            key = (scope, axis)
            source_scenes = source_scene_densities.get(
                key, source_scene_densities.get("%s:%s" % key)
            )
            if source_scenes is None:
                result.add(
                    findings.hard(
                        "voice_density_source_artifact_absent",
                        "scope %s axis %s has no source per-scene density artifact" % (scope, axis),
                        scope=scope,
                        axis=axis,
                    )
                )
                continue
            patterns = _sealed_marker_patterns(contract, scope, axis, marker_sets, result)
            matched_rows = [
                _matches_observation(
                    item, patterns, axis, profile, target_lang, result, failures
                )
                for item in per_scope
            ]
            matched = sum(matched_rows)
            measured = contract.get("measured_source_density", {})
            d_src = measured.get(axis) if isinstance(measured, Mapping) else None
            if not isinstance(d_src, (int, float)) or isinstance(d_src, bool):
                result.add(
                    findings.hard(
                        "voice_density_source_artifact_absent",
                        "scope %s axis %s has no measured source density" % (scope, axis),
                        scope=scope,
                        axis=axis,
                    )
                )
                continue
            # Seal-time refusal blocks newly built contracts; this runtime check
            # protects legacy or externally supplied sealed artifacts from silently
            # disabling the LOSS gate before presence comparison can run.
            if float(d_src) == 0.0:
                result.add(
                    findings.hard(
                        "voice_source_density_zero",

                        "scope %s axis %s has a sealed zero source density; the presence-class LOSS comparison is inert"
                        % (scope, axis),
                        scope=scope,
                        axis=axis,
                    )
                )
            try:
                band, unsealed = _sealed_band(
                    contract, scope, axis, per_scope, bands, source_scenes
                )
            except ValueError as exc:
                raise GateError(str(exc)) from exc
            if unsealed:
                result.add(
                    findings.hard(
                        "voice_band_unsealed",
                        "scope %s axis %s used a caller-derived density band because the contract carries none"
                        % (scope, axis),
                        scope=scope,
                        axis=axis,
                    )
                )
            if float(d_src) > 0.0 and matched == 0 and patterns:
                result.add(
                    findings.hard(
                        "voice_required_marker_absent",
                        "scope %s axis %s has zero target marker presence across %d eligible units despite non-zero source density"
                        % (scope, axis, total),
                        scope=scope,
                        axis=axis,
                    )
                )
            by_scene = defaultdict(lambda: [0, 0])
            for item, did_match in zip(per_scope, matched_rows):
                scene = item["scene"]
                if scene is not None:
                    by_scene[scene][1] += 1
                    by_scene[scene][0] += int(did_match)
            target_scene = [hits / units for hits, units in by_scene.values() if units]
            if not target_scene:
                result.add(
                    findings.hard(
                        "voice_density_target_scenes_absent",
                        "scope %s axis %s has no resolved target scenes" % (scope, axis),
                        scope=scope,
                        axis=axis,
                    )
                )
                continue
            mode = contract.get("voice_enforcement_mode")
            if mode not in config.ENFORCEMENT_MODES:
                raise GateError("contract %s has no configured enforcement mode" % scope)
            verdict = density.verdict(
                matched / total,
                band,
                n_units=total,
                n_scenes=len(target_scene),
                dual_standard=bool(contract.get("dual_standard", False)),
                mode=mode,
                matched=matched,
                total=total,
                d_src=float(d_src),
            )
            finding = density.to_finding(verdict, scope=scope, axis=axis)
            if finding is not None:
                result.add(finding)
    return result


def _presence_and_narration(
    observations: Sequence[Mapping[str, Any]],
    contracts: Mapping[str, Mapping[str, Any]],
    *,
    profile: Any,
    target_lang: str,
) -> findings.FindingSet:
    result = findings.FindingSet()
    failures = set()
    for item in observations:
        contract = contracts.get(item["scope"])
        if contract is None:
            continue
        axes = _contract_axes(contract)
        axis = axes[0] if axes else "ending_transform"
        required = _required_patterns(contract, axis)
        forbidden = _forbidden_patterns(contract)
        if forbidden and _matches_observation(
            item, forbidden, axis, profile, target_lang, result, failures
        ):
            result.add(
                findings.hard(
                    "voice_forbidden_marker_present",
                    "scope %s contains a contract-forbidden marker" % item["scope"],
                    scope=item["scope"],
                    row_key=item["row_key"],
                )
            )
        # Both canonical units and residual narration must use the declared
        # measurement surface before applying an anchored marker pattern.
        narration_text = item.get("narration_text")
        if item["attributed_spans"] == 0:
            narration_matches = required and _matches_observation(
                item, required, axis, profile, target_lang, result, failures
            )
        elif isinstance(narration_text, str):
            narration_item = dict(item)
            narration_item["text"] = narration_text
            narration_item["raw_surface"] = True
            narration_matches = required and _matches_observation(
                narration_item, required, axis, profile, target_lang, result, failures
            )
        else:
            narration_matches = False
        if narration_matches:
            if item["attributed_spans"] == 0:
                result.add(
                    findings.hard(
                        "voice-narration-clean",
                        "voice marker appears on a row with zero attributed spans",
                        scope=item["scope"],
                        row_key=item["row_key"],
                    )
                )
            else:
                result.add(
                    findings.report(
                        "voice-narration-clean",
                        "voice marker appears in residual narration beside attributed speech; inspect the boundary",
                        scope=item["scope"],
                        row_key=item["row_key"],
                    )
                )
    return result


def _exclusivity(
    observations: Sequence[Mapping[str, Any]],
    contracts: Mapping[str, Mapping[str, Any]],
    *,
    profile: Any,
    target_lang: str,
) -> findings.FindingSet:
    """Enforce the sealed ``exclusive_with`` declaration."""
    result = findings.FindingSet()
    failures = set()
    for owner, contract in contracts.items():
        rule = contract.get("exclusivity", {})
        if not isinstance(rule, Mapping):
            continue
        protected = rule.get("exclusive_with", ())
        if isinstance(protected, str):
            protected = (protected,)
        if not isinstance(protected, Sequence) or isinstance(protected, (bytes, Mapping)):
            continue
        target_scopes = {scope for scope in protected if isinstance(scope, str)}
        if not target_scopes:
            continue
        axes = _contract_axes(contract)
        axis = axes[0] if axes else "ending_transform"
        required = _required_patterns(contract, axis)
        for item in observations:
            if item["scope"] in target_scopes and _matches_observation(
                item, required, axis, profile, target_lang, result, failures
            ):
                result.add(
                    findings.hard(
                        "voice_exclusivity",
                        "scope %s uses marker contractually exclusive to %s" % (item["scope"], owner),
                        scope=item["scope"],
                        row_key=item["row_key"],
                    )
                )
    return result




def corpus(
    observations: Iterable[Any],
    contracts: Iterable[Mapping[str, Any]],
    *,
    catalogue_markers: Optional[Mapping[str, Any]],
    target_lang: str,
    source_scene_densities: Mapping[Any, Sequence[float]],
    measurable_axes: Mapping[str, Sequence[str]],
    quote_parity_findings: Any,
    ladder_findings: Any,
    marker_sets: Optional[Mapping[Any, Sequence[str]]] = None,
    bands: Optional[Mapping[Any, Sequence[float]]] = None,
    profile: Any = None,
    base_register_whitelist: Optional[Sequence[str]] = None,
    review_decisions: Optional[Mapping[str, Any]] = None,
) -> Tuple[findings.FindingSet, Dict[str, Any]]:
    """Run all character-corpus checks from source artifacts and canonical units.

    Sealed ``marker_sets``, ``catalogue_markers``, and ``review_decisions`` win
    over caller values. ``base_register_whitelist`` belongs to the target-language
    measurement adapter rather than one character contract and is therefore the
    explicit trust boundary left outside the seal.
    """
    normalized = [_observation(item, index) for index, item in enumerate(_as_list(observations, "observations"))]
    scope_contracts = _normalise_contracts(contracts)
    if not isinstance(measurable_axes, Mapping):
        raise GateError("measurable_axes must be a scope-to-axis artifact mapping")
    result = findings.FindingSet()

    for scope, contract in scope_contracts.items():
        axes = _contract_axes(contract)
        pinned_axes = contract.get("measurable_axes")
        pinned_valid = (
            isinstance(pinned_axes, list)
            and bool(pinned_axes)
            and all(isinstance(axis, str) and axis for axis in pinned_axes)
            and len(set(pinned_axes)) == len(pinned_axes)
        )
        declared = measurable_axes.get(scope)
        if declared is None:
            declared_axes = ()
        elif isinstance(declared, (str, bytes, Mapping)):
            raise GateError("measurable_axes[%r] must be an axis sequence" % scope)
        else:
            try:
                declared_axes = tuple(declared)
            except TypeError as exc:
                raise GateError("measurable_axes[%r] must be an axis sequence" % scope) from exc
            if any(not isinstance(axis, str) or not axis for axis in declared_axes):
                raise GateError("measurable_axes[%r] must contain non-empty axis names" % scope)
        if not axes or not declared_axes or not set(axes).issubset(set(declared_axes)):
            result.add(
                findings.hard(
                    "voice_enforcement_inert",
                    "scope %s has a contract but no measurable resolved axis" % scope,
                    scope=scope,
                )
            )
        elif not pinned_valid:
            result.add(
                findings.hard(
                    "voice_enforcement_inert",
                    "scope %s contract has no sealed measurable-axis pin" % scope,
                    scope=scope,
                )
            )
        elif set(declared_axes) != set(pinned_axes):
            result.add(
                findings.hard(
                    "contract_source_measurement_changed",
                    "scope %s runtime measurable axes %s differ from sealed axes %s"
                    % (scope, sorted(declared_axes), sorted(pinned_axes)),
                    scope=scope,
                )
            )
        elif not _required_patterns(contract):
            result.add(
                findings.hard(
                    "voice_enforcement_inert",
                    "scope %s has no required target marker pattern" % scope,
                    scope=scope,
                )
            )

    presence = _presence_and_narration(
        normalized, scope_contracts, profile=profile, target_lang=target_lang
    )
    result.extend(list(presence.hard) + list(presence.reported))
    exclusive = _exclusivity(
        normalized, scope_contracts, profile=profile, target_lang=target_lang
    )
    result.extend(list(exclusive.hard) + list(exclusive.reported))
    density_found = _density_rows(
        normalized,
        scope_contracts,
        source_scene_densities=source_scene_densities,
        marker_sets=marker_sets,
        bands=bands,
        profile=profile,
        target_lang=target_lang,
    )
    result.extend(list(density_found.hard) + list(density_found.reported))
    invention_found, queue, invention_counts = invention(
        normalized,
        scope_contracts.values(),
        catalogue_markers=catalogue_markers,
        target_lang=target_lang,
        base_register_whitelist=base_register_whitelist,
        review_decisions=review_decisions,
        profile=profile,
    )
    result.extend(list(invention_found.hard) + list(invention_found.reported))
    parity = _finding_set(quote_parity_findings, "quote_parity_findings")
    result.extend(list(parity.hard) + list(parity.reported))
    ladder = _finding_set(ladder_findings, "ladder_findings")
    result.extend(list(ladder.hard) + list(ladder.reported))
    return result, {
        "invention_counts": invention_counts,
        "review_queue": queue,
        "density_findings": density_found.to_json(),
    }


def _not_run(gate: str, reason: str) -> findings.Finding:
    """A mandatory gate that did not run is a hard failure, never a clean skip."""
    return findings.hard(
        "gate_not_run",
        "%s was not run: %s" % (gate, reason),
        scope=gate,
    )


def _summary(result: findings.FindingSet, *, ran: bool, skipped_reason: Optional[str]) -> Dict[str, Any]:
    return {
        "hard": len(result.hard),
        "report": len(result.reported),
        "ran": ran,
        "skipped_reason": skipped_reason,
    }


def _call_result(callable_value: Callable[..., Any], *args: Any, label: str) -> Any:
    if not callable(callable_value):
        raise GateError("%s must be an injected callable" % label)
    return callable_value(*args)


def _seal_result(value: Any) -> Tuple[Optional[Mapping[str, Any]], findings.FindingSet]:
    if isinstance(value, tuple) and len(value) == 2:
        sealed, found = value
        if sealed is not None and not isinstance(sealed, Mapping):
            raise GateError("seal_contract returned a non-contract sealed value")
        return sealed, _finding_set(found, "contract seal findings")
    if isinstance(value, Mapping):
        return value, findings.FindingSet()
    raise GateError("seal_contract must return (sealed_contract_or_none, findings)")


def _length_result(value: Any, contract: Mapping[str, Any]) -> findings.FindingSet:
    if isinstance(value, findings.FindingSet) or isinstance(value, findings.Finding):
        return _finding_set(value, "length findings")
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], bool):
        ok, failures = value
        result = findings.FindingSet()
        if not ok:
            values = _as_list(failures, "length failures")
            if not values:
                values = [None]
            for failure in values:
                row_key = failure[0] if isinstance(failure, tuple) and failure else None
                axis = failure[1] if isinstance(failure, tuple) and len(failure) > 1 else None
                result.add(
                    findings.hard(
                        "contract_length_infeasible",
                        "declared longest required realisation cannot fit the layout budget",
                        scope=contract.get("speaker"),
                        row_key=row_key,
                        axis=axis,
                    )
                )
        return result
    raise GateError("length_check must return FindingSet or (bool, failures)")


def _bind_all(source: findings.FindingSet, contract: Mapping[str, Any]) -> findings.FindingSet:
    result = findings.FindingSet()
    result.extend(bind_finding(finding, contract) for finding in list(source.hard) + list(source.reported))
    return result


def run(
    *,
    contracts: Iterable[Mapping[str, Any]],
    attribution_gate: Callable[[], Any],
    seal_contract: Callable[[Mapping[str, Any]], Any],
    length_check: Callable[[Mapping[str, Any]], Any],
    observations: Iterable[Any],
    catalogue_markers: Optional[Mapping[str, Any]],
    target_lang: str,
    source_scene_densities: Mapping[Any, Sequence[float]],
    measurable_axes: Mapping[str, Sequence[str]],
    quote_parity_findings: Any,
    marker_sets: Optional[Mapping[Any, Sequence[str]]] = None,
    bands: Optional[Mapping[Any, Sequence[float]]] = None,
    profile: Any = None,
    base_register_whitelist: Optional[Sequence[str]] = None,
    review_decisions: Optional[Mapping[str, Any]] = None,
    ladder_check: Optional[Callable[[Mapping[str, Any]] , Any]] = None,
    waivers: Iterable[Mapping[str, Any]] = (),
) -> Tuple[findings.FindingSet, Dict[str, Dict[str, Any]]]:
    """Execute gates in the published order and return findings plus every status.

    Sealed gate inputs override caller values; only the target-adapter
    base-register whitelist remains outside character-contract authority.  Caller
    bands are a legacy fallback only and emit ``voice_band_unsealed``.
    """
    contract_rows = _as_list(contracts, "contracts")
    by_gate = {gate: findings.FindingSet() for gate in _GATE_ORDER}
    ran = {gate: False for gate in _GATE_ORDER}
    skipped = {gate: None for gate in _GATE_ORDER}

    corpus_report: Optional[Dict[str, Any]] = None
    current_contract_hashes: Tuple[str, ...] = ()
    # 1. attribution -----------------------------------------------------------
    ran["character-attribution"] = True
    attr_value = _call_result(attribution_gate, label="attribution_gate")
    by_gate["character-attribution"] = _finding_set(attr_value, "attribution findings")
    if isinstance(attr_value, Mapping):
        records = attr_value.get("attributions", attr_value.get("records", ()))
        for record in _as_list(records, "attribution records"):
            evidence_tier = _value(record, "evidence_tier")
            target_tier = _value(record, "target_tier")
            status = _value(record, "status")
            if evidence_tier == "T2" and (target_tier != "T2" or status != "pending"):
                by_gate["character-attribution"].add(
                    findings.hard(
                        "attribution_t2_confirmed",
                        "a T2-only attribution was presented as target-gateable or confirmed",
                        scope=_value(record, "speaker"),
                        row_key=_value(record, "row_key"),
                    )
                )
    if by_gate["character-attribution"].hard:
        reason = "character-attribution emitted hard findings"
        for gate in ("contract-seal", "capacity/length", "character-corpus"):
            skipped[gate] = reason
            by_gate[gate].add(_not_run(gate, reason))
    else:

        # 2. contract seal -----------------------------------------------------
        ran["contract-seal"] = True
        sealed: List[Mapping[str, Any]] = []
        if not contract_rows:
            by_gate["contract-seal"].add(
                findings.hard(
                    "contracts_empty",
                    "no character contracts were supplied; corpus enforcement would be inert",
                )
            )
        for contract in contract_rows:
            if not isinstance(contract, Mapping):
                raise GateError("contracts must contain objects")
            one, found = _seal_result(_call_result(seal_contract, contract, label="seal_contract"))
            bound = _bind_all(found, contract)
            by_gate["contract-seal"].extend(list(bound.hard) + list(bound.reported))
            if one is not None:
                sealed.append(one)
        if by_gate["contract-seal"].hard or len(sealed) != len(contract_rows):
            if not by_gate["contract-seal"].hard:
                by_gate["contract-seal"].add(
                    findings.hard(
                        "contract_seal_missing",
                        "seal callback returned no sealed contract without a finding",
                    )
                )
            reason = "contract-seal did not produce every sealed contract"
            for gate in ("capacity/length", "character-corpus"):
                skipped[gate] = reason
                by_gate[gate].add(_not_run(gate, reason))
        else:
            # 3. capacity/length ------------------------------------------------
            ran["capacity/length"] = True
            for contract in sealed:
                found = _length_result(_call_result(length_check, contract, label="length_check"), contract)
                bound = _bind_all(found, contract)
                by_gate["capacity/length"].extend(list(bound.hard) + list(bound.reported))

            # 4. corpus runs even when capacity had hard findings. -------------
            ran["character-corpus"] = True
            ladder = findings.FindingSet()
            if ladder_check is None:
                for contract in sealed:
                    ladder.add(
                        bind_finding(
                            findings.hard(
                                "contract_voice_drop_ledger_absent",
                                "no voice-drop ledger check was supplied; a ladder under-run could pass silently",
                                scope=contract.get("speaker"),
                            ),
                            contract,
                        )
                    )
            else:
                for contract in sealed:
                    found = _finding_set(_call_result(ladder_check, contract, label="ladder_check"), "ladder findings")
                    bound = _bind_all(found, contract)
                    ladder.extend(list(bound.hard) + list(bound.reported))
            current_contract_hashes = tuple(contract_hash(contract) for contract in sealed)
            corpus_found, corpus_report = corpus(
                observations,
                sealed,
                catalogue_markers=catalogue_markers,
                target_lang=target_lang,
                source_scene_densities=source_scene_densities,
                marker_sets=marker_sets,
                bands=bands,
                profile=profile,
                base_register_whitelist=base_register_whitelist,
                review_decisions=review_decisions,
                quote_parity_findings=quote_parity_findings,
                ladder_findings=ladder,
                measurable_axes=measurable_axes,
            )
            # Corpus findings are bound by scope.  Unscoped parity findings remain
            # non-waivable reports/hard findings rather than receiving a guessed
            # contract binding.
            for finding in list(corpus_found.hard) + list(corpus_found.reported):
                contract = next((item for item in sealed if item.get("speaker") == finding.scope), None)
                by_gate["character-corpus"].add(bind_finding(finding, contract) if contract is not None else finding)

    # Apply only waivers whose code actually arose.  An orphaned/stale waiver is
    # attached to the owning gate where possible; it can never vanish as a no-op.
    waiver_rows = _as_list(waivers, "waivers")
    unmatched = list(waiver_rows)
    for gate in _GATE_ORDER:
        source = by_gate[gate]
        codes = {finding.code for finding in list(source.hard) + list(source.reported)}
        selected = [
            waiver
            for waiver in unmatched
            if isinstance(waiver, Mapping) and set(_waived_codes(waiver)) & codes
        ]

        if not selected:
            continue
        remaining, _applied, rejected = apply_waivers(
            source, selected, current_contract_hashes=current_contract_hashes
        )
        remaining.extend(rejected)
        by_gate[gate] = remaining
        for waiver in selected:
            unmatched.remove(waiver)
    if unmatched:
        # A well-formed waiver for a corrected finding is report-only obsolete;
        # malformed and stale records remain hard through ``apply_waivers``.
        for waiver in unmatched:
            waiver_codes = _waived_codes(waiver)
            target = (
                "character-corpus"
                if "DENSITY_VERDICT" in waiver_codes
                or any(code.startswith("voice_") for code in waiver_codes)
                else "contract-seal"
            )
            _remaining, _applied, waiver_findings = apply_waivers(
                [], [waiver], current_contract_hashes=current_contract_hashes
            )
            by_gate[target].extend(waiver_findings)

    combined = findings.FindingSet()
    for gate in _GATE_ORDER:
        combined.extend(list(by_gate[gate].hard) + list(by_gate[gate].reported))
    summary = {
        gate: _summary(by_gate[gate], ran=ran[gate], skipped_reason=skipped[gate])
        for gate in _GATE_ORDER
    }
    if corpus_report is not None:
        summary["character-corpus"]["invention_counts"] = corpus_report["invention_counts"]
        summary["character-corpus"]["review_queue"] = corpus_report["review_queue"]
    # Stamp each sealed contract's authority onto the gate summary. A
    # `translator_declared` contract asserts only that the translator's own declared
    # rendering was applied faithfully; it makes no claim that the rendering is
    # correct Korean. Without this the two are indistinguishable in a report, which
    # would let the weaker claim be read as the stronger one.
    authorities = {}
    for contract in contract_rows:
        if not isinstance(contract, Mapping):
            continue
        speaker = contract.get("speaker")
        if speaker is not None:
            authorities[speaker] = contract.get("authority")
    summary["contract-seal"]["authorities"] = authorities
    summary["contract-seal"]["declared_without_precedent"] = sorted(
        speaker
        for speaker, authority in authorities.items()
        if authority == config.AUTHORITY_TRANSLATOR_DECLARED
    )
    return combined, summary
