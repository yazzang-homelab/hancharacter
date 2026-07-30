import ast
import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest

from hancharacter import config, contracts, corpus, findings, gates



_DIGEST = hashlib.sha256(b"contract-fixture-corpus").hexdigest()
_GOLDEN = hashlib.sha256(b"contract-fixture-golden").hexdigest()


class _Plugin:
    def __init__(self, version="fixture-plugin-1"):
        self.VERSION = version


class _Catalogue:
    """Small independently graduated catalogue; never the shipped catalogue."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="hc-contract-")
        os.makedirs(os.path.join(self.root, "types"))
        os.makedirs(os.path.join(self.root, "realisations", "ko"))
        self.version("fixture-v1")
        self._write(
            "types/t1.json",
            {
                "id": "t1",
                "axis": "ending_transform",
                "source_lang": "ja",
                "source_marker": "~fixture",
                "pattern_set": [r"fixture$"],
                "provenance": {"origin": "character", "notes": "fixture"},
            },
        )
        self._write(
            "realisations/ko/r1.json",
            {
                "id": "r1",
                "type_id": "t1",
                "source_lang": "ja",
                "target_lang": "ko",
                "source_marker": "~fixture",
                "target_realisation": "~fixture-ko",
                "length_cost": {"model": "append", "value": 3},
                "precedents": ["p1"],
                "density_band_default": [0.2, 0.8],
                "pattern_set": [r"픽스처$"],
            },
        )

    def _write(self, path, value):
        full_path = os.path.join(self.root, path)
        with open(full_path, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)

    def version(self, value):
        with open(os.path.join(self.root, "VERSION"), "w", encoding="utf-8") as handle:
            handle.write(value)

    def cleanup(self):
        shutil.rmtree(self.root, True)


def _axis_status(_language):
    return {
        "ending_transform": config.AXIS_STATUS_APPLICABLE,
        "utterance_frame": config.AXIS_STATUS_APPLICABLE,
    }


def _canonical_stages():
    """Reach canonical through corpus.graduate, not a hand-written stage string."""
    rows = []
    source_keys = ("src1", "src2", "src3")
    for index in range(config.CANONICAL_MIN_OCCURRENCES):
        rows.append(
            {
                "verdict": config.REVIEW_ACCEPT,
                "source": {
                    "class": config.SOURCE_SECONDARY,
                    "independent_key": source_keys[index % len(source_keys)],
                },
                "reviewer_verdicts": {"review_a": "accept", "review_b": "accept"},
            }
        )
    # Kappa needs disagreement opportunity.  These two rows preserve the accepted
    # count while making the score defined and above the configured floor.
    # Kappa must now be a stable verdict rather than a value at the floor, so the
    # fixture carries the minimum configuration that survives any single verdict
    # flip: six agreed rejections for marginal variance plus one disagreement in
    # each direction. That yields kappa 0.746 with zero destabilising flips.
    extra = [("reject", "reject")] * 6 + [("accept", "reject"), ("reject", "accept")]
    rows.extend(
        {
            "verdict": (
                config.REVIEW_REJECT if a == b else config.REVIEW_NEEDS_REVIEW
            ),
            "source": {"class": config.SOURCE_SECONDARY, "independent_key": "src4"},
            "reviewer_verdicts": {"review_a": a, "review_b": b},
        }
        for a, b in extra
    )
    for row in rows:
        row["reviewer"] = "review_a"
        row["review2"] = "review_b"
    entry = corpus.graduate(
        "t1", rows, {"adopted": 1, "unresolved_contradictions": 0}, 1
    )
    if entry["stage"] != config.STAGE_CANONICAL:
        raise AssertionError("fixture did not honestly graduate: %s" % entry["unmet"])
    return {"t1": entry["stage"]}


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.catalogue = _Catalogue()
        self.addCleanup(self.catalogue.cleanup)
        self.stages = _canonical_stages()

    def _build(self, **overrides):
        values = {
            "attribution": {
                "evidence_tier": "t1",
                "target_tier": "t1",
                "status": "attributed",
            },
            "required_markers": [r"픽스처$"],
            "forbidden_markers": [r"금지$"],
            "measured_source_density": {"ending_transform": 0.5},
            "bands": {"all": {"ending_transform": [0.2, 0.8]}},
            "scope_overrides": {
                "mode=normal|state=calm|form=base|arc=opening": {
                    "bands": {"ending_transform": [0.2, 0.8]}
                }
            },
            "exclusivity": {"exclusive_with": []},
            "edition_medium": "subtitle",
            "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
            "declared_speakers": ["speaker_a"],
            "corpus_digests": {"t1": _DIGEST},
            "required_glyphs": [],
            "marker_sets": {"ending_transform": [r"픽스처$"]},
            "catalogue_markers": {"fixture": [r"픽스처$"]},
            "review_decisions": {},
            "axis_status": _axis_status,
            "measurable": config.MEASURABLE_AXIS_STATUSES,
            "root": self.catalogue.root,
        }
        values.setdefault("authority", config.AUTHORITY_PRECEDENT_BACKED)
        values.update(overrides)
        return contracts.build(
            "fixture-work", "speaker_a", ["t1"], "ja", "ko", **values
        )

    def _seal(self, contract, **overrides):
        plugin = overrides.pop("plugin", _Plugin())
        values = {
            "schema_validate": lambda candidate: [],
            "graduation_stages": self.stages,
            "source_evidence_ok": lambda type_id: True,
            "length_ok": True,
            "plugin_for": lambda language: plugin,
            "plugin_measurable_axes": lambda language: ["ending_transform"],
            "plugin_golden_digest": lambda language: _GOLDEN,
            "rejected_precedent_match": [],
            "glyph_available": lambda glyph: True,
            "coverage": {"speaker_a": config.COVERAGE_FLOOR_X},
            "dialect_findings": [],
        }
        values.update(overrides)
        return contracts.seal(contract, **values)

    @staticmethod
    def _waiver(sealed, category="coverage", codes=("DENSITY_VERDICT",)):
        return contracts.create_waiver(
            sealed,
            category,
            waiver_id="fixture-waiver",
            reason="fixture exception",
            waived_codes=list(codes),
            granted_by="fixture-operator",
            granted_at="2026-07-29T00:00:00Z",
        )


    @staticmethod
    def _codes(result):
        return {finding.code for finding in result.hard}

    @staticmethod
    def _reported_codes(result):
        return {finding.code for finding in result.reported}


    def test_build_resolves_axes_and_adds_only_corpus_digest(self):
        contract = self._build()
        self.assertNotIn("seal", contract)
        self.assertEqual(["t1"], contract["type_ids"])
        self.assertEqual(
            {
                "axis": "ending_transform",
                "marker": "~fixture",
                "pattern_set": [r"fixture$"],
                "corpus_digest": _DIGEST,
            },
            contract["axes"][0],
        )
        self.assertEqual("fixture-v1", contract["catalogue_version"])

    def test_build_seals_exclusive_with_and_gate_inputs(self):
        contract = self._build(exclusivity={"exclusive_with": ["speaker_b"]})
        self.assertEqual({"exclusive_with": ["speaker_b"]}, contract["exclusivity"])
        self.assertEqual({"ending_transform": [r"픽스처$"]}, contract["marker_sets"])
        self.assertEqual({"fixture": [r"픽스처$"]}, contract["catalogue_markers"])
        self.assertEqual({}, contract["review_decisions"])

    def test_seal_refuses_closed_schema_failure_independently(self):
        sealed, result = self._seal(self._build(), schema_validate=lambda candidate: ["closed error"])
        self.assertIsNone(sealed)
        self.assertEqual({"contract_schema_invalid"}, self._codes(result))

    def test_seal_refuses_ungraduated_marker_independently(self):
        sealed, result = self._seal(self._build(), graduation_stages={"t1": "provisional"})
        self.assertIsNone(sealed)
        self.assertEqual({"contract_type_not_canonical"}, self._codes(result))

    def test_seal_refuses_infeasible_length_independently(self):
        sealed, result = self._seal(self._build(), length_ok=False)
        self.assertIsNone(sealed)
        self.assertEqual({"contract_length_infeasible"}, self._codes(result))

    def test_seal_refuses_missing_measure_plugin_independently(self):
        def missing(_language):
            raise LookupError("no plugin")

        sealed, result = self._seal(self._build(), plugin_for=missing)
        self.assertIsNone(sealed)
        self.assertEqual({"contract_source_measurement_unavailable"}, self._codes(result))

    def test_seal_refuses_empty_measurable_plugin_axes(self):
        sealed, result = self._seal(
            self._build(), plugin_measurable_axes=lambda language: []
        )
        self.assertIsNone(sealed)
        self.assertEqual({"contract_source_measurement_unavailable"}, self._codes(result))

    def test_seal_rejects_absent_evidence_and_propagates_callback_errors(self):
        for label, overrides in (
            ("precedent", {"rejected_precedent_match": None}),
            ("dialect", {"dialect_findings": None}),
        ):
            with self.subTest(label=label):
                with self.assertRaises(contracts.ContractError):
                    self._seal(self._build(), **overrides)

        def validator(_candidate):
            raise RuntimeError("schema backend unavailable")

        with self.assertRaisesRegex(RuntimeError, "schema backend unavailable"):
            self._seal(self._build(), schema_validate=validator)

    def test_seal_refuses_rejected_precedent_match_independently(self):
        rejected = [findings.hard("precedent_rejected_reproduced", "fixture match")]
        sealed, result = self._seal(self._build(), rejected_precedent_match=rejected)
        self.assertIsNone(sealed)
        self.assertEqual({"contract_rejected_precedent_match"}, self._codes(result))

    def test_seal_refuses_missing_required_glyph_independently(self):
        contract = self._build(required_glyphs=["★"])
        sealed, result = self._seal(contract, glyph_available=lambda glyph: False)
        self.assertIsNone(sealed)
        self.assertEqual({"contract_required_glyph_unavailable"}, self._codes(result))

    def test_seal_refuses_low_speaker_coverage_independently(self):
        sealed, result = self._seal(
            self._build(), coverage={"speaker_a": config.COVERAGE_FLOOR_X - 0.01}
        )
        self.assertIsNone(sealed)
        self.assertEqual({"contract_speaker_coverage_below_floor"}, self._codes(result))

    def test_seal_refuses_zero_source_density_for_a_required_axis(self):
        sealed, result = self._seal(
            self._build(measured_source_density={"ending_transform": 0.0})
        )
        self.assertIsNone(sealed)
        self.assertEqual({"contract_source_density_zero"}, self._codes(result))

    def test_seal_refuses_declared_coverage_floor_below_frozen_floor(self):
        sealed, result = self._seal(
            self._build(coverage_floor=0.10), coverage={"speaker_a": 0.10}
        )
        self.assertIsNone(sealed)
        self.assertEqual({"contract_coverage_floor_below_frozen"}, self._codes(result))
        finding = result.hard[0]
        self.assertEqual("hard", finding.severity)
        self.assertIn("0.10", finding.detail)
        self.assertIn("%.2f" % config.COVERAGE_FLOOR_X, finding.detail)

    def test_coverage_waiver_clears_only_matching_lowered_floor_candidate(self):
        self.assertIn(
            "contract_coverage_floor_below_frozen",
            gates._WAIVABLE_BY_CATEGORY["coverage"],
        )
        self.assertNotIn(
            "contract_coverage_floor_below_frozen", gates._NON_WAIVABLE_CODES
        )
        candidate = self._build(coverage_floor=0.10)
        sealed, result = self._seal(candidate, coverage={"speaker_a": 0.10})
        self.assertIsNone(sealed)
        finding = gates.bind_finding(result.hard[0], candidate)
        candidate_hash = gates.contract_hash(candidate)
        self.assertEqual(candidate_hash, gates.contract_hash(copy.deepcopy(candidate)))
        waiver = {
            "id": "lowered-floor-waiver",
            "category": "coverage",
            "contract_hash": candidate_hash,
            "reason": "published fixture exception",
            "waived_codes": ["contract_coverage_floor_below_frozen"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-30T00:00:00Z",
            "stale": False,
        }
        remaining, applied, rejected = gates.apply_waivers([finding], [waiver])
        self.assertEqual([], remaining.hard)
        self.assertEqual(1, len(applied))
        self.assertEqual([], rejected)

        stale = dict(waiver, id="stale-lowered-floor-waiver", contract_hash="0" * 64)
        remaining, applied, rejected = gates.apply_waivers([finding], [stale])
        self.assertEqual([finding], remaining.hard)
        self.assertEqual([], applied)
        self.assertEqual(["waiver_rejected"], [item.code for item in rejected])

        mistyped = dict(
            waiver,
            id="mistyped-lowered-floor-waiver",
            waived_codes=["contract_coverage_floor_below_froze"],
        )
        remaining, applied, rejected = gates.apply_waivers([finding], [mistyped])
        self.assertEqual([finding], remaining.hard)
        self.assertEqual([], applied)
        self.assertEqual(["waiver_rejected"], [item.code for item in rejected])

    def test_coverage_waiver_does_not_clear_coverage_below_declared_floor(self):
        candidate = self._build(coverage_floor=0.10)
        sealed, result = self._seal(candidate, coverage={"speaker_a": 0.09})
        self.assertIsNone(sealed)
        lower_floor = next(
            finding
            for finding in result.hard
            if finding.code == "contract_coverage_floor_below_frozen"
        )
        speaker_floor = next(
            finding
            for finding in result.hard
            if finding.code == "contract_speaker_coverage_below_floor"
        )
        waiver = {
            "id": "lowered-floor-waiver",
            "category": "coverage",
            "contract_hash": gates.contract_hash(candidate),
            "reason": "published fixture exception",
            "waived_codes": ["contract_coverage_floor_below_frozen"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-30T00:00:00Z",
            "stale": False,
        }
        remaining, applied, rejected = gates.apply_waivers(
            [gates.bind_finding(lower_floor, candidate), speaker_floor], [waiver]
        )
        self.assertEqual(
            {"contract_speaker_coverage_below_floor"},
            {finding.code for finding in remaining.hard},
        )
        self.assertEqual(1, len(applied))
        self.assertEqual([], rejected)


    def test_seal_is_silent_at_frozen_coverage_floor(self):
        sealed, result = self._seal(
            self._build(coverage_floor=config.COVERAGE_FLOOR_X),
            coverage={"speaker_a": config.COVERAGE_FLOOR_X},
        )
        self.assertTrue(result.is_clean())
        self.assertIsNotNone(sealed)
        self.assertEqual(set(), self._reported_codes(result))

    def test_seal_is_silent_above_frozen_coverage_floor(self):
        higher_floor = config.COVERAGE_FLOOR_X + 0.10
        sealed, result = self._seal(
            self._build(coverage_floor=higher_floor), coverage={"speaker_a": higher_floor}
        )
        self.assertTrue(result.is_clean())
        self.assertIsNotNone(sealed)
        self.assertEqual(set(), self._reported_codes(result))

    def test_seal_refuses_undecided_dialect_pair_independently(self):
        undecided = [findings.hard("dialect_pair_undecided", "fixture pair")]
        sealed, result = self._seal(self._build(), dialect_findings=undecided)
        self.assertIsNone(sealed)
        self.assertEqual({"contract_dialect_pair_undecided"}, self._codes(result))

    def test_fully_satisfied_contract_seals(self):
        sealed, result = self._seal(self._build())
        self.assertTrue(result.is_clean())
        self.assertIsNotNone(sealed)
        self.assertEqual("sha256", sealed["seal"]["algorithm"])
        self.assertRegex(sealed["seal"]["hash"], r"^[0-9a-f]{64}$")
        self.assertEqual("fixture-plugin-1", sealed["plugin_version"])
        self.assertEqual(_GOLDEN, sealed["golden_digest"])
        self.assertEqual(["ending_transform"], sealed["measurable_axes"])


    def test_seal_refuses_a_measurable_axis_shrink_after_sealing(self):
        sealed, result = self._seal(
            self._build(),
            plugin_measurable_axes=lambda language: [
                "ending_transform", "utterance_frame"
            ],
        )
        self.assertTrue(result.is_clean())
        resealed, result = self._seal(
            sealed, plugin_measurable_axes=lambda language: ["ending_transform"]
        )
        self.assertIsNone(resealed)
        self.assertEqual({"contract_source_measurement_changed"}, self._codes(result))

    def test_seal_hash_changes_for_axis_band_catalogue_and_plugin(self):
        sealed, result = self._seal(self._build())
        self.assertTrue(result.is_clean())
        baseline = sealed["seal"]["hash"]

        changed_axis = copy.deepcopy(sealed)
        changed_axis["axes"][0]["marker"] = "~changed"
        changed, result = self._seal(changed_axis)
        self.assertTrue(result.is_clean())
        self.assertNotEqual(baseline, changed["seal"]["hash"])

        changed_band = copy.deepcopy(sealed)
        changed_band["bands"]["all"]["ending_transform"] = [0.3, 0.8]
        changed, result = self._seal(changed_band)
        self.assertTrue(result.is_clean())
        self.assertNotEqual(baseline, changed["seal"]["hash"])

        changed_catalogue = copy.deepcopy(sealed)
        changed_catalogue["catalogue_version"] = "fixture-v2"
        changed, result = self._seal(changed_catalogue)
        self.assertTrue(result.is_clean())
        self.assertNotEqual(baseline, changed["seal"]["hash"])

        changed, result = self._seal(self._build(), plugin=_Plugin("fixture-plugin-2"))
        self.assertTrue(result.is_clean())
        self.assertNotEqual(baseline, changed["seal"]["hash"])

    def test_rebase_reseals_and_stales_affected_waiver(self):
        sealed, result = self._seal(self._build())
        self.assertTrue(result.is_clean())
        waiver = self._waiver(sealed)

        self.assertTrue(contracts.waiver_is_current(waiver, sealed))
        self.catalogue.version("fixture-v2")
        rebased, result, rebased_waivers = contracts.rebase(
            sealed,
            corpus_digests={"t1": _DIGEST},
            axis_status=_axis_status,
            measurable=config.MEASURABLE_AXIS_STATUSES,
            schema_validate=lambda candidate: [],
            graduation_stages=self.stages,
            length_ok=True,
            plugin_for=lambda language: _Plugin(),
            plugin_measurable_axes=lambda language: ["ending_transform"],
            plugin_golden_digest=lambda language: _GOLDEN,
            rejected_precedent_match=[],
            glyph_available=lambda glyph: True,
            coverage={"speaker_a": config.COVERAGE_FLOOR_X},
            dialect_findings=[],
            waivers=[waiver],
            root=self.catalogue.root,
        )
        self.assertTrue(result.is_clean())
        self.assertIsNotNone(rebased)
        self.assertNotEqual(sealed["seal"]["hash"], rebased["seal"]["hash"])
        self.assertTrue(rebased_waivers[0]["stale"])
        self.assertFalse(contracts.waiver_is_current(rebased_waivers[0], rebased))

    def test_waiver_category_outside_closed_set_is_rejected(self):
        sealed, _result = self._seal(self._build())
        with self.assertRaises(contracts.ContractError):
            contracts.create_waiver(
                sealed,
                "anything_else",
                waiver_id="fixture-waiver",
                reason="fixture",
                waived_codes=["DENSITY_VERDICT"],
                granted_by="fixture-operator",
                granted_at="2026-07-29T00:00:00Z",
            )

    def test_waiver_rejects_non_string_code_before_duplicate_check(self):
        sealed, result = self._seal(self._build())
        self.assertTrue(result.is_clean())
        with self.assertRaises(contracts.ContractError):
            contracts.create_waiver(
                sealed,
                "coverage",
                waiver_id="fixture-waiver",
                reason="fixture",
                waived_codes=[["not-a-code"]],
                granted_by="fixture-operator",
                granted_at="2026-07-29T00:00:00Z",
            )


    def test_waiver_is_stale_after_any_contract_edit(self):
        sealed, result = self._seal(self._build())
        self.assertTrue(result.is_clean())
        waiver = self._waiver(sealed)

        edited = copy.deepcopy(sealed)
        edited["bands"]["all"]["ending_transform"] = [0.3, 0.8]
        self.assertFalse(contracts.waiver_is_current(waiver, edited))

    def test_contract_waiver_applies_and_mistyped_nonwaivable_code_is_rejected(self):
        sealed, result = self._seal(self._build())
        self.assertTrue(result.is_clean())
        finding = gates.bind_finding(
            findings.hard("contract_speaker_coverage_below_floor", "fixture coverage"),
            sealed,
        )
        waiver = self._waiver(
            sealed, codes=("contract_speaker_coverage_below_floor",)
        )
        remaining, applied, rejected = gates.apply_waivers([finding], [waiver])
        self.assertEqual([], remaining.hard)
        self.assertEqual(1, len(applied))
        self.assertEqual([], rejected)

        mistyped = copy.deepcopy(waiver)
        mistyped["waived_codes"] = ["contract_speaker_coverage_below_flor"]
        remaining, applied, rejected = gates.apply_waivers([finding], [mistyped])
        self.assertEqual([finding], remaining.hard)
        self.assertEqual([], applied)
        self.assertEqual(["waiver_rejected"], [item.code for item in rejected])
        self.assertEqual("hard", rejected[0].severity)

    def test_length_feasible_is_false_for_append_cpl_overrun_and_uses_declared_budget(self):
        contract = self._build()
        budgets = {"subtitle": {"cpl": 10, "cps": 100}}
        feasible, failures = contracts.length_feasible(
            [{"key": "r1", "medium": "subtitle"}],
            contract,
            {
                "r1": {
                    "id": "r1",
                    "type_id": "t1",
                    "length_cost": {"model": "append", "value": 3},
                }
            },
            eligible_segments=lambda row: [{"text": "abcdefgh"}],
            budgets=budgets,
        )
        self.assertFalse(feasible)
        self.assertEqual(("r1", "ending_transform", "subtitle"), failures[0][:3])
        self.assertEqual(budgets["subtitle"], failures[0][3])
        self.assertEqual(11.0, failures[0][4]["cpl"])

    def test_length_feasible_is_true_when_append_cost_fits(self):
        feasible, failures = contracts.length_feasible(
            [{"key": "r1", "medium": "subtitle"}],
            self._build(),
            {
                "r1": {
                    "id": "r1",
                    "type_id": "t1",
                    "length_cost": {"model": "append", "value": 3},
                }
            },
            eligible_segments=lambda row: [{"text": "abcdefg"}],
            budgets={"subtitle": {"cpl": 10}},
        )
        self.assertTrue(feasible)
        self.assertEqual([], failures)

    def test_length_feasible_rejects_vacuous_rows_and_segments(self):
        realisations = {
            "r1": {
                "id": "r1",
                "type_id": "t1",
                "length_cost": {"model": "append", "value": 3},
            }
        }
        cases = (
            ([], lambda _row: [{"text": "abcdefg"}]),
            ([{"key": "r1", "medium": "subtitle"}], lambda _row: []),
        )
        for rows, eligible_segments in cases:
            with self.subTest(rows=rows):
                with self.assertRaises(contracts.ContractError):
                    contracts.length_feasible(
                        rows,
                        self._build(),
                        realisations,
                        eligible_segments=eligible_segments,
                        budgets={"subtitle": {"cpl": 10}},
                    )

    def test_utterance_frame_multiply_cost_is_computed_multiplicatively(self):
        contract = {
            "type_ids": ["t1"],
            "axes": [{"axis": "utterance_frame"}],
            "edition_medium": "subtitle",
        }
        feasible, failures = contracts.length_feasible(
            [{"key": "r1", "medium": "subtitle"}],
            contract,
            {
                "r1": {
                    "id": "r1",
                    "type_id": "t1",
                    "length_cost": {"model": "multiply", "value": 1.5},
                }
            },
            eligible_segments=lambda row: [{"text": "abcdefgh"}],
            budgets={"subtitle": {"cpl": 11}},
        )
        self.assertFalse(feasible)
        self.assertEqual(12.0, failures[0][4]["chars"])
        self.assertEqual(12.0, failures[0][4]["cpl"])

    def test_bare_scene_scope_override_is_rejected(self):
        with self.assertRaises(contracts.ContractError) as caught:
            self._build(
                scope_overrides={
                    "scene_001": {"bands": {"ending_transform": [0.2, 0.8]}}
                }
            )
        self.assertIn("not a scene id", str(caught.exception))

    def test_absent_ladder_ledger_is_hard(self):
        result = contracts.ladder_ledger_check(self._build(), None)
        self.assertEqual({"contract_voice_drop_ledger_absent"}, self._codes(result))

    def test_ladder_underrun_is_hard_and_cannot_be_waived(self):
        sealed, result = self._seal(self._build())
        self.assertTrue(result.is_clean())
        waiver = self._waiver(sealed)

        self.assertTrue(contracts.waiver_is_current(waiver, sealed))
        result = contracts.ladder_ledger_check(
            sealed,
            [
                {
                    "event": "voice-drop",
                    "reason": "priority_ladder",
                    "under_run": True,
                    "row_key": "r1",
                    "axis": "ending_transform",
                }
            ],
        )
        self.assertEqual({"contract_ladder_marker_underrun"}, self._codes(result))

    def test_invalid_ladder_ledger_row_is_hard(self):
        result = contracts.ladder_ledger_check(
            self._build(), [{"event": "voice-drop", "reason": "priority_ladder"}]
        )
        self.assertEqual({"contract_voice_drop_ledger_invalid"}, self._codes(result))

    def test_every_contract_hard_finding_has_a_named_trigger_test(self):
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "hancharacter",
            "contracts.py",
        )
        with open(path, "r", encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        emitted = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not (
                isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "findings"
                and node.func.attr == "hard"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                continue
            emitted.add(node.args[0].value)
        covered = {
            "contract_schema_invalid",
            "contract_type_not_canonical",
            "contract_length_infeasible",
            "contract_source_measurement_unavailable",
            "contract_source_measurement_changed",
            "contract_rejected_precedent_match",
            "contract_required_glyph_unavailable",
            "contract_speaker_coverage_below_floor",
            "contract_coverage_floor_below_frozen",
            "contract_source_density_zero",
            "contract_dialect_pair_undecided",
            "contract_voice_drop_ledger_absent",
            "contract_voice_drop_ledger_invalid",
            "contract_ladder_marker_underrun",
            # Path A: triggered by AuthorityRouteTests.
            "contract_source_evidence_incomplete",
        }
        self.assertEqual(covered, emitted)


if __name__ == "__main__":
    unittest.main()


class AuthorityRouteTests(unittest.TestCase):
    """Path A: a second, weaker, explicitly labelled sealing route.

    `precedent_backed` asserts the rendering is the established convention and needs
    a canonical type. `translator_declared` asserts only that the translator's own
    declared rendering is applied at the source's measured density, and needs the
    source-side evidence alone. Requiring an adopted precedent made the tool unable
    to govern a first translation, which is the common real case.
    """

    def setUp(self):
        self.base = ContractTests()
        self.base.setUp()
        self.addCleanup(self.base.doCleanups)

    def _candidate(self, authority):
        return self.base._build(authority=authority)

    def _seal(self, authority, **overrides):
        return self.base._seal(self._candidate(authority), **overrides)

    def test_an_undeclared_authority_is_hard_and_never_defaults(self):
        contract = self._candidate(config.AUTHORITY_PRECEDENT_BACKED)
        del contract["authority"]
        errors = contracts.validate_contract(contract)
        self.assertTrue(any("authority" in error for error in errors), errors)

    def test_an_unknown_authority_is_rejected(self):
        contract = self._candidate(config.AUTHORITY_PRECEDENT_BACKED)
        contract["authority"] = "whatever"
        errors = contracts.validate_contract(contract)
        self.assertTrue(any("authority" in error for error in errors), errors)

    def test_contract_source_evidence_incomplete_blocks_the_declared_route(self):
        sealed, found = self._seal(
            config.AUTHORITY_TRANSLATOR_DECLARED,
            source_evidence_ok=lambda type_id: "occurrences 1 < 8",
        )
        self.assertIsNone(sealed)
        self.assertIn(
            "contract_source_evidence_incomplete",
            [finding["code"] for finding in found.to_json()],
        )

    def test_the_declared_route_seals_without_any_adopted_precedent(self):
        """The premise of path A: no precedent, and it still enforces."""
        sealed, found = self._seal(
            config.AUTHORITY_TRANSLATOR_DECLARED,
            graduation_stages={"t1": config.STAGE_PROVISIONAL},
            source_evidence_ok=lambda type_id: True,
        )
        self.assertIsNotNone(sealed, [f["code"] for f in found.to_json()])
        self.assertEqual(config.AUTHORITY_TRANSLATOR_DECLARED, sealed["authority"])

    def test_the_precedent_route_still_requires_canonical(self):
        sealed, found = self._seal(
            config.AUTHORITY_PRECEDENT_BACKED,
            graduation_stages={"t1": config.STAGE_PROVISIONAL},
        )
        self.assertIsNone(sealed)
        self.assertIn(
            "contract_type_not_canonical",
            [finding["code"] for finding in found.to_json()],
        )

    def test_a_missing_source_evidence_join_refuses_rather_than_permits(self):
        """The default must fail closed; a guard that defaults to off is not a guard."""
        contract = self._candidate(config.AUTHORITY_TRANSLATOR_DECLARED)
        values = {
            "schema_validate": lambda candidate: [],
            "graduation_stages": {"t1": config.STAGE_PROVISIONAL},
            "length_ok": True,
            "plugin_for": lambda language: _Plugin(),
            "plugin_measurable_axes": lambda language: ["ending_transform"],
            "plugin_golden_digest": lambda language: _GOLDEN,
            "rejected_precedent_match": [],
            "glyph_available": lambda glyph: True,
            "coverage": {"speaker_a": config.COVERAGE_FLOOR_X},
            "dialect_findings": [],
        }
        sealed, found = contracts.seal(contract, **values)
        self.assertIsNone(sealed)
        self.assertIn(
            "contract_source_evidence_incomplete",
            [finding["code"] for finding in found.to_json()],
        )

    def test_a_rejected_precedent_still_refuses_the_declared_route(self):
        """The asymmetry that keeps the weaker route honest.

        Dropping the adopted-precedent requirement must not drop the
        rejected-precedent refusal: a translator may not declare a rendering that a
        published precedent already shows to be a flattening.
        """
        rejection = findings.FindingSet()
        rejection.add(
            findings.hard("contract_rejected_precedent_match", "matches a rejection")
        )
        for authority in config.CONTRACT_AUTHORITIES:
            with self.subTest(authority=authority):
                sealed, found = self._seal(
                    authority,
                    graduation_stages={"t1": config.STAGE_CANONICAL},
                    source_evidence_ok=lambda type_id: True,
                    rejected_precedent_match=rejection,
                )
                self.assertIsNone(sealed)
                self.assertIn(
                    "contract_rejected_precedent_match",
                    [finding["code"] for finding in found.to_json()],
                )

    def test_the_authority_is_bound_into_the_seal_hash(self):
        """So it cannot be edited to the stronger claim after sealing."""
        hashes = {}
        for authority in config.CONTRACT_AUTHORITIES:
            sealed, _ = self._seal(
                authority,
                graduation_stages={"t1": config.STAGE_CANONICAL},
                source_evidence_ok=lambda type_id: True,
            )
            self.assertIsNotNone(sealed)
            hashes[authority] = sealed["seal"]["hash"]
        self.assertEqual(2, len(set(hashes.values())), hashes)
