"""Segmentation spine for character-attributed speech measurements.

A gating unit is one attributed group for one ``(row_key, speaker)`` pair:
all of that speaker's colour-run spans in the evidence collapse to one unit,
and all matching quoted speech spans on a side collapse to at most one unit.
The group retains its original spans for report-only per-span counts.  A
source group with no pivot speech group is the explicit 1:0 loss case,
published through ``config.COUNTER_SCOPE_UNREALISED`` rather than forced into
an equality assertion.

Quoted spans are paired across tags. H1 classifies a declared speech-delimiter
pair as speech only when its opener is the first non-whitespace content in a
text stretch split by non-layout markup; a pair opened later in that stretch is
a term. Delimiters explicitly declared as term delimiters are terms as well.
Consequently a mid-stretch quoted title is excluded before quote parity is
counted. The quote span itself is the scope extent, so attribution text in the
same stretch is not included in a speaker group.

For a single-standard work, declared colour runs in the same source text make
scope assignment exact, independent of intervening control markup. That
exactness is why downstream density gating may be hard only for that case;
dual-standard measurements retain the same segmentation but are report-only.
"""

from collections.abc import Mapping

import dataclasses
from dataclasses import dataclass, field
import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

from hancharacter import config

from hancharacter import findings


@dataclass
class Row:
    """Normalized dialogue data kept independent from any host adapter."""

    key: str
    evidence: str
    pivot: str
    evidence_lang: str = ""
    pivot_lang: str = ""
    scene: Optional[str] = None
    target: Optional[str] = None


@dataclass
class Span:
    """A raw-payload extent; offsets always refer to the unstripped payload."""

    start: int
    end: int
    text: str
    kind: str
    scope: Optional[str] = None


@dataclass
class Unit:
    """Keeps source provenance so report-only counts can audit a grouped gate unit."""

    row_key: str
    scope: str
    side: str
    base: str
    reading: str
    scene: Optional[str] = None
    spans: List[Span] = field(default_factory=list)


@dataclass
class Eligibility:
    """Keeps blockers beside scopes so callers cannot silently gate ambiguous text."""

    eligible: bool
    reasons: List[str]
    scopes: List[str]


_COLOR_ATTRIBUTE_RE = re.compile(
    r"(?:^|\s)[\w:-]*colou?r[\w:-]*\s*=\s*"
    r"(?:\"([^\"]*)\"|'([^']*)'|([^\s/>]+))",
    re.IGNORECASE,
)


def strip_tags(s: str, profile, *, keep_ruby_reading: bool) -> str:
    """Keep ruby surfaces before removing markup so lexical axes remain reproducible."""

    def replace_ruby(match):
        base = match.group("base")
        if keep_ruby_reading:
            return base + match.group("reading")
        return base

    return profile.tag_re.sub("", profile.ruby_re.sub(replace_ruby, s))


def stretches(s: str, profile) -> List[Span]:
    """H1 splits text stretches only at non-layout markup; units ignore them."""
    result = []
    start = 0
    ignored_tags = set(profile.layout_tags)
    ignored_tags.update(profile.data.get("page_tags", ()))
    for match in profile.tag_re.finditer(s):
        if match.group(0) in ignored_tags:
            continue
        if start < match.start():
            result.append(
                Span(
                    start=start,
                    end=match.start(),
                    text=s[start:match.start()],
                    kind="narration",
                    scope=None,
                )
            )
        start = match.end()
    if start < len(s):
        result.append(
            Span(start=start, end=len(s), text=s[start:], kind="narration", scope=None)
        )
    return result


def _visible_text(s: str, profile) -> Tuple[str, List[int]]:
    """Cross-tag pairing needs raw offsets after markup is removed from delimiter search."""

    chunks = []
    offsets = []
    start = 0
    for match in profile.tag_re.finditer(s):
        if start < match.start():
            chunks.append(s[start:match.start()])
            offsets.extend(range(start, match.start()))
        start = match.end()
    if start < len(s):
        chunks.append(s[start:])
        offsets.extend(range(start, len(s)))
    return "".join(chunks), offsets


def _delimiter_pairs(
    visible: str,
    opener: str,
    closer: str,
    implicit_closers: Tuple[int, ...] = (),
) -> Tuple[List[Tuple[int, int, int]], bool]:
    """Pair delimiters, including declared role-change closes when configured."""
    pairs = []
    malformed = False
    if opener == closer:
        cursor = 0
        role_index = 0
        while True:
            opening = visible.find(opener, cursor)
            if opening < 0:
                break
            # A role tag at the same visible offset precedes an opener after that
            # tag, so it cannot close the new quote.
            while (
                role_index < len(implicit_closers)
                and implicit_closers[role_index] <= opening
            ):
                role_index += 1
            closing = visible.find(closer, opening + len(opener))
            role_closing = (
                implicit_closers[role_index]
                if role_index < len(implicit_closers)
                else None
            )
            if role_closing is not None and (
                closing < 0 or role_closing < closing
            ):
                pairs.append((opening, role_closing, 0))
                role_index += 1
                cursor = role_closing
                continue
            if closing < 0:
                malformed = True
                break
            pairs.append((opening, closing, len(closer)))
            cursor = closing + len(closer)
        return pairs, malformed

    stack = []
    cursor = 0
    role_index = 0
    while cursor < len(visible):
        while (
            role_index < len(implicit_closers)
            and implicit_closers[role_index] < cursor
        ):
            role_index += 1
        opening = visible.find(opener, cursor)
        closing = visible.find(closer, cursor)
        role_closing = (
            implicit_closers[role_index]
            if role_index < len(implicit_closers)
            else -1
        )
        if opening < 0 and closing < 0 and role_closing < 0:
            break
        next_delimiter = min(
            value for value in (opening, closing) if value >= 0
        ) if opening >= 0 or closing >= 0 else -1
        if role_closing >= 0 and (
            next_delimiter < 0 or role_closing <= next_delimiter
        ):
            if stack:
                pairs.append((stack.pop(), role_closing, 0))
            role_index += 1
            continue
        if opening >= 0 and (closing < 0 or opening < closing):
            stack.append(opening)
            cursor = opening + len(opener)
            continue
        if not stack:
            malformed = True
        else:
            pairs.append((stack.pop(), closing, len(closer)))
        cursor = closing + len(closer)
    return pairs, malformed or bool(stack)


def _stretch_initial(s: str, profile, opener_at: int) -> bool:
    """Apply H1 after pairing, not before, so markup cannot break a quote pair."""
    for stretch in stretches(s, profile):
        if stretch.start <= opener_at < stretch.end:
            prefix = strip_tags(
                s[stretch.start:opener_at], profile, keep_ruby_reading=False
            )
            return not prefix.strip()
    return False


def _role_closer_positions(s: str, profile) -> Tuple[int, ...]:
    """Return visible offsets of tags declared to close a pending speech opener."""
    positions = []
    visible_offset = 0
    source_start = 0
    for match in profile.tag_re.finditer(s):
        visible_offset += match.start() - source_start
        label = _label_from_tag(match.group(0), profile)
        if label in profile.speaker_roles:
            positions.append(visible_offset)
        source_start = match.end()
    return tuple(positions)


def _quote_scan(s: str, profile, lang: str) -> Tuple[List[Span], bool]:
    """Keeping pairing and H1 together prevents callers from counting raw quote marks."""

    declared = profile.delimiters(lang)
    if declared is None:
        raise ValueError("missing delimiter declaration for language %r" % lang)
    if not isinstance(declared, Mapping):
        raise ValueError("delimiter declaration for language %r must be an object" % lang)
    # Stretch-initiality is a positional tie-breaker for a language whose speech
    # and terminology share one delimiter (English uses `"` for both), so a
    # mid-stretch quote reads as terminology. A language that gives terminology its
    # own delimiters has already disambiguated by declaration, and applying the
    # positional rule there would misread a second consecutive utterance as a term
    # and hide an invented line. Which behaviour applies is declared, not inferred.
    positional = declared.get("speech_is_positional", True)
    closes_on_role_change = declared.get("closes_on_role_change", False)
    if not isinstance(closes_on_role_change, bool):
        raise ValueError(
            "delimiter declaration for language %r has non-boolean "
            "closes_on_role_change %r" % (lang, closes_on_role_change)
        )
    if not isinstance(positional, bool):
        raise ValueError(
            "delimiter declaration for language %r has non-boolean "
            "speech_is_positional %r" % (lang, positional)
        )
    visible, offsets = _visible_text(s, profile)
    implicit_closers = (
        _role_closer_positions(s, profile) if closes_on_role_change else ()
    )
    spans = []
    malformed = False
    seen = set()

    for declared_kind in ("speech", "term"):
        pairs = declared.get(declared_kind)
        if not isinstance(pairs, (list, tuple)):
            raise ValueError(
                "delimiter declaration for language %r has invalid %s pairs %r"
                % (lang, declared_kind, pairs)
            )
        if declared_kind == "speech" and not pairs:
            # An empty speech list would return zero spans without complaining,
            # which makes quote parity compare 0 to 0 and empties every density
            # denominator while the run still exits clean. That silent-pass shape
            # is the single failure this module exists to make impossible.
            raise ValueError(
                "delimiter declaration for language %r declares no speech pairs; "
                "a zero-span result would make the parity gate unreachable" % lang
            )
        for pair in pairs:
            if (
                not isinstance(pair, (list, tuple))
                or len(pair) != 2
                or any(not isinstance(delimiter, str) or not delimiter for delimiter in pair)
            ):
                raise ValueError("invalid delimiter pair for language %r: %r" % (lang, pair))

            opener, closer = pair
            matches, pair_malformed = _delimiter_pairs(
                visible, opener, closer, implicit_closers
            )
            malformed = malformed or pair_malformed
            for opening, closing, closing_length in matches:
                raw_start = offsets[opening]
                if closing_length:
                    raw_end = offsets[closing + closing_length - 1] + 1
                elif closing < len(offsets):
                    # The tag itself is stripped from the unit; ending at the first
                    # following visible character keeps its implicit close audible
                    # without leaking the next role's text into this span.
                    raw_end = offsets[closing]
                else:
                    raw_end = len(s)
                extent = (raw_start, raw_end)
                if extent in seen:
                    continue
                seen.add(extent)
                if declared_kind == "term":
                    kind = "term"
                elif not positional or _stretch_initial(s, profile, raw_start):
                    kind = "speech"
                else:
                    kind = "term"
                spans.append(
                    Span(
                        start=raw_start,
                        end=raw_end,
                        text=s[raw_start:raw_end],
                        kind=kind,
                        scope=None,
                    )
                )
    spans.sort(key=lambda span: (span.start, span.end))
    return spans, malformed


def speech_spans(s: str, profile, lang: str) -> List[Span]:
    """Expose the shared H1 classifier so every caller excludes terms consistently."""

    return _quote_scan(s, profile, lang)[0]


def _label_from_tag(tag: str, profile, *, want_colour: bool = True) -> Optional[str]:
    """Unknown colour values must remain visible so attribution cannot be guessed.

    `want_colour=False` asks only for a bare tag name (`<player>`) and deliberately
    ignores a colour attribute (`<color=keyword1>`). The distinction matters for
    target visibility: a runtime substitution renders glyphs, whereas a colour tag
    renders nothing on its own even when its declared label carries a glyph-bearing
    role. Conflating the two let a target reduced to colour markup read as non-empty,
    which silenced the spine's only hard gate.
    """

    payload = tag[1:-1] if tag.startswith("<") and tag.endswith(">") else tag
    colour_match = _COLOR_ATTRIBUTE_RE.search(payload)
    if colour_match:
        if not want_colour:
            return None
        label = next(value for value in colour_match.groups() if value is not None)
        return label

    for label in profile.speaker_roles:
        boundary = r"(?<![0-9A-Za-z_.-])%s(?![0-9A-Za-z_.-])" % re.escape(label)
        if re.search(boundary, payload):
            return label
    return None



def _target_visible_text(target: str, profile) -> str:
    """Keep rendered term substitutions visible only for the emptied-target check."""
    def replace_ruby(match):
        return match.group("base")

    def replace_tag(match):
        # A term label denotes a runtime substitution that renders glyphs. A colour
        # tag renders nothing on its own, so it is never content here even when its
        # declared label happens to carry a glyph-bearing role.
        label = _label_from_tag(match.group(0), profile, want_colour=False)
        return "x" if profile.role(label) == config.ROLE_TERM else ""

    visible = profile.ruby_re.sub(replace_ruby, target)
    visible = profile.tag_re.sub(replace_tag, visible)
    visible = "".join(
        ch
        for ch in visible
        if unicodedata.category(ch) not in config.TARGET_VISIBILITY_BLANK_CATEGORIES
    )
    return visible.strip()

def _evidence_runs(s: str, profile) -> Tuple[List[Span], List[str], bool]:
    """Declared roles are the sole evidence authority, preserving unknown-label evidence."""

    spans = []
    scopes = []
    undeclared = False
    active_scope = None
    active_start = None

    for match in profile.tag_re.finditer(s):
        label = _label_from_tag(match.group(0), profile)
        if label is None:
            continue
        if label not in profile.speaker_roles:
            undeclared = True
        next_scope = label if profile.is_speaker(label) else None
        if active_scope == next_scope and label in profile.speaker_roles:
            continue
        if active_scope is not None and active_start is not None and active_start < match.start():
            spans.append(
                Span(
                    start=active_start,
                    end=match.start(),
                    text=s[active_start:match.start()],
                    kind="speech",
                    scope=active_scope,
                )
            )
        active_scope = next_scope
        active_start = match.end() if next_scope is not None else None
        if next_scope is not None and next_scope not in scopes:
            scopes.append(next_scope)

    if active_scope is not None and active_start is not None and active_start < len(s):
        spans.append(
            Span(
                start=active_start,
                end=len(s),
                text=s[active_start:],
                kind="speech",
                scope=active_scope,
            )
        )
    return spans, scopes, undeclared


def _unit_from_span(row: Row, side: str, scope: str, span: Span, profile) -> Unit:
    return Unit(
        row_key=row.key,
        scope=scope,
        side=side,
        scene=row.scene,
        base=strip_tags(span.text, profile, keep_ruby_reading=False),
        reading=strip_tags(span.text, profile, keep_ruby_reading=True),
        spans=[span],
    )


def evidence_units(row: Row, profile) -> List[Unit]:
    """Evidence starts with declared colour spans so non-speaker markup cannot attribute text."""

    spans, _, _ = _evidence_runs(row.evidence, profile)
    return [
        _unit_from_span(row, "evidence", span.scope, span, profile)
        for span in spans
        if span.scope is not None
    ]


def side_units(row: Row, profile, side: str) -> List[Unit]:
    """A side inherits one unambiguous source scope so narration cannot enter a group."""

    if side == "pivot":
        payload = row.pivot
        lang = row.pivot_lang or profile.pivot_lang
    elif side == "target":
        if row.target is None:
            return []
        payload = row.target
        lang = profile.target_lang
    else:
        raise ValueError("side must be 'pivot' or 'target', got %r" % side)

    _, scopes, undeclared = _evidence_runs(row.evidence, profile)
    if undeclared or len(scopes) != 1:
        return []
    scope = scopes[0]
    return [
        _unit_from_span(row, side, scope, span, profile)
        for span in speech_spans(payload, profile, lang)
        if span.kind == "speech"
    ]


def group_units(units: Iterable[Unit]) -> Dict[Tuple[str, str], Unit]:
    """One row/speaker group prevents per-span layout from changing the gate denominator."""

    grouped = {}
    for unit in units:
        key = (unit.row_key, unit.scope)
        grouped.setdefault(key, []).append(unit)

    result = {}
    for key, members in grouped.items():
        sides = {member.side for member in members}
        if len(sides) != 1:
            raise ValueError("cannot group units from different sides for %r" % (key,))
        members.sort(
            key=lambda member: min(
                (span.start for span in member.spans), default=-1
            )
        )
        spans = []
        for member in members:
            spans.extend(member.spans)
        spans.sort(key=lambda span: (span.start, span.end))
        result[key] = Unit(
            row_key=key[0],
            scope=key[1],
            side=members[0].side,
            scene=members[0].scene,
            base=" ".join(member.base for member in members),
            reading=" ".join(member.reading for member in members),
            spans=spans,
        )
    return result


def _has_unpairable_quotes(s: str, profile, lang: str) -> bool:
    """A true zero speech side is a loss; only an orphaned delimiter is ambiguous."""

    _, malformed = _quote_scan(s, profile, lang)
    return malformed


def eligibility(row: Row, profile, *, duplicate_source: bool = False) -> Eligibility:
    """Keep narration clean while publishing every attribution ambiguity to callers."""

    _, scopes, undeclared = _evidence_runs(row.evidence, profile)
    reasons = []
    if undeclared:
        reasons.append(config.INELIGIBLE_UNDECLARED)
    if len(scopes) >= 2:
        reasons.append(config.INELIGIBLE_MIXED_SPAN)
    if duplicate_source:
        reasons.append(config.INELIGIBLE_DUPLICATE_SOURCE)
    if scopes:
        pivot_lang = row.pivot_lang or profile.pivot_lang
        unsplittable = _has_unpairable_quotes(row.pivot, profile, pivot_lang)
        if row.target is not None:
            unsplittable = unsplittable or _has_unpairable_quotes(
                row.target, profile, profile.target_lang
            )
        if unsplittable:
            reasons.append(config.INELIGIBLE_UNSPLITTABLE)
    return Eligibility(eligible=not reasons, reasons=reasons, scopes=scopes)


def quote_parity(row: Row, profile):
    """Fail an emptied utterance; report every count difference.

    Speech-span counts are not comparable across sides as a hard gate. Whether a
    quoted span counts as speech depends on the per-language `speech_is_positional`
    declaration, and the shipped profile deliberately declares the pivot positional
    and the target not — so an attribution-first pivot (`He said, "A."`, whose quote
    is mid-stretch and therefore classified as terminology) counts zero speech spans
    against a faithful target's one. Making that hard fails correct work.

    Two further reasons the count comparison cannot carry a hard verdict:
    dropping quotation marks is a typographic choice, not voice loss; and on an
    eligible row the evidence side always has a speaker scope, so a pivot with no
    quoted span means the *pivot* dropped a line the source has — which is already
    published as `voice_scope_unrealised`, and a target restoring it is faithful to
    the source. Detecting a fabricated voice is the job of the catalogue-anchored
    invention scan, not of a span count.

    What remains unambiguous is a target with no visible text at all: the utterance
    was translated to nothing.
    """
    if row.target is None:
        return None
    state = eligibility(row, profile)
    if not state.eligible or not state.scopes:
        return None
    pivot_lang = row.pivot_lang or profile.pivot_lang
    pivot_count = sum(
        span.kind == "speech" for span in speech_spans(row.pivot, profile, pivot_lang)
    )
    target_visible = _target_visible_text(row.target, profile)
    if pivot_count and not target_visible:
        return findings.hard(
            "voice-quote-parity",
            "pivot carries %d speech span(s) but the target has no visible text: "
            "the utterance was translated to nothing" % pivot_count,
            row_key=row.key,
            scope=state.scopes[0],
        )
    target_count = sum(
        span.kind == "speech"
        for span in speech_spans(row.target, profile, profile.target_lang)
    )
    if pivot_count == target_count:
        return None
    return findings.report(
        "voice-quote-parity",
        "pivot has %d speech spans but target has %d; a split or merged quotation, a "
        "typographic choice, or a line the pivot dropped are all legitimate causes"
        % (pivot_count, target_count),
        row_key=row.key,
        scope=state.scopes[0],
    )


def _ineligibility_counts() -> Dict[str, int]:
    return {
        config.INELIGIBLE_MIXED_SPAN: 0,
        config.INELIGIBLE_DUPLICATE_SOURCE: 0,
        config.INELIGIBLE_PENDING: 0,
        config.INELIGIBLE_UNDECLARED: 0,
        config.INELIGIBLE_UNSPLITTABLE: 0,
    }


def resolve_scene(row: Row, profile) -> Optional[str]:
    """Resolve a row's scene from the declared key rule, then the row's own field.

    The rule lives here rather than in a caller so every entry point resolves scenes
    identically. While it lived only in the CLI, calling the spine directly produced
    `scene=None`, every unit fell out of the per-scene band, and the density verdict
    was silently capped at `report` by under-sampling.
    """
    pattern = profile.scene_pattern
    if pattern is not None:
        for key in (row.key, row.key.rsplit("/", 1)[-1]):
            match = pattern.search(key)
            if match is not None:
                return match.group(1)
    if isinstance(row.scene, str) and not row.scene.strip():
        return None
    return row.scene


def segment_report(rows: Iterable[Row], profile) -> Dict[str, object]:
    """Publish source counts here so later density policy cannot rewrite segmentation facts."""

    # Normalise scenes once, here, so a direct caller and the CLI agree. Blank
    # metadata is absent, not a bucket name, so it must take the resolver path.
    rows = [
        row if not (row.scene is None or (isinstance(row.scene, str) and not row.scene.strip()))
        else dataclasses.replace(row, scene=resolve_scene(row, profile))
        for row in rows
    ]
    speaker_scopes = [
        label
        for label, role in profile.speaker_roles.items()
        if role == config.ROLE_SPEAKER
    ]
    scopes = {
        scope: {
            "evidence_units": 0,
            "pivot_units": 0,
            "target_units": 0,
            "unrealised": 0,
            "rows": [],
            "scene_counts": {},
            "units_without_scene": 0,
            "n_scenes": 0,
        }
        for scope in speaker_scopes
    }
    coverage = {
        scope: {"eligible_units": 0, "attributed_units": 0, "ratio": None}
        for scope in speaker_scopes
    }
    ineligible = _ineligibility_counts()
    report_findings = findings.FindingSet()
    report = {
        "rows": len(rows),
        "eligible_rows": 0,
        "ineligible_rows": 0,
        "pure_narration_rows": 0,
        "ineligible": ineligible,
        "counters": {
            config.COUNTER_SCOPE_UNREALISED: 0,
            config.COUNTER_UNITS_WITHOUT_SCENE: 0,
        },
        "scopes": scopes,
        "coverage": coverage,
        "unmeasured_scopes": [],
        "findings": [],
        "hard_findings": 0,
    }


    for row in rows:
        state = eligibility(row, profile)
        if not state.eligible:
            for reason in state.reasons:
                ineligible[reason] += 1
            report["ineligible_rows"] += 1
            continue
        if row.target is not None:
            parity_finding = quote_parity(row, profile)
            if parity_finding is not None:
                report_findings.add(parity_finding)
        if not state.scopes:
            report["pure_narration_rows"] += 1
            continue


        report["eligible_rows"] += 1
        evidence = group_units(evidence_units(row, profile))
        pivot = group_units(side_units(row, profile, "pivot"))
        target = group_units(side_units(row, profile, "target"))
        for scope in state.scopes:
            key = (row.key, scope)
            scope_report = scopes[scope]
            scope_report["evidence_units"] += int(key in evidence)
            scope_report["pivot_units"] += int(key in pivot)
            scope_report["target_units"] += int(key in target)
            scope_report["rows"].append(row.key)

            if key in evidence:
                coverage[scope]["attributed_units"] += 1
                scene = evidence[key].scene
                if scene is None:
                    # A unit with no scene is invisible to the band, and an
                    # invisible unit caps every density verdict at `report` via
                    # under-sampling. Publish the count so that cap is a visible
                    # fact rather than a silent one.
                    scope_report["units_without_scene"] += 1
                    report["counters"][config.COUNTER_UNITS_WITHOUT_SCENE] += 1
                else:
                    scene_counts = scope_report["scene_counts"]
                    scene_counts[scene] = scene_counts.get(scene, 0) + 1
            if key in evidence and key in pivot:
                coverage[scope]["eligible_units"] += 1
            if key in evidence and key not in pivot:
                scope_report["unrealised"] += 1
                report["counters"][config.COUNTER_SCOPE_UNREALISED] += 1

    unmeasured_scopes = []
    for scope, scope_coverage in coverage.items():
        denominator = scope_coverage["attributed_units"]
        if denominator:
            scope_coverage["ratio"] = (
                scope_coverage["eligible_units"] / denominator
            )
        else:
            unmeasured_scopes.append(scope)
        scope_report = scopes[scope]
        scope_report["scene_counts"] = dict(
            sorted(scope_report["scene_counts"].items())
        )
        scope_report["n_scenes"] = len(scope_report["scene_counts"])
    report["unmeasured_scopes"] = unmeasured_scopes
    report["findings"] = report_findings.to_json()
    report["hard_findings"] = len(report_findings.hard)
    return report
