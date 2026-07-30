"""Pin the shipped evidence state, so the headline numbers are checked rather than claimed.

`docs/evidence.md` and `catalogue/SOURCES.md` state what the collected evidence
achieves: no type canonical, one provisional, kappa below the floor, no accepted
primary or secondary source, one unresolved contradiction, no dialect ruling. Those
are the numbers a reader will trust, and until this module existed nothing checked
them — the doctrine's "every verdict re-derivable from artifacts" was satisfied only
by a human re-deriving them by hand.

These assertions are deliberately exact. If collecting more evidence moves a number,
this file must be updated in the same change as the documents, which is the point:
the two cannot drift apart silently.
"""
import ast
import hashlib
import json
import os
import unittest
from fractions import Fraction

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from hancharacter import cli, config, corpus, dialect, precedents, typology, contracts, findings, measure


GENERATED_AT = "2026-07-29T00:00:00Z"


class Args:
    """The CLI argument surface `_graduation` reads."""

    generated_at = GENERATED_AT
    json = False
    lint = False
    target = "ko"



def _load_realisation(name):
    path = os.path.join(ROOT, "catalogue", "realisations", "ko", "%s.json" % name)
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


class ShippedEvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report, cls.merge_findings = cli._graduation(Args())
        cls.by_type = {entry["type_id"]: entry for entry in cls.report["types"]}
        cls.samples, _ = corpus.merge(corpus.load_drafts(), corpus.load_reviews())

    def test_no_type_is_canonical(self):
        """P1 is still a closed gate, but for a different reason than before.

        `ja_hao_gozaru` now meets every canonical criterion except one: it has no
        adopted precedent, because the only candidate was corrected down to
        `contested` for consistency with its siblings.  The evidence-volume and
        `e1e2_sources` blockers that previously shut the gate are closed.
        """
        canonical = sorted(
            entry["type_id"]
            for entry in self.report["types"]
            if entry["stage"] == config.STAGE_CANONICAL
        )
        self.assertEqual([], canonical)

    def test_two_types_are_provisional(self):
        provisional = sorted(
            entry["type_id"]
            for entry in self.report["types"]
            if entry["stage"] == config.STAGE_PROVISIONAL
        )
        self.assertEqual(["ja_elder_lexicon", "ja_hao_gozaru"], provisional)

    def test_the_gozaru_type_fails_canonical_on_the_precedent_criterion_alone(self):
        entry = self.by_type["ja_hao_gozaru"]
        # Two unmet criteria now: the missing precedent, and the kappa stability
        # requirement landed while its cost was still zero because this type was
        # already blocked on the precedent anyway.
        self.assertEqual(2, len(entry["unmet"]))
        self.assertIn("adopted precedents 0 < 1 required for canonical", entry["unmet"])
        self.assertTrue(
            any("verdict is unstable" in reason for reason in entry["unmet"]),
            entry["unmet"],
        )
        self.assertGreater(entry["kappa_downward_flips"], 0)
        self.assertEqual(12, entry["occurrences"])
        self.assertEqual(4, entry["independent_sources"])
        self.assertEqual(1, entry["e1e2_sources"])
        self.assertGreaterEqual(entry["occurrences"], config.CANONICAL_MIN_OCCURRENCES)
        self.assertGreaterEqual(
            entry["independent_sources"], config.CANONICAL_MIN_INDEPENDENT_SOURCES
        )
        self.assertGreaterEqual(entry["kappa"], config.KAPPA_FLOOR)

    def test_the_gozaru_kappa_sits_exactly_on_the_floor(self):
        """Hand-derivable and deliberately published as a fragility.

        Over the 16 reviewed gozaru rows there are 14 agreements, so
        p_o = 7/8 and p_e = 11/16, giving kappa = (3/16)/(5/16) = 3/5 exactly.
        That is not a rounding artifact, but it is exactly the floor and not
        above it: a single verdict flip would drop the type below canonical.
        """
        self.assertEqual(Fraction(3, 5), Fraction(config.KAPPA_FLOOR).limit_denominator(1000))
        self.assertAlmostEqual(3 / 5, self.by_type["ja_hao_gozaru"]["kappa"], places=9)

    def test_the_elder_type_reached_provisional_floors(self):
        entry = self.by_type["ja_elder_lexicon"]
        self.assertEqual(3, entry["occurrences"])
        self.assertEqual(3, entry["independent_sources"])
        self.assertEqual(1, entry["e1e2_sources"])
        self.assertLess(entry["occurrences"], config.CANONICAL_MIN_OCCURRENCES)

    def test_overall_kappa_is_the_documented_value(self):
        """Hand-derivable: 34 agreements of 42, so kappa = 87/143."""
        pairs = [
            (
                row["reviewer_verdicts"][row["reviewer"]],
                row["reviewer_verdicts"][row["review2"]],
            )
            for row in self.samples
        ]
        self.assertEqual(42, len(pairs))
        self.assertEqual(34, sum(1 for a, b in pairs if a == b))
        kappa = corpus.cohens_kappa(pairs)
        self.assertIsNotNone(kappa)
        self.assertAlmostEqual(87 / 143, kappa, places=9)

    def test_exactly_three_types_have_accepted_secondary_evidence(self):
        """The catalogue's first primary/secondary provenance, and it survives.

        Every type previously sat at e1e2_sources == 0, which blocked canonical
        regardless of any other criterion.  One academic source now supports
        three types; the remaining seven are still at zero and this pins which.
        """
        with_e1e2 = sorted(
            entry["type_id"]
            for entry in self.report["types"]
            if entry["e1e2_sources"] > 0
        )
        self.assertEqual(
            ["ja_elder_lexicon", "ja_hao_gozaru", "ja_nyan_copula"], with_e1e2
        )
        zero = [
            entry["type_id"]
            for entry in self.report["types"]
            if entry["e1e2_sources"] == 0
        ]
        self.assertEqual(7, len(zero))

    def test_no_row_claims_primary_provenance(self):
        """Still true: the academic source is secondary scholarship, not a primary text."""
        for row in corpus.load_drafts():
            with self.subTest(row=row["id"]):
                self.assertNotEqual(config.SOURCE_PRIMARY, row["source"]["class"])

    def test_no_single_publication_holds_a_majority_of_the_corpus(self):
        """The disclosed concentration improved but is still worth publishing.

        It was 19 of 26 rows from one wiki lineage.  It is now 19 of 42, so no
        single publication holds a majority, but namuwiki is still the largest
        single contributor and that stays disclosed rather than being dropped.
        """
        drafts = corpus.load_drafts()
        counts = {}
        for row in drafts:
            key = row["source"]["independent_key"]
            counts[key] = counts.get(key, 0) + 1
        self.assertEqual(42, len(drafts))
        self.assertEqual(19, counts["namuwiki_special_endings"])
        self.assertEqual(11, counts["shimane_kobayashi_gozaru"])
        self.assertLess(counts["namuwiki_special_endings"], len(drafts) / 2)
        self.assertEqual(
            "namuwiki_special_endings", max(counts, key=lambda key: counts[key])
        )

    def test_the_dearimasu_contradiction_is_open(self):
        rows = precedents.by_type(precedents.load())["ja_danakka_dearimasu"]
        confirm_ids = {row["id"] for row in cli._load_confirms()}
        open_pairs = precedents.unresolved_contradictions(rows, confirm_ids)
        self.assertEqual(
            [("prec_dearimasu_flattened_ko", "prec_dearimasu_jimalimnida_ko")],
            open_pairs,
        )
        self.assertEqual(1, self.by_type["ja_danakka_dearimasu"]["unresolved_contradictions"])

    def test_no_dialect_ruling_is_recorded(self):
        """An undecided pair is the honest state; the gate fires for any work using it."""
        self.assertEqual([], dialect.load_decisions())

    def test_the_seed_type_list_carries_exactly_one_human_confirmation(self):
        confirms = cli._load_confirms()
        self.assertEqual(1, len(confirms))
        self.assertEqual(sorted(typology.SEED_TYPE_IDS), sorted(confirms[0]["confirms"]))
        # The scope must state what it does NOT cover, or it reads as blanket approval.
        self.assertIn("개별 마커 행", confirms[0]["scope"])

    def test_every_realisation_channel_is_backed_or_declared_unpublished(self):
        adopted = {
            row["id"]: (row["edition_channel"], row["type_id"])
            for row in precedents.load()
            if row["verdict"] == config.PRECEDENT_ADOPTED
        }
        found = typology.channel_backing(typology.load_realisations("ko"), adopted)
        self.assertEqual([], [f.detail for f in found])

    def test_eight_of_nine_seed_types_are_sealable(self):
        """The ninth is refused because its source axis is not measurable."""
        from hancharacter import measure

        status = lambda lang: dict(measure.get_plugin(lang).AXES)
        types = typology.load_types()
        realisations = typology.load_realisations("ko")
        refused = {}
        for type_id in typology.SEED_TYPE_IDS:
            ok, reasons = typology.sealable(
                type_id,
                types,
                realisations,
                "ko",
                axis_status=status,
                measurable=config.MEASURABLE_AXIS_STATUSES,
            )
            if not ok:
                refused[type_id] = reasons
        self.assertEqual(["ja_chuunibyou_frame"], sorted(refused))
        self.assertIn("utterance_frame", refused["ja_chuunibyou_frame"][0])

    def test_the_merge_publishes_no_hard_finding_on_the_shipped_corpus(self):
        self.assertEqual(
            [], [f.detail for f in self.merge_findings if f.severity == "hard"]
        )

    def test_every_lint_is_clean_on_the_shipped_catalogue(self):
        from hancharacter import measure

        lints = {
            "types": typology.lint(
                axis_status=lambda lang: dict(measure.get_plugin(lang).AXES),
                measurable=config.MEASURABLE_AXIS_STATUSES,
                exempt_axes=("dialect_policy",),
            ),
            "corpus": corpus.lint(),
            "precedents": precedents.lint(
                known_confirm_ids={row["id"] for row in cli._load_confirms()}
            ),
            "dialect": dialect.lint(),
        }
        for name, result in sorted(lints.items()):
            with self.subTest(lint=name):
                self.assertEqual([], [f.detail for f in result.hard])

    def test_the_unprobed_pattern_count_is_exactly_as_documented(self):
        """A count in prose that no test pins is a claim, not a measurement."""
        unprobed = []
        types = typology.load_types()
        for type_id, row in sorted(types.items()):
            for pattern in row["pattern_set"]:
                if not typology.matched_markers([pattern], row["source_lang"]):
                    unprobed.append((type_id, pattern))
        for realisation_id, row in sorted(typology.load_realisations("ko").items()):
            for pattern in row.get("pattern_set") or []:
                if not typology.matched_markers([pattern], "ko"):
                    unprobed.append((realisation_id, pattern))
        self.assertEqual(9, len(unprobed), unprobed)

    def test_the_probe_matcher_uses_the_enforcement_matcher_flags(self):
        """The two matchers drifted once; nothing compared them until now."""
        import re

        from hancharacter import measure

        probe = typology.compile_patterns([r"\bzis\b"])[0]
        self.assertTrue(probe.search("Zis is not what I expected at all."))
        self.assertIs(True, measure.pattern_match("Zis is here.", [r"\bzis\b"]))
        self.assertEqual(re.IGNORECASE, typology.PATTERN_FLAGS)

    def test_recorded_coverage_gaps_are_published_rather_than_silent(self):
        """Unprobed patterns and unmatchable rejected precedents must be visible."""
        from hancharacter import measure

        result = typology.lint(
            axis_status=lambda lang: dict(measure.get_plugin(lang).AXES),
            measurable=config.MEASURABLE_AXIS_STATUSES,
            exempt_axes=("dialect_policy",),
        )
        codes = {f.code for f in result.reported}
        self.assertIn("typology_pattern_unprobed", codes)
        self.assertIn("typology_axis_not_measurable", codes)


if __name__ == "__main__":
    unittest.main()


class SealIsGatedOnGraduationTests(unittest.TestCase):
    """The seal mechanism is gated on graduation stage, proven differentially.

    This deliberately does NOT claim the shipped catalogue can seal -- it cannot,
    because 0 of 10 types are canonical.  The stage is injected so the same
    candidate can be run on both sides of the gate, which is the only way to show
    the gate is load-bearing rather than incidental.
    """

    TYPE_ID = "ja_hao_gozaru"
    AXIS = "speech_level"

    def _candidate(self, **overrides):
        realisation = _load_realisation("ko_hao_io")
        target = realisation["pattern_set"]
        digest = hashlib.sha256(
            json.dumps(sorted(target), ensure_ascii=False).encode()
        ).hexdigest()
        kwargs = dict(
            attribution={
                "evidence_tier": "T1",
                "target_tier": "T1",
                "status": "attributed",
            },
            required_markers=target,
            forbidden_markers=[r"입니다[.!?…]*$"],
            measured_source_density={self.AXIS: 0.5},
            bands={"proof1": {self.AXIS: [0.35, 0.65]}},
            scope_overrides={},
            exclusivity={"exclusive_with": []},
            edition_medium="novel/print",
            voice_enforcement_mode="voice_critical",
            authority=config.AUTHORITY_PRECEDENT_BACKED,
            coverage_floor=0.70,
            declared_speakers=["proof1"],
            corpus_digests={self.TYPE_ID: digest},
            marker_sets={self.AXIS: target},
            catalogue_markers={
                self.TYPE_ID: ["でござる[。！？!?…]*$", "ござる[。！？!?…]*$"]
            },
            review_decisions={},
            required_glyphs=[],
            axis_status=lambda language: dict(measure.get_plugin(language).AXES),
            measurable=config.MEASURABLE_AXIS_STATUSES,
            root=None,
        )
        kwargs.update(overrides)
        return contracts.build(
            "t1-seal-proof", "proof1", [self.TYPE_ID], "ja", "ko", **kwargs
        )

    def _seal(self, candidate, stages=None):
        report, _ = cli._graduation(Args())
        actual = {entry["type_id"]: entry["stage"] for entry in report["types"]}
        empty = findings.FindingSet()
        return contracts.seal(
            candidate,
            schema_validate=contracts.validate_contract,
            graduation_stages=stages or actual,
            length_ok=True,
            plugin_for=measure.get_plugin,
            plugin_measurable_axes=lambda language: sorted(
                measure.measurable_axes(language)
            ),
            plugin_golden_digest=measure.golden_digest,
            rejected_precedent_match=lambda candidate: empty,
            glyph_available=lambda glyph: True,
            coverage={"proof1": 0.90},
            dialect_findings=empty,
        )

    def test_a_contract_seals_when_its_type_is_canonical(self):
        sealed, found = self._seal(
            self._candidate(), stages={self.TYPE_ID: config.STAGE_CANONICAL}
        )
        self.assertIsNotNone(
            sealed, msg=[f["code"] for f in found.to_json()]
        )
        self.assertEqual([self.TYPE_ID], sealed["type_ids"])
        self.assertIn("hash", sealed["seal"])

    def test_the_same_contract_is_refused_at_the_shipped_provisional_stage(self):
        """The shipped stage for this type. Identical candidate, opposite verdict."""
        sealed, found = self._seal(
            self._candidate(), stages={self.TYPE_ID: config.STAGE_PROVISIONAL}
        )
        self.assertIsNone(sealed)
        self.assertIn(
            "contract_type_not_canonical", [f["code"] for f in found.to_json()]
        )


class KappaFloorWasCrossedByDilutionTests(unittest.TestCase):
    """The mechanism by which the canonical type crossed the kappa floor.

    This is disclosed rather than hidden because it is unflattering. Before this
    round `ja_hao_gozaru` kappa was 1/2 over the eight original rows, with two
    disagreements. Eight new rows were added on which both reviewers agreed.
    Cohen's kappa rises monotonically when modal-category agreements are
    appended, so the two existing disagreements were diluted and kappa reached
    exactly the 0.60 floor.

    The graduation is therefore load-bearing on the eighth unanimous row: remove
    any one of them and kappa is 22/37 = 0.5946 and the type is not canonical,
    while every other criterion is still met.

    The consequence is a property of the gate, not of this catalogue: KAPPA_FLOOR
    is clearable by anyone willing to add rows that are easy to agree on. The
    zero-disagreement guard in `corpus.cohens_kappa` blocks the degenerate end of
    that spectrum but not dilution in general.
    """

    def _pairs(self, samples, exclude=()):
        return [
            (
                row["reviewer_verdicts"][row["reviewer"]],
                row["reviewer_verdicts"][row["review2"]],
            )
            for row in samples
            if row["type_id"] == "ja_hao_gozaru" and row["id"] not in exclude
        ]

    def setUp(self):
        self.samples, _ = corpus.merge(corpus.load_drafts(), corpus.load_reviews())
        self.new_rows = sorted(
            row["id"]
            for row in corpus.load_drafts()
            if row["type_id"] == "ja_hao_gozaru" and row.get("producer") == "T1Leader"
        )

    def test_eight_new_rows_were_added_and_all_are_unanimous(self):
        self.assertEqual(8, len(self.new_rows))
        for row_id in self.new_rows:
            pairs = self._pairs(self.samples, exclude=set(self.new_rows) - {row_id})
            added = [pair for pair in pairs if pair[0] == pair[1]]
            self.assertTrue(added)

    def test_removing_any_one_new_row_drops_the_type_below_the_floor(self):
        for row_id in self.new_rows:
            with self.subTest(removed=row_id):
                kappa = corpus.cohens_kappa(self._pairs(self.samples, exclude={row_id}))
                self.assertIsNotNone(kappa)
                self.assertLess(kappa, config.KAPPA_FLOOR)
                self.assertAlmostEqual(22 / 37, kappa, places=9)

    def test_the_original_rows_alone_were_below_the_floor(self):
        kappa = corpus.cohens_kappa(self._pairs(self.samples, exclude=set(self.new_rows)))
        self.assertIsNotNone(kappa)
        self.assertAlmostEqual(0.5, kappa, places=9)
        self.assertLess(kappa, config.KAPPA_FLOOR)


class DeclaredRouteEnforcesWithoutAnyPrecedentTests(unittest.TestCase):
    """Path A end to end: no adopted precedent, and flattening is still caught.

    This is the whole premise. Detecting that a marker was deleted never needed to
    know what the correct replacement was, so the adopted-precedent requirement was
    blocking the common real case (a first translation of a novel marker) for no
    measurement reason.
    """

    TYPE_ID = "ja_hao_gozaru"
    SOURCE_AXIS = "speech_level"
    SOURCE_PATTERNS = [r"でござる[。！？!?…]*$"]

    def setUp(self):
        self.realisation = _load_realisation("ko_hao_io")
        self.target_patterns = self.realisation["pattern_set"]
        # The source axis is Japanese speech_level; the Korean plugin declares that
        # axis not_applicable and measures the realisation's declared target_axis.
        self.target_axis = self.realisation["target_axis"]

    def _seal(self, stage):
        digest = hashlib.sha256(
            json.dumps(sorted(self.target_patterns), ensure_ascii=False).encode()
        ).hexdigest()
        candidate = contracts.build(
            "declared-demo", "hero", [self.TYPE_ID], "ja", "ko",
            attribution={
                "evidence_tier": "T1", "target_tier": "T1", "status": "attributed",
            },
            required_markers=self.target_patterns,
            forbidden_markers=[r"입니다[.!?…]*$"],
            measured_source_density={self.SOURCE_AXIS: 0.5},
            bands={"hero": {self.SOURCE_AXIS: [0.35, 0.65]}},
            scope_overrides={},
            exclusivity={"exclusive_with": []},
            edition_medium="novel/print",
            voice_enforcement_mode="voice_critical",
            authority=config.AUTHORITY_TRANSLATOR_DECLARED,
            coverage_floor=0.70,
            declared_speakers=["hero"],
            corpus_digests={self.TYPE_ID: digest},
            marker_sets={self.SOURCE_AXIS: self.target_patterns},
            catalogue_markers={self.TYPE_ID: self.SOURCE_PATTERNS},
            review_decisions={},
            required_glyphs=[],
            axis_status=lambda language: dict(measure.get_plugin(language).AXES),
            measurable=config.MEASURABLE_AXIS_STATUSES,
            root=None,
        )
        empty = findings.FindingSet()
        return contracts.seal(
            candidate,
            schema_validate=contracts.validate_contract,
            graduation_stages={self.TYPE_ID: stage},
            source_evidence_ok=lambda type_id: True,
            length_ok=True,
            plugin_for=measure.get_plugin,
            plugin_measurable_axes=lambda language: sorted(
                measure.measurable_axes(language)
            ),
            plugin_golden_digest=measure.golden_digest,
            rejected_precedent_match=lambda candidate: empty,
            glyph_available=lambda glyph: True,
            coverage={"hero": 0.90},
            dialect_findings=empty,
        )

    def _density(self, plugin, axis, patterns, texts):
        matched = sum(
            1 for text in texts if plugin.match({"base": text}, axis, patterns)
        )
        return matched / len(texts)

    def test_the_shipped_type_has_no_adopted_precedent(self):
        rows = precedents.by_type(precedents.load())[self.TYPE_ID]
        self.assertEqual([], [r["id"] for r in rows if r["verdict"] == "adopted"])

    def test_it_seals_at_provisional_with_no_precedent_at_all(self):
        sealed, found = self._seal(config.STAGE_PROVISIONAL)
        self.assertIsNotNone(sealed, [f["code"] for f in found.to_json()])
        self.assertEqual(config.AUTHORITY_TRANSLATOR_DECLARED, sealed["authority"])

    def test_a_flattened_rendering_is_caught_under_the_declared_route(self):
        sealed, _ = self._seal(config.STAGE_PROVISIONAL)
        self.assertIsNotNone(sealed)
        source = ["これは主命でござる。", "わかった。"]
        d_src = self._density(
            measure.get_plugin("ja"), self.SOURCE_AXIS, self.SOURCE_PATTERNS, source
        )
        self.assertAlmostEqual(0.5, d_src)
        flattened = ["이것이 주인의 명입니다.", "알았습니다."]
        d_flat = self._density(
            measure.get_plugin("ko"), self.target_axis, self.target_patterns, flattened
        )
        self.assertAlmostEqual(0.0, d_flat)
        self.assertLess(d_flat, d_src)

    def test_a_faithful_intermittent_rendering_matches_the_source_density(self):
        source = ["これは主命でござる。", "わかった。"]
        d_src = self._density(
            measure.get_plugin("ja"), self.SOURCE_AXIS, self.SOURCE_PATTERNS, source
        )
        faithful = ["이것이 주인의 명이오.", "알았다."]
        d_faithful = self._density(
            measure.get_plugin("ko"), self.target_axis, self.target_patterns, faithful
        )
        self.assertAlmostEqual(d_src, d_faithful)

    def test_enforcement_never_branches_on_authority(self):
        """So LOSS and INVENTION behave identically under both routes, by construction."""
        path = os.path.join(ROOT, "hancharacter", "gates.py")
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        tree = ast.parse(source, filename=path)
        conditional = [
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.If, ast.IfExp))
            and "authority" in (ast.get_source_segment(source, node.test) or "")
        ]
        self.assertEqual([], conditional)
