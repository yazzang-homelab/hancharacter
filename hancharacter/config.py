"""Project configuration, per-adapter declarations, and the frozen constants.

Every constant here is part of the approved plan's contract. Changing one is a
policy change, not a tuning knob: the gate verdicts are re-derived from these
numbers, so a silent edit invalidates every published report.
"""
from collections.abc import Mapping

import copy
import json
import os
import re
from types import MappingProxyType


# ---------------------------------------------------------------- constants ---
# Coverage floor at contract seal, per speaker (R4).
COVERAGE_FLOOR_X = 0.70
# Absolute band tolerance outside which a density finding becomes hard.
OUTER_TOL = 0.15
# Below either of these a scope is `under-sampled` and density is report-only.
MIN_UNITS_PER_SCOPE = 20
MIN_SCENES_PER_BAND = 5
# Wilson interval confidence and the floor width applied to it.
WILSON_Z = 1.96          # 95%
WILSON_FLOOR_WIDTH = 0.15
# Band widening when the evidence language is not the pivot language (R1/R2 of
# the dual-standard policy).
DUAL_STD_WIDEN = 0.10
# A novel, non-catalogue sentence-final form must recur this often in one scope
# before it is reported as a suspected invention.
NOVELTY_RECURRENCE_K = 3
# Corpus review floors.
KAPPA_FLOOR = 0.60
QUOTE_MAX_CHARS_PER_ROW = 120
QUOTE_MAX_CHARS_PER_WORK = 1000
DUMP_CONSECUTIVE_ROWS = 3
DUMP_NGRAM_TOKENS = 8
# Report-side heuristic only; never a gating threshold (H3).
TERM_QUOTE_MIN_LEN = 8
# --------------------------------------------------- P1 evidence vocabularies ---
# Why a source-side type exists at all. `positional` covers a marker carried by a
# role/position rather than a person (a shopkeeper, a narrator), which is the class
# 役割語 scholarship treats as distinct from an individual character quirk.
ORIGIN_REGIONAL = "regional"
ORIGIN_HISTORICAL = "historical"
ORIGIN_CHARACTER = "character"
ORIGIN_POSITIONAL = "positional"
TYPE_ORIGINS = (
    ORIGIN_REGIONAL,
    ORIGIN_HISTORICAL,
    ORIGIN_CHARACTER,
    ORIGIN_POSITIONAL,
)

# What the recorder actually consulted for a corpus row. This exists because the
# graduation rule rewards `primary`/`secondary` evidence, which creates a standing
# incentive to relabel a wiki mirror or a search snippet as the work itself. The
# provenance is therefore declared separately from the class and cross-checked, so
# laundering a mirror into primary evidence is a schema error rather than a matter
# of good intentions.
CONSULTED_DIRECT = "direct_read"
CONSULTED_MIRROR = "mirror"
CONSULTED_SNIPPET = "search_snippet"
CONSULTED_FIXTURE = "fixture_file"
CONSULTED_CITED_BY = "cited_by"
CONSULTED_VIA = (
    CONSULTED_DIRECT,
    CONSULTED_MIRROR,
    CONSULTED_SNIPPET,
    CONSULTED_FIXTURE,
    CONSULTED_CITED_BY,
)

SOURCE_PRIMARY = "primary"
SOURCE_SECONDARY = "secondary"
SOURCE_REFERENCE = "reference"
SOURCE_FIXTURE = "fixture"
SOURCE_CLASSES = (
    SOURCE_PRIMARY,
    SOURCE_SECONDARY,
    SOURCE_REFERENCE,
    SOURCE_FIXTURE,
)
# The E1/E2 tier the canonical rule counts.
E1E2_SOURCE_CLASSES = (SOURCE_PRIMARY, SOURCE_SECONDARY)
# Claiming the work itself requires having opened the work itself.
PRIMARY_CONSULTED_VIA = (CONSULTED_DIRECT, CONSULTED_FIXTURE)
# A secondary source may be read through a mirror or a retrieved snippet, but
# never through someone else's citation of it: `cited_by` is hearsay, and hearsay
# that counts toward a graduation floor is a fabricated floor.
SECONDARY_CONSULTED_VIA = (
    CONSULTED_DIRECT,
    CONSULTED_MIRROR,
    CONSULTED_SNIPPET,
    CONSULTED_FIXTURE,
)

# Corpus review verdicts, kept distinct from precedent verdicts below. Collapsing
# the two vocabularies would let "this quote is transcribed correctly" stand in for
# "the industry adopted this rendering", which are unrelated claims.
REVIEW_ACCEPT = "accept"
REVIEW_REJECT = "reject"
REVIEW_NEEDS_REVIEW = "needs_review"
REVIEW_VERDICTS = (REVIEW_ACCEPT, REVIEW_REJECT, REVIEW_NEEDS_REVIEW)

PRECEDENT_ADOPTED = "adopted"
PRECEDENT_CONTESTED = "contested"
PRECEDENT_REJECTED = "rejected"
PRECEDENT_VERDICTS = (PRECEDENT_ADOPTED, PRECEDENT_CONTESTED, PRECEDENT_REJECTED)
# The channel a rendering that no published edition shipped must declare.
PRECEDENT_CHANNEL_UNPUBLISHED = "unpublished"

# Graduation stages and their floors.
STAGE_OBSERVED = "observed"
STAGE_PROVISIONAL = "provisional"
STAGE_CANONICAL = "canonical"
STAGES = (STAGE_OBSERVED, STAGE_PROVISIONAL, STAGE_CANONICAL)
PROVISIONAL_MIN_OCCURRENCES = 3
PROVISIONAL_MIN_INDEPENDENT_SOURCES = 2
CANONICAL_MIN_OCCURRENCES = 8
CANONICAL_MIN_INDEPENDENT_SOURCES = 3
CANONICAL_MIN_E1E2_SOURCES = 1
CANONICAL_MIN_ADOPTED_PRECEDENTS = 1
CANONICAL_MIN_HUMAN_CONFIRMS = 1

# Distinguishability and rejected-precedent matching share one similarity measure
# on one probe corpus, so a pair cannot be "distinct enough to keep" and
# "similar enough to be the rejected rendering" at the same time.
JACCARD_DISTINCT_MAX = 0.5
JACCARD_REJECTED_MATCH_MIN = 0.5

# Dialect target strategies (R3).
DIALECT_FLAVOUR_LEXICON = "flavour_lexicon"
DIALECT_FULL_SUBSTITUTION = "full_substitution"
DIALECT_STRATEGIES = (DIALECT_FLAVOUR_LEXICON, DIALECT_FULL_SUBSTITUTION)

# The only permitted provenance for a probe-corpus row. The probe corpus decides
# whether two realisations are distinguishable, so it must be authored here: a
# probe built from quoted script text would both leak the text and let the
# distinguishability verdict drift with whatever happened to be quoted.
PROBE_ORIGIN_AUTHORED = "authored_synthetic"
PROBE_ORIGINS = (PROBE_ORIGIN_AUTHORED,)

# A probe row is either an exemplar of some marker or a deliberate control that no
# marker should match. The distinction has to be declared, because the check that
# matters -- does this pattern also fire on ordinary unmarked speech -- is
# impossible without knowing which rows are unmarked. The catalogue shipped eleven
# control rows before this field existed and nothing could use them, which is how
# four over-generic patterns reached the enforced artifacts.
PROBE_MARKED = "marked"
PROBE_UNMARKED = "unmarked"
PROBE_MARKEDNESS = (PROBE_MARKED, PROBE_UNMARKED)

# Enforcement modes (R1).
MODE_PROSE_FIDELITY = "prose_fidelity"
MODE_VOICE_CRITICAL = "voice_critical"
ENFORCEMENT_MODES = (MODE_PROSE_FIDELITY, MODE_VOICE_CRITICAL)

# Density verdict statuses are distinct from finding severities; density owns the
# conversion through ``density.to_finding``.
DENSITY_STATUS_PASS = "pass"
DENSITY_STATUS_REPORT = "report"
DENSITY_STATUS_HARD = "hard"
DENSITY_STATUSES = (
    DENSITY_STATUS_PASS,
    DENSITY_STATUS_REPORT,
    DENSITY_STATUS_HARD,
)

# Closed measurement-axis status vocabulary.  A plugin declaration outside this
# set is a contract error, never an implicit declaration of unmeasurability.
AXIS_STATUS_APPLICABLE = "applicable"
AXIS_STATUS_LEXICAL = "lexical"
AXIS_STATUS_NOT_APPLICABLE = "not_applicable"
AXIS_STATUSES = (
    AXIS_STATUS_APPLICABLE,
    AXIS_STATUS_LEXICAL,
    AXIS_STATUS_NOT_APPLICABLE,
)
MEASURABLE_AXIS_STATUSES = (
    AXIS_STATUS_APPLICABLE,
    AXIS_STATUS_LEXICAL,
)

# Closed set of waiver categories. An open-ended category string is not a gate.
WAIVER_CATEGORIES = (
    "policy_density",
    "arc_scope",
    "edition_variant",
    "glyph_fallback",
    "coverage",
    "dialect_ruling",
)

# Attribution roles a declared label may carry. Only `speaker` attributes.
ROLE_SPEAKER = "speaker"
ROLE_PRONOUN = "pronoun"
ROLE_TERM = "term"
ROLE_SYSTEM = "system"
ROLE_CLOSE = "close"
ROLES = (ROLE_SPEAKER, ROLE_PRONOUN, ROLE_TERM, ROLE_SYSTEM, ROLE_CLOSE)

# Ineligibility reasons, published by count in every attribution report.
INELIGIBLE_MIXED_SPAN = "mixed_speaker_span"
INELIGIBLE_DUPLICATE_SOURCE = "duplicate_source_key"
INELIGIBLE_PENDING = "t2_pending"
INELIGIBLE_UNDECLARED = "undeclared_label"
INELIGIBLE_UNSPLITTABLE = "unsplittable_payload"
# Report-only: an eligible source group whose pivot has no speech span (M3).
COUNTER_SCOPE_UNREALISED = "voice_scope_unrealised"
# Report-only: an attributed unit with no resolvable scene. Such a unit is
# invisible to the per-scene band, which caps the density verdict at report.
COUNTER_UNITS_WITHOUT_SCENE = "units_without_scene"

# Keys a profile may declare. An undeclared key is a hard failure, so a typo can
# never silently disable enforcement.
PROFILE_ALLOWLIST = (
    "work",
    "voice_enforcement_mode",
    "evidence_lang",
    "pivot_lang",
    "target_lang",
    "speaker_roles",
    "tag_pattern",
    "layout_tags",
    "page_tags",
    "ruby_pattern",
    "delimiters",
    "term_quote_min_len",
    "coverage_floor",
    "edition_medium",
    "budgets",
    "dialect_policy",
    "scene_pattern",
    # Which CSV column names the speaker, for a CSV-shaped input. Declared rather
    # than guessed: a guessed speaker column is attribution invented from a header.
    "csv_speaker_column",
)

# Keys a profile MUST declare. These are the ones whose absence would otherwise
# be filled by a guess, and a guessed language or an empty role map silently
# removes a character from measurement. `schemas._validate_profile` consumes this
# same tuple, and `Profile.__init__` finishes by running the closed schema, so a
# profile cannot pass the loader every command uses while failing the validator.
PROFILE_REQUIRED = (
    "work",
    "voice_enforcement_mode",
    "evidence_lang",
    "pivot_lang",
    "target_lang",
    "speaker_roles",
    "delimiters",
)

# The one documentation key a profile may carry. Kept deliberately narrow: an
# open `_`-prefix escape would let a misspelled declaration hide as a comment.
PROFILE_COMMENT_KEY = "_comment"

DEFAULT_TAG_PATTERN = r"<[^>\n]*>"
DEFAULT_RUBY_PATTERN = r"<ruby>(?P<base>[^<]*)<rt>(?P<reading>[^<]*)</rt></ruby>"
# Unicode general categories that render no glyph. Tested by category rather than
# enumerated, because an allowlist of code points closes instances while the class
# stays open: U+200B was caught and U+200C, U+200D, U+2060, U+00AD were not.
# `str.strip()` already removes the whitespace class, including U+00A0 and U+3000.
TARGET_VISIBILITY_BLANK_CATEGORIES = ("Cf", "Cc")


def fixture_path():
    """Read-only external corpus used by tests and the e2e run.

    The fixture is never copied into this repository: it is somebody else's
    game text. Tests that need it skip when it is absent.
    """
    return os.environ.get(
        "HANCHARACTER_FIXTURE", "/root/tmp/crimson-kr/work/text_src.json"
    )


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def catalogue_root():
    """Per-work sealed contracts. One directory per work, holding `lock.json`."""
    return os.environ.get(
        "HANCHARACTER_CATALOGUE", os.path.join(repo_root(), "characters")
    )


def typology_root():
    """Shared, work-independent evidence catalogue.

    Deliberately separate from `catalogue_root`: types, realisations, precedents
    and corpus samples are knowledge about a source language and a target
    language, reusable across works, while a contract is a sealed claim about one
    character in one work. Storing them together would make a per-work seal look
    like catalogue evidence.
    """
    return os.environ.get(
        "HANCHARACTER_TYPOLOGY", os.path.join(repo_root(), "catalogue")
    )


def _freeze_declaration(value):
    """Recursively freeze validated JSON-shaped declarations."""
    if isinstance(value, dict):
        return MappingProxyType(
            {key: _freeze_declaration(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_declaration(item) for item in value)
    return value


def _json_value(value):
    """Recover JSON containers for the public serialisation helper."""
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    return value

class Profile:
    """A per-work declaration. Nothing is inferred; everything is declared."""

    def __init__(self, data, path=None):
        self.path = path
        # Deep-copy first, so caller-owned nested structures cannot change a
        # constructed declaration. Freeze after validation so direct access cannot
        # later change roles or delimiter grammar without a fresh validation pass.
        payload = copy.deepcopy(dict(data))
        # Only `_comment` is a documentation key. Any other unrecognised key is a
        # declaration typo, and a typo that validates is a declaration that does
        # not do what its author believes it does.
        unknown = [
            key
            for key in payload
            if key != PROFILE_COMMENT_KEY and key not in PROFILE_ALLOWLIST
        ]
        if unknown:
            raise ValueError(
                "undeclared profile keys %s (allowlist: %s)"
                % (sorted(unknown), ", ".join(PROFILE_ALLOWLIST))
            )
        missing = [key for key in PROFILE_REQUIRED if key not in payload]
        if missing:
            raise ValueError(
                "profile is missing required declarations %s; nothing is "
                "inferred here, because a guessed language or an empty role map "
                "silently removes a character from measurement" % (missing,)
            )
        mode = payload["voice_enforcement_mode"]
        if mode not in ENFORCEMENT_MODES:
            raise ValueError(
                "voice_enforcement_mode must be one of %s, got %r"
                % (list(ENFORCEMENT_MODES), mode)
            )
        roles = payload["speaker_roles"]
        if not isinstance(roles, dict):
            raise ValueError("speaker_roles must be an object")
        for label, role in roles.items():
            if role not in ROLES:
                raise ValueError(
                    "speaker_roles[%r] has invalid role %r; allowed roles: %s"
                    % (label, role, ", ".join(ROLES))
                )
        # The closed schema is the single authority for everything structural
        # (delimiter shape, per-language coverage, a non-empty speech list). The
        # checks above stay because they produce sharper messages for the three
        # mistakes an author actually makes, but nothing may load through this
        # constructor that `schemas` would reject: the loader is what every
        # measuring command uses, so a rule only the opt-in validator enforces is
        # a rule that does not exist. Imported here, not at module scope, because
        # `schemas` imports this module.
        from hancharacter import schemas

        schemas.require("profile", payload)
        self._data = _freeze_declaration(payload)

    @property
    def data(self):
        """Read the validated declaration without allowing post-validation mutation."""
        return self._data

    # -- declarations -------------------------------------------------------
    # Every accessor below indexes `data` directly. `__init__` has already proved
    # the key is present, and a `.get(key, guess)` here would quietly reintroduce
    # the inference the required-key check exists to forbid.
    @property
    def work(self):
        return self.data["work"]

    @property
    def mode(self):
        return self.data["voice_enforcement_mode"]

    @property
    def evidence_lang(self):
        return self.data["evidence_lang"]

    @property
    def pivot_lang(self):
        return self.data["pivot_lang"]

    @property
    def target_lang(self):
        return self.data["target_lang"]

    @property
    def dual_standard(self):
        """True when markers are measured in one language and shipped from another."""
        return self.evidence_lang != self.pivot_lang

    @property
    def speaker_roles(self):
        return dict(self.data["speaker_roles"])

    def role(self, label):
        return self.speaker_roles.get(label)

    def is_speaker(self, label):
        return self.role(label) == ROLE_SPEAKER

    @property
    def tag_re(self):
        return re.compile(self.data.get("tag_pattern", DEFAULT_TAG_PATTERN))

    @property
    def ruby_re(self):
        return re.compile(self.data.get("ruby_pattern", DEFAULT_RUBY_PATTERN))

    @property
    def layout_tags(self):
        """Tags omitted from H1 boundaries and stripped from unit surfaces."""
        return tuple(self.data.get("layout_tags", ("<br>", "<page>")))

    @property
    def scene_pattern(self):
        """Compiled optional row-key scene declaration, or None for row metadata."""
        pattern = self.data.get("scene_pattern")
        return None if pattern is None else re.compile(pattern)

    @property
    def term_quote_min_len(self):
        return int(self.data.get("term_quote_min_len", TERM_QUOTE_MIN_LEN))

    @property
    def coverage_floor(self):
        return float(self.data.get("coverage_floor", COVERAGE_FLOOR_X))

    @property
    def edition_medium(self):
        return self.data.get("edition_medium")

    def budgets(self):
        return dict(self.data.get("budgets", {}))

    def dialect_policy(self):
        return dict(self.data.get("dialect_policy", {"target_strategy": "flavour_lexicon"}))

    def delimiters(self, lang):
        """Declared delimiter map for one language, or None when undeclared.

        `None` still happens for a row-level language override that the profile
        never declared; the caller raises on it. It cannot happen for the
        evidence, pivot, or target language, because the schema requires those.
        """
        return self.data["delimiters"].get(lang)

    def to_json(self):
        return json.dumps(_json_value(self.data), ensure_ascii=False, sort_keys=True, indent=1)


def load_profile(path):
    with open(path, "r", encoding="utf-8") as fh:
        return Profile(json.load(fh), path=path)

# A contract's authority: what entitles it to enforce a target rendering.
#
# `precedent_backed` is the original and stronger claim -- the type is canonical,
# which means a published edition is cited as having shipped this rendering. Such a
# contract asserts that the rendering is the established convention.
#
# `translator_declared` is a deliberately weaker, separately labelled route. It
# rests on the source-side evidence only: the marker is real and measurable. It
# asserts nothing about which Korean rendering is correct, only that the rendering
# the translator declared is applied at the source's measured density, consistently
# and exclusively. It exists because requiring an adopted precedent makes the tool
# unable to govern the first translation of a novel marker, which is the common real
# case, and because detecting that a marker was deleted never needed to know what
# the correct replacement was.
#
# There is no default. A contract that declares neither hard-fails, because a guard
# that defaults to the weaker route is not a guard.
AUTHORITY_PRECEDENT_BACKED = "precedent_backed"
AUTHORITY_TRANSLATOR_DECLARED = "translator_declared"
CONTRACT_AUTHORITIES = (AUTHORITY_PRECEDENT_BACKED, AUTHORITY_TRANSLATOR_DECLARED)
