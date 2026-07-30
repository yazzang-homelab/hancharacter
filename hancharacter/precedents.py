"""Published-precedent table: what editions actually shipped.

A precedent is a claim about the world -- this edition rendered this marker this
way -- and is deliberately kept in a different vocabulary from corpus review.
``adopted`` says an edition shipped a rendering; ``accept`` says a transcription is
correct. Sharing one vocabulary would let the second be counted as the first by
the canonical rule.

Two rules here are the ones that decide whether the gate works at all.

**A resolution must point at something.** A contradiction counts as resolved only
when the row's ``resolved_by`` names a human confirmation that actually exists. A
``resolved_by`` pointing at nothing is a hard finding, not a resolution: treating
it as resolved would be a gate anyone could clear by inventing an id.

**An unmatched rejected precedent is a recorded gap, not silence.** A rejected
precedent with no ``target_pattern_set`` cannot be matched mechanically. That is
reported explicitly, because a rejected rendering nobody can check for is an
unautomatable claim, and this project records those as limitations rather than
asserting them as coverage.
"""
import json
import os
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from . import config, findings, schemas


class PrecedentError(Exception):
    """A precedent table that cannot be loaded. Never downgraded to a warning."""


def table_path(root: Optional[str] = None) -> str:
    base = config.typology_root() if root is None else root
    return os.path.join(base, "precedents.jsonl")


def load(root: Optional[str] = None) -> List[Dict[str, Any]]:
    path = table_path(root)
    if not os.path.isfile(path):
        raise PrecedentError("no precedent table at %s" % path)
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for index, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise PrecedentError("%s:%d: %s" % (path, index, exc))
                errors = schemas.validate("precedent", row)
                if errors:
                    raise PrecedentError(
                        "%s:%d: %s" % (path, index, "; ".join(errors))
                    )
                if row["id"] in seen:
                    raise PrecedentError(
                        "%s:%d: duplicate precedent id %r" % (path, index, row["id"])
                    )
                seen.add(row["id"])
                rows.append(row)
    except OSError as exc:
        raise PrecedentError("%s: %s" % (path, exc))
    return rows


def by_type(rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["type_id"], []).append(row)
    return grouped


def _with_verdict(rows: Sequence[Dict[str, Any]], verdict: str) -> List[Dict[str, Any]]:
    return [row for row in rows if row["verdict"] == verdict]


def adopted(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _with_verdict(rows, config.PRECEDENT_ADOPTED)


def contested(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _with_verdict(rows, config.PRECEDENT_CONTESTED)


def rejected(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return _with_verdict(rows, config.PRECEDENT_REJECTED)


def unresolved_contradictions(
    rows: Sequence[Dict[str, Any]], known_confirm_ids: Iterable[str] = ()
) -> List[Tuple[str, str]]:
    """Contradicting pairs with no existing human confirmation resolving them.

    ``known_confirm_ids`` is passed in rather than read from the confirmation log,
    so the dependency stays one-way and the join is visible at the call site.
    """
    confirms = frozenset(known_confirm_ids)
    out: List[Tuple[str, str]] = []
    for row in rows:
        for other in row.get("contradicts", []):
            resolver = row.get("resolved_by")
            if resolver is not None and resolver in confirms:
                continue
            out.append((row["id"], other))
    return sorted(out)


def siblings(rows: Sequence[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """Adopted rows grouped by ``edition_channel``."""
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in adopted(rows):
        grouped.setdefault(row["edition_channel"], []).append(row)
    return grouped


def select_sibling(
    rows: Sequence[Dict[str, Any]], edition_medium: Optional[str]
) -> Tuple[Optional[Dict[str, Any]], List[findings.Finding]]:
    """Pick the adopted precedent for *edition_medium*.

    With several siblings and no selector, this refuses rather than taking the
    first row. Silently picking one is how a work ships the wrong convention while
    every check reports success.
    """
    groups = siblings(rows)
    if not groups:
        return None, []
    if edition_medium is not None and edition_medium in groups:
        chosen = sorted(groups[edition_medium], key=lambda r: r["id"])[0]
        return chosen, []
    if len(groups) == 1:
        only = sorted(next(iter(groups.values())), key=lambda r: r["id"])[0]
        return only, []
    return None, [
        findings.hard(
            "precedent_sibling_unselected",
            "type %s has adopted precedents on %d edition channels (%s) and "
            "edition_medium %r selects none of them; picking one silently would "
            "ship a convention nobody chose"
            % (
                rows[0]["type_id"] if rows else "?",
                len(groups),
                ", ".join(sorted(groups)),
                edition_medium,
            ),
        )
    ]


def canonical_support(
    rows: Sequence[Dict[str, Any]], known_confirm_ids: Iterable[str] = ()
) -> Tuple[bool, List[findings.Finding]]:
    """Whether the precedent table supports canonical status for one type."""
    out: List[findings.Finding] = []
    adopted_rows = adopted(rows)
    contradictions = unresolved_contradictions(rows, known_confirm_ids)
    type_id = rows[0]["type_id"] if rows else "?"
    if len(adopted_rows) < config.CANONICAL_MIN_ADOPTED_PRECEDENTS:
        out.append(
            findings.hard(
                "precedent_no_adopted_support",
                "type %s cites %d adopted precedent(s); canonical status requires "
                "at least %d, because a rendering no edition ever shipped is a "
                "proposal rather than a precedent"
                % (
                    type_id,
                    len(adopted_rows),
                    config.CANONICAL_MIN_ADOPTED_PRECEDENTS,
                ),
                scope=type_id,
            )
        )
    for left, right in contradictions:
        out.append(
            findings.hard(
                "precedent_contradiction_unresolved",
                "precedent %s contradicts %s with no human ruling recorded; an "
                "unresolved contradiction blocks canonical status for type %s"
                % (left, right, type_id),
                scope=type_id,
            )
        )
    return (not out), out


def rejected_match(
    realisation: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
    *,
    matched_markers: Callable[[Sequence[str], str], FrozenSet[str]],
    containment: Callable[[Iterable[str], Iterable[str]], float],
) -> List[findings.Finding]:
    """Seal-time check that a realisation does not reproduce a rejected rendering.

    ``matched_markers`` and ``containment`` are injected so this module neither
    duplicates the measure nor reaches into the typology loader.

    The measure is **containment, not Jaccard**, and that is load-bearing. Jaccard's
    union denominator let an offender dilute the score by adding unrelated
    patterns: a realisation shipping a rejected caricature alongside four
    legitimate patterns scored 0.2 against a 0.5 gate and passed while openly
    enforcing the caricature. Adding patterns is a mechanical way to clear a gate,
    which is the definition of a gate that can be skipped. Containment asks the
    asymmetric question this check actually poses -- how much of the rejected
    rendering does this realisation reproduce -- and cannot be diluted.
    """
    out: List[findings.Finding] = []
    target_lang = realisation["target_lang"]
    own_patterns = realisation.get("pattern_set") or []
    own = matched_markers(own_patterns, target_lang) if own_patterns else frozenset()
    for row in rejected(rows):
        patterns = row.get("target_pattern_set")
        if not patterns:
            out.append(
                findings.report(
                    "precedent_rejected_unmatchable",
                    "rejected precedent %s carries no target_pattern_set, so no "
                    "realisation can be checked against it mechanically; this is "
                    "a recorded gap in coverage, not a clean result" % row["id"],
                    scope=realisation["id"],
                )
            )
            continue
        if not own_patterns:
            out.append(
                findings.report(
                    "precedent_rejected_uncheckable_realisation",
                    "realisation %s declares no pattern_set, so it cannot be "
                    "checked against rejected precedent %s"
                    % (realisation["id"], row["id"]),
                    scope=realisation["id"],
                )
            )
            continue
        reference = matched_markers(patterns, target_lang)
        # A declared-but-unmatchable pattern set is the same gap as no pattern set
        # at all, and it used to fall through to the measure: a rejected precedent
        # matching nothing scored 0.0 against every realisation and cleared them
        # all silently, while two sides matching nothing scored 1.0 and fired hard
        # on zero evidence. Both are decided here instead.
        if not reference:
            out.append(
                findings.report(
                    "precedent_rejected_unmatchable",
                    "rejected precedent %s declares a target_pattern_set that "
                    "matches no probe row, so no realisation can be checked "
                    "against it mechanically; this is a recorded gap in coverage, "
                    "not a clean result" % row["id"],
                    scope=realisation["id"],
                )
            )
            continue
        similarity = containment(own, reference)
        if similarity >= config.JACCARD_REJECTED_MATCH_MIN:
            out.append(
                findings.hard(
                    "precedent_rejected_reproduced",
                    "realisation %s reproduces %.0f%% of rejected precedent %s "
                    "(containment %.3f >= %.2f): %s. Shipping a rendering an "
                    "edition already got wrong is not a fresh choice"
                    % (
                        realisation["id"],
                        similarity * 100,
                        row["id"],
                        similarity,
                        config.JACCARD_REJECTED_MATCH_MIN,
                        row["target_realisation"],
                    ),
                    scope=realisation["id"],
                )
            )
    return out


def lint(
    root: Optional[str] = None,
    *,
    known_confirm_ids: Iterable[str] = (),
    matched_markers: Optional[Callable[[Sequence[str], str], FrozenSet[str]]] = None,
) -> findings.FindingSet:
    """Publish every precedent-table defect this phase can decide mechanically."""
    result = findings.FindingSet()
    try:
        rows = load(root)
    except PrecedentError as exc:
        result.add(findings.hard("precedent_table_unloadable", str(exc)))
        return result
    if not rows:
        result.add(
            findings.hard(
                "precedent_table_empty",
                "%s holds no rows; a precedent lint that returns clean on an "
                "empty table has checked nothing" % table_path(root)
            )
        )
        return result

    ids = {row["id"] for row in rows}
    confirms = frozenset(known_confirm_ids)
    for row in rows:
        for other in row.get("contradicts", []):
            if other not in ids:
                result.add(
                    findings.hard(
                        "precedent_contradiction_dangling",
                        "precedent %s says it contradicts %s, which is not in the "
                        "table" % (row["id"], other),
                        scope=row["id"],
                    )
                )
        resolver = row.get("resolved_by")
        if resolver is not None and resolver not in confirms:
            result.add(
                findings.hard(
                    "precedent_resolution_dangling",
                    "precedent %s claims resolution by %s, which is not in the "
                    "human confirmation log; a resolution pointing at nothing is "
                    "a gate anyone could clear by inventing an id"
                    % (row["id"], resolver),
                    scope=row["id"],
                )
            )

    # One (type, marker, channel) triple cannot be both adopted and contested:
    # that is a table asserting an edition both did and did not settle it.
    seen: Dict[Tuple[str, str, str], Set[str]] = {}
    for row in rows:
        triple = (row["type_id"], row["source_marker"], row["edition_channel"])
        seen.setdefault(triple, set()).add(row["verdict"])
    for triple, verdicts in sorted(seen.items()):
        if {config.PRECEDENT_ADOPTED, config.PRECEDENT_CONTESTED} <= verdicts:
            result.add(
                findings.hard(
                    "precedent_verdict_conflict",
                    "type %s marker %r on channel %s is recorded as both adopted "
                    "and contested; the table cannot assert an edition both "
                    "settled and did not settle one rendering" % triple,
                    scope=triple[0],
                )
            )

    # A rejected rendering can only be enforced if the probe corpus exercises its
    # pattern set. Where it does not, `rejected_match` records a gap and returns no
    # hard finding, so a realisation copying that exact rendering passes. The gap is
    # tolerable as a *report* at match time only because the table itself is
    # required to be probe-covered here.
    if matched_markers is not None:
        for row in rejected(rows):
            patterns = row.get("target_pattern_set")
            if not patterns:
                continue  # deletion cannot be a positive pattern; see rejected_match
            if not matched_markers(patterns, row["target_lang"]):
                result.add(
                    findings.hard(
                        "precedent_rejected_pattern_unprobed",
                        "rejected precedent %s declares a target_pattern_set that "
                        "matches no %s probe row, so no realisation can ever be "
                        "checked against it: a realisation reproducing this exact "
                        "rendering would pass. Add a probe row exercising it, or "
                        "drop the pattern set and record the gap"
                        % (row["id"], row["target_lang"]),
                        scope=row["id"],
                    )
                )

    for type_id, group in sorted(by_type(rows).items()):
        for _, contradiction in enumerate(
            unresolved_contradictions(group, confirms)
        ):
            result.add(
                findings.report(
                    "precedent_contradiction_open",
                    "type %s has an open contradiction %s vs %s awaiting a human "
                    "ruling; it blocks canonical status for that type"
                    % (type_id, contradiction[0], contradiction[1]),
                    scope=type_id,
                )
            )
    return result
