import json
import os
import shutil
import tempfile
import unittest

from hancharacter import config, precedents, typology


def _precedent(precedent_id, **over):
    row = {
        "id": precedent_id,
        "axis": "ending_transform",
        "type_id": "fixture_type",
        "source_lang": "ja",
        "target_lang": "ko",
        "source_marker": "~x",
        "source_work": "fixture work",
        "target_realisation": "~fixture",
        "edition_channel": "official",
        "verdict": "adopted",
        "citation": "fixture citation",
    }
    row.update(over)
    return row


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hc-prec-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write(self, rows):
        with open(precedents.table_path(self.root), "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_loads_and_groups_by_type(self):
        self._write([_precedent("p1"), _precedent("p2", type_id="other_type")])
        rows = precedents.load(self.root)
        self.assertEqual(2, len(rows))
        grouped = precedents.by_type(rows)
        self.assertEqual({"fixture_type", "other_type"}, set(grouped))

    def test_duplicate_ids_are_an_error(self):
        self._write([_precedent("p1"), _precedent("p1")])
        with self.assertRaises(precedents.PrecedentError):
            precedents.load(self.root)

    def test_a_malformed_line_names_the_line_number(self):
        with open(precedents.table_path(self.root), "w", encoding="utf-8") as fh:
            fh.write(json.dumps(_precedent("p1")) + "\n")
            fh.write("{not json\n")
        with self.assertRaises(precedents.PrecedentError) as caught:
            precedents.load(self.root)
        self.assertIn(":2:", str(caught.exception))

    def test_lint_on_an_absent_table_is_hard(self):
        result = precedents.lint(self.root)
        self.assertFalse(result.is_clean())

    def test_lint_on_an_empty_table_is_hard(self):
        open(precedents.table_path(self.root), "w", encoding="utf-8").close()
        result = precedents.lint(self.root)
        self.assertIn("precedent_table_empty", [f.code for f in result.hard])

    def test_a_dangling_contradiction_reference_is_hard(self):
        self._write([_precedent("p1", contradicts=["nope"])])
        result = precedents.lint(self.root)
        self.assertIn("precedent_contradiction_dangling", [f.code for f in result.hard])

    def test_a_resolution_pointing_at_nothing_is_hard(self):
        self._write(
            [_precedent("p1", contradicts=["p2"], resolved_by="absent_confirm"),
             _precedent("p2", verdict="rejected")]
        )
        result = precedents.lint(self.root)
        self.assertIn("precedent_resolution_dangling", [f.code for f in result.hard])

    def test_a_verdict_conflict_on_one_triple_is_hard(self):
        self._write(
            [
                _precedent("p1", verdict="adopted"),
                _precedent("p2", verdict="contested"),
            ]
        )
        result = precedents.lint(self.root)
        self.assertIn("precedent_verdict_conflict", [f.code for f in result.hard])


class VerdictTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _precedent("p_adopted", verdict="adopted"),
            _precedent("p_contested", verdict="contested", edition_channel="community"),
            _precedent("p_rejected", verdict="rejected", edition_channel="licensed"),
        ]

    def test_filters_partition_by_verdict(self):
        self.assertEqual(["p_adopted"], [r["id"] for r in precedents.adopted(self.rows)])
        self.assertEqual(["p_contested"], [r["id"] for r in precedents.contested(self.rows)])
        self.assertEqual(["p_rejected"], [r["id"] for r in precedents.rejected(self.rows)])

    def test_an_unresolved_contradiction_is_detected(self):
        rows = [_precedent("p1", contradicts=["p2"]), _precedent("p2", verdict="rejected")]
        self.assertEqual([("p1", "p2")], precedents.unresolved_contradictions(rows))

    def test_a_contradiction_resolved_by_an_existing_confirm_is_cleared(self):
        rows = [
            _precedent("p1", contradicts=["p2"], resolved_by="confirm_one"),
            _precedent("p2", verdict="rejected"),
        ]
        self.assertEqual(
            [], precedents.unresolved_contradictions(rows, {"confirm_one"})
        )

    def test_a_resolution_naming_an_unknown_confirm_is_not_treated_as_resolved(self):
        rows = [
            _precedent("p1", contradicts=["p2"], resolved_by="invented_confirm"),
            _precedent("p2", verdict="rejected"),
        ]
        self.assertEqual(
            [("p1", "p2")], precedents.unresolved_contradictions(rows, {"other"})
        )

    def test_canonical_support_requires_an_adopted_row(self):
        ok, found = precedents.canonical_support(
            [_precedent("p1", verdict="contested")]
        )
        self.assertFalse(ok)
        self.assertIn("precedent_no_adopted_support", [f.code for f in found])

    def test_canonical_support_fails_on_an_open_contradiction(self):
        rows = [
            _precedent("p1", verdict="adopted", contradicts=["p2"]),
            _precedent("p2", verdict="rejected"),
        ]
        ok, found = precedents.canonical_support(rows)
        self.assertFalse(ok)
        self.assertIn("precedent_contradiction_unresolved", [f.code for f in found])

    def test_canonical_support_passes_with_an_adopted_row_and_no_contradiction(self):
        ok, found = precedents.canonical_support([_precedent("p1", verdict="adopted")])
        self.assertTrue(ok)
        self.assertEqual([], found)


class SiblingTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            _precedent("p_official", edition_channel="official"),
            _precedent("p_licensed", edition_channel="licensed"),
        ]

    def test_adopted_rows_on_different_channels_are_siblings(self):
        groups = precedents.siblings(self.rows)
        self.assertEqual({"official", "licensed"}, set(groups))

    def test_the_declared_edition_medium_selects_its_sibling(self):
        chosen, found = precedents.select_sibling(self.rows, "licensed")
        self.assertEqual("p_licensed", chosen["id"])
        self.assertEqual([], found)

    def test_an_ambiguous_sibling_set_with_no_selector_is_hard(self):
        chosen, found = precedents.select_sibling(self.rows, None)
        self.assertIsNone(chosen)
        self.assertIn("precedent_sibling_unselected", [f.code for f in found])

    def test_a_single_sibling_needs_no_selector(self):
        chosen, found = precedents.select_sibling([self.rows[0]], None)
        self.assertEqual("p_official", chosen["id"])
        self.assertEqual([], found)


class RejectedMatcherTests(unittest.TestCase):
    """Both directions matter: a matcher that always fires is as broken as one
    that never does."""

    def _matcher_args(self):
        return {
            "matched_markers": typology.matched_markers,
            "containment": typology.containment,
        }

    def test_it_fires_on_a_realisation_reproducing_a_rejected_rendering(self):
        rejected = _precedent(
            "p_rejected",
            verdict="rejected",
            target_pattern_set=[r"다해[.!?…]*$", r"해쓰[.!?…]*$"],
        )
        offender = {
            "id": "ko_offender",
            "type_id": "fixture_type",
            "target_lang": "ko",
            "pattern_set": [r"다해[.!?…]*$"],
        }
        found = precedents.rejected_match(offender, [rejected], **self._matcher_args())
        codes = [f.code for f in found]
        self.assertIn("precedent_rejected_reproduced", codes)
        self.assertTrue(
            any(f.severity == "hard" for f in found if f.code == "precedent_rejected_reproduced")
        )

    def test_it_does_not_fire_on_an_innocent_realisation(self):
        rejected = _precedent(
            "p_rejected", verdict="rejected", target_pattern_set=[r"다해[.!?…]*$"]
        )
        innocent = {
            "id": "ko_innocent",
            "type_id": "fixture_type",
            "target_lang": "ko",
            "pattern_set": [r"이오[.!?…]*$"],
        }
        found = precedents.rejected_match(innocent, [rejected], **self._matcher_args())
        self.assertEqual(
            [], [f for f in found if f.code == "precedent_rejected_reproduced"]
        )

    def test_a_marked_ending_is_not_matched_against_a_deletion_precedent(self):
        """A LOSS precedent carries no pattern, so it cannot flag faithful work.

        Encoding deletion as a positive pattern such as `입니다$` would match every
        faithful polite line, including the correctly marked `~지 말입니다`.
        """
        loss = _precedent("p_loss", verdict="rejected")
        loss.pop("target_pattern_set", None)
        marked = {
            "id": "ko_marked",
            "type_id": "fixture_type",
            "target_lang": "ko",
            "pattern_set": [r"지 말입니다[.!?…]*$"],
        }
        found = precedents.rejected_match(marked, [loss], **self._matcher_args())
        codes = [f.code for f in found]
        self.assertNotIn("precedent_rejected_reproduced", codes)
        self.assertIn("precedent_rejected_unmatchable", codes)
        gap = [f for f in found if f.code == "precedent_rejected_unmatchable"][0]
        self.assertEqual("report", gap.severity)
        self.assertIn("recorded gap", gap.detail)

    def test_a_realisation_with_no_patterns_is_recorded_as_uncheckable(self):
        rejected = _precedent(
            "p_rejected", verdict="rejected", target_pattern_set=[r"다해[.!?…]*$"]
        )
        bare = {
            "id": "ko_bare",
            "type_id": "fixture_type",
            "target_lang": "ko",
        }
        found = precedents.rejected_match(bare, [rejected], **self._matcher_args())
        self.assertIn(
            "precedent_rejected_uncheckable_realisation", [f.code for f in found]
        )


class ShippedTableTests(unittest.TestCase):
    def _confirm_ids(self):
        from hancharacter import cli

        return {row["id"] for row in cli._load_confirms()}

    def test_the_shipped_table_lints_clean(self):
        result = precedents.lint(known_confirm_ids=self._confirm_ids())
        self.assertEqual([], [f.detail for f in result.hard])

    def test_the_shipped_table_carries_all_three_verdicts(self):
        """A table with only adopted rows would never exercise the rules."""
        rows = precedents.load()
        verdicts = {row["verdict"] for row in rows}
        self.assertEqual(set(config.PRECEDENT_VERDICTS), verdicts)

    def test_no_shipped_realisation_reproduces_a_rejected_precedent(self):
        rows = precedents.load()
        grouped = precedents.by_type(rows)
        hard = []
        for realisation in typology.load_realisations("ko").values():
            hard.extend(
                f
                for f in precedents.rejected_match(
                    realisation,
                    grouped.get(realisation["type_id"], []),
                    matched_markers=typology.matched_markers,
                    containment=typology.containment,
                )
                if f.severity == "hard"
            )
        self.assertEqual([], [f.detail for f in hard])

    def test_the_gozaru_type_now_has_no_adopted_channel(self):
        """Honest consequence of applying one precedent standard to every row.

        This type once had two adopted channels. The first was corrected to
        contested because it rested on a forum author describing a register rather
        than on a published edition. The second, prec_gozaru_io_ko, had the same
        standing -- one wiki list, no broadcast or publication record -- and was
        left adopted while it was the adopted-precedent leg of the project's only
        canonical type. Correcting it costs that type its canonical status, which
        is the honest outcome rather than a regression.
        """
        rows = precedents.by_type(precedents.load())["ja_hao_gozaru"]
        groups = precedents.siblings(rows)
        self.assertEqual([], sorted(groups))
        self.assertEqual(
            [], [row["id"] for row in rows if row["verdict"] == "adopted"]
        )
        # With no adopted row there is nothing to select, and the selector says so
        # rather than falling back to a contested row.
        chosen, found = precedents.select_sibling(rows, None)
        self.assertIsNone(chosen)
        self.assertEqual([], found)


if __name__ == "__main__":
    unittest.main()
