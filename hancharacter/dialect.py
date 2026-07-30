"""Dialect policy (R3) and the ``dialect_pair_undecided`` gate.

Mapping a source regional dialect onto a real target regional dialect is a
decision with consequences no metric can evaluate: rendering Kansai as Gyeongsang
imports a whole set of Korean regional associations the original never carried.
So the default is ``flavour_lexicon`` -- carry the dialect as lexical and ending
flavour -- and ``full_substitution`` requires both an adopted precedent for that
specific pair and enough corpus evidence.

Where a work declares a dialect pair and no ruling exists, the pipeline STOPS.
That is the whole point: this is the one place the project asks a human, because
the choice is editorial rather than measurable. A default here would be the
system quietly making an editorial decision and reporting success.

Rulings are bound to their triple by a NUL-delimited SHA-1. NUL-delimited so
``("a", "bc")`` and ``("ab", "c")`` cannot collide -- a delimiter-free
concatenation is the classic way a hash-bound decision silently authorises a
different decision. A row whose stored hash disagrees with its own declared fields
is stale and is not honoured, which is what makes a ruling invalid after an edit.
"""
import hashlib
import json
import os
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config, findings, schemas


class DialectError(Exception):
    """A decision log that cannot be loaded. Never downgraded to a warning."""


def decisions_path(root: Optional[str] = None) -> str:
    base = config.typology_root() if root is None else root
    return os.path.join(base, "dialect_decisions.jsonl")


def decision_hash(source_dialect: str, target_dialect: str, work: str) -> str:
    """SHA-1 over ``source \\0 target \\0 work``.

    The NUL separators are load-bearing: without them ``("a", "bc", w)`` and
    ``("ab", "c", w)`` hash identically, and a ruling made about one dialect pair
    would authorise a different one.
    """
    payload = "\0".join((source_dialect, target_dialect, work)).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()


def load_decisions(root: Optional[str] = None) -> List[Dict[str, Any]]:
    """Validated rulings. A missing file is an empty log, not an error.

    An absent log means nothing has been ruled on yet, which the gate turns into a
    hard finding for any work that needs a ruling. Raising here instead would make
    the honest initial state indistinguishable from a broken installation.
    """
    path = decisions_path(root)
    if not os.path.isfile(path):
        return []
    rows: List[Dict[str, Any]] = []
    ids: set = set()
    hashes: set = set()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for index, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError as exc:
                    raise DialectError("%s:%d: %s" % (path, index, exc))
                errors = schemas.validate("dialect_decision", row)
                if errors:
                    raise DialectError("%s:%d: %s" % (path, index, "; ".join(errors)))
                if row["id"] in ids:
                    raise DialectError(
                        "%s:%d: duplicate decision id %r" % (path, index, row["id"])
                    )
                if row["decision_hash"] in hashes:
                    raise DialectError(
                        "%s:%d: duplicate decision_hash %s; one triple cannot "
                        "carry two rulings" % (path, index, row["decision_hash"])
                    )
                ids.add(row["id"])
                hashes.add(row["decision_hash"])
                rows.append(row)
    except OSError as exc:
        raise DialectError("%s: %s" % (path, exc))
    return rows


def is_stale(row: Dict[str, Any]) -> bool:
    """True when a ruling's stored hash disagrees with its own declared fields."""
    return row["decision_hash"] != decision_hash(
        row["source_dialect"], row["target_dialect"], row["work"]
    )


def decision_for(
    source_dialect: str,
    target_dialect: str,
    work: str,
    decisions: Sequence[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], List[findings.Finding]]:
    """The non-stale ruling for one triple, plus findings for any stale one.

    A stale row is returned as no decision at all. Honouring it would mean a
    ruling about one dialect pair silently authorising another after an edit,
    which is exactly what binding the hash to the triple exists to prevent.
    """
    wanted = decision_hash(source_dialect, target_dialect, work)
    out: List[findings.Finding] = []
    match = None
    for row in decisions:
        if is_stale(row):
            out.append(
                findings.hard(
                    "dialect_decision_stale",
                    "decision %s stores hash %s but its declared fields (%s -> %s, "
                    "work %r) hash to %s; the ruling was edited after it was made "
                    "and is not honoured"
                    % (
                        row["id"],
                        row["decision_hash"],
                        row["source_dialect"],
                        row["target_dialect"],
                        row["work"],
                        decision_hash(
                            row["source_dialect"], row["target_dialect"], row["work"]
                        ),
                    ),
                )
            )
            continue
        if row["decision_hash"] == wanted:
            match = row
    return match, out


def full_substitution_allowed(
    source_dialect: str,
    target_dialect: str,
    *,
    adopted_precedents: int,
    sample_count: int,
    floor: int = config.PROVISIONAL_MIN_OCCURRENCES,
) -> Tuple[bool, List[findings.Finding]]:
    """Whether a whole-dialect substitution has the evidence R3 demands."""
    out: List[findings.Finding] = []
    pair = "%s -> %s" % (source_dialect, target_dialect)
    if adopted_precedents < 1:
        out.append(
            findings.hard(
                "dialect_full_substitution_unprecedented",
                "full_substitution for %s cites no adopted precedent; mapping a "
                "source region onto a real target region imports associations the "
                "original never carried, so it needs a published precedent rather "
                "than a preference" % pair,
            )
        )
    if sample_count < floor:
        out.append(
            findings.hard(
                "dialect_full_substitution_undersampled",
                "full_substitution for %s rests on %d corpus sample(s), below the "
                "graduation floor of %d" % (pair, sample_count, floor),
            )
        )
    return (not out), out


def gate(
    dialect_policy: Dict[str, Any],
    work: str,
    *,
    decisions: Sequence[Dict[str, Any]],
    adopted_precedent_ids: Iterable[str] = (),
    sample_count: int = 0,
    floor: int = config.PROVISIONAL_MIN_OCCURRENCES,
) -> List[findings.Finding]:
    """The hard interactive gate.

    Returns no findings when the work declares no dialect pair. A work with no
    dialect speaker must not be stopped by a dialect gate: a gate that fires on
    faithful work is as broken as one that never fires.
    """
    out: List[findings.Finding] = []
    strategy = dialect_policy.get("target_strategy", config.DIALECT_FLAVOUR_LEXICON)
    if strategy not in config.DIALECT_STRATEGIES:
        out.append(
            findings.hard(
                "dialect_strategy_undeclared",
                "target_strategy %r is not one of %s"
                % (strategy, list(config.DIALECT_STRATEGIES)),
            )
        )
        return out
    source_dialect = dialect_policy.get("source_dialect")
    target_dialect = dialect_policy.get("target_dialect")
    if not source_dialect or not target_dialect:
        # No pair declared. `flavour_lexicon` needs no ruling, but claiming a
        # whole-dialect substitution without naming the dialects is a decision
        # with no subject.
        if strategy == config.DIALECT_FULL_SUBSTITUTION:
            out.append(
                findings.hard(
                    "dialect_pair_undeclared",
                    "work %r selects full_substitution without naming both a "
                    "source_dialect and a target_dialect; there is nothing to rule "
                    "on and nothing to verify" % work,
                )
            )
        return out

    decision, stale_findings = decision_for(
        source_dialect, target_dialect, work, decisions
    )
    out.extend(stale_findings)
    expected = decision_hash(source_dialect, target_dialect, work)
    if decision is None:
        out.append(
            findings.hard(
                "dialect_pair_undecided",
                "work %r declares the dialect pair (%s -> %s) with no recorded "
                "ruling. This choice is editorial rather than measurable, so the "
                "pipeline stops here: record a dialect_decision whose "
                "decision_hash is %s, naming the strategy, a written reason and "
                "the deciding operator. There is deliberately no default."
                % (work, source_dialect, target_dialect, expected),
            )
        )
        return out
    # A ruling authorises the strategy it names. Keying the evidence check on the
    # ruling alone let a work select full_substitution while resting on a
    # flavour_lexicon ruling: the evidence check never ran and the caller reported
    # no findings at all.
    if decision["strategy"] != strategy:
        out.append(
            findings.hard(
                "dialect_strategy_mismatch",
                "work %r declares target_strategy %r but its recorded ruling %s "
                "authorises %r; a ruling authorises only the strategy it names"
                % (work, strategy, decision["id"], decision["strategy"]),
            )
        )
    if config.DIALECT_FULL_SUBSTITUTION in (strategy, decision["strategy"]):
        # Derived from the ruling's own cited precedents, cross-checked against the
        # adopted table, rather than taken as a caller-supplied count. A floor
        # supplied as an integer by whoever invokes the gate is not a floor.
        cited = list(decision.get("precedents", []))
        # `adopted_precedent_ids` may be a plain set of ids, or a mapping of
        # id -> (source_dialect, target_dialect) when the caller can supply the pair.
        # With the pair available, a citation only counts when it is evidence about
        # THIS pair: without that check a ruling cleared its floor by citing an
        # adopted row about an unrelated marker.
        if isinstance(adopted_precedent_ids, dict):
            backed = [
                ref
                for ref in cited
                if adopted_precedent_ids.get(ref)
                == (source_dialect, target_dialect)
            ]
            foreign = [
                ref
                for ref in cited
                if ref in adopted_precedent_ids and ref not in backed
            ]
            if foreign:
                out.append(
                    findings.hard(
                        "dialect_precedent_pair_mismatch",
                        "ruling %s cites adopted precedent(s) %s, which are not "
                        "evidence about the pair (%s -> %s); evidence about a "
                        "different marker does not authorise this substitution"
                        % (
                            decision["id"],
                            sorted(foreign),
                            source_dialect,
                            target_dialect,
                        ),
                    )
                )
        else:
            adopted = frozenset(adopted_precedent_ids)
            backed = [ref for ref in cited if ref in adopted]
        if cited and not backed:
            out.append(
                findings.hard(
                    "dialect_precedents_unbacked",
                    "ruling %s cites precedents %s, none of which is an adopted row "
                    "in the precedent table" % (decision["id"], sorted(cited)),
                )
            )
        _, evidence_findings = full_substitution_allowed(
            source_dialect,
            target_dialect,
            adopted_precedents=len(backed),
            sample_count=sample_count,
            floor=floor,
        )
        # An operator ruling does not manufacture evidence. If the pair lacks a
        # precedent, the ruling is recorded and still refused.
        out.extend(evidence_findings)
    return out


def lint(root: Optional[str] = None) -> findings.FindingSet:
    """Report stale or unloadable rulings. An empty log is a legitimate state."""
    result = findings.FindingSet()
    try:
        decisions = load_decisions(root)
    except DialectError as exc:
        result.add(findings.hard("dialect_decisions_unloadable", str(exc)))
        return result
    for row in decisions:
        if is_stale(row):
            result.add(
                findings.hard(
                    "dialect_decision_stale",
                    "decision %s was edited after it was made and is not honoured"
                    % row["id"],
                    scope=row["id"],
                )
            )
    result.add(
        findings.report(
            "dialect_decision_count",
            "%d dialect ruling(s) recorded; a pair with no ruling stops the "
            "pipeline for the work that declares it" % len(decisions),
        )
    )
    return result
