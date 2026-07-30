import hashlib
import json
import os
import shutil
import tempfile
import unittest

from hancharacter import config, dialect


def _decision(decision_id="d1", source="kansai", target="gyeongsang", work="w", **over):
    row = {
        "id": decision_id,
        "source_dialect": source,
        "target_dialect": target,
        "work": work,
        "strategy": config.DIALECT_FLAVOUR_LEXICON,
        "reason": "fixture ruling",
        "decided_by": "fixture operator",
        "decided_at": "2026-01-01T00:00:00Z",
        "decision_hash": dialect.decision_hash(source, target, work),
    }
    row.update(over)
    return row


class HashTests(unittest.TestCase):
    def test_the_hash_matches_a_hand_computation(self):
        expected = hashlib.sha1(b"kansai\0gyeongsang\0w").hexdigest()
        self.assertEqual(expected, dialect.decision_hash("kansai", "gyeongsang", "w"))

    def test_nul_delimiting_prevents_a_boundary_collision(self):
        """Without delimiters ("a","bc") and ("ab","c") hash identically, and one
        ruling would silently authorise a different pair."""
        self.assertNotEqual(
            dialect.decision_hash("a", "bc", "w"),
            dialect.decision_hash("ab", "c", "w"),
        )

    def test_the_work_participates_in_the_hash(self):
        self.assertNotEqual(
            dialect.decision_hash("a", "b", "one"),
            dialect.decision_hash("a", "b", "two"),
        )


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hc-dialect-")
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write(self, rows):
        with open(dialect.decisions_path(self.root), "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    def test_an_absent_log_is_an_empty_log_not_an_error(self):
        """Nothing ruled on yet must be distinguishable from a broken install."""
        self.assertEqual([], dialect.load_decisions(self.root))

    def test_duplicate_ids_are_an_error(self):
        self._write([_decision("d1"), _decision("d1", source="other")])
        with self.assertRaises(dialect.DialectError):
            dialect.load_decisions(self.root)

    def test_duplicate_hashes_are_an_error(self):
        self._write([_decision("d1"), _decision("d2")])
        with self.assertRaises(dialect.DialectError) as caught:
            dialect.load_decisions(self.root)
        self.assertIn("one triple cannot carry two rulings", str(caught.exception))

    def test_lint_reports_a_stale_ruling(self):
        self._write([_decision("d1", decision_hash="0" * 40)])
        result = dialect.lint(self.root)
        self.assertIn("dialect_decision_stale", [f.code for f in result.hard])

    def test_lint_on_an_empty_log_is_a_legitimate_state(self):
        result = dialect.lint(self.root)
        self.assertTrue(result.is_clean())
        self.assertIn("dialect_decision_count", [f.code for f in result.reported])


class StalenessTests(unittest.TestCase):
    def test_a_ruling_whose_hash_disagrees_with_its_fields_is_stale(self):
        row = _decision("d1")
        row["target_dialect"] = "busan"  # edited after the hash was computed
        self.assertTrue(dialect.is_stale(row))

    def test_a_stale_ruling_is_not_honoured(self):
        row = _decision("d1")
        row["target_dialect"] = "busan"
        found, notes = dialect.decision_for("kansai", "busan", "w", [row])
        self.assertIsNone(found)
        self.assertIn("dialect_decision_stale", [f.code for f in notes])

    def test_a_matching_ruling_is_returned(self):
        row = _decision("d1")
        found, notes = dialect.decision_for("kansai", "gyeongsang", "w", [row])
        self.assertEqual("d1", found["id"])
        self.assertEqual([], notes)


class FullSubstitutionTests(unittest.TestCase):
    def test_zero_adopted_precedents_is_refused(self):
        ok, found = dialect.full_substitution_allowed(
            "kansai", "gyeongsang", adopted_precedents=0, sample_count=99
        )
        self.assertFalse(ok)
        self.assertIn(
            "dialect_full_substitution_unprecedented", [f.code for f in found]
        )

    def test_a_sample_count_below_the_floor_is_refused(self):
        ok, found = dialect.full_substitution_allowed(
            "kansai", "gyeongsang", adopted_precedents=1, sample_count=0
        )
        self.assertFalse(ok)
        self.assertIn(
            "dialect_full_substitution_undersampled", [f.code for f in found]
        )

    def test_both_conditions_met_is_allowed(self):
        ok, found = dialect.full_substitution_allowed(
            "kansai",
            "gyeongsang",
            adopted_precedents=1,
            sample_count=config.PROVISIONAL_MIN_OCCURRENCES,
        )
        self.assertTrue(ok)
        self.assertEqual([], found)


class GateTests(unittest.TestCase):
    def test_a_declared_pair_with_no_ruling_stops_the_pipeline(self):
        policy = {
            "target_strategy": config.DIALECT_FLAVOUR_LEXICON,
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
        }
        found = dialect.gate(policy, "w", decisions=[])
        codes = [f.code for f in found]
        self.assertIn("dialect_pair_undecided", codes)
        self.assertTrue(all(f.severity == "hard" for f in found))
        # The operator is told exactly what to record.
        detail = [f for f in found if f.code == "dialect_pair_undecided"][0].detail
        self.assertIn(dialect.decision_hash("kansai", "gyeongsang", "w"), detail)
        self.assertIn("no default", detail)

    def test_a_recorded_ruling_clears_the_gate(self):
        policy = {
            "target_strategy": config.DIALECT_FLAVOUR_LEXICON,
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
        }
        found = dialect.gate(policy, "w", decisions=[_decision("d1")])
        self.assertEqual([], found)

    def test_a_work_with_no_dialect_pair_is_not_stopped(self):
        """A gate that fires on faithful work is as broken as one that never fires."""
        policy = {"target_strategy": config.DIALECT_FLAVOUR_LEXICON}
        self.assertEqual([], dialect.gate(policy, "w", decisions=[]))

    def test_full_substitution_without_a_named_pair_is_refused(self):
        policy = {"target_strategy": config.DIALECT_FULL_SUBSTITUTION}
        found = dialect.gate(policy, "w", decisions=[])
        self.assertIn("dialect_pair_undeclared", [f.code for f in found])

    def test_an_operator_ruling_does_not_manufacture_evidence(self):
        policy = {
            "target_strategy": config.DIALECT_FULL_SUBSTITUTION,
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
        }
        ruling = _decision("d1", strategy=config.DIALECT_FULL_SUBSTITUTION)
        found = dialect.gate(policy, "w", decisions=[ruling])
        codes = [f.code for f in found]
        self.assertIn("dialect_full_substitution_unprecedented", codes)
        self.assertNotIn("dialect_pair_undecided", codes)

    def test_a_ruling_authorises_only_the_strategy_it_names(self):
        """A flavour_lexicon ruling must not authorise a full_substitution work."""
        policy = {
            "target_strategy": config.DIALECT_FULL_SUBSTITUTION,
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
        }
        ruling = _decision("d1", strategy=config.DIALECT_FLAVOUR_LEXICON)
        found = dialect.gate(policy, "w", decisions=[ruling])
        self.assertIn("dialect_strategy_mismatch", [f.code for f in found])

    def test_cited_precedents_must_exist_as_adopted_rows(self):
        """The evidence floor is derived from artifacts, not from a caller's integer."""
        policy = {
            "target_strategy": config.DIALECT_FULL_SUBSTITUTION,
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
        }
        ruling = _decision(
            "d1",
            strategy=config.DIALECT_FULL_SUBSTITUTION,
            precedents=["prec_invented"],
        )
        found = dialect.gate(policy, "w", decisions=[ruling], adopted_precedent_ids=set())
        self.assertIn("dialect_precedents_unbacked", [f.code for f in found])

    def test_full_substitution_passes_when_the_cited_precedent_is_adopted(self):
        """The gate must be clearable by real evidence, or it is not a gate."""
        policy = {
            "target_strategy": config.DIALECT_FULL_SUBSTITUTION,
            "source_dialect": "kansai",
            "target_dialect": "gyeongsang",
        }
        ruling = _decision(
            "d1",
            strategy=config.DIALECT_FULL_SUBSTITUTION,
            precedents=["prec_real"],
        )
        found = dialect.gate(
            policy,
            "w",
            decisions=[ruling],
            adopted_precedent_ids={"prec_real"},
            sample_count=config.PROVISIONAL_MIN_OCCURRENCES,
        )
        self.assertEqual([], found)

    def test_an_undeclared_strategy_is_refused(self):
        found = dialect.gate({"target_strategy": "improvise"}, "w", decisions=[])
        self.assertIn("dialect_strategy_undeclared", [f.code for f in found])


class ShippedStateTests(unittest.TestCase):
    def test_the_kansai_pair_is_deliberately_left_undecided(self):
        """No adopted source-region to target-region precedent was verified, so the
        honest state is undecided and the gate must fire for any work using it."""
        decisions = dialect.load_decisions()
        self.assertEqual([], decisions)
        policy = {
            "target_strategy": config.DIALECT_FULL_SUBSTITUTION,
            "source_dialect": "kansai_osaka",
            "target_dialect": "gyeongsang_busan",
        }
        found = dialect.gate(policy, "any_work", decisions=decisions)
        self.assertIn("dialect_pair_undecided", [f.code for f in found])

    def test_the_shipped_fixture_profile_needs_no_ruling(self):
        from hancharacter import config as cfg

        profile = cfg.load_profile(
            os.path.join(cfg.repo_root(), "profiles", "crimson_fixture.json")
        )
        found = dialect.gate(
            profile.dialect_policy(), profile.work, decisions=dialect.load_decisions()
        )
        self.assertEqual([], found)


if __name__ == "__main__":
    unittest.main()
