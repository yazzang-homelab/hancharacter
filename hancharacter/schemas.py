"""Closed JSON artifact validation for the character measurement catalogue."""
import re
from typing import Any, Dict, Iterable, List, Sequence

from hancharacter import config


KINDS = (
    "type",
    "realisation",
    "contract",
    "corpus_draft",
    "corpus_review",
    "corpus_sample",
    "precedent",
    "human_confirm",
    "dialect_decision",
    "probe_row",
    "graduation_report",
    "waiver",
    "manifest",
    "profile",
)

AXES = frozenset(
    {
        "speech_level",
        "pronouns",
        "ending_transform",
        "interjection_laugh",
        "lexical_register",
        "sentence_habit",
        "dialect_policy",
        "orthographic_distortion",
        "punctuation_policy",
        "utterance_frame",
        "phoneme_substitution",
    }
)
_LENGTH_COST_MODELS = ("append", "multiply", "split")
# Corpus review verdicts and precedent verdicts are separate vocabularies on
# purpose; see the note on `config.REVIEW_VERDICTS`.
_VERDICTS = config.REVIEW_VERDICTS
_PRECEDENT_VERDICTS = config.PRECEDENT_VERDICTS
_SOURCE_CLASSES = config.SOURCE_CLASSES
_EDITION_CHANNELS = ("official", "licensed", "community", "unpublished")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SHA1_RE = re.compile(r"[0-9a-f]{40}")
_ID_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*")


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _add_missing(errors: List[str], kind: str, obj: Dict[str, Any], required: Iterable[str]) -> None:
    for key in required:
        if key not in obj:
            errors.append("%s: missing required key %r" % (kind, key))


def _closed(
    errors: List[str],
    label: str,
    obj: Any,
    required: Sequence[str],
    allowed: Sequence[str],
) -> bool:
    if not isinstance(obj, dict):
        errors.append("%s: expected object" % label)
        return False
    for key in required:
        if key not in obj:
            errors.append("%s: missing required key %r" % (label, key))
    for key in obj:
        if key not in allowed:
            errors.append("%s: unknown key %r" % (label, key))
    return True


def _string(errors: List[str], label: str, value: Any) -> None:
    if not isinstance(value, str) or not value:
        errors.append("%s: expected a non-empty string" % label)


def _language(errors: List[str], label: str, value: Any) -> None:
    _string(errors, label, value)
    if isinstance(value, str) and not re.fullmatch(r"[a-z]{2,3}(?:-[A-Za-z0-9]+)*", value):
        errors.append("%s: expected a language code" % label)


def _axis(errors: List[str], label: str, value: Any) -> None:
    if value not in AXES:
        errors.append("%s: expected one of %s" % (label, sorted(AXES)))


def _sha256(errors: List[str], label: str, value: Any) -> None:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        errors.append("%s: expected a lowercase SHA-256 digest" % label)

def _sha1(errors: List[str], label: str, value: Any) -> None:
    if not isinstance(value, str) or not _SHA1_RE.fullmatch(value):
        errors.append("%s: expected a lowercase SHA-1 digest" % label)


def _id(errors: List[str], label: str, value: Any) -> None:
    """Validate a join key.

    Every catalogue artifact is joined by id, so an id carrying a space, an
    uppercase letter or a path separator would produce two spellings of the same
    row and a join that silently drops evidence.
    """
    if not isinstance(value, str) or not value or not _ID_RE.fullmatch(value):
        errors.append(
            "%s: expected a lowercase id matching %s" % (label, _ID_RE.pattern)
        )


def _enum(errors: List[str], label: str, value: Any, allowed: Sequence[str]) -> None:
    if value not in allowed:
        errors.append("%s: expected one of %s" % (label, list(allowed)))


def _timestamp(errors: List[str], label: str, value: Any) -> None:
    """Require an ISO-8601 UTC instant.

    A free-form date string would make "confirmed before the edit" unorderable,
    and the staleness rule for a dialect decision depends on that ordering.
    """
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value
    ):
        errors.append("%s: expected an ISO-8601 UTC timestamp ending in Z" % label)


def _string_list(errors: List[str], label: str, value: Any, *, nonempty: bool = False) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        errors.append("%s: expected a list of non-empty strings" % label)
    elif nonempty and not value:
        errors.append("%s: expected a non-empty list" % label)


def _quantifier_end(pattern: str, index: int):
    """Return the first index after a regex quantifier beginning at *index*."""
    if pattern[index] in "*+?":
        return index + 1
    if pattern[index] != "{":
        return None
    match = re.match(r"\{\d+(?:,\d*)?\}", pattern[index:])
    return None if match is None else index + match.end()


def _has_nested_quantifier(pattern: str) -> bool:
    """Detect a quantified group that already contains a quantifier.

    This is deliberately a declaration-time heuristic, not a claim that every
    expensive regular expression can be recognised or time-bounded by `re`.
    """
    groups = []
    escaped = False
    in_class = False
    index = 0
    while index < len(pattern):
        character = pattern[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\":
            escaped = True
            index += 1
            continue
        if in_class:
            if character == "]":
                in_class = False
            index += 1
            continue
        if character == "[":
            in_class = True
            index += 1
            continue
        if character == "(":
            groups.append(False)
            index += 1
            continue
        if character == ")":
            contains_quantifier = groups.pop() if groups else False
            quantifier_end = (
                _quantifier_end(pattern, index + 1)
                if index + 1 < len(pattern)
                else None
            )
            if quantifier_end is not None:
                if contains_quantifier:
                    return True
                if groups:
                    groups[-1] = True
            index += 1
            continue
        quantifier_end = _quantifier_end(pattern, index)
        if quantifier_end is not None:
            # The `?` that introduces `(?:...)`, `(?P<...>)`, and lookarounds is
            # group syntax, not an optional repetition inside the group.
            if groups and not (character == "?" and index > 0 and pattern[index - 1] == "("):
                groups[-1] = True
            index = quantifier_end
            continue
        index += 1
    return False



def _pattern_list(errors: List[str], label: str, value: Any, *, nonempty: bool = False) -> None:
    _string_list(errors, label, value, nonempty=nonempty)
    if not isinstance(value, list):
        return
    for index, pattern in enumerate(value):
        if not isinstance(pattern, str):
            continue
        try:
            re.compile(pattern)
        except re.error as error:
            errors.append("%s[%d]: invalid regular expression: %s" % (label, index, error))
        else:
            if _has_nested_quantifier(pattern):
                errors.append(
                    "%s[%d]: nested quantified group is not permitted" % (label, index)
                )


def _validate_provenance(value: Any, errors: List[str]) -> None:
    """A type must say why it exists, not merely that it does.

    `origin` separates a regional dialect from a historical register from an
    individual quirk. Without it a target realisation cannot be chosen honestly:
    a regional origin invites a regional target strategy, and a character quirk
    does not.
    """
    if not _closed(
        errors,
        "type.provenance",
        value,
        ("origin", "notes"),
        ("origin", "notes"),
    ):
        return
    _enum(errors, "type.provenance.origin", value.get("origin"), config.TYPE_ORIGINS)
    _string(errors, "type.provenance.notes", value.get("notes"))


def _derivation_required(obj: Dict[str, Any], required: Sequence[str]) -> Sequence[str]:
    """Relax the required set for a preset derivation.

    A row carrying `preset` is a derivation, not a finished artifact: the fields it
    omits are supplied by resolving the preset. Demanding them on disk would force
    every derived row to restate the preset, which defeats the merge the
    distinguishability lint prescribes as its remedy.

    This does NOT weaken the schema. `typology` validates the RESOLVED artifact
    against the full required set, so an incomplete row is caught at load time
    rather than at write time. The two checks answer different questions: is this
    derivation well-formed, and is what it resolves to a complete artifact.
    """
    if "preset" not in obj:
        return required
    return tuple(key for key in required if key in ("id",)) + ("preset", "overrides")


def _validate_type(obj: Dict[str, Any], errors: List[str]) -> None:
    required = ("id", "axis", "source_lang", "source_marker", "pattern_set", "provenance")
    allowed = required + ("description", "aliases", "preset", "overrides")
    _add_missing(errors, "type", obj, _derivation_required(obj, required))
    for key in obj:
        if key not in allowed:
            errors.append("type: unknown key %r" % key)
    if "id" in obj:
        _id(errors, "type.id", obj["id"])
    if "source_marker" in obj:
        _string(errors, "type.source_marker", obj["source_marker"])
    if "axis" in obj:
        _axis(errors, "type.axis", obj["axis"])
    if "source_lang" in obj:
        _language(errors, "type.source_lang", obj["source_lang"])
    if "pattern_set" in obj:
        _pattern_list(errors, "type.pattern_set", obj["pattern_set"], nonempty=True)
    if "provenance" in obj:
        _validate_provenance(obj["provenance"], errors)
    if "description" in obj:
        _string(errors, "type.description", obj["description"])
    if "aliases" in obj:
        _string_list(errors, "type.aliases", obj["aliases"])
    # A pair that fails the distinguishability lint must be merged as a preset
    # plus overrides rather than kept as two types, so the merge has to be
    # expressible here or the lint has no remedy and would just be disabled.
    if "preset" in obj:
        _id(errors, "type.preset", obj["preset"])
    if "overrides" in obj:
        if not isinstance(obj["overrides"], dict) or not obj["overrides"]:
            errors.append("type.overrides: expected a non-empty object")
        elif "preset" not in obj:
            errors.append("type.overrides: meaningless without type.preset")


def _validate_length_cost(value: Any, errors: List[str]) -> None:
    if not _closed(
        errors,
        "realisation.length_cost",
        value,
        ("model", "value"),
        ("model", "value"),
    ):
        return
    model = value.get("model")
    if model not in _LENGTH_COST_MODELS:
        errors.append(
            "realisation.length_cost.model: expected one of %s"
            % list(_LENGTH_COST_MODELS)
        )
    cost = value.get("value")
    if not _is_number(cost) or cost < 0:
        errors.append("realisation.length_cost.value: expected a non-negative number")


def _validate_band(value: Any, errors: List[str], label: str) -> None:
    """Require a two-element density band inside [0, 1] with lo <= hi.

    A default band is what the metric compares against before a work supplies its
    own measured distribution, so an inverted or out-of-range band would produce a
    comparison no realisation can satisfy or one every realisation satisfies.
    """
    if not isinstance(value, list) or len(value) != 2 or not all(_is_number(v) for v in value):
        errors.append("%s: expected a two-element [lo, hi] list of numbers" % label)
        return
    lo, hi = value
    if not (0.0 <= lo <= hi <= 1.0):
        errors.append("%s: expected 0 <= lo <= hi <= 1, got [%r, %r]" % (label, lo, hi))


def _validate_realisation(obj: Dict[str, Any], errors: List[str]) -> None:
    required = (
        "id",
        "type_id",
        "source_lang",
        "target_lang",
        "source_marker",
        "target_realisation",
        "length_cost",
        "precedents",
        "density_band_default",
    )
    allowed = required + (
        "notes",
        "glyph_requirements",
        "edition_channel",
        "pattern_set",
        # The axis this realisation is MEASURED ON in the target language, when
        # that differs from the source type's axis. Korean renders a Japanese
        # speech-level marker as a sentence-ending transform, so the source axis and
        # the target axis are genuinely different questions. This matters because
        # every measure plugin checks its `AXES` declaration BEFORE consulting a
        # caller's pattern set, so a realisation measured on an axis its target
        # plugin calls `not_applicable` is dead: its patterns are never applied.
        "target_axis",
        # A pair of realisations the distinguishability lint judges
        # indistinguishable must be merged as preset + overrides rather than kept
        # as two independent rows. Two source markers can legitimately share one
        # target convention -- `~っス` and `~であります` both ship KO
        # `~지 말입니다` -- and the honest record of that is one realisation the
        # other derives from, not two rows asserting they differ.
        "preset",
        "overrides",
    )
    _add_missing(errors, "realisation", obj, _derivation_required(obj, required))
    for key in obj:
        if key not in allowed:
            errors.append("realisation: unknown key %r" % key)
    for key in ("id", "type_id"):
        if key in obj:
            _id(errors, "realisation.%s" % key, obj[key])
    for key in ("source_marker", "target_realisation"):
        if key in obj:
            _string(errors, "realisation.%s" % key, obj[key])
    for key in ("source_lang", "target_lang"):
        if key in obj:
            _language(errors, "realisation.%s" % key, obj[key])
    if "length_cost" in obj:
        _validate_length_cost(obj["length_cost"], errors)
    if "precedents" in obj:
        # Non-empty by schema: a realisation with no precedent reference cannot
        # reach canonical anyway, and allowing an empty list here would let the
        # precedent requirement look satisfiable by omission.
        _string_list(errors, "realisation.precedents", obj["precedents"], nonempty=True)
        for index, ref in enumerate(obj["precedents"] if isinstance(obj["precedents"], list) else []):
            _id(errors, "realisation.precedents[%d]" % index, ref)
    if "density_band_default" in obj:
        _validate_band(obj["density_band_default"], errors, "realisation.density_band_default")
    if "glyph_requirements" in obj:
        _string_list(errors, "realisation.glyph_requirements", obj["glyph_requirements"])
    if "edition_channel" in obj:
        _enum(errors, "realisation.edition_channel", obj["edition_channel"], _EDITION_CHANNELS)
    if "pattern_set" in obj:
        _pattern_list(errors, "realisation.pattern_set", obj["pattern_set"], nonempty=True)
    if "target_axis" in obj:
        _axis(errors, "realisation.target_axis", obj["target_axis"])
    if "preset" in obj:
        _id(errors, "realisation.preset", obj["preset"])
    if "overrides" in obj:
        if not isinstance(obj["overrides"], dict) or not obj["overrides"]:
            errors.append("realisation.overrides: expected a non-empty object")
        elif "preset" not in obj:
            errors.append("realisation.overrides: meaningless without realisation.preset")
    if "notes" in obj:
        _string(errors, "realisation.notes", obj["notes"])


def _validate_resolved_axes(value: Any, errors: List[str]) -> None:
    if not isinstance(value, list) or not value:
        errors.append("contract.axes: expected a non-empty list of resolved markers")
        return
    for index, marker in enumerate(value):
        label = "contract.axes[%d]" % index
        required = ("axis", "marker", "pattern_set", "corpus_digest")
        if not _closed(errors, label, marker, required, required):
            continue
        _axis(errors, "%s.axis" % label, marker.get("axis"))
        _string(errors, "%s.marker" % label, marker.get("marker"))
        _pattern_list(errors, "%s.pattern_set" % label, marker.get("pattern_set"), nonempty=True)
        _sha256(errors, "%s.corpus_digest" % label, marker.get("corpus_digest"))


def _validate_contract(obj: Dict[str, Any], errors: List[str]) -> None:
    required = ("character_id", "source_lang", "catalogue_version", "axes")
    allowed = required + ("plugin_version", "golden_digest", "created_at")
    _add_missing(errors, "contract", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("contract: unknown key %r" % key)
    if "character_id" in obj:
        _string(errors, "contract.character_id", obj["character_id"])
    if "source_lang" in obj:
        _language(errors, "contract.source_lang", obj["source_lang"])
    if "catalogue_version" in obj:
        _string(errors, "contract.catalogue_version", obj["catalogue_version"])
    if "axes" in obj:
        _validate_resolved_axes(obj["axes"], errors)
    if "plugin_version" in obj:
        _string(errors, "contract.plugin_version", obj["plugin_version"])
    if "golden_digest" in obj:
        _sha256(errors, "contract.golden_digest", obj["golden_digest"])
    if "created_at" in obj:
        _string(errors, "contract.created_at", obj["created_at"])


def _validate_corpus_source(value: Any, errors: List[str]) -> None:
    required = ("class", "cite", "consulted_via", "independent_key", "locator")
    if not _closed(errors, "corpus_sample.source", value, required, required):
        return
    source_class = value.get("class")
    _enum(errors, "corpus_sample.source.class", source_class, _SOURCE_CLASSES)
    _string(errors, "corpus_sample.source.cite", value.get("cite"))
    consulted = value.get("consulted_via")
    _enum(errors, "corpus_sample.source.consulted_via", consulted, config.CONSULTED_VIA)
    # `independent_key` is what makes "independent source" decidable by machine.
    # Mirrors of one text must share a key, so three mirrors of one wiki page
    # cannot masquerade as the three independent sources the canonical rule
    # demands. Getting this wrong is the cheapest way to fake graduation.
    _id(errors, "corpus_sample.source.independent_key", value.get("independent_key"))
    # `locator` names the specific page, article, episode or chapter. It exists
    # because independence counting and dump detection need DIFFERENT granularity.
    # Four articles on one wiki are ONE independent source -- they share an
    # editorial community, so counting them separately would fake a graduation
    # floor -- but consecutive rows drawn from four different articles are not a
    # copied passage. Keying dump detection on `independent_key` alone conflates
    # the two and makes an honest, well-spread corpus unshippable, which is a rule
    # that punishes faithful collection instead of catching redistribution.
    _string(errors, "corpus_sample.source.locator", value.get("locator"))
    # The provenance cross-check. A class that outranks what was actually opened is
    # rejected outright rather than downgraded, because a silent downgrade would
    # leave the row counting toward a floor its author believed it cleared.
    if source_class == config.SOURCE_PRIMARY and consulted in config.CONSULTED_VIA:
        if consulted not in config.PRIMARY_CONSULTED_VIA:
            errors.append(
                "corpus_sample.source: class %r requires consulted_via in %s, got %r; "
                "a mirror or a search snippet is not the work itself"
                % (config.SOURCE_PRIMARY, list(config.PRIMARY_CONSULTED_VIA), consulted)
            )
    if source_class == config.SOURCE_SECONDARY and consulted in config.CONSULTED_VIA:
        if consulted not in config.SECONDARY_CONSULTED_VIA:
            errors.append(
                "corpus_sample.source: class %r requires consulted_via in %s, got %r; "
                "someone else's citation of a source is hearsay, and hearsay that "
                "counts toward a graduation floor is a fabricated floor"
                % (
                    config.SOURCE_SECONDARY,
                    list(config.SECONDARY_CONSULTED_VIA),
                    consulted,
                )
            )


def _validate_corpus_sample(obj: Dict[str, Any], errors: List[str]) -> None:
    required = (
        "id",
        "type_id",
        "axis",
        "work",
        "producer",
        "reviewer",
        "review2",
        "reviewer_verdicts",
        "verdict",
        "quote",
        "quote_len",
        "source",
    )
    allowed = required + ("marker", "notes")
    _add_missing(errors, "corpus_sample", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("corpus_sample: unknown key %r" % key)
    for key in ("id", "type_id"):
        if key in obj:
            _id(errors, "corpus_sample.%s" % key, obj[key])
    if "axis" in obj:
        _axis(errors, "corpus_sample.axis", obj["axis"])
    for key in ("work", "producer", "reviewer", "review2", "quote"):
        if key in obj:
            _string(errors, "corpus_sample.%s" % key, obj[key])
    for key in ("marker", "notes"):
        if key in obj:
            _string(errors, "corpus_sample.%s" % key, obj[key])
    # Independence of review is structural, not a matter of trust: a row whose
    # producer also reviewed it has one opinion wearing two names, and the kappa
    # computed over it would be a self-agreement score.
    producer = obj.get("producer")
    for key in ("reviewer", "review2"):
        if isinstance(producer, str) and obj.get(key) == producer:
            errors.append(
                "corpus_sample.%s: must differ from producer %r" % (key, producer)
            )
    if isinstance(obj.get("reviewer"), str) and obj.get("reviewer") == obj.get("review2"):
        errors.append("corpus_sample.review2: must differ from reviewer")
    if "verdict" in obj:
        _enum(errors, "corpus_sample.verdict", obj["verdict"], _VERDICTS)
    # Per-reviewer verdicts are required because kappa cannot be computed from a
    # single resolved verdict. Recording only the resolution would let "dual review
    # agreeing" be asserted rather than measured.
    if "reviewer_verdicts" in obj:
        votes = obj["reviewer_verdicts"]
        if not isinstance(votes, dict) or len(votes) < 2:
            errors.append(
                "corpus_sample.reviewer_verdicts: expected an object with at least "
                "two reviewer entries"
            )
        else:
            expected = {obj.get("reviewer"), obj.get("review2")}
            if expected != set(votes):
                errors.append(
                    "corpus_sample.reviewer_verdicts: keys %s must be exactly the "
                    "declared reviewers %s"
                    % (sorted(map(str, votes)), sorted(str(v) for v in expected))
                )
            for name, vote in sorted(votes.items(), key=lambda kv: str(kv[0])):
                _enum(
                    errors,
                    "corpus_sample.reviewer_verdicts[%r]" % name,
                    vote,
                    _VERDICTS,
                )
    # The resolved verdict must follow from the votes. Without this a row could
    # declare `accept` while both reviewers said `needs_review`, inflating the
    # occurrence count that feeds every graduation floor while leaving kappa
    # perfectly honest -- the numbers would disagree and nothing would say so.
    votes = obj.get("reviewer_verdicts")
    resolved = obj.get("verdict")
    if isinstance(votes, dict) and votes and resolved in _VERDICTS:
        cast = set(votes.values())
        if cast == {config.REVIEW_ACCEPT}:
            implied = config.REVIEW_ACCEPT
        elif cast == {config.REVIEW_REJECT}:
            implied = config.REVIEW_REJECT
        else:
            implied = config.REVIEW_NEEDS_REVIEW
        if resolved != implied:
            errors.append(
                "corpus_sample.verdict: %r does not follow from reviewer_verdicts "
                "%r, which imply %r" % (resolved, votes, implied)
            )
    if "quote_len" in obj:
        quote_len = obj["quote_len"]
        if not isinstance(quote_len, int) or isinstance(quote_len, bool) or quote_len < 0:
            errors.append("corpus_sample.quote_len: expected a non-negative integer")
        elif isinstance(obj.get("quote"), str) and quote_len != len(obj["quote"]):
            errors.append("corpus_sample.quote_len: must equal len(quote)")
        if isinstance(quote_len, int) and not isinstance(quote_len, bool) and quote_len > config.QUOTE_MAX_CHARS_PER_ROW:
            errors.append(
                "corpus_sample.quote_len: exceeds configured row ceiling %d"
                % config.QUOTE_MAX_CHARS_PER_ROW
            )
    if "source" in obj:
        _validate_corpus_source(obj["source"], errors)


def _validate_precedent(obj: Dict[str, Any], errors: List[str]) -> None:
    required = (
        "id",
        "axis",
        "type_id",
        "source_lang",
        "target_lang",
        "source_marker",
        "source_work",
        "target_realisation",
        "edition_channel",
        "verdict",
        "citation",
    )
    allowed = required + (
        "notes",
        "contradicts",
        "resolved_by",
        "target_pattern_set",
        # A dialect precedent names the pair it is about, so a dialect ruling can be
        # checked against evidence for THAT pair. Without these a ruling cleared its
        # evidence floor by citing any adopted row at all, including one about an
        # unrelated sentence-final marker.
        "source_dialect",
        "target_dialect",
    )
    _add_missing(errors, "precedent", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("precedent: unknown key %r" % key)
    if "axis" in obj:
        _axis(errors, "precedent.axis", obj["axis"])
    for key in ("id", "type_id"):
        if key in obj:
            _id(errors, "precedent.%s" % key, obj[key])
    for key in ("source_marker", "source_work", "target_realisation", "citation"):
        if key in obj:
            _string(errors, "precedent.%s" % key, obj[key])
    for key in ("source_lang", "target_lang"):
        if key in obj:
            _language(errors, "precedent.%s" % key, obj[key])
    if "edition_channel" in obj:
        _enum(errors, "precedent.edition_channel", obj["edition_channel"], _EDITION_CHANNELS)
    # Deliberately NOT the corpus review vocabulary. `adopted` is a claim about
    # what a published edition actually shipped; `accept` is a claim about whether
    # a transcription is correct. A shared vocabulary would let the second be
    # counted as the first by the canonical rule.
    if "verdict" in obj:
        _enum(errors, "precedent.verdict", obj["verdict"], _PRECEDENT_VERDICTS)
    if "notes" in obj:
        _string(errors, "precedent.notes", obj["notes"])
    # An unresolved contradiction blocks canonical status, so both the pointer to
    # the contradicted row and the pointer to its resolution have to be first-class
    # columns; recording either in prose would make the rule unenforceable.
    if "contradicts" in obj:
        _string_list(errors, "precedent.contradicts", obj["contradicts"])
        for index, ref in enumerate(obj["contradicts"] if isinstance(obj["contradicts"], list) else []):
            _id(errors, "precedent.contradicts[%d]" % index, ref)
        if isinstance(obj["contradicts"], list) and obj.get("id") in obj["contradicts"]:
            errors.append("precedent.contradicts: must not contain the row's own id")
    if "resolved_by" in obj:
        _id(errors, "precedent.resolved_by", obj["resolved_by"])
    for key in ("source_dialect", "target_dialect"):
        if key in obj:
            _string(errors, "precedent.%s" % key, obj[key])
    if "target_pattern_set" in obj:
        _pattern_list(
            errors, "precedent.target_pattern_set", obj["target_pattern_set"], nonempty=True
        )


def _validate_human_confirm(obj: Dict[str, Any], errors: List[str]) -> None:
    """A human confirmation, with its scope stated rather than implied.

    `scope` is required and free-form because the confirmations this project
    actually collects are narrower than they look: approving a list of eight types
    is not approving every marker row underneath them. An unscoped confirmation
    would be read as blanket approval of whatever it happened to be attached to.
    """
    required = (
        "id",
        "confirms",
        "scope",
        "confirmed_by",
        "confirmed_at",
        "artifact_cite",
        "artifact_sha256",
    )
    allowed = required + ("notes", "resolves")
    _add_missing(errors, "human_confirm", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("human_confirm: unknown key %r" % key)
    if "id" in obj:
        _id(errors, "human_confirm.id", obj["id"])
    if "confirms" in obj:
        _string_list(errors, "human_confirm.confirms", obj["confirms"], nonempty=True)
        for index, ref in enumerate(obj["confirms"] if isinstance(obj["confirms"], list) else []):
            _id(errors, "human_confirm.confirms[%d]" % index, ref)
    for key in ("scope", "confirmed_by", "artifact_cite"):
        if key in obj:
            _string(errors, "human_confirm.%s" % key, obj[key])
    if "confirmed_at" in obj:
        _timestamp(errors, "human_confirm.confirmed_at", obj["confirmed_at"])
    if "artifact_sha256" in obj:
        _sha256(errors, "human_confirm.artifact_sha256", obj["artifact_sha256"])
    if "notes" in obj:
        _string(errors, "human_confirm.notes", obj["notes"])
    if "resolves" in obj:
        _string_list(errors, "human_confirm.resolves", obj["resolves"])
        for index, ref in enumerate(obj["resolves"] if isinstance(obj["resolves"], list) else []):
            _id(errors, "human_confirm.resolves[%d]" % index, ref)


def _validate_dialect_decision(obj: Dict[str, Any], errors: List[str]) -> None:
    """An operator ruling on one (source dialect, target dialect, work) triple.

    `decision_hash` binds the ruling to the exact triple it was made about, so
    renaming either dialect or moving the ruling to another work leaves it stale
    rather than silently authorising a different substitution.
    """
    required = (
        "id",
        "source_dialect",
        "target_dialect",
        "work",
        "strategy",
        "reason",
        "decided_by",
        "decided_at",
        "decision_hash",
    )
    allowed = required + ("notes", "precedents")
    _add_missing(errors, "dialect_decision", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("dialect_decision: unknown key %r" % key)
    if "id" in obj:
        _id(errors, "dialect_decision.id", obj["id"])
    for key in ("source_dialect", "target_dialect", "work", "reason", "decided_by"):
        if key in obj:
            _string(errors, "dialect_decision.%s" % key, obj[key])
    if "strategy" in obj:
        _enum(errors, "dialect_decision.strategy", obj["strategy"], config.DIALECT_STRATEGIES)
    if "decided_at" in obj:
        _timestamp(errors, "dialect_decision.decided_at", obj["decided_at"])
    if "decision_hash" in obj:
        _sha1(errors, "dialect_decision.decision_hash", obj["decision_hash"])
    if "notes" in obj:
        _string(errors, "dialect_decision.notes", obj["notes"])
    if "precedents" in obj:
        _string_list(errors, "dialect_decision.precedents", obj["precedents"])
        for index, ref in enumerate(obj["precedents"] if isinstance(obj["precedents"], list) else []):
            _id(errors, "dialect_decision.precedents[%d]" % index, ref)


def _validate_probe_row(obj: Dict[str, Any], errors: List[str]) -> None:
    """One authored probe utterance.

    `origin` is closed to a single value. The probe corpus decides whether two
    realisations are distinguishable, so quoted script text must not enter it:
    that would leak the text and make the distinguishability verdict depend on
    which lines happened to be quoted.
    """
    required = ("id", "lang", "text", "origin", "markedness")
    allowed = required + ("notes",)
    _add_missing(errors, "probe_row", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("probe_row: unknown key %r" % key)
    if "id" in obj:
        _id(errors, "probe_row.id", obj["id"])
    if "lang" in obj:
        _language(errors, "probe_row.lang", obj["lang"])
    if "text" in obj:
        _string(errors, "probe_row.text", obj["text"])
    if "origin" in obj:
        _enum(errors, "probe_row.origin", obj["origin"], config.PROBE_ORIGINS)
    # Required, not optional. An unlabelled row cannot serve as a control, and the
    # check that a pattern does not fire on ordinary unmarked speech is the one
    # that keeps an over-generic pattern out of an enforced artifact.
    if "markedness" in obj:
        _enum(errors, "probe_row.markedness", obj["markedness"], config.PROBE_MARKEDNESS)
    if "notes" in obj:
        _string(errors, "probe_row.notes", obj["notes"])


def _validate_corpus_draft(obj: Dict[str, Any], errors: List[str]) -> None:
    """A producer's proposed corpus row, before any review.

    Drafts and reviews are separate artifacts on purpose. If one author wrote a
    row together with both of its reviewer verdicts, "dual review agreeing" would
    be one opinion typed three times, and the kappa computed over it would be a
    self-agreement score. Keeping them apart makes reviewer independence a
    property of the file layout instead of a promise.
    """
    required = ("id", "type_id", "axis", "work", "producer", "quote", "quote_len", "source")
    allowed = required + ("marker", "notes")
    _add_missing(errors, "corpus_draft", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("corpus_draft: unknown key %r" % key)
    for key in ("id", "type_id"):
        if key in obj:
            _id(errors, "corpus_draft.%s" % key, obj[key])
    if "axis" in obj:
        _axis(errors, "corpus_draft.axis", obj["axis"])
    for key in ("work", "producer", "quote", "marker", "notes"):
        if key in obj:
            _string(errors, "corpus_draft.%s" % key, obj[key])
    if "quote_len" in obj:
        quote_len = obj["quote_len"]
        if not isinstance(quote_len, int) or isinstance(quote_len, bool) or quote_len < 0:
            errors.append("corpus_draft.quote_len: expected a non-negative integer")
        elif isinstance(obj.get("quote"), str) and quote_len != len(obj["quote"]):
            errors.append("corpus_draft.quote_len: must equal len(quote)")
        elif quote_len > config.QUOTE_MAX_CHARS_PER_ROW:
            errors.append(
                "corpus_draft.quote_len: exceeds configured row ceiling %d"
                % config.QUOTE_MAX_CHARS_PER_ROW
            )
    if "source" in obj:
        # Reuses the corpus_sample source rules, including the provenance
        # cross-check, so a draft cannot claim provenance that the merged row
        # would be rejected for.
        _validate_corpus_source(obj["source"], errors)


def _validate_corpus_review(obj: Dict[str, Any], errors: List[str]) -> None:
    """One reviewer's independent verdict on one draft."""
    required = ("sample_id", "reviewer", "verdict")
    allowed = required + ("note",)
    _add_missing(errors, "corpus_review", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("corpus_review: unknown key %r" % key)
    if "sample_id" in obj:
        _id(errors, "corpus_review.sample_id", obj["sample_id"])
    for key in ("reviewer", "note"):
        if key in obj:
            _string(errors, "corpus_review.%s" % key, obj[key])
    if "verdict" in obj:
        _enum(errors, "corpus_review.verdict", obj["verdict"], _VERDICTS)


def _validate_graduation_entry(value: Any, errors: List[str], label: str) -> None:
    required = (
        "type_id",
        "stage",
        "occurrences",
        "independent_sources",
        "e1e2_sources",
        "adopted_precedents",
        "unresolved_contradictions",
        "dual_review_agreeing",
        "human_confirms",
        "kappa",
        "kappa_downward_flips",
        "source_evidence_ok",
        "source_evidence_unmet",
        "unmet",
    )
    if not _closed(errors, label, value, required, required):
        return
    _id(errors, "%s.type_id" % label, value.get("type_id"))
    _enum(errors, "%s.stage" % label, value.get("stage"), config.STAGES)
    for key in (
        "occurrences",
        "independent_sources",
        "e1e2_sources",
        "adopted_precedents",
        "unresolved_contradictions",
        "dual_review_agreeing",
        "human_confirms",
        "kappa_downward_flips",
    ):
        count = value.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            errors.append("%s.%s: expected a non-negative integer" % (label, key))
    kappa = value.get("kappa")
    # `None` is a real outcome, not a missing value: kappa is undefined when the
    # reviewers rated everything identically with no variance to disagree about.
    if kappa is not None and (not _is_number(kappa) or not -1.0 <= kappa <= 1.0):
        errors.append("%s.kappa: expected null or a number in [-1, 1]" % label)
    _string_list(errors, "%s.unmet" % label, value.get("unmet"))
    _string_list(
        errors, "%s.source_evidence_unmet" % label, value.get("source_evidence_unmet")
    )
    source_ok = value.get("source_evidence_ok")
    if not isinstance(source_ok, bool):
        errors.append("%s.source_evidence_ok: expected a boolean" % label)
    elif source_ok != (not value.get("source_evidence_unmet")):
        # The flag and the list must agree, so a report cannot claim the source-side
        # evidence is complete while still listing what it lacks.
        errors.append(
            "%s.source_evidence_ok contradicts source_evidence_unmet" % label
        )
    if value.get("stage") == config.STAGE_CANONICAL and value.get("unmet"):
        errors.append(
            "%s: stage is canonical but unmet criteria are listed %r; a stage that "
            "ignores its own unmet criteria is not a gate"
            % (label, value.get("unmet"))
        )


def _validate_graduation_report(obj: Dict[str, Any], errors: List[str]) -> None:
    required = ("catalogue_version", "generated_at", "types")
    allowed = required + ("notes",)
    _add_missing(errors, "graduation_report", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("graduation_report: unknown key %r" % key)
    if "catalogue_version" in obj:
        _string(errors, "graduation_report.catalogue_version", obj["catalogue_version"])
    if "generated_at" in obj:
        _timestamp(errors, "graduation_report.generated_at", obj["generated_at"])
    if "types" in obj:
        if not isinstance(obj["types"], list) or not obj["types"]:
            errors.append("graduation_report.types: expected a non-empty list")
        else:
            for index, entry in enumerate(obj["types"]):
                _validate_graduation_entry(
                    entry, errors, "graduation_report.types[%d]" % index
                )
    if "notes" in obj:
        _string(errors, "graduation_report.notes", obj["notes"])


def _validate_waiver(obj: Dict[str, Any], errors: List[str]) -> None:
    """A waiver of specific findings on one sealed contract.

    `contract_hash` binds the waiver to the exact seal it was granted against, so a
    rebase leaves it stale rather than silently authorising a contract that has
    since changed. `waived_codes` is explicit because a category-wide waiver would
    clear findings nobody examined, and the category set is closed so a waiver
    cannot be invented by naming a new one.
    """
    required = ("id", "category", "contract_hash", "reason", "waived_codes", "granted_by", "granted_at")
    allowed = required + ("stale", "notes")
    _add_missing(errors, "waiver", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("waiver: unknown key %r" % key)
    if "id" in obj:
        _id(errors, "waiver.id", obj["id"])
    if "category" in obj:
        _enum(errors, "waiver.category", obj["category"], config.WAIVER_CATEGORIES)
    if "contract_hash" in obj:
        _sha256(errors, "waiver.contract_hash", obj["contract_hash"])
    for key in ("reason", "granted_by", "notes"):
        if key in obj:
            _string(errors, "waiver.%s" % key, obj[key])
    if "granted_at" in obj:
        _timestamp(errors, "waiver.granted_at", obj["granted_at"])
    if "waived_codes" in obj:
        _string_list(errors, "waiver.waived_codes", obj["waived_codes"], nonempty=True)
    if "stale" in obj and not isinstance(obj["stale"], bool):
        errors.append("waiver.stale: expected a boolean")


def _validate_manifest_artifacts(value: Any, errors: List[str]) -> None:
    if not isinstance(value, list):
        errors.append("manifest.artifacts: expected a list")
        return
    for index, artifact in enumerate(value):
        label = "manifest.artifacts[%d]" % index
        if not _closed(errors, label, artifact, ("kind", "id", "digest"), ("kind", "id", "digest")):
            continue
        if artifact.get("kind") not in KINDS:
            errors.append("%s.kind: expected one of %s" % (label, list(KINDS)))
        _string(errors, "%s.id" % label, artifact.get("id"))
        _sha256(errors, "%s.digest" % label, artifact.get("digest"))


def _validate_manifest(obj: Dict[str, Any], errors: List[str]) -> None:
    required = ("work", "catalogue_version", "artifacts")
    _add_missing(errors, "manifest", obj, required)
    for key in obj:
        if key not in required:
            errors.append("manifest: unknown key %r" % key)
    for key in ("work", "catalogue_version"):
        if key in obj:
            _string(errors, "manifest.%s" % key, obj[key])
    if "artifacts" in obj:
        _validate_manifest_artifacts(obj["artifacts"], errors)


def _validate_delimiters(value: Any, errors: List[str]) -> None:
    if not isinstance(value, dict):
        errors.append("profile.delimiters: expected an object")
        return
    for lang, declaration in value.items():
        _language(errors, "profile.delimiters.%s" % lang, lang)
        label = "profile.delimiters.%s" % lang
        if not _closed(
            errors,
            label,
            declaration,
            ("speech", "term"),
            ("speech", "term", "closes_on_role_change", "speech_is_positional"),
        ):
            continue
        for category in ("speech", "term"):
            pairs = declaration.get(category)
            pair_label = "%s.%s" % (label, category)
            if not isinstance(pairs, list):
                errors.append("%s: expected a list of delimiter pairs" % pair_label)
                continue
            if category == "speech" and not pairs:
                errors.append(
                    "%s: expected a non-empty list of delimiter pairs" % pair_label
                )
            for pair in pairs:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or any(not isinstance(item, str) or not item for item in pair)
                ):
                    errors.append("%s: expected [open, close] string pairs" % pair_label)
                    break
        if "closes_on_role_change" in declaration and not isinstance(
            declaration["closes_on_role_change"], bool
        ):
            errors.append("%s.closes_on_role_change: expected a boolean" % label)
        if "speech_is_positional" in declaration and not isinstance(
            declaration["speech_is_positional"], bool
        ):
            errors.append("%s.speech_is_positional: expected a boolean" % label)
        speech_pairs = [
            tuple(pair) for pair in (declaration.get("speech") or [])
            if isinstance(pair, list) and len(pair) == 2
        ]
        term_pairs = [
            tuple(pair) for pair in (declaration.get("term") or [])
            if isinstance(pair, list) and len(pair) == 2
        ]
        shared = sorted(set(speech_pairs) & set(term_pairs))
        if shared:
            # With one pair declared for both roles the scan order decides, which
            # means the declaration does not actually say what the author thinks.
            errors.append(
                "%s: pair %r is declared as both speech and term" % (label, shared[0])
            )
        if declaration.get("speech_is_positional") is False and not term_pairs:
            # Turning the positional tie-breaker off says "the delimiters already
            # disambiguate". Without a terminology delimiter nothing disambiguates
            # and every quoted span becomes speech.
            errors.append(
                "%s: speech_is_positional false requires distinct term delimiters"
                % label
            )


def _validate_profile(obj: Dict[str, Any], errors: List[str]) -> None:
    required = config.PROFILE_REQUIRED
    allowed = tuple(config.PROFILE_ALLOWLIST) + (config.PROFILE_COMMENT_KEY,)
    _add_missing(errors, "profile", obj, required)
    for key in obj:
        if key not in allowed:
            errors.append("profile: unknown key %r" % key)
    if "work" in obj:
        _string(errors, "profile.work", obj["work"])
    if "voice_enforcement_mode" in obj and obj["voice_enforcement_mode"] not in config.ENFORCEMENT_MODES:
        errors.append(
            "profile.voice_enforcement_mode: expected one of %s"
            % list(config.ENFORCEMENT_MODES)
        )
    for key in ("evidence_lang", "pivot_lang", "target_lang"):
        if key in obj:
            _language(errors, "profile.%s" % key, obj[key])
    roles = obj.get("speaker_roles")
    if "speaker_roles" in obj:
        if not isinstance(roles, dict):
            errors.append("profile.speaker_roles: expected an object")
        else:
            for label, role in roles.items():
                _string(errors, "profile.speaker_roles key", label)
                if role not in config.ROLES:
                    errors.append(
                        "profile.speaker_roles.%s: expected one of %s"
                        % (label, list(config.ROLES))
                    )
            if not any(role == config.ROLE_SPEAKER for role in roles.values()):
                errors.append(
                    "profile.speaker_roles: expected at least one speaker role"
                )
    for key in ("tag_pattern", "ruby_pattern", "edition_medium", "_comment"):
        if key in obj:
            _string(errors, "profile.%s" % key, obj[key])
    if "scene_pattern" in obj:
        _string(errors, "profile.scene_pattern", obj["scene_pattern"])
        if isinstance(obj["scene_pattern"], str) and obj["scene_pattern"]:
            try:
                compiled = re.compile(obj["scene_pattern"])
            except re.error as error:
                errors.append(
                    "profile.scene_pattern: invalid regular expression: %s" % error
                )
            else:
                if compiled.groups < 1:
                    errors.append(
                        "profile.scene_pattern: expected a first capture group"
                    )
                if _has_nested_quantifier(obj["scene_pattern"]):
                    errors.append(
                        "profile.scene_pattern: nested quantified group is not permitted"
                    )
    for key in ("layout_tags", "page_tags"):
        if key in obj:
            _string_list(errors, "profile.%s" % key, obj[key])
    delimiters = obj.get("delimiters")
    if "delimiters" in obj:
        _validate_delimiters(delimiters, errors)
        if isinstance(delimiters, dict):
            for key in ("evidence_lang", "pivot_lang", "target_lang"):
                language = obj.get(key)
                if isinstance(language, str) and language and language not in delimiters:
                    errors.append(
                        "profile.delimiters: missing declaration for %s %r"
                        % (key, language)
                    )
    if "term_quote_min_len" in obj and (
        not isinstance(obj["term_quote_min_len"], int)
        or isinstance(obj["term_quote_min_len"], bool)
        or obj["term_quote_min_len"] < 0
    ):
        errors.append("profile.term_quote_min_len: expected a non-negative integer")
    if "coverage_floor" in obj and (
        not _is_number(obj["coverage_floor"])
        or obj["coverage_floor"] < 0
        or obj["coverage_floor"] > 1
    ):
        errors.append("profile.coverage_floor: expected a number from 0 through 1")
    if "csv_speaker_column" in obj:
        _string(errors, "profile.csv_speaker_column", obj["csv_speaker_column"])
    if "budgets" in obj and not isinstance(obj["budgets"], dict):
        errors.append("profile.budgets: expected an object")
    if "dialect_policy" in obj:
        policy = obj["dialect_policy"]
        # `source_dialect` and `target_dialect` are optional here on purpose: a work
        # with no dialect speaker declares only the strategy. When either is named,
        # the dialect gate has a triple to bind an operator ruling to.
        if not _closed(
            errors,
            "profile.dialect_policy",
            policy,
            ("target_strategy",),
            ("target_strategy", "source_dialect", "target_dialect"),
        ):
            return
        _enum(
            errors,
            "profile.dialect_policy.target_strategy",
            policy.get("target_strategy"),
            config.DIALECT_STRATEGIES,
        )
        for key in ("source_dialect", "target_dialect"):
            if key in policy:
                _string(errors, "profile.dialect_policy.%s" % key, policy[key])


def validate(kind: str, obj: Any) -> List[str]:
    """Return closed-schema errors for an artifact; an empty list is valid."""

    if kind not in KINDS:
        return ["unknown schema kind %r" % (kind,)]
    if not isinstance(obj, dict):
        return ["%s: expected object" % kind]
    errors: List[str] = []
    if kind == "type":
        _validate_type(obj, errors)
    elif kind == "realisation":
        _validate_realisation(obj, errors)
    elif kind == "contract":
        _validate_contract(obj, errors)
    elif kind == "corpus_draft":
        _validate_corpus_draft(obj, errors)
    elif kind == "corpus_review":
        _validate_corpus_review(obj, errors)
    elif kind == "corpus_sample":
        _validate_corpus_sample(obj, errors)
    elif kind == "precedent":
        _validate_precedent(obj, errors)
    elif kind == "human_confirm":
        _validate_human_confirm(obj, errors)
    elif kind == "dialect_decision":
        _validate_dialect_decision(obj, errors)
    elif kind == "probe_row":
        _validate_probe_row(obj, errors)
    elif kind == "graduation_report":
        _validate_graduation_report(obj, errors)
    elif kind == "waiver":
        _validate_waiver(obj, errors)
    elif kind == "manifest":
        _validate_manifest(obj, errors)
    elif kind == "profile":
        _validate_profile(obj, errors)
    else:  # pragma: no cover - guarded by the KINDS check above
        raise AssertionError(
            "kind %r is in KINDS but has no validator; an unvalidated artifact "
            "kind would validate vacuously" % (kind,)
        )
    return errors


def require(kind: str, obj: Any) -> None:
    """Raise ``ValueError`` when a closed artifact schema rejects *obj*."""

    errors = validate(kind, obj)
    if errors:
        raise ValueError("; ".join(errors))
