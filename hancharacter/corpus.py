"""Corpus evidence: independent dual review, graduation, and the quotation lint.

Three design decisions here are load-bearing, and each exists because the obvious
implementation produces a check that cannot fail.

**Drafts and reviews are separate files.** A producer writes
``samples.draft.jsonl``; each reviewer writes ``reviews/<reviewer>.jsonl``. If one
author wrote a row together with both of its reviewer verdicts, "dual review
agreeing" would be one opinion typed three times and the kappa computed over it
would be a self-agreement score. Independence is therefore a property of the file
layout, not a promise in a comment.

**Kappa may be undefined, and undefined is not agreement.** Cohen's kappa needs
variance to measure. When both reviewers used one identical category on every row
there is no disagreement opportunity, so this module returns ``None`` rather than
1.0. Coercing that to 1.0 would manufacture the strongest possible agreement score
out of the weakest possible evidence, and the canonical rule would then pass on it.

**Dump detection and independence counting use different granularity.**
``independent_key`` answers "is this a separate source", so mirrors and separate
articles of one publication share it. ``locator`` answers "is this the same
passage". Consecutive-row dump detection keys on ``locator``; the n-gram
reassembly check keys on the coarser ``independent_key``, because reassembling a
passage across two articles of one publication is still reassembly.
"""
import json
import os
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from . import config, findings, schemas


class CorpusError(Exception):
    """A corpus that cannot be loaded. Never downgraded to a warning."""


# Tokenisation for the n-gram reassembly check. Whitespace splitting would make
# the check a no-op on Japanese and Korean, which are the languages this project
# exists to measure -- a check that cannot fire on its own target languages is not
# a check. So: CJK ideographs, kana and Hangul syllables are each one token, while
# runs of Latin letters and digits stay whole words.
_TOKEN_RE = re.compile(
    r"[\u3040-\u30ff]"        # kana
    r"|[\u4e00-\u9fff]"       # CJK ideographs
    r"|[\uac00-\ud7a3]"       # Hangul syllables
    r"|[0-9A-Za-z_'\u00c0-\u024f]+"
)


def tokenise(text: str) -> List[str]:
    """Split *text* into comparison tokens; see ``_TOKEN_RE`` for the rationale."""
    return _TOKEN_RE.findall(text)


def _root(root: Optional[str] = None) -> str:
    return config.typology_root() if root is None else root


def context_without_marker(row: Dict[str, Any]) -> str:
    """The quote with the row's own declared marker removed.

    Used only by the reassembly check. A corpus exists to record the same marker
    from several sources, so two rows sharing the marker string are doing their
    job; two rows sharing the text AROUND it are rebuilding a passage.
    """
    quote = row.get("quote") or ""
    marker = (row.get("marker") or "").strip()
    if not marker:
        return quote
    # Markers are written with a leading tilde to show they attach to a stem, and
    # some rows record two spellings separated by a slash. Strip each variant.
    for variant in (part.strip().lstrip("~") for part in marker.split("/")):
        if variant:
            quote = quote.replace(variant, " ")
    return quote


def _read_jsonl(path: str) -> List[Any]:
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for index, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    rows.append(json.loads(line))
                except ValueError as exc:
                    raise CorpusError("%s:%d: %s" % (path, index, exc))
    except OSError as exc:
        raise CorpusError("%s: %s" % (path, exc))
    return rows


def drafts_path(root: Optional[str] = None) -> str:
    return os.path.join(_root(root), "samples.draft.jsonl")


def reviews_dir(root: Optional[str] = None) -> str:
    return os.path.join(_root(root), "reviews")


def load_drafts(root: Optional[str] = None) -> List[Dict[str, Any]]:
    path = drafts_path(root)
    if not os.path.isfile(path):
        raise CorpusError("no corpus drafts at %s" % path)
    rows = _read_jsonl(path)
    seen = set()
    for row in rows:
        errors = schemas.validate("corpus_draft", row)
        if errors:
            raise CorpusError("%s: %s" % (path, "; ".join(errors)))
        if row["id"] in seen:
            raise CorpusError("%s: duplicate draft id %r" % (path, row["id"]))
        seen.add(row["id"])
    return rows


def load_reviews(root: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """Reviewer id -> their verdicts, keyed by the filename stem.

    The filename stem must equal the ``reviewer`` field on every row in the file.
    Without that check one reviewer could file verdicts under another's name and
    the independence the two-file layout buys would be lost.
    """
    directory = reviews_dir(root)
    if not os.path.isdir(directory):
        raise CorpusError("no review directory at %s" % directory)
    out: Dict[str, List[Dict[str, Any]]] = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        path = os.path.join(directory, name)
        reviewer = name[: -len(".jsonl")]
        rows = _read_jsonl(path)
        seen = set()
        for row in rows:
            errors = schemas.validate("corpus_review", row)
            if errors:
                raise CorpusError("%s: %s" % (path, "; ".join(errors)))
            if row["reviewer"] != reviewer:
                raise CorpusError(
                    "%s: row for %s declares reviewer %r, but the filename says "
                    "%r; a reviewer must not be able to file under another name"
                    % (path, row["sample_id"], row["reviewer"], reviewer)
                )
            if row["sample_id"] in seen:
                raise CorpusError(
                    "%s: reviewer %s rated %s twice"
                    % (path, reviewer, row["sample_id"])
                )
            seen.add(row["sample_id"])
        out[reviewer] = rows
    return out


def _resolve_verdict(votes: Sequence[str]) -> str:
    """Unanimous accept or reject stands; anything else is ``needs_review``.

    Disagreement is preserved rather than resolved by majority. A row two
    reviewers read differently is exactly the row a human should look at, and
    majority-voting it away would delete the signal the review exists to produce.
    """
    unique = set(votes)
    if unique == {config.REVIEW_ACCEPT}:
        return config.REVIEW_ACCEPT
    if unique == {config.REVIEW_REJECT}:
        return config.REVIEW_REJECT
    return config.REVIEW_NEEDS_REVIEW


def merge(
    drafts: Sequence[Dict[str, Any]],
    reviews: Dict[str, Sequence[Dict[str, Any]]],
) -> Tuple[List[Dict[str, Any]], List[findings.Finding]]:
    """Join drafts with independent reviews into validated ``corpus_sample`` rows."""
    out: List[Dict[str, Any]] = []
    found: List[findings.Finding] = []
    by_id = {draft["id"]: draft for draft in drafts}

    votes: Dict[str, Dict[str, str]] = {}
    for reviewer, rows in sorted(reviews.items()):
        for row in rows:
            sample_id = row["sample_id"]
            if sample_id not in by_id:
                found.append(
                    findings.hard(
                        "corpus_review_orphaned",
                        "reviewer %s rated %s, which is not a draft; a verdict on "
                        "a row that does not exist is a verdict nobody can audit"
                        % (reviewer, sample_id),
                        row_key=sample_id,
                    )
                )
                continue
            votes.setdefault(sample_id, {})[reviewer] = row["verdict"]

    for draft in drafts:
        sample_id = draft["id"]
        reviewers = sorted(votes.get(sample_id, {}))
        if len(reviewers) < 2:
            found.append(
                findings.hard(
                    "corpus_review_insufficient",
                    "draft %s has %d independent review(s); two are required, so "
                    "this row counts toward no graduation floor"
                    % (sample_id, len(reviewers)),
                    row_key=sample_id,
                )
            )
            continue
        if draft["producer"] in reviewers:
            found.append(
                findings.hard(
                    "corpus_producer_reviewed_own_row",
                    "draft %s was reviewed by its own producer %s; one opinion "
                    "wearing two names is not dual review"
                    % (sample_id, draft["producer"]),
                    row_key=sample_id,
                )
            )
            continue
        # The resolution is computed from EVERY vote, not from the two the closed
        # schema can carry. Resolving from the first two by id let a 2-1 split
        # resolve as unanimous accept: the third reviewer's rejection was dropped
        # and the row counted toward every graduation floor.
        cast = dict(votes[sample_id])
        resolved = _resolve_verdict(list(cast.values()))
        # Choose the two carried reviewers so a dissenter is always among them.
        # Otherwise `reviewer_verdicts` would imply a different verdict than the one
        # recorded, and the schema's consistency check would reject an honest row.
        dissenting = sorted(r for r in reviewers if cast[r] != config.REVIEW_ACCEPT)
        agreeing = sorted(r for r in reviewers if cast[r] == config.REVIEW_ACCEPT)
        ordered = (dissenting + agreeing) if dissenting else agreeing
        primary, secondary = sorted(ordered[:2])
        pair = {primary: cast[primary], secondary: cast[secondary]}
        if len(reviewers) > 2:
            # The closed schema binds `reviewer_verdicts` to exactly two reviewers,
            # so the remaining verdicts cannot live inside the validated row.
            # Published here so nothing is dropped silently.
            found.append(
                findings.report(
                    "corpus_extra_reviewer_not_carried",
                    "draft %s was reviewed by %d reviewers (%s), resolving to %r "
                    "from all votes; the validated row carries %s and %s, and the "
                    "remaining verdict(s) %s are recorded only here"
                    % (
                        sample_id,
                        len(reviewers),
                        ", ".join(reviewers),
                        resolved,
                        primary,
                        secondary,
                        ", ".join(
                            "%s=%s" % (r, cast[r])
                            for r in reviewers
                            if r not in (primary, secondary)
                        ),
                    ),
                    row_key=sample_id,
                )
            )
        row = {
            "id": sample_id,
            "type_id": draft["type_id"],
            "axis": draft["axis"],
            "work": draft["work"],
            "producer": draft["producer"],
            "reviewer": primary,
            "review2": secondary,
            "reviewer_verdicts": pair,
            "verdict": resolved,
            "quote": draft["quote"],
            "quote_len": draft["quote_len"],
            "source": dict(draft["source"]),
        }
        for optional in ("marker", "notes"):
            if optional in draft:
                row[optional] = draft[optional]
        errors = schemas.validate("corpus_sample", row)
        if errors:
            found.append(
                findings.hard(
                    "corpus_merged_row_invalid",
                    "merged sample %s does not satisfy the closed schema: %s"
                    % (sample_id, "; ".join(errors)),
                    row_key=sample_id,
                )
            )
            continue
        out.append(row)
    return out, found


def kappa_floor_downward_flips(pairs: Sequence[Tuple[str, str]]) -> int:
    """Count single verdict flips that would drop an at-or-above-floor kappa below it.

    ``KAPPA_FLOOR`` alone is clearable by dilution: appending rows that are easy
    to agree on raises Cohen's kappa monotonically, so two real disagreements can
    be diluted until the value touches the floor.  ``ja_hao_gozaru`` reached
    exactly 3/5 that way, and removing any one of the eight added rows put it back
    at 22/37.

    This adds a stability requirement instead of an arbitrary minimum count: a
    kappa may satisfy the floor only if the *verdict* survives any single
    annotation change.  It is derivable rather than invented, and it refuses both
    knife-edge proximity to the floor and the small-sample instability that makes
    a high kappa untrustworthy -- a 0.77 computed from seven rows moves further on
    one flip than a 0.85 computed from fifty.

    The check is deliberately **one-directional**.  Only a downward flip changes
    an outcome, so only downward instability disqualifies.  A type below the floor
    that one flip would push above is already unmet, and treating that instability
    as qualifying would be a new escape rather than a guard.  Upward instability is
    reported for transparency but never grants anything.

    Returns 0 when kappa is undefined or already below the floor, so this can only
    ever remove a pass, never create one.
    """

    base = cohens_kappa(pairs)
    if base is None or base < config.KAPPA_FLOOR:
        return 0
    verdicts = tuple(config.REVIEW_VERDICTS)
    mutable = [list(pair) for pair in pairs]
    flips = 0
    for index in range(len(mutable)):
        for rater in (0, 1):
            original = mutable[index][rater]
            for verdict in verdicts:
                if verdict == original:
                    continue
                mutable[index][rater] = verdict
                candidate = cohens_kappa([tuple(pair) for pair in mutable])
                if candidate is None or candidate < config.KAPPA_FLOOR:
                    flips += 1
            mutable[index][rater] = original
    return flips


def cohens_kappa(pairs: Sequence[Tuple[str, str]]) -> Optional[float]:
    """Cohen's kappa for two raters over ``config.REVIEW_VERDICTS``.

    Returns ``None`` when kappa is undefined, which is an honest outcome and is
    never coerced to a number.  The canonical rule treats ``None`` as unmet
    rather than as perfect.

    Three cases are undefined:

    - no rows at all;
    - expected agreement of exactly 1.0, because both raters used a single
      identical category;
    - **zero observed disagreements.**  This third case was the escape.  The
      ``expected >= 1.0`` guard fires only when the raters used exactly one
      category between them, so a single row in a different category creates
      marginal variance while the raters still never actually disagreed, and
      kappa comes out at 1.0.  That is precisely the "fabricated agreement
      score" this function refuses in the other two cases, arriving through a
      side door.  A reliability statistic computed from no disagreement
      measures nothing about reliability.
    """

    total = len(pairs)
    if total == 0:
        return None
    categories = tuple(config.REVIEW_VERDICTS)
    agreed = sum(1 for a, b in pairs if a == b)
    if agreed == total:
        return None
    observed = agreed / total
    expected = 0.0
    for category in categories:
        p_a = sum(1 for a, _ in pairs if a == category) / total
        p_b = sum(1 for _, b in pairs if b == category) / total
        expected += p_a * p_b
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def _pairs_for(samples: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    pairs = []
    for row in samples:
        verdicts = row["reviewer_verdicts"]
        first, second = row["reviewer"], row["review2"]
        pairs.append((verdicts[first], verdicts[second]))
    return pairs


def kappa_by_type(samples: Sequence[Dict[str, Any]]) -> Dict[str, Optional[float]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in samples:
        grouped.setdefault(row["type_id"], []).append(row)
    return {
        type_id: cohens_kappa(_pairs_for(rows))
        for type_id, rows in sorted(grouped.items())
    }


def independent_sources(samples: Sequence[Dict[str, Any]]) -> int:
    """Distinct ``source.independent_key`` values. Mirrors count once."""
    return len({row["source"]["independent_key"] for row in samples})


def e1e2_count(samples: Sequence[Dict[str, Any]]) -> int:
    """Distinct independent keys carrying primary or secondary evidence."""
    return len(
        {
            row["source"]["independent_key"]
            for row in samples
            if row["source"]["class"] in config.E1E2_SOURCE_CLASSES
        }
    )


def copyright_lint(
    rows: Sequence[Dict[str, Any]],
) -> List[findings.Finding]:
    """Quotation limits, recomputed rather than trusted."""
    out: List[findings.Finding] = []

    per_work: Dict[str, int] = {}
    for row in rows:
        quote = row.get("quote") or ""
        declared = row.get("quote_len")
        if len(quote) != declared:
            out.append(
                findings.hard(
                    "corpus_quote_len_mismatch",
                    "row %s declares quote_len %r but the quote is %d characters; "
                    "a self-declared length is not a measurement"
                    % (row.get("id"), declared, len(quote)),
                    row_key=row.get("id"),
                )
            )
        if len(quote) > config.QUOTE_MAX_CHARS_PER_ROW:
            out.append(
                findings.hard(
                    "corpus_quote_over_row_ceiling",
                    "row %s quotes %d characters, over the %d ceiling"
                    % (row.get("id"), len(quote), config.QUOTE_MAX_CHARS_PER_ROW),
                    row_key=row.get("id"),
                )
            )
        work = row.get("work")
        per_work[work] = per_work.get(work, 0) + len(quote)
    for work, total in sorted(per_work.items()):
        if total > config.QUOTE_MAX_CHARS_PER_WORK:
            out.append(
                findings.hard(
                    "corpus_quote_over_work_cap",
                    "work %r is quoted for %d characters in total, over the %d cap"
                    % (work, total, config.QUOTE_MAX_CHARS_PER_WORK),
                )
            )

    # Consecutive-passage dump, keyed on `locator`: the same page quoted three
    # times in a row is sequential copying.
    run_key = None
    run_ids: List[str] = []
    for row in rows:
        key = (row["source"]["independent_key"], row["source"].get("locator"))
        if key == run_key:
            run_ids.append(row.get("id"))
        else:
            run_key, run_ids = key, [row.get("id")]
        if len(run_ids) >= config.DUMP_CONSECUTIVE_ROWS:
            out.append(
                findings.hard(
                    "corpus_consecutive_dump",
                    "rows %s quote %s consecutively from one passage (%s); the "
                    "corpus ships markers and citations, not a transcription"
                    % (", ".join(str(i) for i in run_ids), config.DUMP_CONSECUTIVE_ROWS,
                       " / ".join(str(part) for part in key)),
                    row_key=row.get("id"),
                )
            )
            run_ids = []

    # Split-dump reassembly, keyed on the coarser `independent_key`: quoting one
    # passage across many rows to rebuild it is the evasion the consecutive check
    # alone would miss, and it works across articles of one publication too.
    #
    # The row's own declared marker is removed from the quote first. Under this
    # tokenisation each Hangul or kana syllable is one token, so an eight-token run
    # is only about eight characters, and a marker string is often longer than
    # that. Two rows cataloguing `~지 말입니다(~であります)` for two different
    # characters would otherwise be reported as reassembling a passage, when
    # quoting one marker twice is precisely what a marker corpus is for. What
    # remains after the marker is removed is surrounding context, and eight shared
    # tokens of context across rows really is reassembly.
    by_source: Dict[str, List[Dict[str, Any]]] = {}
    for row in rows:
        by_source.setdefault(row["source"]["independent_key"], []).append(row)
    n = config.DUMP_NGRAM_TOKENS
    for key, group in sorted(by_source.items()):
        grams: Dict[Tuple[str, ...], str] = {}
        for row in group:
            tokens = tokenise(context_without_marker(row))
            for start in range(0, max(0, len(tokens) - n + 1)):
                gram = tuple(tokens[start : start + n])
                previous = grams.get(gram)
                if previous is not None and previous != row.get("id"):
                    out.append(
                        findings.hard(
                            "corpus_split_dump",
                            "rows %s and %s from source %s share a %d-token run "
                            "%r; quoting one passage across several rows "
                            "reassembles it"
                            % (previous, row.get("id"), key, n, " ".join(gram)),
                            row_key=row.get("id"),
                        )
                    )
                else:
                    grams.setdefault(gram, row.get("id"))
        # The marker strip above is itself an evasion route: an attacker can
        # declare a whole quoted passage as this row's `marker`, and the strip
        # would then remove exactly the text the reassembly check is looking for.
        # The discriminator is that two rows legitimately cataloguing one marker
        # declare the SAME marker string -- that is why they are both filed under
        # it -- while a laundered passage is sliced into DIFFERENT markers per row.
        # So: two rows of one source whose markers differ but share a run of
        # `DUMP_NGRAM_TOKENS` tokens are reassembling a passage through the marker
        # field, and identical markers are left alone.
        marker_grams: Dict[Tuple[str, ...], Tuple[str, str]] = {}
        for row in group:
            marker = (row.get("marker") or "").strip()
            if not marker:
                continue
            tokens = tokenise(marker)
            for start in range(0, max(0, len(tokens) - n + 1)):
                gram = tuple(tokens[start : start + n])
                previous = marker_grams.get(gram)
                if previous is not None and previous[1] != marker:
                    out.append(
                        findings.hard(
                            "corpus_marker_laundered_dump",
                            "rows %s and %s from source %s declare DIFFERENT "
                            "markers that share a %d-token run %r; a marker is a "
                            "short form, so two different markers overlapping by "
                            "this much are slices of one passage being laundered "
                            "through the marker field"
                            % (previous[0], row.get("id"), key, n, " ".join(gram)),
                            row_key=row.get("id"),
                        )
                    )
                else:
                    marker_grams.setdefault(gram, (row.get("id"), marker))
    return out


def graduate(
    type_id: str,
    samples: Sequence[Dict[str, Any]],
    precedent_facts: Dict[str, int],
    human_confirms: int,
) -> Dict[str, Any]:
    """One ``graduation_report.types[]`` entry, with every unmet reason named.

    ``precedent_facts`` is supplied by the caller rather than read from
    ``precedents.py``: the dependency stays one-way so this module can be tested
    without a precedent table, and the join is visible at the call site.

    Only rows whose resolved verdict is ``accept`` count as occurrences. A
    ``needs_review`` or ``reject`` row counts toward nothing, but it stays visible
    in the report so a thin type cannot look well-evidenced.
    """
    accepted = [row for row in samples if row["verdict"] == config.REVIEW_ACCEPT]
    occurrences = len(accepted)
    sources = independent_sources(accepted)
    e1e2 = e1e2_count(accepted)
    adopted = int(precedent_facts.get("adopted", 0))
    contradictions = int(precedent_facts.get("unresolved_contradictions", 0))
    agreeing = sum(
        1
        for row in samples
        if len(set(row["reviewer_verdicts"].values())) == 1
    )
    pairs = _pairs_for(samples)
    kappa = cohens_kappa(pairs)
    kappa_flips = kappa_floor_downward_flips(pairs)

    unmet: List[str] = []
    if occurrences < config.PROVISIONAL_MIN_OCCURRENCES:
        unmet.append(
            "occurrences %d < %d required for provisional"
            % (occurrences, config.PROVISIONAL_MIN_OCCURRENCES)
        )
    if sources < config.PROVISIONAL_MIN_INDEPENDENT_SOURCES:
        unmet.append(
            "independent sources %d < %d required for provisional"
            % (sources, config.PROVISIONAL_MIN_INDEPENDENT_SOURCES)
        )
    provisional_ok = not unmet

    canonical_unmet: List[str] = []
    if occurrences < config.CANONICAL_MIN_OCCURRENCES:
        canonical_unmet.append(
            "occurrences %d < %d required for canonical"
            % (occurrences, config.CANONICAL_MIN_OCCURRENCES)
        )
    if sources < config.CANONICAL_MIN_INDEPENDENT_SOURCES:
        canonical_unmet.append(
            "independent sources %d < %d required for canonical"
            % (sources, config.CANONICAL_MIN_INDEPENDENT_SOURCES)
        )
    if e1e2 < config.CANONICAL_MIN_E1E2_SOURCES:
        canonical_unmet.append(
            "primary/secondary sources %d < %d required for canonical"
            % (e1e2, config.CANONICAL_MIN_E1E2_SOURCES)
        )
    # Target-side convention claims are collected separately from source-side
    # evidence claims. The two answer different questions -- "is this marker real
    # and measurable" versus "is this Korean rendering the established convention"
    # -- and conflating them in one list is why the tool could not govern a first
    # translation. `translator_declared` contracts need the former only.
    convention_unmet: List[str] = []
    if adopted < config.CANONICAL_MIN_ADOPTED_PRECEDENTS:
        convention_unmet.append(
            "adopted precedents %d < %d required for canonical"
            % (adopted, config.CANONICAL_MIN_ADOPTED_PRECEDENTS)
        )
    if contradictions:
        convention_unmet.append(
            "%d unresolved precedent contradiction(s) must be ruled on first"
            % contradictions
        )
    if agreeing < 1:
        canonical_unmet.append("no row has both reviewers agreeing")
    if human_confirms < config.CANONICAL_MIN_HUMAN_CONFIRMS:
        canonical_unmet.append(
            "human confirmations %d < %d required for canonical"
            % (human_confirms, config.CANONICAL_MIN_HUMAN_CONFIRMS)
        )
    if kappa is None:
        canonical_unmet.append(
            "kappa is undefined (no disagreement opportunity), which is not "
            "agreement and cannot satisfy the %.2f floor" % config.KAPPA_FLOOR
        )
    elif kappa < config.KAPPA_FLOOR:
        canonical_unmet.append(
            "kappa %.3f < %.2f floor" % (kappa, config.KAPPA_FLOOR)
        )
    elif kappa_flips:
        canonical_unmet.append(
            "kappa %.3f meets the %.2f floor but the verdict is unstable: %d single "
            "verdict flip(s) would drop it below, so the floor was reached by a margin "
            "too thin to certify" % (kappa, config.KAPPA_FLOOR, kappa_flips)
        )

    # Source-side evidence is everything except the convention claims. It is what
    # `translator_declared` requires and it is reported separately so an operator
    # can see which of the two claims is missing.
    source_evidence_unmet = unmet + canonical_unmet
    source_evidence_ok = not source_evidence_unmet
    canonical_unmet = canonical_unmet + convention_unmet

    if provisional_ok and not canonical_unmet:
        stage = config.STAGE_CANONICAL
        reasons: List[str] = []
    elif provisional_ok:
        stage = config.STAGE_PROVISIONAL
        reasons = canonical_unmet
    else:
        stage = config.STAGE_OBSERVED
        reasons = unmet + canonical_unmet

    return {
        "type_id": type_id,
        "stage": stage,
        "occurrences": occurrences,
        "independent_sources": sources,
        "e1e2_sources": e1e2,
        "adopted_precedents": adopted,
        "unresolved_contradictions": contradictions,
        "dual_review_agreeing": agreeing,
        "human_confirms": human_confirms,
        "kappa": None if kappa is None else round(kappa, 6),
        "kappa_downward_flips": kappa_flips,
        "source_evidence_ok": source_evidence_ok,
        "source_evidence_unmet": source_evidence_unmet,
        "unmet": reasons,
    }


def graduation_report(
    samples: Sequence[Dict[str, Any]],
    *,
    catalogue_version: str,
    generated_at: str,
    type_ids: Sequence[str],
    precedent_facts: Dict[str, Dict[str, int]],
    confirms_by_type: Dict[str, int],
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """A validated ``graduation_report`` artifact over *type_ids*.

    ``generated_at`` is injected rather than read from the clock so the artifact
    is reproducible and its digest is stable.
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for row in samples:
        grouped.setdefault(row["type_id"], []).append(row)
    entries = [
        graduate(
            type_id,
            grouped.get(type_id, []),
            precedent_facts.get(type_id, {}),
            confirms_by_type.get(type_id, 0),
        )
        for type_id in type_ids
    ]
    report = {
        "catalogue_version": catalogue_version,
        "generated_at": generated_at,
        "types": entries,
    }
    if notes:
        report["notes"] = notes
    schemas.require("graduation_report", report)
    return report


def lint(root: Optional[str] = None) -> findings.FindingSet:
    """Publish every corpus defect this phase can decide mechanically."""
    result = findings.FindingSet()
    try:
        drafts = load_drafts(root)
    except CorpusError as exc:
        result.add(findings.hard("corpus_drafts_unloadable", str(exc)))
        return result
    if not drafts:
        result.add(
            findings.hard(
                "corpus_drafts_empty",
                "%s holds no rows; a corpus lint that returns clean on an empty "
                "corpus has checked nothing" % drafts_path(root),
            )
        )
        return result
    try:
        reviews = load_reviews(root)
    except CorpusError as exc:
        result.add(findings.hard("corpus_reviews_unloadable", str(exc)))
        return result
    if len(reviews) < 2:
        result.add(
            findings.hard(
                "corpus_reviewers_insufficient",
                "%s holds %d reviewer file(s); dual review needs two independent "
                "reviewers, and with fewer no row can graduate"
                % (reviews_dir(root), len(reviews)),
            )
        )
    samples, merge_findings = merge(drafts, reviews)
    result.extend(merge_findings)
    # The quotation lint runs on the DRAFTS, in file order, because that is what
    # is committed to the repository. Running it only on merged rows would let an
    # unreviewed row carry an over-length quote with nothing checking it.
    result.extend(copyright_lint(drafts))
    if not samples and reviews:
        result.add(
            findings.hard(
                "corpus_no_row_merged",
                "no draft survived review to become a sample, so no evidence is "
                "available to any graduation decision",
            )
        )
    return result
