"""Declared speaker attribution and target-side gating eligibility.

The segmentation spine owns the canonical unit: one attributed group for one
``(row, speaker)`` pair.  This module classifies how such a group was
attributed, records target-side confirmation separately from source evidence,
and publishes the eligibility facts that later gates consume.
"""
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from hancharacter import config, findings, segment


T1 = "T1"
T2 = "T2"
T3 = "T3"
_TIERS = (T1, T2, T3)


@dataclass(frozen=True)
class Attribution:
    """One source attribution with its independent target-side eligibility tier."""

    speaker: str
    evidence_tier: str
    target_tier: str
    status: str
    basis: str
    confirmed_by: Optional[str] = None
    confirmed_at: Optional[str] = None

    def __post_init__(self) -> None:
        if self.evidence_tier not in _TIERS:
            raise ValueError("unknown evidence tier %r" % self.evidence_tier)
        if self.target_tier not in _TIERS:
            raise ValueError("unknown target tier %r" % self.target_tier)
        if self.evidence_tier == T2 and (
            self.target_tier != T2 or self.status != "pending"
        ):
            raise ValueError("a T2 source candidate must remain target T2 and pending")
        if self.target_tier == T2 and self.status != "pending":
            raise ValueError("a target T2 attribution must be pending")
        if self.target_tier == T3:
            if self.status != "confirmed":
                raise ValueError("a target T3 attribution must be confirmed")
            if not isinstance(self.confirmed_by, str) or not self.confirmed_by.strip():
                raise ValueError("a target T3 attribution requires confirmed_by")
            if not isinstance(self.confirmed_at, str) or not self.confirmed_at.strip():
                raise ValueError("a target T3 attribution requires confirmed_at")
        elif self.confirmed_by is not None or self.confirmed_at is not None:
            raise ValueError("confirmation identity and time are reserved for target T3")


@dataclass(frozen=True)
class GatedUnit:
    """The deliberately narrow data surface exposed to downstream voice gates.

    There is no tier field here.  ``attributed_for_gating`` constructs these only
    for target T1 or T3 groups, so a caller cannot accidentally treat a pending
    T2 candidate as an attributed unit.
    """

    row_key: str
    speaker: str
    scope: str
    source_text: str
    target_text: str
    scene: Optional[str]
    eligible: bool


@dataclass(frozen=True)
class _Context:
    raw: Any
    row: segment.Row
    basis: str


@dataclass(frozen=True)
class _Analysis:
    contexts: Tuple[_Context, ...]
    states: Tuple[segment.Eligibility, ...]
    duplicate_rows: frozenset
    attributions: Tuple[Attribution, ...]
    attribution_by_group: Dict[Tuple[str, str], Attribution]
    pending_by_row: Dict[str, Attribution]


_REASON_KEYS = (
    config.INELIGIBLE_MIXED_SPAN,
    config.INELIGIBLE_DUPLICATE_SOURCE,
    config.INELIGIBLE_PENDING,
    config.INELIGIBLE_UNDECLARED,
    config.INELIGIBLE_UNSPLITTABLE,
    config.COUNTER_SCOPE_UNREALISED,
)


def _value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


def _as_row(raw: Any, profile) -> segment.Row:
    """Accept normalized rows and mapping-shaped adapter records without guessing."""
    if isinstance(raw, segment.Row):
        row = raw
    else:
        key = _value(raw, "key")
        if not isinstance(key, str) or not key:
            raise ValueError("attribution row requires a non-empty key")
        row = segment.Row(
            key=key,
            evidence=_value(raw, "evidence", ""),
            pivot=_value(raw, "pivot", ""),
            evidence_lang=_value(raw, "evidence_lang", profile.evidence_lang),
            pivot_lang=_value(raw, "pivot_lang", profile.pivot_lang),
            scene=_value(raw, "scene"),
            target=_value(raw, "target"),
        )
    if row.scene is None or (isinstance(row.scene, str) and not row.scene.strip()):
        row = replace(row, scene=segment.resolve_scene(row, profile))
    return row


def _speaker_roles(profile) -> Dict[str, str]:
    roles = profile.speaker_roles
    if not isinstance(roles, Mapping):
        raise ValueError("profile speaker_roles must be a mapping")
    return dict(roles)


def _tag_labels(row: segment.Row, profile) -> List[str]:
    """Read label evidence only; segmentation remains the unit authority."""
    labels = []
    for match in profile.tag_re.finditer(row.evidence):
        label = segment._label_from_tag(match.group(0), profile)
        if label is not None:
            labels.append(label)
    return labels


def _adapter_name(raw: Any) -> Optional[str]:
    value = _value(raw, "adapter", _value(raw, "format"))
    return value.lower() if isinstance(value, str) else None



def _raw_adapter_label(raw: Any, profile, roles: Mapping[str, str]) -> Optional[str]:
    """Return an explicitly structural label; never infer one from ordinary text."""
    adapter = _adapter_name(raw)
    if adapter not in ("srt", "ass", "po", "csv"):
        return None

    if adapter in ("srt", "ass"):
        candidate = _value(raw, "speaker_prefix", _value(raw, "speaker"))
        if not isinstance(candidate, str):
            return None
        candidate = candidate.strip()
        if not candidate:
            return None
        if candidate in roles:
            return candidate
        for separator in (":", "-", "—"):
            if separator in candidate:
                label = candidate.split(separator, 1)[0].strip()
                return label or None
        # ASS Name fields are separate structural columns, not prose. Preserve an
        # unknown value so lint_speaker_roles can hard-fail the missing declaration.
        return candidate

    if adapter == "po":
        candidate = _value(raw, "msgctxt")
        if not isinstance(candidate, str):
            return None
        if candidate.startswith("speaker:"):
            candidate = candidate[len("speaker:"):]
        return candidate.strip() or None

    # CSV attribution is structural only when the adapter identifies the declared
    # speaker column.  This local fallback is intentionally strict until the
    # profile/schema owner exposes that declaration in the closed profile shape.
    column = _value(raw, "speaker_column")
    candidate = _value(raw, "csv_speaker", _value(raw, "speaker"))
    profile_data = getattr(profile, "data", {})
    declared_column = (
        profile_data.get("csv_speaker_column")
        if isinstance(profile_data, Mapping)
        else None
    )
    if isinstance(declared_column, str) and column == declared_column and isinstance(candidate, str):
        return candidate
    return None


def _present_labels(raw: Any, row: segment.Row, profile, roles: Mapping[str, str]) -> List[str]:
    labels = _tag_labels(row, profile)
    label = _raw_adapter_label(raw, profile, roles)
    if label is not None:
        labels.append(label)
    return labels


def _structural_context(raw: Any, profile) -> _Context:
    """Map approved adapter structure into the spine without making a second unit model."""
    row = _as_row(raw, profile)
    state = segment.eligibility(row, profile)
    if state.scopes or state.reasons:
        return _Context(raw=raw, row=row, basis="declared speaker_roles source markup")

    roles = _speaker_roles(profile)
    label = _raw_adapter_label(raw, profile, roles)
    if label is None or roles.get(label) != config.ROLE_SPEAKER:
        return _Context(raw=raw, row=row, basis="no declared structural speaker evidence")

    # Feed the adapter's declared structure through the existing segmenter rather
    # than creating a format-specific unit.  An unclosed source role is valid here:
    # the group ends at the end of this row, exactly as an SRT/ASS/PO/CSV record does.
    synthetic = replace(row, evidence="<color=%s>%s" % (label, row.evidence))
    return _Context(
        raw=raw,
        row=synthetic,
        basis="declared %s speaker field %r" % (_adapter_name(raw), label),
    )


def _candidate_speaker(raw: Any) -> Optional[str]:
    """Read an explicitly marked heuristic candidate, never an incidental label."""
    declared_tier = _value(raw, "attribution_tier", _value(raw, "evidence_tier"))
    attribution = _value(raw, "attribution")
    if isinstance(attribution, Attribution):
        if attribution.evidence_tier == T2:
            return attribution.speaker
    elif isinstance(attribution, Mapping):
        if attribution.get("evidence_tier") == T2:
            candidate = attribution.get("speaker")
            return candidate if isinstance(candidate, str) else None
    if declared_tier != T2:
        return None
    candidate = _value(raw, "candidate_speaker", _value(raw, "speaker_candidate"))
    return candidate if isinstance(candidate, str) and candidate else None


def _confirmation_index(confirmations: Iterable[Any]) -> Dict[Tuple[str, str], Dict[str, str]]:
    indexed: Dict[Tuple[str, str], Dict[str, str]] = {}
    for confirmation in confirmations:
        row_key = _value(confirmation, "row_key")
        speaker = _value(confirmation, "speaker")
        confirmed_by = _value(confirmation, "confirmed_by")
        confirmed_at = _value(confirmation, "confirmed_at")
        if not all(isinstance(value, str) and value.strip() for value in (row_key, speaker, confirmed_by, confirmed_at)):
            raise ValueError(
                "attribution confirmation requires row_key, speaker, confirmed_by, and confirmed_at"
            )
        key = (row_key, speaker)
        value = {"confirmed_by": confirmed_by, "confirmed_at": confirmed_at}
        existing = indexed.get(key)
        if existing is not None and existing != value:
            raise ValueError("conflicting confirmations for %r" % (key,))
        indexed[key] = value
    return indexed


def _duplicate_rows(contexts: Sequence[_Context]) -> frozenset:
    by_source: Dict[str, List[str]] = {}
    for context in contexts:
        by_source.setdefault(context.row.evidence, []).append(context.row.key)
    return frozenset(
        row_key for row_keys in by_source.values() if len(row_keys) > 1 for row_key in row_keys
    )


def _analyse(rows: Iterable[Any], profile, confirmations: Iterable[Any]) -> _Analysis:
    contexts = tuple(_structural_context(raw, profile) for raw in rows)
    duplicates = _duplicate_rows(contexts)
    confirmation_index = _confirmation_index(confirmations)
    states = tuple(
        segment.eligibility(
            context.row,
            profile,
            duplicate_source=context.row.key in duplicates,
        )
        for context in contexts
    )
    attributed: List[Attribution] = []
    by_group: Dict[Tuple[str, str], Attribution] = {}
    pending_by_row: Dict[str, Attribution] = {}
    roles = _speaker_roles(profile)

    for context, state in zip(contexts, states):
        if state.reasons:
            continue
        if len(state.scopes) == 1:
            speaker = state.scopes[0]
            confirmation = confirmation_index.get((context.row.key, speaker))
            if confirmation is None:
                attribution = Attribution(
                    speaker=speaker,
                    evidence_tier=T1,
                    target_tier=T1,
                    status="attributed",
                    basis="%s for %r" % (context.basis, speaker),
                )
            else:
                attribution = Attribution(
                    speaker=speaker,
                    evidence_tier=T1,
                    target_tier=T3,
                    status="confirmed",
                    basis="%s for %r; target attribution human-confirmed" % (context.basis, speaker),
                    confirmed_by=confirmation["confirmed_by"],
                    confirmed_at=confirmation["confirmed_at"],
                )
            attributed.append(attribution)
            by_group[(context.row.key, speaker)] = attribution
            continue

        candidate = _candidate_speaker(context.raw)
        if candidate is not None:
            # Candidate labels may be known declarations, but that does not turn an
            # heuristic into a structural fact.  A candidate for an unknown label is
            # likewise kept pending and never becomes a scope.
            role = roles.get(candidate)
            basis = "heuristic candidate for %r" % candidate
            if role is not None:
                basis += " (declared role %r is not attribution evidence)" % role
            attribution = Attribution(
                speaker=candidate,
                evidence_tier=T2,
                target_tier=T2,
                status="pending",
                basis=basis,
            )
            attributed.append(attribution)
            pending_by_row[context.row.key] = attribution

    return _Analysis(
        contexts=contexts,
        states=states,
        duplicate_rows=duplicates,
        attributions=tuple(attributed),
        attribution_by_group=by_group,
        pending_by_row=pending_by_row,
    )


def attributions(rows: Iterable[Any], profile, *, confirmations: Iterable[Any] = ()) -> Tuple[Attribution, ...]:
    """Return declared and pending attributions without exposing them to a gate."""
    return _analyse(rows, profile, confirmations).attributions


def lint_speaker_roles(rows: Iterable[Any], profile) -> List[findings.Finding]:
    """Compare declared role labels with structural labels actually present."""
    raw_rows = tuple(rows)
    roles = _speaker_roles(profile)
    present = set()
    for raw in raw_rows:
        row = _as_row(raw, profile)
        present.update(_present_labels(raw, row, profile, roles))

    out: List[findings.Finding] = []
    for label in sorted(present - set(roles)):
        out.append(
            findings.hard(
                "attribution_undeclared_label",
                "row markup contains label %r, but speaker_roles does not declare it; "
                "it cannot be attributed" % label,
                scope=label,
            )
        )
    for label in sorted(set(roles) - present):
        out.append(
            findings.report(
                "attribution_dead_speaker_role",
                "speaker_roles declares label %r, but it never appears in these rows" % label,
                scope=label,
            )
        )
    return out


def _eligibility_counts() -> Dict[str, int]:
    return {key: 0 for key in _REASON_KEYS}


def _gated_units(analysis: _Analysis, profile) -> Tuple[GatedUnit, ...]:
    """Build only canonical source/pivot groups; no T2 record reaches this boundary."""
    units: List[GatedUnit] = []
    for context, state in zip(analysis.contexts, analysis.states):
        if state.reasons or len(state.scopes) != 1:
            continue
        scope = state.scopes[0]
        attribution = analysis.attribution_by_group.get((context.row.key, scope))
        if attribution is None or attribution.target_tier not in (T1, T3):
            continue
        evidence = segment.group_units(segment.evidence_units(context.row, profile))
        pivot = segment.group_units(segment.side_units(context.row, profile, "pivot"))
        target = segment.group_units(segment.side_units(context.row, profile, "target"))
        key = (context.row.key, scope)
        if key not in evidence or key not in pivot:
            continue
        target_unit = target.get(key)
        units.append(
            GatedUnit(
                row_key=context.row.key,
                speaker=scope,
                scope=scope,
                source_text=evidence[key].reading,
                target_text="" if target_unit is None else target_unit.reading,
                scene=evidence[key].scene,
                eligible=True,
            )
        )
    return tuple(units)


def attributed_for_gating(
    rows: Iterable[Any], profile, *, confirmations: Iterable[Any] = ()
) -> Tuple[GatedUnit, ...]:
    """Expose target T1/T3 canonical groups and nothing pending to downstream gates."""
    return _gated_units(_analyse(rows, profile, confirmations), profile)


def eligibility(rows: Iterable[Any], profile) -> Dict[str, int]:
    """Publish every source eligibility reason, including checked-zero reasons."""
    analysis = _analyse(rows, profile, ())
    counts = _eligibility_counts()
    for state in analysis.states:
        for reason in state.reasons:
            counts[reason] += 1
    for row_key in analysis.pending_by_row:
        counts[config.INELIGIBLE_PENDING] += 1
    # The spine alone owns whether a source group was realised by the pivot.
    spine = segment.segment_report([context.row for context in analysis.contexts], profile)
    counts[config.COUNTER_SCOPE_UNREALISED] = spine["counters"][config.COUNTER_SCOPE_UNREALISED]
    return counts


def _scope_tier(tiers: Sequence[str]) -> str:
    if not tiers:
        return "unattributed"
    unique = sorted(set(tiers))
    return unique[0] if len(unique) == 1 else "mixed"


def attribution_report(
    rows: Iterable[Any], profile, *, confirmations: Iterable[Any] = ()
) -> Dict[str, object]:
    """Return the serialisable attribution facts that later phases must not rewrite."""
    raw_rows = tuple(rows)
    analysis = _analyse(raw_rows, profile, confirmations)
    spine = segment.segment_report([context.row for context in analysis.contexts], profile)
    counts = _eligibility_counts()
    report_findings: List[findings.Finding] = list(lint_speaker_roles(raw_rows, profile))

    for context, state in zip(analysis.contexts, analysis.states):
        for reason in state.reasons:
            counts[reason] += 1
        if context.row.key in analysis.duplicate_rows:
            report_findings.append(
                findings.report(
                    "attribution_duplicate_source_deferred",
                    "host TM keys on the source (evidence) string, so two rows sharing it "
                    "cannot be attributed apart; voice measurement is deferred",
                    row_key=context.row.key,
                )
            )
    for row_key, attribution in sorted(analysis.pending_by_row.items()):
        counts[config.INELIGIBLE_PENDING] += 1
        report_findings.append(
            findings.report(
                "attribution_t2_pending",
                "row has a T2 heuristic candidate for %r and remains pending; it cannot gate"
                % attribution.speaker,
                row_key=row_key,
                scope=attribution.speaker,
            )
        )

    counts[config.COUNTER_SCOPE_UNREALISED] = spine["counters"][config.COUNTER_SCOPE_UNREALISED]
    if not raw_rows:
        report_findings.append(
            findings.hard(
                "attribution_rows_empty",
                "no rows were supplied; attribution cannot pass with no units to check",
            )
        )

    scope_tiers: Dict[str, List[str]] = {
        scope: [] for scope in spine["scopes"]
    }
    by_tier = {tier: 0 for tier in _TIERS}
    for unit in _gated_units(analysis, profile):
        attribution = analysis.attribution_by_group[(unit.row_key, unit.speaker)]
        by_tier[attribution.target_tier] += 1
        scope_tiers.setdefault(unit.speaker, []).append(attribution.target_tier)
    # T2 candidates are visible in counts, but are not eligible units and do not
    # enter either scopes.units or the denominator used by t1_rate.
    by_tier[T2] += len(analysis.pending_by_row)
    for row_key, attribution in analysis.pending_by_row.items():
        scope_tiers.setdefault(attribution.speaker, []).append(T2)

    scopes = {
        scope: {
            "units": len(scope_tiers.get(scope, [])) - scope_tiers.get(scope, []).count(T2),
            "target_tier": _scope_tier(scope_tiers.get(scope, [])),
        }
        for scope in sorted(scope_tiers)
    }
    report_findings.extend(
        findings.Finding(**entry) for entry in spine["findings"]
    )
    return {
        "rows": len(raw_rows),
        "by_tier": by_tier,
        "eligibility": counts,
        "scopes": scopes,
        "findings": [finding.to_json() for finding in report_findings],
    }


def t1_rate(report: Mapping[str, Any]) -> Optional[float]:
    """Return T1's share of eligible (T1/T3) units, or ``None`` when none exist."""
    by_tier = report.get("by_tier")
    if not isinstance(by_tier, Mapping):
        raise ValueError("attribution report is missing by_tier")
    try:
        t1 = by_tier[T1]
        t3 = by_tier[T3]
    except KeyError as exc:
        raise ValueError("attribution report is missing tier %s" % exc.args[0]) from exc
    if not isinstance(t1, int) or not isinstance(t3, int) or t1 < 0 or t3 < 0:
        raise ValueError("attribution report tiers must be non-negative integers")
    denominator = t1 + t3
    return None if denominator == 0 else t1 / denominator
