import ast
import hashlib
import json
import os
import unittest

from hancharacter import config, gates, segment
from hancharacter import findings


MATRIX_PATH = "/root/tmp/hancharacter-qa/g003-fixtures/matrix.json"


def _profile():
    return config.Profile(
        {
            "work": "gates-fixture",
            "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
            "evidence_lang": "en",
            "pivot_lang": "en",
            "target_lang": "ko",
            "speaker_roles": {
                "speaker": config.ROLE_SPEAKER,
                "term": config.ROLE_TERM,
                "close": config.ROLE_CLOSE,
            },
            "delimiters": {
                "en": {"speech": [['"', '"']], "term": []},
                "ko": {"speech": [['"', '"']], "term": [["「", "」"]], "speech_is_positional": False},
            },
        }
    )


def _contract(mode=config.MODE_VOICE_CRITICAL, speaker="speaker", **overrides):
    value = {
        "speaker": speaker,
        "axes": [{"axis": "ending_transform"}],
        "required_markers": [r"픽$"],
        "forbidden_markers": [r"금지$"],
        "measured_source_density": {"ending_transform": 1.0},
        "voice_enforcement_mode": mode,
        "exclusivity": {"exclusive_with": []},
        "bands": {"all": {"ending_transform": [1.0, 1.0]}},
        "scope_overrides": {},
        "marker_sets": {"ending_transform": [r"픽$"]},
        "catalogue_markers": {"fixture": [r"픽$"]},
        "review_decisions": {},
        "seal": {"hash": hashlib.sha256((speaker + mode).encode("utf-8")).hexdigest()},
        "measurable_axes": ["ending_transform"],

    }
    value.update(overrides)
    return value


def _observations(text="픽", *, scope="speaker", count=20, eligible=True, pending=False, attributed_spans=1):
    return [
        {
            "row_key": "row-%02d" % index,
            "scope": scope,
            "text": text,
            "scene": "scene-%d" % (index // 4),
            "eligible": eligible,
            "pending": pending,
            "attributed_spans": attributed_spans,
        }
        for index in range(count)
    ]


def _source_scenes(scope="speaker", axis="ending_transform"):
    return {(scope, axis): [1.0] * config.MIN_SCENES_PER_BAND}


def _empty_findings():
    return findings.FindingSet()


class GateMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(MATRIX_PATH, encoding="utf-8") as handle:
            cls.matrix = json.load(handle)
        cls.profile = _profile()

    def _run(self, contract=None, **overrides):
        contract = _contract() if contract is None else contract
        values = {
            "contracts": [contract],
            "attribution_gate": _empty_findings,
            "seal_contract": lambda item: (item, _empty_findings()),
            "length_check": lambda item: (True, []),
            "observations": _observations(),
            "catalogue_markers": {"fixture": [r"픽$"]},
            "target_lang": "ko",
            "source_scene_densities": _source_scenes(),
            "measurable_axes": {contract["speaker"]: ["ending_transform"]},
            "quote_parity_findings": _empty_findings(),
            "ladder_check": lambda item: _empty_findings(),
            "review_decisions": {},
        }
        values.update(overrides)
        return gates.run(**values)

    @staticmethod
    def _code_severity(found, code):
        values = [(item.code, item.severity) for item in list(found.hard) + list(found.reported)]
        if code is None:
            return None, None
        for actual_code, severity in values:
            if actual_code == code:
                return actual_code, severity
        return None, None

    def _matrix_observed(self, case):
        case_id = case["id"]
        if case_id == "contracts-empty":
            found, _summary = self._run(contracts=[])
            return found, case["expected_code"]
        if case_id == "zero-eligible-units":
            found, _summary = self._run(
                observations=_observations(eligible=False)
            )
            return found, case["expected_code"]
        if case_id == "empty-measurable-axis-set":
            found, _summary = self._run(measurable_axes={"speaker": []})
            return found, case["expected_code"]
        if case_id == "ungraduated-marker-seal":
            found, _summary = self._run(
                seal_contract=lambda item: (
                    None,
                    [findings.hard("contract_type_not_canonical", "fixture ungraduated")],
                )
            )
            return found, case["expected_code"]
        if case_id == "catalogue-marker-without-contract":
            found, _queue, _counts = gates.invention(
                [{"row_key": "invented", "scope": "other", "text": "픽", "eligible": False, "pending": False}],
                [_contract()],
                catalogue_markers={"fixture": [r"픽$"]},
                target_lang="ko",
                review_decisions={"other:픽": "not a novel-form review"},
            )
            return found, case["expected_code"]
        if case_id == "novel-recurring-form":
            rows = [
                {"row_key": "novel-%d" % index, "scope": "speaker", "text": "말쨩", "sentence_final": "쨩"}
                for index in range(config.NOVELTY_RECURRENCE_K)
            ]
            found, queue, _counts = gates.invention(
                rows,
                [_contract(review_decisions={"speaker:쨩": "human triage"})],
                catalogue_markers={"fixture": [r"픽$"]},
                target_lang="ko",
                review_decisions={"speaker:쨩": "human triage"},
            )
            self.assertEqual(1, len(queue))
            self.assertEqual("triaged", queue[0]["status"])
            return found, case["expected_code"]
        if case_id == "t2-confirmed-rejected":
            found, _summary = self._run(
                attribution_gate=lambda: {
                    "findings": [],
                    "records": [{"speaker": "speaker", "evidence_tier": "T2", "target_tier": "T3", "status": "confirmed"}],
                }
            )
            return found, case["expected_code"]
        if case_id == "length-infeasible":
            found, _summary = self._run(length_check=lambda item: (False, [("row", "ending_transform")]))
            return found, case["expected_code"]
        if case_id == "glyph-unavailable":
            found, _summary = self._run(
                seal_contract=lambda item: (
                    None,
                    [findings.hard("contract_required_glyph_unavailable", "fixture glyph")],
                )
            )
            return found, case["expected_code"]
        if case_id == "rejected-precedent-match":
            found, _summary = self._run(
                seal_contract=lambda item: (
                    None,
                    [findings.hard("contract_rejected_precedent_match", "fixture precedent")],
                )
            )
            return found, case["expected_code"]
        if case_id == "coverage-below-floor-waivable":
            contract = _contract()
            raw = gates.bind_finding(
                findings.hard("contract_speaker_coverage_below_floor", "fixture coverage"), contract
            )
            waiver = {
                "id": "fixture-coverage",
                "category": "coverage",
                "contract_hash": gates.contract_hash(contract),
                "reason": "fixture coverage decision",
                "waived_codes": ["contract_speaker_coverage_below_floor"],
                "granted_by": "fixture-operator",
                "granted_at": "2026-07-29T00:00:00Z",
                "stale": False,
            }

            remaining, applied, rejected = gates.apply_waivers([raw], [waiver])
            self.assertEqual(1, len(applied))
            self.assertEqual([], rejected)
            self.assertEqual([], remaining.hard)
            return None, case["expected_code"], raw
        if case_id == "parity-term-vs-speech-pass":
            row = segment.Row(
                key="term-only",
                evidence="<color=speaker>source<color=close>",
                pivot='name "Term"',
                evidence_lang="en",
                pivot_lang="en",
                target="이름 「용어」",
            )
            found = findings.FindingSet()
            parity = segment.quote_parity(row, self.profile)
            if parity is not None:
                found.add(parity)
            return found, case["expected_code"]
        if case_id == "parity-dropped-speech-fail":
            row = segment.Row(
                key="dropped",
                evidence="<color=speaker>source<color=close>",
                pivot='"speech"',
                evidence_lang="en",
                pivot_lang="en",
                target="",
            )
            found = findings.FindingSet()
            parity = segment.quote_parity(row, self.profile)
            if parity is not None:
                found.add(parity)
            return found, case["expected_code"]
        if case_id == "short-real-utterance-unit":
            row = segment.Row(
                key="short",
                evidence="<color=speaker>s<color=close>",
                pivot='"A" named "Term"',
                evidence_lang="en",
                pivot_lang="en",
                target='"가" 이름 「용어」',
            )
            grouped = segment.group_units(segment.side_units(row, self.profile, "target"))
            self.assertEqual(1, len(grouped))
            return findings.FindingSet(), case["expected_code"]
        if case_id == "innocent-narration-clean":
            found, _report = gates.corpus(
                _observations(),
                [_contract()],
                catalogue_markers={"fixture": [r"픽$"]},
                target_lang="ko",
                source_scene_densities=_source_scenes(),
                measurable_axes={"speaker": ["ending_transform"]},
                quote_parity_findings=[],
                ladder_findings=[],
            )
            self.assertNotIn("voice-narration-clean", [item.code for item in found.hard])
            return found, case["expected_code"]
        if case_id.startswith("presence-loss-"):
            mode = case["setup"]["mode"]
            found, _summary = self._run(
                contract=_contract(mode), observations=_observations("끝다")
            )
            return found, case["expected_code"]
        if case_id == "sealed-band-verdict":
            found, _summary = self._run(
                contract=_contract(bands={"all": {"ending_transform": [0.0, 0.0]}}),
                bands={"speaker:ending_transform": [1.0, 1.0]},
            )
            return found, case["expected_code"]
        if case_id.startswith("density-loss-"):
            mode = case["setup"]["mode"]
            found, _report = gates.corpus(
                _observations("끝다"),
                [_contract(mode)],
                catalogue_markers={"fixture": [r"픽$"]},
                target_lang="ko",
                source_scene_densities=_source_scenes(),
                measurable_axes={"speaker": ["ending_transform"]},
                quote_parity_findings=[],
                ladder_findings=[],
            )
            return found, case["expected_code"]
        self.fail("matrix case has no executor: %s" % case_id)

    def test_negative_fixture_matrix_matches_code_and_severity(self):
        for case in self.matrix:
            with self.subTest(case=case["id"]):
                response = self._matrix_observed(case)
                if len(response) == 3:
                    _unused, expected_code, raw = response
                    observed_code, observed_severity = raw.code, raw.severity
                else:
                    found, expected_code = response
                    observed_code, observed_severity = self._code_severity(found, expected_code)
                self.assertEqual(case["expected_code"], observed_code)
                self.assertEqual(case["expected_severity"], observed_severity)

    def test_run_order_and_skip_summary_are_published(self):
        order = []
        attribution = findings.FindingSet()
        attribution.add(findings.hard("attribution_fixture", "broken attribution"))
        found, summary = self._run(
            attribution_gate=lambda: (order.append("attribution") or attribution),
            seal_contract=lambda item: (order.append("seal") or (item, _empty_findings())),
            length_check=lambda item: (order.append("length") or (True, [])),
        )
        self.assertEqual(["attribution"], order)
        self.assertTrue(found.hard)
        self.assertEqual(list(("character-attribution", "contract-seal", "capacity/length", "character-corpus")), list(summary))
        self.assertTrue(summary["character-attribution"]["ran"])
        for gate in ("contract-seal", "capacity/length", "character-corpus"):
            self.assertFalse(summary[gate]["ran"])
            self.assertIsNotNone(summary[gate]["skipped_reason"])

    def test_faithful_artifact_run_stays_green(self):
        found, summary = self._run()
        self.assertTrue(found.is_clean())
        self.assertEqual([], found.reported)
        self.assertTrue(all(summary[gate]["ran"] for gate in summary))
        self.assertTrue(all(summary[gate]["skipped_reason"] is None for gate in summary))
        self.assertEqual(
            {"eligible": 20, "ineligible": 0, "pending": 0, "total": 20},
            summary["character-corpus"]["invention_counts"],
        )

    def test_capacity_failure_does_not_hide_character_corpus(self):
        found, summary = self._run(
            observations=_observations("끝다"),
            length_check=lambda item: (False, [("row", "ending_transform")]),
        )
        self.assertTrue(summary["capacity/length"]["hard"])
        self.assertTrue(summary["character-corpus"]["ran"])
        self.assertIn("DENSITY_VERDICT", [item.code for item in found.hard])

    def test_contracts_present_but_inert_enforcement_cannot_ship_green(self):
        for contract, observations, axes in (
            (_contract(axes=[]), _observations(), {"speaker": []}),
            (_contract(), [], {"speaker": ["ending_transform"]}),
            (_contract(), _observations(), {"speaker": []}),
        ):
            with self.subTest(contract=contract, observations=len(observations), axes=axes):
                found, summary = self._run(
                    contract=contract,
                    observations=observations,
                    measurable_axes=axes,
                )
                self.assertTrue(summary["character-corpus"]["ran"])
                self.assertIn("voice_enforcement_inert", [item.code for item in found.hard])
                self.assertFalse(found.is_clean())

    def test_model_output_cannot_authorise_a_gate(self):
        # The only asserted pass-like value is ignored: density is recomputed from
        # target surfaces and source-scene artifacts, so this still fails hard.
        rows = _observations("끝다")
        for row in rows:
            row["model_verdict"] = "pass"
            row["model_confidence"] = 1.0
        found, summary = self._run(observations=rows)
        self.assertTrue(summary["character-corpus"]["ran"])
        self.assertIn("DENSITY_VERDICT", [item.code for item in found.hard])

    def test_invention_counts_include_ineligible_and_pending_rows(self):
        rows = [
            {"row_key": "eligible", "scope": "other", "text": "픽", "eligible": True, "pending": False},
            {"row_key": "ineligible", "scope": "other", "text": "픽", "eligible": False, "pending": False},
            {"row_key": "pending", "scope": "other", "text": "픽", "eligible": False, "pending": True},
        ]
        found, _queue, counts = gates.invention(
            rows,
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            review_decisions={"other:픽": "human triage"},
        )
        self.assertEqual({"eligible": 1, "ineligible": 1, "pending": 1, "total": 3}, counts)
        self.assertEqual(3, len([item for item in found.hard if item.code == "voice_invention_catalogue"]))

    def test_base_register_whitelist_excludes_repeated_ordinary_casual_korean(self):
        rows = [
            {"row_key": "casual-%d" % index, "scope": "speaker", "text": "알겠어"}
            for index in range(config.NOVELTY_RECURRENCE_K)
        ]
        found, queue, _counts = gates.invention(
            rows,
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
        )
        self.assertEqual([], queue)
        self.assertNotIn("voice_invention_novel_recurring", [item.code for item in found.reported])

    def test_final_form_normalises_declared_delimiters_before_fallback(self):
        cases = (
            ("bare", "이제 가겜다능."),
            ("quoted", '"이제 가겜다능."'),
            ("quoted-plus-trailing-tag", '"이제 가겜다능."<br>'),
            ("tag-then-quote", '<br>"이제 가겜다능."'),
            ("cjk-quoted", "「이제 가겜다능。」"),
        )
        for index, (name, text) in enumerate(cases):
            with self.subTest(name=name):
                item = gates._observation(
                    {"row_key": name, "scope": "speaker", "text": text}, index
                )
                found = _empty_findings()
                self.assertEqual(
                    "능",
                    gates._final_form(
                        item, "ending_transform", self.profile, "ko", found, set()
                    ),
                )
                self.assertTrue(found.is_clean())

        item = gates._observation(
            {"row_key": "declared", "scope": "speaker", "text": "끝다", "sentence_final": "쨩"},
            len(cases),
        )
        self.assertEqual(
            "쨩",
            gates._final_form(
                item, "ending_transform", self.profile, "ko", _empty_findings(), set()
            ),
        )

    def test_delimited_novel_form_recurs_at_k_not_below(self):
        self.assertEqual(3, config.NOVELTY_RECURRENCE_K)

        def rows(count):
            return [
                {"row_key": "novel-%d" % index, "scope": "speaker", "text": '"말쨩."<br>'}
                for index in range(count)
            ]

        below, queue, _counts = gates.invention(
            rows(config.NOVELTY_RECURRENCE_K - 1),
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            profile=self.profile,
        )
        self.assertEqual([], queue)
        self.assertNotIn(
            "voice_invention_novel_recurring", [item.code for item in below.reported]
        )

        found, queue, _counts = gates.invention(
            rows(config.NOVELTY_RECURRENCE_K),
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            profile=self.profile,
        )
        self.assertEqual(["voice_invention_novel_recurring"], [item.code for item in found.reported])
        self.assertEqual([("쨩", config.NOVELTY_RECURRENCE_K)], [(item["form"], item["count"]) for item in queue])

    def test_delimited_base_register_whitelist_excludes_ordinary_casual_korean(self):
        rows = [
            {"row_key": "casual-%d" % index, "scope": "speaker", "text": '"알겠어"<br>'}
            for index in range(config.NOVELTY_RECURRENCE_K)
        ]
        found, queue, _counts = gates.invention(
            rows,
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            profile=self.profile,
        )
        self.assertEqual([], queue)
        self.assertNotIn("voice_invention_novel_recurring", [item.code for item in found.reported])

    def test_narration_clean_uses_the_same_surface_for_canonical_and_raw_inputs(self):
        contract = _contract()
        canonical = gates._observation(
            {
                "row_key": "canonical-narration",
                "scope": "speaker",
                "text": '"서술 픽"<br>',
                "attributed_spans": 0,
            },
            0,
        )
        raw = gates._observation(
            {
                "row_key": "raw-narration",
                "scope": "speaker",
                "text": "대사",
                "narration_text": '"서술 픽"<br>',
                "attributed_spans": 1,
            },
            1,
        )
        canonical_found = gates._presence_and_narration(
            [canonical], {"speaker": contract}, profile=self.profile, target_lang="ko"
        )
        raw_found = gates._presence_and_narration(
            [raw], {"speaker": contract}, profile=self.profile, target_lang="ko"
        )
        self.assertEqual(
            [item.code for item in canonical_found.hard],
            [item.code for item in raw_found.reported],
        )
        self.assertEqual(["voice-narration-clean"], [item.code for item in canonical_found.hard])

    def test_unnormalisable_final_form_emits_a_finding(self):
        item = gates._observation(
            {"row_key": "unnormalisable", "scope": "speaker", "text": '"이제 가겜다능."'},
            0,
        )
        found = _empty_findings()
        self.assertIsNone(
            gates._final_form(item, "ending_transform", None, "ko", found, set())
        )
        self.assertEqual(
            ["voice_observation_unnormalisable"], [item.code for item in found.hard]
        )

    def test_untriaged_novel_queue_is_hard_but_triaged_queue_is_not(self):
        rows = [
            {"row_key": "novel-%d" % index, "scope": "speaker", "text": "말쨩", "sentence_final": "쨩"}
            for index in range(config.NOVELTY_RECURRENCE_K)
        ]
        untriaged, queue, _counts = gates.invention(
            rows, [_contract()], catalogue_markers={"fixture": [r"픽$"]}, target_lang="ko"
        )
        self.assertEqual("pending", queue[0]["status"])
        self.assertIn("voice_invention_review_untriaged", [item.code for item in untriaged.hard])
        triaged, queue, _counts = gates.invention(
            rows,
            [_contract(review_decisions={"speaker:쨩": "reviewer accepted ordinary ending"})],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            review_decisions={"speaker:쨩": "reviewer accepted ordinary ending"},
        )
        self.assertEqual("triaged", queue[0]["status"])
        self.assertNotIn("voice_invention_review_untriaged", [item.code for item in triaged.hard])

    def test_narration_clean_is_hard_only_without_attributed_spans(self):
        attributed = _observations(count=20)
        attributed[0]["narration_text"] = "서술 픽"
        found, _report = gates.corpus(
            attributed,
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities=_source_scenes(),
            measurable_axes={"speaker": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        narration = [item for item in found.reported if item.code == "voice-narration-clean"]
        self.assertEqual(["report"], [item.severity for item in narration])
        zero = _observations(count=20, attributed_spans=0)
        found, _report = gates.corpus(
            zero,
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities=_source_scenes(),
            measurable_axes={"speaker": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        self.assertIn("voice-narration-clean", [item.code for item in found.hard])

    def test_empty_or_absent_boundary_artifacts_fail_loudly(self):
        found, summary = self._run(contracts=[])
        self.assertTrue(summary["contract-seal"]["ran"])
        self.assertIn("contracts_empty", [item.code for item in found.hard])
        self.assertFalse(summary["character-corpus"]["ran"])
        self.assertIsNotNone(summary["character-corpus"]["skipped_reason"])

        found, summary = self._run(seal_contract=lambda item: (None, _empty_findings()))
        self.assertIn("contract_seal_missing", [item.code for item in found.hard])
        self.assertFalse(summary["capacity/length"]["ran"])
        self.assertFalse(summary["character-corpus"]["ran"])
        self.assertIsNotNone(summary["character-corpus"]["skipped_reason"])

        without_source, _report = gates.corpus(
            _observations(),
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities={},
            measurable_axes={"speaker": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        self.assertIn("voice_density_source_artifact_absent", [item.code for item in without_source.hard])

        no_scene = _observations()
        for row in no_scene:
            row["scene"] = None
        without_scene, _report = gates.corpus(
            no_scene,
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities=_source_scenes(),
            measurable_axes={"speaker": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        self.assertIn("voice_density_target_scenes_absent", [item.code for item in without_scene.hard])
        found, summary = self._run(ladder_check=None)
        self.assertTrue(summary["character-corpus"]["ran"])
        self.assertIn("contract_voice_drop_ledger_absent", [item.code for item in found.hard])

    def test_waived_seal_finding_cannot_turn_skipped_corpus_green(self):
        contract = _contract()
        waiver = {
            "id": "coverage-waiver",
            "category": "coverage",
            "contract_hash": gates.contract_hash(contract),
            "reason": "fixture coverage exception",
            "waived_codes": ["contract_speaker_coverage_below_floor"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-29T00:00:00Z",
            "stale": False,
        }
        found, summary = self._run(
            seal_contract=lambda item: (
                None,
                [findings.hard("contract_speaker_coverage_below_floor", "fixture low")],
            ),
            waivers=[waiver],
        )
        self.assertFalse(summary["character-corpus"]["ran"])
        self.assertIn("gate_not_run", [item.code for item in found.hard])
        self.assertFalse(found.is_clean())

    def test_empty_observations_and_missing_axis_artifacts_cannot_pass(self):
        found, summary = self._run(observations=None)
        self.assertTrue(summary["character-corpus"]["ran"])
        self.assertIn("voice_observations_empty", [item.code for item in found.hard])

        found, summary = self._run(measurable_axes={})
        self.assertTrue(summary["character-corpus"]["ran"])
        self.assertIn("voice_enforcement_inert", [item.code for item in found.hard])

        found, summary = self._run(
            measurable_axes={"speaker": ["not_applicable"]}
        )
        self.assertTrue(summary["character-corpus"]["ran"])
        self.assertIn("voice_enforcement_inert", [item.code for item in found.hard])

        found, _queue, counts = gates.invention(
            [],
            [_contract()],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
        )
        self.assertEqual({"eligible": 0, "ineligible": 0, "pending": 0, "total": 0}, counts)
        self.assertIn("voice_observations_empty", [item.code for item in found.hard])

    def test_runtime_measurable_axes_must_match_the_sealed_pin(self):
        contract = _contract(
            measurable_axes=["ending_transform", "utterance_frame"]
        )
        found, _report = gates.corpus(
            _observations(),
            [contract],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities=_source_scenes(),
            measurable_axes={"speaker": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        self.assertIn(
            "contract_source_measurement_changed",
            [item.code for item in found.hard],
        )

    def test_required_artifacts_and_callback_errors_fail_loudly(self):
        with self.assertRaises(TypeError):
            gates.corpus(
                _observations(),
                [_contract()],
                catalogue_markers={"fixture": [r"픽$"]},
                target_lang="ko",
                source_scene_densities=_source_scenes(),
            )

        def failing_attribution():
            raise RuntimeError("attribution backend unavailable")

        with self.assertRaisesRegex(RuntimeError, "attribution backend unavailable"):
            self._run(attribution_gate=failing_attribution)


    def test_waivers_are_exact_stale_and_never_clear_presence(self):
        contract = _contract()
        density_finding = gates.bind_finding(findings.hard("DENSITY_VERDICT", "fixture density"), contract)
        waiver = {
            "id": "fixture-density",
            "category": "policy_density",
            "contract_hash": gates.contract_hash(contract),
            "reason": "fixture policy",
            "waived_codes": ["DENSITY_VERDICT"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-29T00:00:00Z",
            "stale": False,
        }

        remaining, applied, rejected = gates.apply_waivers([density_finding], [waiver])
        self.assertEqual([], remaining.hard)
        self.assertEqual(1, len(applied))
        self.assertEqual([], rejected)
        edited = _contract(required_markers=[r"다$"])
        edited["seal"] = {"hash": hashlib.sha256(b"edited-contract").hexdigest()}
        changed_finding = gates.bind_finding(
            findings.hard("DENSITY_VERDICT", "fixture density"), edited
        )
        remaining, applied, rejected = gates.apply_waivers([changed_finding], [waiver])
        self.assertEqual([], applied)
        self.assertEqual(1, len(rejected))
        presence = gates.bind_finding(findings.hard("voice_forbidden_marker_present", "fixture presence"), contract)
        hostile = {
            "id": "hostile-presence",
            "category": "policy_density",
            "contract_hash": gates.contract_hash(contract),
            "reason": "not permitted",
            "waived_codes": ["voice_forbidden_marker_present"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-29T00:00:00Z",
            "stale": False,
        }
        remaining, applied, rejected = gates.apply_waivers([presence], [hostile])
        self.assertEqual([], applied)
        self.assertEqual(["voice_forbidden_marker_present"], [item.code for item in remaining.hard])
        self.assertEqual("waiver_rejected", rejected[0].code)

    def test_explicit_exclusivity_and_forbidden_markers_are_hard(self):
        owner = _contract("voice_critical", speaker="owner", exclusivity={"exclusive_with": ["other"]})
        other = _contract("voice_critical", speaker="other")
        rows = _observations(scope="other")
        found, _report = gates.corpus(
            rows,
            [owner, other],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities={**_source_scenes("owner"), **_source_scenes("other")},
            measurable_axes={"owner": ["ending_transform"], "other": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        self.assertIn("voice_exclusivity", [item.code for item in found.hard])
        unprotected = _contract("voice_critical", speaker="owner")
        found, _report = gates.corpus(
            rows,
            [unprotected, other],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities={**_source_scenes("owner"), **_source_scenes("other")},
            measurable_axes={"owner": ["ending_transform"], "other": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        self.assertNotIn("voice_exclusivity", [item.code for item in found.hard])
        forbidden = _contract(forbidden_markers=[r"픽$"])
        found, _report = gates.corpus(
            _observations(),
            [forbidden],
            catalogue_markers={"fixture": [r"픽$"]},
            target_lang="ko",
            source_scene_densities=_source_scenes(),
            measurable_axes={"speaker": ["ending_transform"]},
            quote_parity_findings=[],
            ladder_findings=[],
        )
        self.assertIn("voice_forbidden_marker_present", [item.code for item in found.hard])


    def test_required_marker_total_loss_is_hard_in_both_modes_and_intermittent_presence_passes(self):
        for mode in (config.MODE_VOICE_CRITICAL, config.MODE_PROSE_FIDELITY):
            with self.subTest(mode=mode):
                found, _summary = self._run(
                    contract=_contract(mode), observations=_observations("끝다")
                )
                absent = [item for item in found.hard if item.code == "voice_required_marker_absent"]
                self.assertEqual(["hard"], [item.severity for item in absent])

        intermittent = _observations("끝다")
        intermittent[0]["text"] = "픽"
        found, _summary = self._run(observations=intermittent)
        self.assertNotIn("voice_required_marker_absent", [item.code for item in found.hard])

    def test_zero_eligible_units_are_inert_not_a_presence_pass(self):
        found, _summary = self._run(observations=_observations(eligible=False))
        self.assertIn("voice_enforcement_inert", [item.code for item in found.hard])
        self.assertNotIn("voice_required_marker_absent", [item.code for item in found.hard])

    def test_zero_sealed_source_density_is_hard_even_before_presence_comparison(self):
        contract = _contract(
            measured_source_density={"ending_transform": 0.0},
            bands={"all": {"ending_transform": [0.0, 0.0]}},
        )
        found, _summary = self._run(
            contract=contract,
            observations=_observations("끝다"),
            source_scene_densities={
                ("speaker", "ending_transform"): [0.0] * config.MIN_SCENES_PER_BAND
            },
        )
        self.assertIn("voice_source_density_zero", [item.code for item in found.hard])

        self.assertNotIn("voice_required_marker_absent", [item.code for item in found.hard])

    def test_zero_source_density_finding_cannot_be_waived(self):
        contract = _contract(measured_source_density={"ending_transform": 0.0})
        finding = gates.bind_finding(
            findings.hard("contract_source_density_zero", "fixture seal-time zero source density"),

            contract,
        )
        waiver = {
            "id": "zero-source-density",
            "category": "policy_density",
            "contract_hash": gates.contract_hash(contract),
            "reason": "must not disable a required marker gate",
            "waived_codes": ["contract_source_density_zero"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-29T00:00:00Z",
            "stale": False,
        }
        remaining, applied, rejected = gates.apply_waivers([finding], [waiver])
        self.assertEqual(["contract_source_density_zero"], [item.code for item in remaining.hard])
        self.assertEqual([], applied)
        self.assertEqual(["waiver_rejected"], [item.code for item in rejected])

    def test_gate_time_zero_source_density_finding_cannot_be_waived(self):
        contract = _contract(measured_source_density={"ending_transform": 0.0})
        finding = gates.bind_finding(
            findings.hard("voice_source_density_zero", "fixture inert LOSS comparison"),
            contract,
        )
        waiver = {
            "id": "gate-time-zero-source-density",
            "category": "policy_density",
            "contract_hash": gates.contract_hash(contract),
            "reason": "must not disable a required marker gate",
            "waived_codes": ["voice_source_density_zero"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-29T00:00:00Z",
            "stale": False,
        }
        remaining, applied, rejected = gates.apply_waivers([finding], [waiver])
        self.assertEqual(["voice_source_density_zero"], [item.code for item in remaining.hard])
        self.assertEqual([], applied)
        self.assertEqual(["waiver_rejected"], [item.code for item in rejected])



    def test_sealed_band_controls_density_and_scope_override(self):
        caller_zero = {"speaker:ending_transform": [0.0, 0.0]}
        found, _summary = self._run(bands=caller_zero)
        self.assertNotIn("DENSITY_VERDICT", [item.code for item in found.hard])

        changed = _contract(bands={"all": {"ending_transform": [0.0, 0.0]}})
        found, _summary = self._run(
            contract=changed,
            bands={"speaker:ending_transform": [1.0, 1.0]},
        )
        self.assertIn("DENSITY_VERDICT", [item.code for item in found.hard])

        override = _contract(
            scope_overrides={
                "mode=normal|state=calm|form=base|arc=opening": {
                    "bands": {"ending_transform": [0.0, 0.0]}
                }
            }
        )
        rows = _observations()
        for row in rows:
            row.update({"mode": "normal", "state": "calm", "form": "base", "arc": "opening"})
        found, _summary = self._run(contract=override, observations=rows)
        self.assertIn("DENSITY_VERDICT", [item.code for item in found.hard])

    def test_missing_sealed_band_is_hard(self):
        contract = _contract(bands={})
        found, _summary = self._run(
            contract=contract,
            bands={"speaker:ending_transform": [1.0, 1.0]},
        )
        self.assertIn("voice_band_unsealed", [item.code for item in found.hard])

    def test_marker_sets_override_is_hard_and_sealed_value_wins(self):
        contract = _contract(
            required_markers=[r"sealed$"],
            marker_sets={"ending_transform": [r"sealed$"]},
        )
        rows = _observations("sealed")
        caller = {"speaker:ending_transform": [r"caller$"]}
        found, _summary = self._run(contract=contract, observations=rows, marker_sets=caller)
        self.assertIn("gate_input_contradicts_seal", [item.code for item in found.hard])
        self.assertNotIn("DENSITY_VERDICT", [item.code for item in found.hard])

        found, _summary = self._run(
            contract=contract,
            observations=rows,
            marker_sets={"speaker:ending_transform": [r"sealed$"]},
        )
        self.assertNotIn("gate_input_contradicts_seal", [item.code for item in found.hard])
        self.assertTrue(found.is_clean())

    def test_catalogue_markers_override_is_hard_and_sealed_value_wins(self):
        contract = _contract(
            required_markers=[r"own$"],
            marker_sets={"ending_transform": [r"own$"]},
            catalogue_markers={"sealed": [r"sealed$"]},
        )
        rows = _observations("sealed")
        found, _summary = self._run(
            contract=contract,
            observations=rows,
            catalogue_markers={"caller": [r"caller$"]},
        )
        self.assertIn("gate_input_contradicts_seal", [item.code for item in found.hard])
        self.assertIn("voice_invention_catalogue", [item.code for item in found.hard])

        found, _summary = self._run(
            contract=contract,
            observations=rows,
            catalogue_markers={"sealed": [r"sealed$"]},
        )
        self.assertNotIn("gate_input_contradicts_seal", [item.code for item in found.hard])
        self.assertIn("voice_invention_catalogue", [item.code for item in found.hard])

    def test_review_decisions_override_is_hard_and_sealed_value_wins(self):
        contract = _contract(review_decisions={"speaker:쨩": "sealed review"})
        rows = _observations("말쨩", count=config.NOVELTY_RECURRENCE_K)
        for row in rows:
            row["sentence_final"] = "쨩"
        found, summary = self._run(
            contract=contract,
            observations=rows,
            review_decisions={"speaker:쨩": "caller review"},
        )
        self.assertIn("gate_input_contradicts_seal", [item.code for item in found.hard])
        self.assertEqual("triaged", summary["character-corpus"]["review_queue"][0]["status"])
        self.assertNotIn("voice_invention_review_untriaged", [item.code for item in found.hard])

        found, summary = self._run(
            contract=contract,
            observations=rows,
            review_decisions={"speaker:쨩": "sealed review"},
        )
        self.assertNotIn("gate_input_contradicts_seal", [item.code for item in found.hard])
        self.assertEqual("triaged", summary["character-corpus"]["review_queue"][0]["status"])

    def test_base_register_whitelist_is_a_target_adapter_boundary(self):
        rows = _observations("말쨩", count=config.NOVELTY_RECURRENCE_K)
        for row in rows:
            row["sentence_final"] = "쨩"
        found, summary = self._run(
            observations=rows, base_register_whitelist=[r"쨩$"]
        )
        self.assertNotIn("gate_input_contradicts_seal", [item.code for item in found.hard])
        self.assertEqual([], summary["character-corpus"]["review_queue"])

    def test_anchored_markers_use_unit_surface_and_bad_raw_observations_are_hard(self):
        delimited = _observations('"픽"')
        found, _summary = self._run(observations=delimited, profile=self.profile)
        self.assertTrue(found.is_clean())

        absent = _observations('"끝다"')
        found, _summary = self._run(observations=absent, profile=self.profile)
        self.assertIn("voice_required_marker_absent", [item.code for item in found.hard])

        found, _summary = self._run(observations=delimited)
        self.assertIn("voice_observation_unnormalisable", [item.code for item in found.hard])

    def test_obsolete_waiver_is_report_only_but_nonwaivable_presence_is_rejected(self):
        contract = _contract()
        obsolete = {
            "id": "obsolete-density",
            "category": "policy_density",
            "contract_hash": gates.contract_hash(contract),
            "reason": "corrected in this revision",
            "waived_codes": ["DENSITY_VERDICT"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-29T00:00:00Z",
            "stale": False,
        }
        found, _summary = self._run(waivers=[obsolete])
        reports = [item for item in found.reported if item.code == "waiver_obsolete"]
        self.assertEqual(["report"], [item.severity for item in reports])
        self.assertIn("can be retired", reports[0].detail)
        self.assertTrue(found.is_clean())

        presence = gates.bind_finding(
            findings.hard("voice_required_marker_absent", "fixture loss"), contract
        )
        hostile = dict(obsolete, id="presence-waiver", waived_codes=["voice_required_marker_absent"])
        remaining, applied, rejected = gates.apply_waivers([presence], [hostile])
        self.assertEqual([], applied)
        self.assertEqual(["voice_required_marker_absent"], [item.code for item in remaining.hard])
        self.assertEqual(["waiver_rejected"], [item.code for item in rejected])
    def test_gate_hard_findings_have_reachability_cases(self):
        path = os.path.join(config.repo_root(), "hancharacter", "gates.py")
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read(), filename=path)
        emitted = {
            node.args[0].value
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "findings"
            and node.func.attr == "hard"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        }
        covered = {
            "waiver_rejected",
            "voice_invention_catalogue",
            "voice_invention_review_untriaged",
            "voice_density_source_artifact_absent",
            "voice_enforcement_inert",
            "contract_source_measurement_changed",
            "gate_not_run",
            "voice_density_target_scenes_absent",
            "voice_forbidden_marker_present",
            "voice-narration-clean",
            "voice_exclusivity",
            "attribution_t2_confirmed",
            "contracts_empty",
            "contract_seal_missing",
            "voice_observations_empty",
            "contract_voice_drop_ledger_absent",
            "contract_length_infeasible",
            "voice_source_density_zero",
            "voice_required_marker_absent",
            "voice_band_unsealed",
            "gate_input_contradicts_seal",
            "voice_observation_unnormalisable",
        }
        self.assertEqual(covered, emitted)


if __name__ == "__main__":
    unittest.main()
