"""Source-side speech-style types and their target realisations.

This module owns three things every later phase depends on:

1. **Resolution.** A type or realisation may derive from another via
   ``preset`` + ``overrides``. Nothing downstream should ever see a derivation;
   it sees the resolved artifact, validated against the full closed schema.
2. **The shared marker measure.** ``matched_markers`` turns a pattern set into the
   set of probe rows it matches, and every similarity question is asked over those
   sets. Two questions, two measures, because they are different shapes:
   ``jaccard`` for the symmetric "are these distinguishable", and ``containment``
   for the asymmetric "does this reproduce that rejected rendering". Using Jaccard
   for the second let an offender dilute the score by adding unrelated patterns.
3. **The distinguishability lint**, whose remedy for a failing pair is a merge,
   not a suppression.

Two deliberate rulings are recorded here because both are places where a
plausible-looking implementation would produce a gate that does not work.

**The plan's conjunction is wrong in both directions, so neither half survives.**
The approved plan says two items are *distinct* iff ``jaccard < 0.5`` **and** their
density bands do not overlap. Read literally, a genuinely distinct pair whose bands
merely overlap -- the common case -- would be forced to merge, so the lint would
fire on faithful catalogue work. But the De Morgan flip this module first shipped
was worse in the other direction: it let ``not overlapping`` alone certify
distinctness at Jaccard 1.0, so two realisations with byte-identical pattern sets
passed by nudging one default band out of overlap. That escape was not theoretical
and it was reachable on the realisation side, which is the side actually enforced.

The band cannot carry this decision at all: ``resolve_axis_set`` and
``schemas._validate_resolved_axes`` carry no band into the sealed contract axis, and
``density_band_default`` is a default any per-character contract overrides. A
distinction that evaporates at the seam where enforcement begins is not a
distinction.

So the rule is the marker measure alone: a pair is **indistinguishable** iff
``jaccard >= JACCARD_DISTINCT_MAX``. ``test_typology`` carries both cases -- the
faithful pair at Jaccard 0.0 that must stay silent, and the identical-pattern pair
that must be reported however the bands are set.

**Empty match sets are not evidence of distinctness.** If neither pattern set
matches anything on the probe corpus, the honest reading is that the probe
corpus cannot tell them apart, so ``jaccard`` returns 1.0 for empty/empty rather
than the 0.0 that set arithmetic would suggest, and an empty match set is
independently a hard finding. A pattern that can match nothing is a check that
can never fail.
"""
import copy
import json
import os
import re
from typing import Any, Callable, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from . import config, findings, schemas


# The types the story commits to seeding. Deliberately a code constant rather
# than a schema field: "is this a seed type" is a statement about this release's
# scope, not a property of the linguistic type, and putting it on disk would
# invite editing the scope to match whatever graduated.
SEED_TYPE_IDS = (
    "ja_nyan_copula",
    "ja_otaku_copula",
    "ja_chuunibyou_frame",
    "ja_seumda_ssu",
    "ja_danakka_dearimasu",
    "ja_hao_gozaru",
    "ja_elder_lexicon",
    "ja_nanodesu",
    "en_eye_dialect_fleur",
)

_INTERMITTENT_MARKER = "intermittent"
_SATURATED_BAND = [1.0, 1.0]


class CatalogueError(Exception):
    """A catalogue that cannot be loaded. Never downgraded to a warning."""


def _root(root: Optional[str] = None) -> str:
    return config.typology_root() if root is None else root


def catalogue_version(root: Optional[str] = None) -> str:
    path = os.path.join(_root(root), "VERSION")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            version = fh.read().strip()
    except OSError as exc:
        raise CatalogueError("catalogue version file is unreadable: %s" % exc)
    if not version:
        raise CatalogueError(
            "catalogue version file %s is empty; a contract stores the catalogue "
            "version it was sealed against, and an empty version makes that "
            "provenance unverifiable" % path
        )
    return version


def _read_json(path: str) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as exc:
        raise CatalogueError("%s: %s" % (path, exc))


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
                    raise CatalogueError("%s:%d: %s" % (path, index, exc))
    except OSError as exc:
        raise CatalogueError("%s: %s" % (path, exc))
    return rows


def _deep_merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Override wins, recursing into nested objects only.

    A list override REPLACES rather than extends. Extending would make a derived
    pattern set silently inherit the preset's patterns as well, so a derivation
    intended to narrow a marker would widen it instead.
    """
    merged = copy.deepcopy(base)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def _resolve(kind: str, raw: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Resolve every ``preset`` derivation, then validate the resolved artifacts.

    The resolved artifact is what gets the full closed-schema check. A derivation
    row is allowed to omit what its preset supplies, so validating only the raw
    rows would let an incomplete final artifact through.
    """
    resolved: Dict[str, Dict[str, Any]] = {}

    def resolve_one(artifact_id: str, seen: Tuple[str, ...]) -> Dict[str, Any]:
        if artifact_id in resolved:
            return resolved[artifact_id]
        if artifact_id in seen:
            raise CatalogueError(
                "%s preset cycle: %s"
                % (kind, " -> ".join(seen + (artifact_id,)))
            )
        if artifact_id not in raw:
            raise CatalogueError("%s %r does not exist" % (kind, artifact_id))
        row = raw[artifact_id]
        preset_id = row.get("preset")
        if preset_id is None:
            out = copy.deepcopy(row)
        else:
            if preset_id not in raw:
                raise CatalogueError(
                    "%s %r derives from preset %r, which does not exist; a "
                    "dangling preset must not resolve to the derivation itself"
                    % (kind, artifact_id, preset_id)
                )
            base = resolve_one(preset_id, seen + (artifact_id,))
            out = _deep_merge(base, row.get("overrides", {}))
            out.pop("preset", None)
            out.pop("overrides", None)
            # The deriving row keeps its own identity; inheriting the preset's id
            # would collapse two catalogue rows into one join key.
            out["id"] = artifact_id
        errors = schemas.validate(kind, out)
        if errors:
            raise CatalogueError(
                "%s %r does not satisfy the closed schema after resolution: %s"
                % (kind, artifact_id, "; ".join(errors))
            )
        resolved[artifact_id] = out
        return out

    for artifact_id in sorted(raw):
        resolve_one(artifact_id, ())
    return resolved


def _load_dir(kind: str, directory: str) -> Dict[str, Dict[str, Any]]:
    if not os.path.isdir(directory):
        raise CatalogueError("%s directory is missing: %s" % (kind, directory))
    raw: Dict[str, Dict[str, Any]] = {}
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(directory, name)
        row = _read_json(path)
        if not isinstance(row, dict):
            raise CatalogueError("%s: expected a JSON object" % path)
        stem = name[: -len(".json")]
        artifact_id = row.get("id")
        # The filename is a second spelling of the id. If they can disagree, one
        # row is reachable under two names and a join drops evidence silently.
        if artifact_id != stem:
            raise CatalogueError(
                "%s declares id %r but its filename stem is %r; the two must "
                "agree or one row becomes reachable under two join keys"
                % (path, artifact_id, stem)
            )
        if artifact_id in raw:
            raise CatalogueError("duplicate %s id %r" % (kind, artifact_id))
        raw[artifact_id] = row
    if not raw:
        raise CatalogueError("%s directory %s ships no artifacts" % (kind, directory))
    return raw


def load_types(root: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Every type, fully resolved and schema-valid."""
    return _resolve("type", _load_dir("type", os.path.join(_root(root), "types")))


def load_realisations(
    target_lang: str, root: Optional[str] = None
) -> Dict[str, Dict[str, Any]]:
    """Every realisation for one target language, fully resolved."""
    directory = os.path.join(_root(root), "realisations", target_lang)
    resolved = _resolve("realisation", _load_dir("realisation", directory))
    mismatched = [
        artifact_id
        for artifact_id, row in sorted(resolved.items())
        if row.get("target_lang") != target_lang
    ]
    if mismatched:
        raise CatalogueError(
            "realisations under %s declare a different target_lang: %s"
            % (directory, mismatched)
        )
    return resolved


def load_probe(lang: str, root: Optional[str] = None) -> List[Dict[str, Any]]:
    path = os.path.join(_root(root), "probe", "%s.jsonl" % lang)
    if not os.path.isfile(path):
        raise CatalogueError(
            "probe corpus for %r is missing at %s; without it the "
            "distinguishability lint has nothing to compare on and would pass "
            "vacuously" % (lang, path)
        )
    rows = _read_jsonl(path)
    seen = set()
    for row in rows:
        errors = schemas.validate("probe_row", row)
        if errors:
            raise CatalogueError("%s: %s" % (path, "; ".join(errors)))
        if row["lang"] != lang:
            raise CatalogueError(
                "%s: row %r declares lang %r" % (path, row["id"], row["lang"])
            )
        if row["id"] in seen:
            raise CatalogueError("%s: duplicate probe id %r" % (path, row["id"]))
        seen.add(row["id"])
    if not rows:
        raise CatalogueError("probe corpus %s is empty" % path)
    return rows


# The flags the frozen enforcement matcher uses. `measure.pattern_match` compiles
# with IGNORECASE, so compiling case-sensitively here would make the probe measure
# and the enforcement measure two different matchers -- which falsifies this
# module's whole "one measure" claim. It was not hypothetical: `\bzis\b` and
# `\bzat\b` failed to match their own sentence-initial probe rows, so two enforced
# patterns carried no probe verification at all.
PATTERN_FLAGS = re.IGNORECASE


def compile_patterns(pattern_set: Sequence[str]) -> List["re.Pattern"]:
    compiled = []
    for pattern in pattern_set:
        try:
            compiled.append(re.compile(pattern, PATTERN_FLAGS))
        except re.error as exc:
            raise CatalogueError("pattern %r does not compile: %s" % (pattern, exc))
    return compiled


def matched_markers(
    pattern_set: Sequence[str], lang: str, *, probe: Optional[Sequence[dict]] = None,
    root: Optional[str] = None,
) -> FrozenSet[str]:
    """Probe-row ids that ANY pattern in *pattern_set* matches.

    This is the shared "matched-marker set on a shared probe corpus". Both the
    distinguishability lint and the rejected-precedent matcher consume it, so
    similarity means one thing across the whole project.
    """
    rows = load_probe(lang, root=root) if probe is None else probe
    compiled = compile_patterns(pattern_set)
    return frozenset(
        row["id"]
        for row in rows
        if any(rx.search(row["text"]) for rx in compiled)
    )


def jaccard(a: Iterable[str], b: Iterable[str]) -> float:
    """Set similarity, with the empty/empty case decided deliberately.

    Two pattern sets that match nothing are not evidence of distinctness; they
    are evidence the probe corpus cannot separate them. Returning 0.0 there would
    read as "distinct" and let two unmeasurable markers coexist, so this returns
    1.0 and the empty match set is separately reported as hard.
    """
    left, right = frozenset(a), frozenset(b)
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 1.0
    return len(left & right) / len(union)


def containment(subject: Iterable[str], reference: Iterable[str]) -> float:
    """Fraction of *reference* that *subject* reproduces. Deliberately asymmetric.

    "Are these two markers distinguishable?" is symmetric and Jaccard answers it.
    "Does this realisation REPRODUCE that rejected rendering?" is not: Jaccard's
    union denominator lets an offender shrink the score by adding unrelated
    patterns, so a realisation shipping a rejected caricature alongside four
    legitimate patterns scored 0.2 and cleared a 0.5 gate. Containment cannot be
    diluted that way.

    Empty reference returns 1.0, matching `jaccard`'s convention: nothing to
    reproduce is not evidence of innocence, and the caller reports the gap.
    """
    subject, reference = frozenset(subject), frozenset(reference)
    if not reference:
        return 1.0
    return len(subject & reference) / len(reference)


def bands_overlap(a: Sequence[float], b: Sequence[float]) -> bool:
    """True when two ``[lo, hi]`` bands share any value, endpoints included.

    No longer part of the distinguishability rule -- see the module docstring for
    why the band conjunct was removed. Retained because a band comparison is still
    the right question elsewhere, and callers ask it directly.
    """
    return not (a[1] < b[0] or b[1] < a[0])


def _derives_from(
    left_id: str, right_id: str, raw_presets: Dict[str, Optional[str]]
) -> bool:
    """True when either id reaches the other through a chain of presets.

    A merge is the prescribed remedy for an indistinguishable pair, so once the
    merge exists the pair must stop being reported. Otherwise the only way to
    silence the finding would be to delete one of the rows, and the lint would be
    punishing the fix it asked for.
    """
    for start, target in ((left_id, right_id), (right_id, left_id)):
        seen = set()
        current = raw_presets.get(start)
        while current is not None and current not in seen:
            if current == target:
                return True
            seen.add(current)
            current = raw_presets.get(current)
    return False


def distinguishability(
    items: Dict[str, Dict[str, Any]],
    lang: str,
    *,
    raw_presets: Optional[Dict[str, Optional[str]]] = None,
    probe: Optional[Sequence[dict]] = None,
    root: Optional[str] = None,
    label: str = "item",
) -> Tuple[List[findings.Finding], int]:
    """Report indistinguishable pairs, and return how many pairs were compared.

    A pair is indistinguishable iff the marker sets are at or above
    ``JACCARD_DISTINCT_MAX`` similar AND their bands overlap. See the module
    docstring for why this is not the plan's literal conjunction.

    The pair count is returned rather than converted into a finding here. A group
    holding exactly one item has no pair to compare, and that is not a defect --
    this release ships exactly one EN-source seed type -- so non-vacuity has to be
    judged across the whole lint rather than per group. Asserting it here would
    fire on a faithful catalogue, which this project treats as just as broken as a
    gate that never fires.
    """
    rows = load_probe(lang, root=root) if probe is None else probe
    controls = frozenset(
        row["id"]
        for row in rows
        if row.get("markedness") == config.PROBE_UNMARKED
    )
    presets = raw_presets or {}
    out: List[findings.Finding] = []
    matches: Dict[str, FrozenSet[str]] = {}
    for item_id, item in sorted(items.items()):
        pattern_set = item.get("pattern_set") or []
        matches[item_id] = matched_markers(pattern_set, lang, probe=rows)
        if not matches[item_id]:
            out.append(
                findings.hard(
                    "typology_pattern_matches_nothing",
                    "%s %s matches no row of the %s probe corpus; a pattern set "
                    "that cannot match anything is a check that can never fail"
                    % (label, item_id, lang),
                    scope=item_id,
                    axis=item.get("axis"),
                )
            )
        # Per pattern, not only per set. A set with one live pattern and three that
        # can never match used to pass whole, so eleven shipped patterns carried no
        # probe verification and nothing said so. Report rather than hard: a probe
        # corpus need not cover every attested variant, and making this hard would
        # punish honest breadth. The wholly-empty set above stays hard.
        for index, pattern in enumerate(pattern_set):
            if not matched_markers([pattern], lang, probe=rows):
                out.append(
                    findings.report(
                        "typology_pattern_unprobed",
                        "%s %s pattern[%d] %r matches no %s probe row, so it is "
                        "enforced without verification; this is a recorded "
                        "coverage gap, not a clean result"
                        % (label, item_id, index, pattern, lang),
                        scope="%s|%d" % (item_id, index),
                    )
                )
        # The control check. The probe corpus ships rows authored to carry no
        # marker at all; a pattern that fires on one of them will score ordinary
        # unmarked speech as carrying the marker, which reports faithful
        # translation as LOSS and lets a flattened translation look marked. This is
        # the check whose absence let four over-generic patterns reach the enforced
        # artifacts.
        hit_controls = sorted(matches[item_id] & controls)
        if hit_controls:
            out.append(
                findings.hard(
                    "typology_pattern_matches_unmarked_row",
                    "%s %s matches unmarked control row(s) %s of the %s probe "
                    "corpus; a pattern that fires on ordinary speech cannot "
                    "distinguish a character marker from the language"
                    % (label, item_id, ", ".join(hit_controls), lang),
                    scope=item_id,
                    axis=item.get("axis"),
                )
            )
    ids = sorted(items)
    compared = 0
    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1 :]:
            compared += 1
            if _derives_from(left_id, right_id, presets):
                continue
            similarity = jaccard(matches[left_id], matches[right_id])
            if similarity >= config.JACCARD_DISTINCT_MAX:
                out.append(
                    findings.hard(
                        "typology_indistinguishable_pair",
                        "%s %s and %s match the probe corpus with Jaccard %.3f "
                        "(>= %.2f), so the catalogue asserts a difference it "
                        "cannot measure; merge one into the other as preset + "
                        "overrides rather than keeping both"
                        % (
                            label,
                            left_id,
                            right_id,
                            similarity,
                            config.JACCARD_DISTINCT_MAX,
                        ),
                        scope="%s|%s" % (left_id, right_id),
                    )
                )
    return out, compared


def similarity_matrix(
    items: Dict[str, Dict[str, Any]], lang: str, *, root: Optional[str] = None
) -> Dict[str, Dict[str, float]]:
    """Full pairwise Jaccard table, for publication in a report artifact."""
    rows = load_probe(lang, root=root)
    matches = {
        item_id: matched_markers(item.get("pattern_set") or [], lang, probe=rows)
        for item_id, item in items.items()
    }
    return {
        left: {
            right: jaccard(matches[left], matches[right])
            for right in sorted(matches)
            if right != left
        }
        for left in sorted(matches)
    }


def resolve_axis_set(
    type_ids: Sequence[str],
    target_lang: str,
    *,
    root: Optional[str] = None,
    axis_status: Callable[[str], Dict[str, str]],
    measurable: Sequence[str],
) -> List[Dict[str, Any]]:
    """The resolved axis set a contract stores, minus the per-marker digest.

    Each entry carries exactly ``axis``, ``marker`` and ``pattern_set`` -- the three
    keys ``contract.axes[i]`` requires besides the digest. Nothing else is emitted,
    because the contract schema is closed: an extra convenience key would make the
    documented instruction below impossible to follow and would tempt a P2
    implementer to widen the closed schema instead, which is the one thing that
    must not happen.

    ``axis_status`` and ``measurable`` are REQUIRED, not optional. They were
    keyword-with-default first, which made the refusal to seal an unmeasurable axis
    opt-in: any caller that forgot the injection sealed anything. A guard that
    defaults to off is not a guard.

    The digest is deliberately absent. It binds a marker to the corpus rows that
    justified it, and that binding is sealed in P2 where the corpus is fixed;
    computing one here would produce a digest over whatever the catalogue happened
    to hold at load time, which is a provenance claim this phase cannot support.
    Callers requiring a sealed axis set add ``corpus_digest`` to each entry and
    nothing else, and ``schemas.validate("contract", ...)`` rejects the artifact
    until they do.
    """
    types = load_types(root=root)
    # Loaded so an unrealised type is refused rather than sealed: a contract axis
    # with no target realisation is a marker nothing can enforce.
    realisations = load_realisations(target_lang, root=root)
    realised = {r["type_id"] for r in realisations.values()}
    out = []
    seen_patterns: Dict[Tuple[str, ...], str] = {}
    for type_id in type_ids:
        if type_id not in types:
            raise CatalogueError("type %r is not in the catalogue" % type_id)
        if type_id not in realised:
            raise CatalogueError(
                "type %r has no %s realisation, so its axis cannot be enforced"
                % (type_id, target_lang)
            )
        ok, reasons = sealable(
            type_id,
            types,
            realisations,
            target_lang,
            axis_status=axis_status,
            measurable=measurable,
        )
        if not ok:
            raise CatalogueError(
                "type %r cannot be sealed: %s. Sealing a marker whose density is a "
                "constant would produce a contract whose gate can never fire, "
                "which is worse than no contract"
                % (type_id, "; ".join(reasons))
            )
        source = types[type_id]
        key = tuple(source["pattern_set"])
        if key in seen_patterns:
            raise CatalogueError(
                "types %r and %r carry identical pattern sets, so sealing both "
                "would count one marker as two independent axis verdicts"
                % (seen_patterns[key], type_id)
            )
        seen_patterns[key] = type_id
        out.append(
            {
                "axis": source["axis"],
                "marker": source["source_marker"],
                "pattern_set": list(source["pattern_set"]),
            }
        )
    return out


def _raw_presets(directory: str) -> Dict[str, Optional[str]]:
    presets: Dict[str, Optional[str]] = {}
    if not os.path.isdir(directory):
        return presets
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            continue
        row = _read_json(os.path.join(directory, name))
        if isinstance(row, dict) and "id" in row:
            presets[row["id"]] = row.get("preset")
    return presets


def target_axis_of(
    realisation: Dict[str, Any], types: Dict[str, Dict[str, Any]]
) -> Optional[str]:
    """The axis a realisation is measured on in the target language.

    Defaults to the source type's axis, because most markers are realised through
    the same mechanism on both sides. A realisation overrides it when the target
    language uses a different mechanism, which is common and legitimate: Korean
    renders a Japanese speech-level marker as a sentence-ending transform.
    """
    declared = realisation.get("target_axis")
    if declared is not None:
        return declared
    source = types.get(realisation["type_id"])
    return None if source is None else source["axis"]


def axis_measurability(
    types: Dict[str, Dict[str, Any]],
    realisations: Dict[str, Dict[str, Any]],
    target_lang: str,
    *,
    axis_status: Callable[[str], Dict[str, str]],
    measurable: Sequence[str],
    exempt_axes: Sequence[str] = (),
) -> List[findings.Finding]:
    """Report a type whose axis its own source-language plugin cannot measure.

    The whole method compares source-marker density against target-marker density.
    An axis a source plugin declares ``not_applicable`` returns False before it ever
    looks at the pattern set, so source density is a constant zero. Either the axis
    is inert -- a gate that can never fire, so LOSS on that marker is undetectable
    -- or a band derived from that constant makes every faithful target rendering
    exceed it, which is a false hard INVENTION. Both branches are broken gates, and
    neither was reported before this check existed.

    The status map is injected rather than imported so this module keeps not
    depending on ``measure``. ``exempt_axes`` is explicit: ``dialect_policy`` is
    owned editorially by ``dialect.py`` rather than by density, and that exemption
    is stated in code with its reason instead of being left as an omission.
    """
    out: List[findings.Finding] = []
    checks = []
    for type_id, source in sorted(types.items()):
        checks.append((type_id, source["axis"], source["source_lang"], "source"))
    for realisation_id, realisation in sorted(realisations.items()):
        axis = target_axis_of(realisation, types)
        if axis is not None:
            checks.append((realisation_id, axis, target_lang, "target"))
    for subject, axis, lang, side in checks:
        if axis in exempt_axes:
            continue
        try:
            statuses = axis_status(lang)
        except LookupError as exc:
            out.append(
                findings.hard(
                    "typology_axis_plugin_missing",
                    "%s needs a %s measure plugin for %r: %s"
                    % (subject, side, lang, exc),
                    scope=subject,
                    axis=axis,
                )
            )
            continue
        if statuses.get(axis) not in measurable:
            # Report, not hard. Cataloguing a marker the current plugins cannot
            # measure is legitimate -- it is a real speech-style type and the
            # limitation is the plugin's, not the catalogue's. What must not happen
            # is SEALING it, and `resolve_axis_set` refuses that separately. Making
            # this hard would instead force deleting honest catalogue entries.
            out.append(
                findings.report(
                    "typology_axis_not_measurable",
                    "%s is measured on axis %r, which the %s plugin for %r declares "
                    "%r (measurable: %s). Every plugin checks its axis declaration "
                    "before consulting a caller's pattern_set, so this marker's %s "
                    "density is a constant and it cannot be enforced. It is "
                    "catalogued but not sealable"
                    % (
                        subject,
                        axis,
                        side,
                        lang,
                        statuses.get(axis),
                        list(measurable),
                        side,
                    ),
                    scope=subject,
                    axis=axis,
                )
            )
    return out


def sealable(
    type_id: str,
    types: Dict[str, Dict[str, Any]],
    realisations: Dict[str, Dict[str, Any]],
    target_lang: str,
    *,
    axis_status: Callable[[str], Dict[str, str]],
    measurable: Sequence[str],
) -> Tuple[bool, List[str]]:
    """Whether a type can be sealed into a contract at all, with reasons.

    Separate from `axis_measurability` because the two answer different questions.
    Cataloguing an unmeasurable marker is honest; sealing one produces a contract
    whose gate can never fire, which is worse than no contract.
    """
    reasons: List[str] = []
    source = types.get(type_id)
    if source is None:
        return False, ["type %r is not in the catalogue" % type_id]
    try:
        source_statuses = axis_status(source["source_lang"])
    except LookupError as exc:
        return False, [str(exc)]
    if source_statuses.get(source["axis"]) not in measurable:
        reasons.append(
            "source plugin for %r declares axis %r as %r"
            % (source["source_lang"], source["axis"], source_statuses.get(source["axis"]))
        )
    own = [r for r in realisations.values() if r["type_id"] == type_id]
    if not own:
        reasons.append("no %s realisation" % target_lang)
    try:
        target_statuses = axis_status(target_lang)
    except LookupError as exc:
        return False, [str(exc)]
    for realisation in sorted(own, key=lambda r: r["id"]):
        axis = target_axis_of(realisation, types)
        if target_statuses.get(axis) not in measurable:
            reasons.append(
                "realisation %s is measured on axis %r, which the %r plugin "
                "declares %r" % (realisation["id"], axis, target_lang,
                                 target_statuses.get(axis))
            )
    return (not reasons), reasons


def channel_backing(
    realisations: Dict[str, Dict[str, Any]],
    adopted_by_id: Dict[str, str],
) -> List[findings.Finding]:
    """A realisation may not claim a publication channel its evidence lacks.

    `edition_channel` says which kind of edition shipped this rendering. Nothing
    read the field before this check existed, so six of nine shipped realisations
    claimed `licensed`, `official` or `community` for renderings their own cited
    precedents record as unpublished project proposals. That is a false provenance
    string on the artifact a contract seals, which is exactly the class of claim
    this project refuses to assert without evidence.

    `adopted_by_id` maps precedent id -> ``(edition_channel, type_id)`` for adopted
    rows only. Passed in so this module does not import the precedent table. The
    type id is part of it because backing must come from a precedent about the SAME
    marker: without that check a realisation could cite an unrelated type's adopted
    row and inherit its publication channel.
    """
    out: List[findings.Finding] = []
    for realisation_id, realisation in sorted(realisations.items()):
        claimed = realisation.get("edition_channel")
        if claimed is None or claimed == config.PRECEDENT_CHANNEL_UNPUBLISHED:
            continue
        backing = sorted(
            {
                adopted_by_id[ref][0]
                for ref in realisation.get("precedents", [])
                if ref in adopted_by_id
                and adopted_by_id[ref][1] == realisation["type_id"]
            }
        )
        if claimed not in backing:
            out.append(
                findings.hard(
                    "typology_channel_unbacked",
                    "realisation %s claims edition_channel %r, but its cited "
                    "adopted precedents support %s. Declare %r unless a published "
                    "edition on that channel is cited"
                    % (
                        realisation_id,
                        claimed,
                        backing or "no channel at all",
                        config.PRECEDENT_CHANNEL_UNPUBLISHED,
                    ),
                    scope=realisation_id,
                )
            )
    return out


def lint(
    root: Optional[str] = None,
    target_lang: str = "ko",
    *,
    axis_status: Optional[Callable[[str], Dict[str, str]]] = None,
    measurable: Sequence[str] = (),
    exempt_axes: Sequence[str] = (),
) -> findings.FindingSet:
    """Publish every catalogue defect this phase can decide mechanically.

    Load failures are converted to hard findings rather than propagating, so one
    broken file cannot hide the state of the rest of the catalogue. An absent or
    empty catalogue is itself hard: a lint that returns clean because there was
    nothing to check has not checked anything.
    """
    result = findings.FindingSet()
    base = _root(root)
    if not os.path.isdir(base):
        result.add(
            findings.hard(
                "typology_catalogue_missing",
                "no catalogue at %s; this lint cannot pass by having nothing to "
                "examine" % base,
            )
        )
        return result

    try:
        version = catalogue_version(base)
    except CatalogueError as exc:
        version = None
        result.add(findings.hard("typology_version_unreadable", str(exc)))

    try:
        types = load_types(base)
    except CatalogueError as exc:
        result.add(findings.hard("typology_types_unloadable", str(exc)))
        return result

    try:
        realisations = load_realisations(target_lang, root=base)
    except CatalogueError as exc:
        result.add(findings.hard("typology_realisations_unloadable", str(exc)))
        realisations = {}

    # Seed coverage. A seed type absent from the catalogue, or present with no
    # target realisation, is a contract this release claims to ship and does not.
    for type_id in SEED_TYPE_IDS:
        if type_id not in types:
            result.add(
                findings.hard(
                    "typology_seed_type_missing",
                    "seed type %s is declared in SEED_TYPE_IDS but absent from "
                    "the catalogue" % type_id,
                    scope=type_id,
                )
            )
    realised_types = {r["type_id"] for r in realisations.values()}
    for type_id in SEED_TYPE_IDS:
        if type_id in types and type_id not in realised_types:
            result.add(
                findings.hard(
                    "typology_seed_type_unrealised",
                    "seed type %s has no %s realisation, so nothing about it can "
                    "be enforced on the target side" % (type_id, target_lang),
                    scope=type_id,
                )
            )
    for realisation_id, realisation in sorted(realisations.items()):
        if realisation["type_id"] not in types:
            result.add(
                findings.hard(
                    "typology_realisation_orphaned",
                    "realisation %s names type %s, which is not in the catalogue"
                    % (realisation_id, realisation["type_id"]),
                    scope=realisation_id,
                )
            )

    # Dangling precedent references. Reported here rather than resolved, because
    # the precedent table is a separate artifact this module must not import.
    precedent_ids = set()
    precedents_path = os.path.join(base, "precedents.jsonl")
    if os.path.isfile(precedents_path):
        try:
            for row in _read_jsonl(precedents_path):
                if isinstance(row, dict) and "id" in row:
                    precedent_ids.add(row["id"])
        except CatalogueError as exc:
            result.add(findings.hard("typology_precedents_unreadable", str(exc)))
    else:
        result.add(
            findings.hard(
                "typology_precedents_missing",
                "no precedents.jsonl at %s; every realisation cites precedent "
                "ids, and with no table those citations are unverifiable"
                % precedents_path,
            )
        )
    for realisation_id, realisation in sorted(realisations.items()):
        for ref in realisation.get("precedents", []):
            if ref not in precedent_ids:
                result.add(
                    findings.hard(
                        "typology_precedent_dangling",
                        "realisation %s cites precedent %s, which does not exist "
                        "in the precedent table" % (realisation_id, ref),
                        scope=realisation_id,
                    )
                )

    # A saturating default band on a marker whose own provenance calls it
    # intermittent. Saturating is the invention defect, so a catalogue that ships
    # it as the default would seed the very failure the metric exists to catch.
    for type_id, source in sorted(types.items()):
        notes = (source.get("provenance") or {}).get("notes", "").lower()
        if _INTERMITTENT_MARKER not in notes:
            continue
        for realisation_id, realisation in sorted(realisations.items()):
            if realisation["type_id"] != type_id:
                continue
            if list(realisation.get("density_band_default") or []) == _SATURATED_BAND:
                result.add(
                    findings.hard(
                        "typology_saturating_band_on_intermittent_marker",
                        "realisation %s defaults to a band of %s while type %s "
                        "records itself as intermittent; saturating a marker the "
                        "source uses intermittently is an invention defect, not "
                        "extra fidelity"
                        % (realisation_id, _SATURATED_BAND, type_id),
                        scope=realisation_id,
                    )
                )

    # Distinguishability, per source language for types and on the target side
    # for realisations. Both directions matter: two source markers may be
    # separable while their target renderings are not.
    by_lang: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for type_id, source in types.items():
        by_lang.setdefault(source["source_lang"], {})[type_id] = source
    type_presets = _raw_presets(os.path.join(base, "types"))
    compared_total = 0
    for lang, group in sorted(by_lang.items()):
        try:
            pair_findings, compared = distinguishability(
                group, lang, raw_presets=type_presets, root=base, label="type"
            )
        except CatalogueError as exc:
            result.add(findings.hard("typology_probe_unusable", str(exc)))
            continue
        result.extend(pair_findings)
        compared_total += compared
    if realisations:
        realisation_presets = _raw_presets(
            os.path.join(base, "realisations", target_lang)
        )
        try:
            pair_findings, compared = distinguishability(
                realisations,
                target_lang,
                raw_presets=realisation_presets,
                root=base,
                label="realisation",
            )
        except CatalogueError as exc:
            result.add(findings.hard("typology_probe_unusable", str(exc)))
        else:
            result.extend(pair_findings)
            compared_total += compared
    # Non-vacuity, judged once across the whole catalogue rather than per group.
    if compared_total == 0:
        result.add(
            findings.hard(
                "typology_no_pair_compared",
                "no pair anywhere in the catalogue was compared for "
                "distinguishability; a lint that examined nothing has not "
                "cleared anything",
            )
        )

    adopted_by_id = {}
    if os.path.isfile(precedents_path):
        try:
            for row in _read_jsonl(precedents_path):
                if (
                    isinstance(row, dict)
                    and row.get("verdict") == config.PRECEDENT_ADOPTED
                    and "id" in row
                ):
                    adopted_by_id[row["id"]] = (
                        row.get("edition_channel"),
                        row.get("type_id"),
                    )
        except CatalogueError:
            pass  # already reported above as typology_precedents_unreadable
    result.extend(channel_backing(realisations, adopted_by_id))

    if axis_status is not None:
        result.extend(
            axis_measurability(
                types,
                realisations,
                target_lang,
                axis_status=axis_status,
                measurable=measurable,
                exempt_axes=exempt_axes,
            )
        )

    if version is not None and not result.hard:
        result.add(
            findings.report(
                "typology_catalogue_clean",
                "catalogue %s: %d types, %d %s realisations, %d seed types"
                % (version, len(types), len(realisations), target_lang,
                   len(SEED_TYPE_IDS)),
            )
        )
    return result
