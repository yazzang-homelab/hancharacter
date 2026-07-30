import json
import os
import shutil
import tempfile
import unittest

from hancharacter import config, corpus, findings, schemas


def _source(key="src_a", cls="reference", via="mirror", locator="page one"):
    return {
        "class": cls,
        "cite": "fixture citation for %s" % key,
        "consulted_via": via,
        "independent_key": key,
        "locator": locator,
    }


def _draft(sample_id, **over):
    row = {
        "id": sample_id,
        "type_id": "fixture_type",
        "axis": "ending_transform",
        "work": "fixture work",
        "producer": "producer_p",
        "marker": "~x",
        "quote": "fixture quote %s" % sample_id,
        "source": _source(),
    }
    row.update(over)
    row["quote_len"] = len(row["quote"])
    if "quote_len" in over:
        row["quote_len"] = over["quote_len"]
    return row


def _reviews(sample_ids, a="accept", b="accept", names=("rev_a", "rev_b")):
    out = {}
    for name, verdict in zip(names, (a, b)):
        out[name] = [
            {"sample_id": sid, "reviewer": name, "verdict": verdict}
            for sid in sample_ids
        ]
    return out


class MergeTests(unittest.TestCase):
    def test_two_agreeing_reviews_produce_a_valid_sample(self):
        drafts = [_draft("s001")]
        samples, found = corpus.merge(drafts, _reviews(["s001"]))
        self.assertEqual([], [f.detail for f in found])
        self.assertEqual(1, len(samples))
        self.assertEqual("accept", samples[0]["verdict"])
        self.assertEqual([], schemas.validate("corpus_sample", samples[0]))

    def test_a_single_review_is_hard_and_produces_no_sample(self):
        drafts = [_draft("s001")]
        reviews = {"rev_a": [{"sample_id": "s001", "reviewer": "rev_a", "verdict": "accept"}]}
        samples, found = corpus.merge(drafts, reviews)
        self.assertEqual([], samples)
        self.assertIn("corpus_review_insufficient", [f.code for f in found])
        self.assertTrue(all(f.severity == "hard" for f in found))

    def test_a_producer_reviewing_their_own_row_is_hard(self):
        drafts = [_draft("s001", producer="rev_a")]
        samples, found = corpus.merge(drafts, _reviews(["s001"]))
        self.assertEqual([], samples)
        self.assertIn("corpus_producer_reviewed_own_row", [f.code for f in found])

    def test_disagreement_resolves_to_needs_review_and_is_preserved(self):
        drafts = [_draft("s001")]
        samples, _ = corpus.merge(drafts, _reviews(["s001"], a="accept", b="reject"))
        self.assertEqual("needs_review", samples[0]["verdict"])
        self.assertEqual(
            {"rev_a": "accept", "rev_b": "reject"}, samples[0]["reviewer_verdicts"]
        )

    def test_unanimous_reject_stays_reject(self):
        drafts = [_draft("s001")]
        samples, _ = corpus.merge(drafts, _reviews(["s001"], a="reject", b="reject"))
        self.assertEqual("reject", samples[0]["verdict"])

    def test_a_review_of_an_unknown_row_is_hard(self):
        samples, found = corpus.merge([_draft("s001")], _reviews(["s404"]))
        codes = [f.code for f in found]
        self.assertIn("corpus_review_orphaned", codes)

    def test_a_third_reviewer_is_reported_rather_than_dropped(self):
        drafts = [_draft("s001")]
        reviews = _reviews(["s001"])
        reviews["rev_c"] = [
            {"sample_id": "s001", "reviewer": "rev_c", "verdict": "reject"}
        ]
        samples, found = corpus.merge(drafts, reviews)
        self.assertEqual(1, len(samples))
        report = [f for f in found if f.code == "corpus_extra_reviewer_not_carried"]
        self.assertEqual(1, len(report))
        self.assertEqual("report", report[0].severity)
        # The resolution uses every vote, so a 2-1 split is needs_review, and the
        # carried pair includes the dissenter so the row stays self-consistent.
        self.assertEqual("needs_review", samples[0]["verdict"])
        self.assertIn("rev_c", samples[0]["reviewer_verdicts"])
        self.assertEqual("reject", samples[0]["reviewer_verdicts"]["rev_c"])
        self.assertIn("rev_b=accept", report[0].detail)

    def test_a_third_reviewers_rejection_cannot_be_dropped(self):
        """Resolving from the first two by id let a 2-1 split count as unanimous."""
        drafts = [_draft("s001")]
        reviews = _reviews(["s001"])
        reviews["rev_c"] = [
            {"sample_id": "s001", "reviewer": "rev_c", "verdict": "reject"}
        ]
        samples, _ = corpus.merge(drafts, reviews)
        self.assertEqual("needs_review", samples[0]["verdict"])
        entry = corpus.graduate("fixture_type", samples, {"adopted": 1}, 1)
        self.assertEqual(0, entry["occurrences"])


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hc-corpus-")
        os.makedirs(os.path.join(self.root, "reviews"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write_drafts(self, rows):
        with open(corpus.drafts_path(self.root), "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _write_reviews(self, name, rows):
        path = os.path.join(self.root, "reviews", "%s.jsonl" % name)
        with open(path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_a_reviewer_may_not_file_under_another_name(self):
        self._write_drafts([_draft("s001")])
        self._write_reviews(
            "rev_a", [{"sample_id": "s001", "reviewer": "rev_b", "verdict": "accept"}]
        )
        with self.assertRaises(corpus.CorpusError) as caught:
            corpus.load_reviews(self.root)
        self.assertIn("filename says", str(caught.exception))

    def test_duplicate_draft_ids_are_an_error(self):
        self._write_drafts([_draft("s001"), _draft("s001")])
        with self.assertRaises(corpus.CorpusError):
            corpus.load_drafts(self.root)

    def test_one_reviewer_rating_a_row_twice_is_an_error(self):
        self._write_drafts([_draft("s001")])
        self._write_reviews(
            "rev_a",
            [
                {"sample_id": "s001", "reviewer": "rev_a", "verdict": "accept"},
                {"sample_id": "s001", "reviewer": "rev_a", "verdict": "reject"},
            ],
        )
        with self.assertRaises(corpus.CorpusError):
            corpus.load_reviews(self.root)

    def test_lint_on_an_empty_root_is_hard_rather_than_clean(self):
        result = corpus.lint(self.root)
        self.assertFalse(result.is_clean())

    def test_lint_with_one_reviewer_file_is_hard(self):
        self._write_drafts([_draft("s001")])
        self._write_reviews(
            "rev_a", [{"sample_id": "s001", "reviewer": "rev_a", "verdict": "accept"}]
        )
        result = corpus.lint(self.root)
        self.assertIn("corpus_reviewers_insufficient", [f.code for f in result.hard])


class KappaTests(unittest.TestCase):
    def test_kappa_matches_a_hand_computation(self):
        # 10 rows: 6 both accept, 2 both reject, 1 A accept/B reject, 1 A reject/B accept.
        pairs = (
            [("accept", "accept")] * 6
            + [("reject", "reject")] * 2
            + [("accept", "reject"), ("reject", "accept")]
        )
        # observed = 8/10 = 0.8
        # A: accept 7/10, reject 3/10.  B: accept 7/10, reject 3/10.
        # expected = 0.7*0.7 + 0.3*0.3 = 0.49 + 0.09 = 0.58
        # kappa = (0.8 - 0.58) / (1 - 0.58) = 0.22 / 0.42
        self.assertAlmostEqual(0.22 / 0.42, corpus.cohens_kappa(pairs))

    def test_kappa_is_none_when_there_was_no_disagreement_opportunity(self):
        """Perfect agreement on one category is not perfect reliability."""
        self.assertIsNone(corpus.cohens_kappa([("accept", "accept")] * 5))

    def test_kappa_is_none_for_an_empty_set(self):
        self.assertIsNone(corpus.cohens_kappa([]))

    def test_total_disagreement_is_negative(self):
        pairs = [("accept", "reject"), ("reject", "accept")]
        value = corpus.cohens_kappa(pairs)
        self.assertIsNotNone(value)
        self.assertLess(value, 0.0)


class SourceCountingTests(unittest.TestCase):
    def _samples(self, sources):
        rows = []
        for index, source in enumerate(sources, start=1):
            drafts = [_draft("s%03d" % index, source=source)]
            merged, _ = corpus.merge(drafts, _reviews(["s%03d" % index]))
            rows.extend(merged)
        return rows

    def test_three_mirrors_of_one_source_count_once(self):
        rows = self._samples(
            [
                _source("one_wiki", locator="article a"),
                _source("one_wiki", locator="article b"),
                _source("one_wiki", locator="article c"),
            ]
        )
        self.assertEqual(3, len(rows))
        self.assertEqual(1, corpus.independent_sources(rows))

    def test_e1e2_ignores_reference_and_fixture_classes(self):
        rows = self._samples(
            [
                _source("a_ref", cls="reference"),
                _source("a_fix", cls="fixture", via="fixture_file"),
                _source("a_sec", cls="secondary", via="search_snippet"),
                _source("a_pri", cls="primary", via="direct_read"),
            ]
        )
        self.assertEqual(4, corpus.independent_sources(rows))
        self.assertEqual(2, corpus.e1e2_count(rows))


class CopyrightLintTests(unittest.TestCase):
    def test_a_declared_length_that_disagrees_is_hard(self):
        row = _draft("s001")
        row["quote_len"] = row["quote_len"] + 5
        codes = [f.code for f in corpus.copyright_lint([row])]
        self.assertIn("corpus_quote_len_mismatch", codes)

    def test_an_over_length_quote_is_hard(self):
        row = _draft("s001", quote="x" * (config.QUOTE_MAX_CHARS_PER_ROW + 1))
        codes = [f.code for f in corpus.copyright_lint([row])]
        self.assertIn("corpus_quote_over_row_ceiling", codes)

    def test_a_per_work_cap_breach_is_hard(self):
        rows = []
        per_row = config.QUOTE_MAX_CHARS_PER_ROW
        needed = config.QUOTE_MAX_CHARS_PER_WORK // per_row + 2
        for index in range(needed):
            rows.append(
                _draft(
                    "s%03d" % index,
                    quote="q" * per_row,
                    source=_source("k%d" % index, locator="loc%d" % index),
                )
            )
        codes = [f.code for f in corpus.copyright_lint(rows)]
        self.assertIn("corpus_quote_over_work_cap", codes)

    def test_three_consecutive_rows_from_one_passage_is_hard(self):
        rows = [
            _draft("s001", source=_source("k", locator="same page")),
            _draft("s002", source=_source("k", locator="same page")),
            _draft("s003", source=_source("k", locator="same page")),
        ]
        codes = [f.code for f in corpus.copyright_lint(rows)]
        self.assertIn("corpus_consecutive_dump", codes)

    def test_three_rows_from_different_passages_of_one_source_is_clean(self):
        """Independence counting and dump detection use different granularity."""
        rows = [
            _draft("s001", source=_source("k", locator="page one")),
            _draft("s002", source=_source("k", locator="page two")),
            _draft("s003", source=_source("k", locator="page three")),
        ]
        codes = [f.code for f in corpus.copyright_lint(rows)]
        self.assertNotIn("corpus_consecutive_dump", codes)

    def test_a_split_dump_fires_on_japanese_text_with_no_spaces(self):
        """A whitespace tokeniser would make this check a no-op on CJK."""
        passage = "むかしむかしあるところにおじいさんとおばあさんがすんでいました"
        rows = [
            _draft(
                "s001",
                marker="",
                quote=passage[:20],
                source=_source("k", locator="page one"),
            ),
            _draft(
                "s002",
                marker="",
                quote=passage[10:30],
                source=_source("k", locator="page two"),
            ),
        ]
        codes = [f.code for f in corpus.copyright_lint(rows)]
        self.assertIn("corpus_split_dump", codes)

    def test_two_rows_cataloguing_one_marker_are_not_a_split_dump(self):
        """The corpus exists to record one marker from several sources."""
        marker = "~지 말입니다(~であります)"
        rows = [
            _draft(
                "s001",
                marker=marker,
                quote="덤프슨 - %s" % marker,
                source=_source("k", locator="page one"),
            ),
            _draft(
                "s002",
                marker=marker,
                quote="드릴 실버 - %s" % marker,
                source=_source("k", locator="page two"),
            ),
        ]
        codes = [f.code for f in corpus.copyright_lint(rows)]
        self.assertNotIn("corpus_split_dump", codes)
        # Identical markers are the corpus doing its job, not laundering.
        self.assertNotIn("corpus_marker_laundered_dump", codes)

    def test_a_passage_laundered_through_the_marker_field_is_caught(self):
        """The marker strip is itself an evasion route, so it is bounded.

        Declaring the quoted passage as this row's marker would otherwise remove
        exactly the text the reassembly check looks for. Two rows legitimately
        cataloguing one marker declare the SAME marker string; a laundered passage
        is sliced into a different marker per row.
        """
        passage = "むかしむかしあるところにおじいさんとおばあさんがすんでいました"
        rows = [
            _draft(
                "s001",
                marker=passage[:20],
                quote=passage[:20],
                source=_source("k", locator="page one"),
            ),
            _draft(
                "s002",
                marker=passage[10:30],
                quote=passage[10:30],
                source=_source("k", locator="page two"),
            ),
        ]
        found = corpus.copyright_lint(rows)
        laundering = [f for f in found if f.code == "corpus_marker_laundered_dump"]
        self.assertTrue(laundering, [f.code for f in found])
        self.assertTrue(all(f.severity == "hard" for f in laundering))

    def test_tokenisation_splits_cjk_per_syllable_and_latin_per_word(self):
        self.assertEqual(["a", "b"], corpus.tokenise("a b"))
        self.assertEqual(["あ", "い", "う"], corpus.tokenise("あいう"))
        self.assertEqual(["가", "나"], corpus.tokenise("가나"))
        self.assertEqual(["hello", "世", "界"], corpus.tokenise("hello 世界"))


class GraduationTests(unittest.TestCase):
    def _samples(self, count, *, keys, verdicts=None, cls="reference", via="mirror"):
        rows = []
        for index in range(count):
            sid = "s%03d" % index
            key = keys[index % len(keys)]
            draft = [
                _draft(sid, source=_source(key, cls=cls, via=via, locator="loc%d" % index))
            ]
            a, b = (verdicts or ("accept", "accept"))
            merged, _ = corpus.merge(draft, _reviews([sid], a=a, b=b))
            rows.extend(merged)
        return rows

    def test_a_thin_type_stays_observed_and_names_every_gap(self):
        entry = corpus.graduate("t", self._samples(1, keys=["k1"]), {}, 0)
        self.assertEqual(config.STAGE_OBSERVED, entry["stage"])
        self.assertTrue(any("required for provisional" in r for r in entry["unmet"]))

    def test_provisional_is_reached_at_the_stated_floors(self):
        rows = self._samples(3, keys=["k1", "k2"])
        entry = corpus.graduate("t", rows, {"adopted": 1}, 1)
        self.assertEqual(config.STAGE_PROVISIONAL, entry["stage"])
        self.assertEqual(3, entry["occurrences"])
        self.assertEqual(2, entry["independent_sources"])

    def test_one_occurrence_short_of_canonical_lists_exactly_that_reason(self):
        rows = self._samples(
            config.CANONICAL_MIN_OCCURRENCES - 1,
            keys=["k1", "k2", "k3"],
            cls="secondary",
            via="search_snippet",
        )
        entry = corpus.graduate("t", rows, {"adopted": 1}, 1)
        self.assertEqual(config.STAGE_PROVISIONAL, entry["stage"])
        self.assertTrue(
            any("required for canonical" in r and "occurrences" in r for r in entry["unmet"]),
            entry["unmet"],
        )

    def test_canonical_requires_a_defined_kappa(self):
        """Unanimous agreement leaves kappa undefined, which blocks canonical."""
        rows = self._samples(
            config.CANONICAL_MIN_OCCURRENCES,
            keys=["k1", "k2", "k3"],
            cls="secondary",
            via="search_snippet",
        )
        entry = corpus.graduate("t", rows, {"adopted": 1}, 1)
        self.assertIsNone(entry["kappa"])
        self.assertNotEqual(config.STAGE_CANONICAL, entry["stage"])
        self.assertTrue(any("kappa is undefined" in r for r in entry["unmet"]))

    def test_canonical_is_reachable_when_every_floor_is_met(self):
        """A gate that no input can clear is as broken as one nothing fails."""
        rows = []
        keys = ["k1", "k2", "k3"]
        total = config.CANONICAL_MIN_OCCURRENCES
        for index in range(total):
            sid = "a%03d" % index
            draft = [
                _draft(
                    sid,
                    source=_source(
                        keys[index % len(keys)],
                        cls="secondary",
                        via="search_snippet",
                        locator="loc%d" % index,
                    ),
                )
            ]
            merged, _ = corpus.merge(draft, _reviews([sid]))
            rows.extend(merged)
        # Kappa now needs a stable verdict, not merely a value at the floor, so the
        # fixture carries what the strengthened rule actually requires: agreed
        # rejections for marginal variance plus a disagreement in each direction.
        # Six agreed rejections and one disagreement each way is the minimum
        # configuration that survives any single verdict flip at 8 accepted rows;
        # it yields kappa 0.746. Recorded here because it proves canonical is still
        # reachable -- a gate no input can clear would be as broken as one nothing
        # fails.
        extra = (
            [("reject", "reject")] * 6
            + [("accept", "reject"), ("reject", "accept")]
        )
        for index, (a, b) in enumerate(extra):
            sid = "d%03d" % index
            draft = [_draft(sid, source=_source("k4", locator="dloc%d" % index))]
            merged, _ = corpus.merge(draft, _reviews([sid], a=a, b=b))
            rows.extend(merged)
        entry = corpus.graduate("t", rows, {"adopted": 1, "unresolved_contradictions": 0}, 1)
        self.assertIsNotNone(entry["kappa"])
        self.assertGreaterEqual(entry["kappa"], config.KAPPA_FLOOR)
        self.assertEqual(0, entry["kappa_downward_flips"])
        self.assertEqual(config.STAGE_CANONICAL, entry["stage"], entry["unmet"])
        self.assertEqual([], entry["unmet"])

    def test_an_unresolved_contradiction_blocks_canonical(self):
        rows = self._samples(
            config.CANONICAL_MIN_OCCURRENCES,
            keys=["k1", "k2", "k3"],
            cls="secondary",
            via="search_snippet",
        )
        entry = corpus.graduate(
            "t", rows, {"adopted": 1, "unresolved_contradictions": 1}, 1
        )
        self.assertNotEqual(config.STAGE_CANONICAL, entry["stage"])
        self.assertTrue(any("contradiction" in r for r in entry["unmet"]))

    def test_only_accepted_rows_count_as_occurrences(self):
        rows = self._samples(4, keys=["k1", "k2"], verdicts=("accept", "reject"))
        entry = corpus.graduate("t", rows, {}, 0)
        self.assertEqual(0, entry["occurrences"])
        # But the rows remain visible, so a thin type cannot look well-evidenced.
        self.assertEqual(4, len(rows))

    def test_the_report_artifact_validates_and_is_reproducible(self):
        rows = self._samples(3, keys=["k1", "k2"])
        kwargs = dict(
            catalogue_version="test",
            generated_at="2026-01-01T00:00:00Z",
            type_ids=["fixture_type"],
            precedent_facts={"fixture_type": {"adopted": 1}},
            confirms_by_type={"fixture_type": 1},
        )
        first = corpus.graduation_report(rows, **kwargs)
        second = corpus.graduation_report(rows, **kwargs)
        self.assertEqual([], schemas.validate("graduation_report", first))
        self.assertEqual(
            json.dumps(first, sort_keys=True), json.dumps(second, sort_keys=True)
        )


class ShippedCorpusTests(unittest.TestCase):
    def test_the_shipped_corpus_lints_clean(self):
        result = corpus.lint()
        self.assertEqual([], [f.detail for f in result.hard])

    def test_the_shipped_corpus_has_two_independent_reviewers(self):
        reviews = corpus.load_reviews()
        self.assertGreaterEqual(len(reviews), 2)
        drafts = corpus.load_drafts()
        producers = {row["producer"] for row in drafts}
        self.assertEqual(set(), producers & set(reviews))

    def test_the_shipped_corpus_produces_a_measurable_kappa(self):
        """If both reviewers agreed on everything, the floor would be untestable."""
        samples, _ = corpus.merge(corpus.load_drafts(), corpus.load_reviews())
        pairs = [
            (row["reviewer_verdicts"][row["reviewer"]],
             row["reviewer_verdicts"][row["review2"]])
            for row in samples
        ]
        self.assertIsNotNone(corpus.cohens_kappa(pairs))


if __name__ == "__main__":
    unittest.main()


class KappaZeroDisagreementTests(unittest.TestCase):
    """A reliability statistic computed from no disagreement measures nothing.

    The `expected >= 1.0` guard fires only when both raters used exactly one
    category between them.  One row in a different category created marginal
    variance while the raters still never actually disagreed, and kappa came
    out at 1.0 -- the same fabricated agreement score the guard exists to
    refuse, reached through a side door.
    """

    def test_unanimous_agreement_in_one_category_is_undefined(self):
        self.assertIsNone(corpus.cohens_kappa([("accept", "accept")] * 5))

    def test_unanimous_agreement_across_two_categories_is_also_undefined(self):
        # This is the case that used to return 1.0.
        pairs = [("accept", "accept")] * 4 + [("reject", "reject")]
        self.assertIsNone(corpus.cohens_kappa(pairs))

    def test_a_single_real_disagreement_makes_kappa_defined(self):
        pairs = [("accept", "accept")] * 4 + [("accept", "reject")]
        self.assertIsNotNone(corpus.cohens_kappa(pairs))

    def test_empty_input_is_undefined(self):
        self.assertIsNone(corpus.cohens_kappa([]))

    def test_the_shipped_canonical_type_has_real_disagreements(self):
        """Its kappa is only meaningful because two rows were genuinely disputed."""
        samples, _ = corpus.merge(corpus.load_drafts(), corpus.load_reviews())
        pairs = [
            (
                row["reviewer_verdicts"][row["reviewer"]],
                row["reviewer_verdicts"][row["review2"]],
            )
            for row in samples
            if row["type_id"] == "ja_hao_gozaru"
        ]
        self.assertEqual(16, len(pairs))
        self.assertEqual(2, sum(1 for a, b in pairs if a != b))
        self.assertIsNotNone(corpus.cohens_kappa(pairs))


class KappaStabilityTests(unittest.TestCase):
    """KAPPA_FLOOR alone is clearable by dilution, so the verdict must be stable.

    A kappa may satisfy the floor only if the floor verdict survives any single
    annotation change. This refuses both knife-edge proximity to the floor and
    the small-sample instability that makes a high kappa untrustworthy.
    """

    def test_it_never_creates_a_pass_only_removes_one(self):
        # Below the floor and undefined both return 0, so the check is one-directional.
        self.assertEqual(0, corpus.kappa_floor_downward_flips([("accept", "reject")] * 4))
        self.assertEqual(0, corpus.kappa_floor_downward_flips([("accept", "accept")] * 4))
        self.assertEqual(0, corpus.kappa_floor_downward_flips([]))

    def test_the_shipped_knife_edge_value_is_unstable(self):
        """ja_hao_gozaru sits exactly on the floor, so any downward flip crosses."""
        samples, _ = corpus.merge(corpus.load_drafts(), corpus.load_reviews())
        pairs = [
            (
                row["reviewer_verdicts"][row["reviewer"]],
                row["reviewer_verdicts"][row["review2"]],
            )
            for row in samples
            if row["type_id"] == "ja_hao_gozaru"
        ]
        self.assertAlmostEqual(3 / 5, corpus.cohens_kappa(pairs), places=9)
        self.assertGreater(corpus.kappa_floor_downward_flips(pairs), 0)

    def test_a_single_disagreement_is_never_stable(self):
        """The two guards interact, and the interaction is meaningful.

        Flipping the only disagreement to agreement makes kappa undefined under the
        zero-disagreement guard, which the stability check counts as crossing. So a
        kappa resting on one disputed row can never certify, however high it is.
        """
        pairs = [("accept", "accept")] * 40 + [("reject", "reject")] * 20 + [
            ("accept", "reject")
        ]
        self.assertGreater(corpus.cohens_kappa(pairs), 0.9)
        self.assertGreater(corpus.kappa_floor_downward_flips(pairs), 0)

    def test_the_requirement_is_satisfiable_and_not_an_infinite_bar(self):
        """A gate nothing can ever pass is broken; this one is passable.

        The minimum stable configuration at the 8-occurrence floor is 8 agreed
        acceptances, 6 agreed rejections and one disagreement in each direction,
        giving kappa 0.746 with zero destabilising flips.
        """
        minimal = (
            [("accept", "accept")] * 8
            + [("reject", "reject")] * 6
            + [("accept", "reject"), ("reject", "accept")]
        )
        self.assertGreaterEqual(corpus.cohens_kappa(minimal), config.KAPPA_FLOOR)
        self.assertEqual(0, corpus.kappa_floor_downward_flips(minimal))

    def test_the_shipped_types_it_disqualifies_were_already_blocked(self):
        """The requirement was landed while its cost was zero, by design."""
        samples, _ = corpus.merge(corpus.load_drafts(), corpus.load_reviews())
        by_type = {}
        for row in samples:
            by_type.setdefault(row["type_id"], []).append(
                (
                    row["reviewer_verdicts"][row["reviewer"]],
                    row["reviewer_verdicts"][row["review2"]],
                )
            )
        unstable = sorted(
            type_id
            for type_id, pairs in by_type.items()
            if corpus.kappa_floor_downward_flips(pairs) > 0
        )
        self.assertEqual(["ja_elder_lexicon", "ja_hao_gozaru"], unstable)
