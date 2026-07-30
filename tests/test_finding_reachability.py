"""Every hard finding this phase can emit must be shown to actually fire.

A hard finding constructed in code but never triggered by any test is
indistinguishable from a dead branch: it could be unreachable, or mis-worded, or
guarding the wrong condition, and nothing would notice. So this module does two
things:

1. It drives each hard finding code in the P1 modules to fire at least once.
2. It enumerates the codes emitted by those modules and asserts that this file
   covers every one of them, so adding a new hard finding without a trigger fails
   the suite rather than quietly shipping an unproven gate.
"""
import ast
import json
import os
import shutil
import tempfile
import unittest

from hancharacter import config, corpus, dialect, precedents, typology


PKG = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "hancharacter"
)
P1_MODULES = ("typology", "corpus", "precedents", "dialect")


def _emitted_hard_codes():
    """Every code passed to ``findings.hard`` in the P1 modules, read from the AST.

    Parsed rather than regex-matched so a reformatted call site cannot slip past
    the enumeration.
    """
    codes = set()
    for name in P1_MODULES:
        path = os.path.join(PKG, "%s.py" % name)
        with open(path, "r", encoding="utf-8") as fh:
            tree = ast.parse(fh.read(), filename=path)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "hard"
                and isinstance(func.value, ast.Name)
                and func.value.id == "findings"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                codes.add(node.args[0].value)
    return codes


def _type(type_id="t1", **over):
    row = {
        "id": type_id,
        "axis": "ending_transform",
        "source_lang": "ja",
        "source_marker": "~x",
        "pattern_set": [r"にゃ[。！？!?…]*$"],
        "provenance": {"origin": "character", "notes": "fixture"},
    }
    row.update(over)
    return row


def _realisation(realisation_id="r1", **over):
    row = {
        "id": realisation_id,
        "type_id": "t1",
        "source_lang": "ja",
        "target_lang": "ko",
        "source_marker": "~x",
        "target_realisation": "~y",
        "length_cost": {"model": "append", "value": 1},
        "precedents": ["p1"],
        "density_band_default": [0.2, 0.8],
        "pattern_set": [r"냥[.!?…]*$"],
    }
    row.update(over)
    return row


def _precedent(precedent_id="p1", **over):
    row = {
        "id": precedent_id,
        "axis": "ending_transform",
        "type_id": "t1",
        "source_lang": "ja",
        "target_lang": "ko",
        "source_marker": "~x",
        "source_work": "w",
        "target_realisation": "~y",
        "edition_channel": "official",
        "verdict": "adopted",
        "citation": "c",
    }
    row.update(over)
    return row


def _source(key="k", locator="p1", **over):
    row = {
        "class": "reference",
        "cite": "c",
        "consulted_via": "mirror",
        "independent_key": key,
        "locator": locator,
    }
    row.update(over)
    return row


def _draft(sample_id="s1", **over):
    row = {
        "id": sample_id,
        "type_id": "t1",
        "axis": "ending_transform",
        "work": "w",
        "producer": "p",
        "marker": "~x",
        "quote": "q %s" % sample_id,
        "source": _source(),
    }
    row.update(over)
    row["quote_len"] = len(row["quote"])
    return row


class Catalogue:
    """A writable temporary catalogue, so each gate can be driven in isolation."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="hc-reach-")
        os.makedirs(os.path.join(self.root, "types"))
        os.makedirs(os.path.join(self.root, "realisations", "ko"))
        os.makedirs(os.path.join(self.root, "probe"))
        os.makedirs(os.path.join(self.root, "reviews"))
        self.version("2026.07")
        for lang in ("ja", "ko"):
            shutil.copyfile(
                os.path.join(config.typology_root(), "probe", "%s.jsonl" % lang),
                os.path.join(self.root, "probe", "%s.jsonl" % lang),
            )

    def version(self, text):
        with open(os.path.join(self.root, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write(text)

    def type(self, row, name=None):
        name = name or row["id"]
        with open(
            os.path.join(self.root, "types", "%s.json" % name), "w", encoding="utf-8"
        ) as fh:
            json.dump(row, fh, ensure_ascii=False)

    def realisation(self, row, name=None):
        name = name or row["id"]
        with open(
            os.path.join(self.root, "realisations", "ko", "%s.json" % name),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(row, fh, ensure_ascii=False)

    def raw(self, relpath, text):
        path = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def jsonl(self, relpath, rows):
        self.raw(
            relpath,
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        )

    def cleanup(self):
        shutil.rmtree(self.root, True)


class HardFindingReachabilityTests(unittest.TestCase):
    """Each test names the codes it drives; `COVERED` is checked against the AST."""

    COVERED = set()

    def setUp(self):
        self.cat = Catalogue()
        self.addCleanup(self.cat.cleanup)

    def _codes(self, result):
        codes = {f.code for f in result.hard}
        type(self).COVERED |= codes
        return codes

    # -- typology ---------------------------------------------------------------
    def test_missing_and_unreadable_catalogue_pieces(self):
        absent = tempfile.mkdtemp(prefix="hc-absent-")
        shutil.rmtree(absent)
        self.assertIn("typology_catalogue_missing", self._codes(typology.lint(absent)))

        self.cat.version("")
        self.cat.type(_type())
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_version_unreadable", codes)

    def test_unloadable_types_and_realisations(self):
        self.cat.raw("types/broken.json", "{not json")
        self.assertIn("typology_types_unloadable", self._codes(typology.lint(self.cat.root)))

        good = Catalogue()
        self.addCleanup(good.cleanup)
        good.type(_type())
        good.raw("realisations/ko/broken.json", "{not json")
        self.assertIn(
            "typology_realisations_unloadable", self._codes(typology.lint(good.root))
        )

    def test_seed_type_missing_and_unrealised(self):
        # A catalogue holding one unrelated type is missing every seed type.
        self.cat.type(_type())
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_seed_type_missing", codes)

        seeded = Catalogue()
        self.addCleanup(seeded.cleanup)
        seed = typology.SEED_TYPE_IDS[0]
        seeded.type(_type(seed))
        seeded.realisation(_realisation("r1", type_id="unrelated"))
        codes = self._codes(typology.lint(seeded.root))
        self.assertIn("typology_seed_type_unrealised", codes)
        self.assertIn("typology_realisation_orphaned", codes)

    def test_precedent_table_missing_unreadable_and_dangling(self):
        self.cat.type(_type())
        self.cat.realisation(_realisation())
        self.assertIn(
            "typology_precedents_missing", self._codes(typology.lint(self.cat.root))
        )

        broken = Catalogue()
        self.addCleanup(broken.cleanup)
        broken.type(_type())
        broken.realisation(_realisation())
        broken.raw("precedents.jsonl", "{not json\n")
        self.assertIn(
            "typology_precedents_unreadable", self._codes(typology.lint(broken.root))
        )

        dangling = Catalogue()
        self.addCleanup(dangling.cleanup)
        dangling.type(_type())
        dangling.realisation(_realisation(precedents=["absent_precedent"]))
        dangling.jsonl("precedents.jsonl", [_precedent("p1")])
        self.assertIn(
            "typology_precedent_dangling", self._codes(typology.lint(dangling.root))
        )

    def test_a_pattern_matching_nothing_is_hard(self):
        self.cat.type(_type(pattern_set=[r"ZZZ_MATCHES_NOTHING_ZZZ$"]))
        self.cat.type(_type("t2", pattern_set=[r"にゃ[。！？!?…]*$"]))
        self.cat.realisation(_realisation())
        self.cat.jsonl("precedents.jsonl", [_precedent("p1")])
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_pattern_matches_nothing", codes)

    def test_an_indistinguishable_pair_is_hard(self):
        self.cat.type(_type("t1"))
        self.cat.type(_type("t2"))  # identical pattern set and no preset link
        self.cat.realisation(_realisation())
        self.cat.jsonl("precedents.jsonl", [_precedent("p1")])
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_indistinguishable_pair", codes)

    def test_no_pair_compared_is_hard(self):
        """One type in one language leaves nothing compared anywhere."""
        self.cat.type(_type())
        self.cat.realisation(_realisation())
        self.cat.jsonl("precedents.jsonl", [_precedent("p1")])
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_no_pair_compared", codes)

    def test_an_unusable_probe_corpus_is_hard(self):
        self.cat.type(_type())
        self.cat.type(_type("t2", pattern_set=[r"ござる[。]*$"]))
        self.cat.realisation(_realisation())
        self.cat.jsonl("precedents.jsonl", [_precedent("p1")])
        os.remove(os.path.join(self.cat.root, "probe", "ja.jsonl"))
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_probe_unusable", codes)

    def test_a_saturating_band_on_an_intermittent_marker_is_hard(self):
        self.cat.type(
            _type(
                provenance={
                    "origin": "character",
                    "notes": "This marker is intermittent by nature.",
                }
            )
        )
        self.cat.type(_type("t2", pattern_set=[r"ござる[。]*$"]))
        self.cat.realisation(_realisation(density_band_default=[1.0, 1.0]))
        self.cat.jsonl("precedents.jsonl", [_precedent("p1")])
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_saturating_band_on_intermittent_marker", codes)

    def test_a_pattern_matching_an_unmarked_control_row_is_hard(self):
        """The check whose absence let four over-generic patterns ship.

        `のだ$` matched the corpus's own unmarked baseline row その荷物は誰のものだ。
        and nothing noticed, because non-vacuity only asked whether a pattern set
        matched *something*.
        """
        self.cat.type(_type(pattern_set=[r"のだ[。！？!?…]*$"]))
        self.cat.type(_type("t2", pattern_set=[r"ござる[。]*$"]))
        self.cat.realisation(_realisation())
        self.cat.jsonl("precedents.jsonl", [_precedent("p1")])
        codes = self._codes(typology.lint(self.cat.root))
        self.assertIn("typology_pattern_matches_unmarked_row", codes)

    def test_no_shipped_pattern_matches_an_unmarked_control_row(self):
        """The positive half: the real catalogue must be clean under that check."""
        result = typology.lint()
        self.assertEqual(
            [],
            [
                f.detail
                for f in result.hard
                if f.code == "typology_pattern_matches_unmarked_row"
            ],
        )

    def test_a_missing_measure_plugin_is_hard(self):
        types = {"t1": _type(source_lang="zz")}
        found = typology.axis_measurability(
            types,
            {},
            "ko",
            axis_status=self._raising_status,
            measurable=config.MEASURABLE_AXIS_STATUSES,
        )
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("typology_axis_plugin_missing", codes)

    @staticmethod
    def _raising_status(lang):
        raise LookupError("no measure plugin for %r" % lang)

    # -- corpus -----------------------------------------------------------------
    def test_corpus_drafts_unloadable_and_empty(self):
        self.assertIn("corpus_drafts_unloadable", self._codes(corpus.lint(self.cat.root)))

        empty = Catalogue()
        self.addCleanup(empty.cleanup)
        empty.raw("samples.draft.jsonl", "")
        self.assertIn("corpus_drafts_empty", self._codes(corpus.lint(empty.root)))

    def test_corpus_reviews_unloadable(self):
        self.cat.jsonl("samples.draft.jsonl", [_draft()])
        shutil.rmtree(os.path.join(self.cat.root, "reviews"))
        self.assertIn("corpus_reviews_unloadable", self._codes(corpus.lint(self.cat.root)))

        mismatched = Catalogue()
        self.addCleanup(mismatched.cleanup)
        mismatched.jsonl("samples.draft.jsonl", [_draft()])
        mismatched.jsonl(
            "reviews/ra.jsonl",
            [{"sample_id": "s1", "reviewer": "someone_else", "verdict": "accept"}],
        )
        mismatched.jsonl(
            "reviews/rb.jsonl",
            [{"sample_id": "s1", "reviewer": "rb", "verdict": "accept"}],
        )
        self.assertIn(
            "corpus_reviews_unloadable", self._codes(corpus.lint(mismatched.root))
        )

    def test_no_row_merged_is_hard(self):
        """Reviews exist but nothing survives to become evidence."""
        self.cat.jsonl("samples.draft.jsonl", [_draft()])
        self.cat.jsonl(
            "reviews/ra.jsonl",
            [{"sample_id": "s1", "reviewer": "ra", "verdict": "accept"}],
        )
        self.cat.jsonl(
            "reviews/rb.jsonl",
            [{"sample_id": "s404", "reviewer": "rb", "verdict": "accept"}],
        )
        codes = self._codes(corpus.lint(self.cat.root))
        self.assertIn("corpus_no_row_merged", codes)
        self.assertIn("corpus_review_orphaned", codes)
        self.assertIn("corpus_review_insufficient", codes)

    def test_a_merged_row_failing_the_schema_is_hard(self):
        """The merge must not emit an invalid sample even from valid inputs."""
        drafts = [_draft("s1", work="")]
        reviews = {
            "ra": [{"sample_id": "s1", "reviewer": "ra", "verdict": "accept"}],
            "rb": [{"sample_id": "s1", "reviewer": "rb", "verdict": "accept"}],
        }
        samples, found = corpus.merge(drafts, reviews)
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("corpus_merged_row_invalid", codes)
        self.assertEqual([], samples)

    def test_corpus_producer_and_quotation_gates(self):
        rows = [
            _draft("s1", producer="ra"),
            _draft("s2", quote="x" * (config.QUOTE_MAX_CHARS_PER_ROW + 1)),
        ]
        rows[1]["quote_len"] = 1  # also a declared-length lie
        found = corpus.copyright_lint(rows)
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("corpus_quote_over_row_ceiling", codes)
        self.assertIn("corpus_quote_len_mismatch", codes)

        cap_rows = [
            _draft(
                "c%d" % i,
                quote="q" * config.QUOTE_MAX_CHARS_PER_ROW,
                source=_source("k%d" % i, locator="l%d" % i),
            )
            for i in range(config.QUOTE_MAX_CHARS_PER_WORK // config.QUOTE_MAX_CHARS_PER_ROW + 2)
        ]
        codes = {f.code for f in corpus.copyright_lint(cap_rows) if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("corpus_quote_over_work_cap", codes)

        dump_rows = [
            _draft("d%d" % i, source=_source("k", locator="same"))
            for i in range(config.DUMP_CONSECUTIVE_ROWS)
        ]
        codes = {f.code for f in corpus.copyright_lint(dump_rows) if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("corpus_consecutive_dump", codes)

        passage = "むかしむかしあるところにおじいさんとおばあさんがすんでいました"
        split = [
            _draft("x1", marker="", quote=passage[:20], source=_source("k", locator="a")),
            _draft("x2", marker="", quote=passage[10:30], source=_source("k", locator="b")),
        ]
        codes = {f.code for f in corpus.copyright_lint(split) if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("corpus_split_dump", codes)

        laundered = [
            _draft("y1", marker=passage[:20], quote=passage[:20], source=_source("k", locator="a")),
            _draft("y2", marker=passage[10:30], quote=passage[10:30], source=_source("k", locator="b")),
        ]
        codes = {f.code for f in corpus.copyright_lint(laundered) if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("corpus_marker_laundered_dump", codes)

    def test_producer_reviewing_own_row_is_hard(self):
        drafts = [_draft("s1", producer="ra")]
        reviews = {
            "ra": [{"sample_id": "s1", "reviewer": "ra", "verdict": "accept"}],
            "rb": [{"sample_id": "s1", "reviewer": "rb", "verdict": "accept"}],
        }
        _, found = corpus.merge(drafts, reviews)
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("corpus_producer_reviewed_own_row", codes)

    def test_insufficient_reviewer_files_is_hard(self):
        self.cat.jsonl("samples.draft.jsonl", [_draft()])
        self.cat.jsonl(
            "reviews/ra.jsonl",
            [{"sample_id": "s1", "reviewer": "ra", "verdict": "accept"}],
        )
        codes = self._codes(corpus.lint(self.cat.root))
        self.assertIn("corpus_reviewers_insufficient", codes)

    def test_a_rejected_pattern_the_probe_never_exercises_is_hard(self):
        """Otherwise a realisation copying that exact rendering passes."""
        self.cat.jsonl(
            "precedents.jsonl",
            [
                _precedent(
                    "p_blind",
                    verdict="rejected",
                    target_pattern_set=[r"NEVER_PROBED_XYZ[.!?…]*$"],
                )
            ],
        )
        result = precedents.lint(
            self.cat.root, matched_markers=typology.matched_markers
        )
        codes = self._codes(result)
        self.assertIn("precedent_rejected_pattern_unprobed", codes)

    def test_a_dialect_ruling_citing_a_foreign_pair_is_hard(self):
        pair = {
            "target_strategy": config.DIALECT_FULL_SUBSTITUTION,
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
        }
        ruling = {
            "id": "d9",
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
            "work": "w",
            "strategy": config.DIALECT_FULL_SUBSTITUTION,
            "reason": "r",
            "decided_by": "o",
            "decided_at": "2026-01-01T00:00:00Z",
            "decision_hash": dialect.decision_hash("kansai", "gyeongsang", "w"),
            "precedents": ["prec_other_marker"],
        }
        found = dialect.gate(
            pair,
            "w",
            decisions=[ruling],
            # Adopted, but evidence about a different marker entirely.
            adopted_precedent_ids={"prec_other_marker": (None, None)},
            sample_count=99,
        )
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("dialect_precedent_pair_mismatch", codes)

    def test_an_unbacked_realisation_channel_is_hard(self):
        adopted = {"p1": ("community", "fixture_type")}
        realisations = {"r1": _realisation(edition_channel="official")}
        found = typology.channel_backing(realisations, adopted)
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("typology_channel_unbacked", codes)

    # -- precedents -------------------------------------------------------------
    def test_precedent_table_unloadable_and_empty(self):
        self.assertIn(
            "precedent_table_unloadable", self._codes(precedents.lint(self.cat.root))
        )
        self.cat.raw("precedents.jsonl", "")
        self.assertIn(
            "precedent_table_empty", self._codes(precedents.lint(self.cat.root))
        )

    def test_precedent_reference_and_verdict_gates(self):
        self.cat.jsonl(
            "precedents.jsonl",
            [
                _precedent("p1", contradicts=["absent"]),
                _precedent("p2", resolved_by="absent_confirm", contradicts=["p1"]),
                _precedent("p3", verdict="contested"),
            ],
        )
        codes = self._codes(precedents.lint(self.cat.root))
        self.assertIn("precedent_contradiction_dangling", codes)
        self.assertIn("precedent_resolution_dangling", codes)
        self.assertIn("precedent_verdict_conflict", codes)

    def test_precedent_support_and_matcher_gates(self):
        rows = [_precedent("p1", verdict="contested")]
        _, found = precedents.canonical_support(rows)
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("precedent_no_adopted_support", codes)

        conflicted = [
            _precedent("p1", verdict="adopted", contradicts=["p2"]),
            _precedent("p2", verdict="rejected"),
        ]
        _, found = precedents.canonical_support(conflicted)
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("precedent_contradiction_unresolved", codes)

        siblings = [
            _precedent("p1", edition_channel="official"),
            _precedent("p2", edition_channel="licensed"),
        ]
        _, found = precedents.select_sibling(siblings, None)
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("precedent_sibling_unselected", codes)

        offender = {
            "id": "ko_bad",
            "type_id": "t1",
            "target_lang": "ko",
            "pattern_set": [r"다해[.!?…]*$"],
        }
        rejected = [
            _precedent("p1", verdict="rejected", target_pattern_set=[r"다해[.!?…]*$"])
        ]
        found = precedents.rejected_match(
            offender,
            rejected,
            matched_markers=typology.matched_markers,
            containment=typology.containment,
        )
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("precedent_rejected_reproduced", codes)

    # -- dialect ----------------------------------------------------------------
    def test_dialect_gates(self):
        self.cat.raw("dialect_decisions.jsonl", "{not json\n")
        self.assertIn(
            "dialect_decisions_unloadable", self._codes(dialect.lint(self.cat.root))
        )

        stale = {
            "id": "d1",
            "source_dialect": "a",
            "target_dialect": "b",
            "work": "w",
            "strategy": config.DIALECT_FLAVOUR_LEXICON,
            "reason": "r",
            "decided_by": "o",
            "decided_at": "2026-01-01T00:00:00Z",
            "decision_hash": "0" * 40,
        }
        stale_cat = Catalogue()
        self.addCleanup(stale_cat.cleanup)
        stale_cat.jsonl("dialect_decisions.jsonl", [stale])
        self.assertIn(
            "dialect_decision_stale", self._codes(dialect.lint(stale_cat.root))
        )

        pair = {
            "target_strategy": config.DIALECT_FLAVOUR_LEXICON,
            "source_dialect": "a",
            "target_dialect": "b",
        }
        found = dialect.gate(pair, "w", decisions=[])
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("dialect_pair_undecided", codes)

        found = dialect.gate({"target_strategy": "improvise"}, "w", decisions=[])
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("dialect_strategy_undeclared", codes)

        found = dialect.gate(
            {"target_strategy": config.DIALECT_FULL_SUBSTITUTION}, "w", decisions=[]
        )
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("dialect_pair_undeclared", codes)

        ok, found = dialect.full_substitution_allowed(
            "a", "b", adopted_precedents=0, sample_count=0
        )
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("dialect_full_substitution_unprecedented", codes)
        self.assertIn("dialect_full_substitution_undersampled", codes)

        full = {
            "target_strategy": config.DIALECT_FULL_SUBSTITUTION,
            "source_dialect": "a",
            "target_dialect": "b",
        }
        ruling = {
            "id": "d2",
            "source_dialect": "a",
            "target_dialect": "b",
            "work": "w",
            "strategy": config.DIALECT_FLAVOUR_LEXICON,
            "reason": "r",
            "decided_by": "o",
            "decided_at": "2026-01-01T00:00:00Z",
            "decision_hash": dialect.decision_hash("a", "b", "w"),
        }
        found = dialect.gate(full, "w", decisions=[ruling])
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("dialect_strategy_mismatch", codes)

        cited = dict(ruling, id="d3", strategy=config.DIALECT_FULL_SUBSTITUTION,
                     precedents=["prec_invented"])
        found = dialect.gate(full, "w", decisions=[cited], adopted_precedent_ids=set())
        codes = {f.code for f in found if f.severity == "hard"}
        type(self).COVERED |= codes
        self.assertIn("dialect_precedents_unbacked", codes)


class ZZCoverageTests(unittest.TestCase):
    """Named to sort last: it audits what the tests above actually drove.

    This is the check that keeps the file honest. Adding a hard finding without a
    trigger makes the suite fail instead of shipping an unproven gate.
    """

    def test_every_emitted_hard_finding_code_was_driven(self):
        emitted = _emitted_hard_codes()
        self.assertTrue(emitted, "no hard finding codes found; the AST scan is broken")
        missing = sorted(emitted - HardFindingReachabilityTests.COVERED)
        self.assertEqual(
            [],
            missing,
            "these hard findings are emitted but never driven by a test, so "
            "nothing proves they can fire: %s" % missing,
        )


if __name__ == "__main__":
    unittest.main()
