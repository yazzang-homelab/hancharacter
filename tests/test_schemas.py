import copy
import unittest

from hancharacter import config

from hancharacter.schemas import KINDS, require, validate


DIGEST = "a" * 64


def valid_artifacts():
    return {
        "type": {
            "id": "ja-ending-nya",
            "axis": "ending_transform",
            "source_lang": "ja",
            "source_marker": "にゃ",
            "pattern_set": ["にゃ[。！？!?]*$"],
            "provenance": {"origin": "character", "notes": "Invented fixture type."},
        },
        "realisation": {
            "type_id": "ja-ending-nya",
            "id": "ko-nya-01",
            "source_lang": "ja",
            "target_lang": "ko",
            "source_marker": "にゃ",
            "target_realisation": "냥",
            "length_cost": {"model": "append", "value": 1},
            "precedents": ["prec-nya-01"],
            "density_band_default": [0.2, 0.8],
        },
        "contract": {
            "character_id": "sample-speaker",
            "source_lang": "ja",
            "catalogue_version": "2026.07",
            "axes": [
                {
                    "axis": "ending_transform",
                    "marker": "にゃ",
                    "pattern_set": ["にゃ[。！？!?]*$"],
                    "corpus_digest": DIGEST,
                }
            ],
        },
        "corpus_draft": {
            "id": "sample-01",
            "type_id": "ja-ending-nya",
            "axis": "ending_transform",
            "work": "invented-work",
            "producer": "producer-a",
            "quote": "Invented sample.",
            "quote_len": len("Invented sample."),
            "source": {
                "class": "fixture",
                "cite": "sample-01",
                "consulted_via": "fixture_file",
                "independent_key": "invented-fixture",
                "locator": "test fixture row",
            },
        },
        "corpus_review": {
            "sample_id": "sample-01",
            "reviewer": "reviewer-b",
            "verdict": "accept",
        },
        "corpus_sample": {
            "id": "sample-01",
            "type_id": "ja-ending-nya",
            "axis": "ending_transform",
            "work": "invented-work",
            "producer": "producer-a",
            "reviewer": "reviewer-b",
            "review2": "reviewer-c",
            "reviewer_verdicts": {"reviewer-b": "accept", "reviewer-c": "accept"},
            "verdict": "accept",
            "quote": "Invented sample.",
            "quote_len": len("Invented sample."),
            "source": {
                "class": "fixture",
                "cite": "sample-01",
                "consulted_via": "fixture_file",
                "independent_key": "invented-fixture",
                "locator": "test fixture row",
            },
        },
        "precedent": {
            "id": "prec-nya-01",
            "axis": "ending_transform",
            "type_id": "ja-ending-nya",
            "source_lang": "ja",
            "target_lang": "ko",
            "source_marker": "にゃ",
            "source_work": "invented-work",
            "target_realisation": "냥",
            "edition_channel": "community",
            "verdict": "adopted",
            "citation": "invented-work/sample-01",
        },
        "human_confirm": {
            "id": "confirm-01",
            "confirms": ["ja-ending-nya"],
            "scope": "Confirms the fixture type only, not any marker row beneath it.",
            "confirmed_by": "fixture-operator",
            "confirmed_at": "2026-07-29T00:00:00Z",
            "artifact_cite": "tests/test_schemas.py",
            "artifact_sha256": DIGEST,
        },
        "dialect_decision": {
            "id": "dialect-01",
            "source_dialect": "invented-source-dialect",
            "target_dialect": "invented-target-dialect",
            "work": "invented-work",
            "strategy": "flavour_lexicon",
            "reason": "Fixture ruling; no real dialect pair is decided here.",
            "decided_by": "fixture-operator",
            "decided_at": "2026-07-29T00:00:00Z",
            "decision_hash": "b" * 40,
        },
        "probe_row": {
            "id": "probe-ja-01",
            "lang": "ja",
            "text": "これは合成された検査文です。",
            "origin": "authored_synthetic",
            "markedness": "marked",
        },
        "graduation_report": {
            "catalogue_version": "2026.07",
            "generated_at": "2026-07-29T00:00:00Z",
            "types": [
                {
                    "type_id": "ja-ending-nya",
                    "stage": "observed",
                    "occurrences": 1,
                    "independent_sources": 1,
                    "e1e2_sources": 0,
                    "adopted_precedents": 0,
                    "unresolved_contradictions": 0,
                    "dual_review_agreeing": 1,
                    "human_confirms": 0,
                    "kappa": None,
                "kappa_downward_flips": 0,
                "source_evidence_ok": True,
                "source_evidence_unmet": [],
                    "unmet": ["occurrences 1 < 3"],
                }
            ],
        },
        "waiver": {
            "id": "waiver-01",
            "category": "coverage",
            "contract_hash": DIGEST,
            "reason": "Fixture waiver; bound to one seal and stale on any rebase.",
            "waived_codes": ["coverage_below_floor"],
            "granted_by": "fixture-operator",
            "granted_at": "2026-07-29T00:00:00Z",
        },
        "manifest": {
            "work": "invented-work",
            "catalogue_version": "2026.07",
            "artifacts": [{"kind": "contract", "id": "sample-speaker", "digest": DIGEST}],
        },
        "profile": {
            "work": "invented-work",
            "voice_enforcement_mode": "voice_critical",
            "evidence_lang": "ja",
            "pivot_lang": "en",
            "target_lang": "ko",
            "speaker_roles": {"sample-speaker": "speaker"},
            "delimiters": {
                "ja": {"speech": [["「", "」"]], "term": []},
                "en": {"speech": [["\"", "\""]], "term": []},
                "ko": {"speech": [["\"", "\""]], "term": []},
            },
        },
    }


class SchemaTests(unittest.TestCase):
    def test_each_kind_accepts_a_minimal_valid_instance(self):
        artifacts = valid_artifacts()
        self.assertEqual(tuple(artifacts), KINDS)
        for kind in KINDS:
            with self.subTest(kind=kind):
                self.assertEqual([], validate(kind, artifacts[kind]))
                require(kind, artifacts[kind])

    def test_each_kind_reports_missing_and_unknown_keys(self):
        required_key = {
            "type": "id",
            "realisation": "type_id",
            "contract": "character_id",
            "corpus_sample": "producer",
            "precedent": "axis",
            "human_confirm": "confirms",
            "dialect_decision": "decision_hash",
            "probe_row": "origin",
            "graduation_report": "types",
            "corpus_draft": "producer",
            "corpus_review": "verdict",
            "waiver": "waived_codes",
            "manifest": "work",
            "profile": "work",
        }
        # Every kind must be named here, so adding a kind without a deletion probe
        # cannot leave that kind's required-key enforcement untested.
        self.assertEqual(sorted(required_key), sorted(KINDS))
        for kind, artifact in valid_artifacts().items():
            with self.subTest(kind=kind, case="missing"):
                missing = copy.deepcopy(artifact)
                del missing[required_key[kind]]
                self.assertTrue(validate(kind, missing))
            with self.subTest(kind=kind, case="unknown"):
                unknown = copy.deepcopy(artifact)
                unknown["unexpected"] = True
                self.assertTrue(validate(kind, unknown))

    def test_type_requires_a_stated_origin_from_the_closed_vocabulary(self):
        artifact = valid_artifacts()["type"]
        artifact["provenance"] = {"origin": "vibes", "notes": "n"}
        self.assertIn(
            "type.provenance.origin: expected one of %s" % list(config.TYPE_ORIGINS),
            validate("type", artifact),
        )

    def test_type_overrides_without_a_preset_is_rejected(self):
        artifact = valid_artifacts()["type"]
        artifact["overrides"] = {"pattern_set": ["x$"]}
        self.assertIn(
            "type.overrides: meaningless without type.preset",
            validate("type", artifact),
        )

    def test_primary_evidence_may_not_be_claimed_from_a_mirror(self):
        """A mirror is not the work. This is the cheapest way to fake a floor."""
        artifact = valid_artifacts()["corpus_sample"]
        artifact["source"] = {
            "class": "primary",
            "cite": "https://example.invalid/mirror-of-something",
            "consulted_via": "mirror",
            "independent_key": "some-mirror",
            "locator": "mirrored page",
        }
        errors = validate("corpus_sample", artifact)
        self.assertTrue(
            any("a mirror or a search snippet is not the work itself" in e for e in errors),
            errors,
        )

    def test_secondary_evidence_may_not_be_claimed_from_hearsay(self):
        artifact = valid_artifacts()["corpus_sample"]
        artifact["source"] = {
            "class": "secondary",
            "cite": "A work cited by another work",
            "consulted_via": "cited_by",
            "independent_key": "cited-only",
            "locator": "cited page",
        }
        errors = validate("corpus_sample", artifact)
        self.assertTrue(any("hearsay" in e for e in errors), errors)

    def test_a_snippet_read_secondary_source_is_accepted(self):
        """The cross-check must not reject the provenance it exists to permit."""
        artifact = valid_artifacts()["corpus_sample"]
        artifact["source"] = {
            "class": "secondary",
            "cite": "Retrieved scholarship, read as a search result",
            "consulted_via": "search_snippet",
            "independent_key": "retrieved-scholarship",
            "locator": "retrieved page",
        }
        self.assertEqual([], validate("corpus_sample", artifact))

    def test_corpus_source_requires_an_independence_key(self):
        artifact = valid_artifacts()["corpus_sample"]
        del artifact["source"]["independent_key"]
        errors = validate("corpus_sample", artifact)
        self.assertTrue(any("independent_key" in e for e in errors), errors)

    def test_corpus_source_requires_a_passage_locator(self):
        """Independence counting and dump detection need different granularity.

        `independent_key` collapses mirrors and separate articles of one
        publication into one source, which is right for counting independence.
        Dump detection needs to know whether two rows quote the same PASSAGE, so
        the locator is required rather than optional: without it the reassembly
        check would treat four different articles as one page and report an
        honest, well-spread corpus as a transcription.
        """
        artifact = valid_artifacts()["corpus_sample"]
        del artifact["source"]["locator"]
        errors = validate("corpus_sample", artifact)
        self.assertIn("corpus_sample.source: missing required key 'locator'", errors)

    def test_producer_may_not_review_their_own_row(self):
        artifact = valid_artifacts()["corpus_sample"]
        artifact["producer"] = artifact["reviewer"]
        artifact["reviewer_verdicts"] = {
            artifact["reviewer"]: "accept",
            artifact["review2"]: "accept",
        }
        self.assertIn(
            "corpus_sample.reviewer: must differ from producer %r" % artifact["producer"],
            validate("corpus_sample", artifact),
        )

    def test_the_two_reviewers_must_be_distinct(self):
        artifact = valid_artifacts()["corpus_sample"]
        artifact["review2"] = artifact["reviewer"]
        artifact["reviewer_verdicts"] = {artifact["reviewer"]: "accept"}
        errors = validate("corpus_sample", artifact)
        self.assertIn("corpus_sample.review2: must differ from reviewer", errors)

    def test_reviewer_verdict_keys_must_be_the_declared_reviewers(self):
        artifact = valid_artifacts()["corpus_sample"]
        artifact["reviewer_verdicts"] = {"reviewer-b": "accept", "someone-else": "accept"}
        errors = validate("corpus_sample", artifact)
        self.assertTrue(
            any("must be exactly the declared reviewers" in e for e in errors), errors
        )

    def test_precedent_verdicts_are_not_the_corpus_review_vocabulary(self):
        """`accept` says a transcription is right; `adopted` says an edition shipped it."""
        artifact = valid_artifacts()["precedent"]
        artifact["verdict"] = "accept"
        self.assertIn(
            "precedent.verdict: expected one of %s" % list(config.PRECEDENT_VERDICTS),
            validate("precedent", artifact),
        )
        sample = valid_artifacts()["corpus_sample"]
        sample["verdict"] = "adopted"
        self.assertIn(
            "corpus_sample.verdict: expected one of %s" % list(config.REVIEW_VERDICTS),
            validate("corpus_sample", sample),
        )

    def test_precedent_may_not_contradict_itself(self):
        artifact = valid_artifacts()["precedent"]
        artifact["contradicts"] = [artifact["id"]]
        self.assertIn(
            "precedent.contradicts: must not contain the row's own id",
            validate("precedent", artifact),
        )

    def test_realisation_band_must_be_ordered_and_in_range(self):
        for band in ([0.8, 0.2], [-0.1, 0.5], [0.5, 1.4], [0.5], "0.5"):
            with self.subTest(band=band):
                artifact = valid_artifacts()["realisation"]
                artifact["density_band_default"] = band
                errors = validate("realisation", artifact)
                self.assertTrue(
                    any("density_band_default" in e for e in errors), (band, errors)
                )

    def test_realisation_precedent_list_may_not_be_empty(self):
        artifact = valid_artifacts()["realisation"]
        artifact["precedents"] = []
        errors = validate("realisation", artifact)
        self.assertTrue(any("realisation.precedents" in e for e in errors), errors)

    def test_ids_are_join_keys_and_reject_ambiguous_spellings(self):
        for bad in ("Sample-01", "sample 01", "sample/01", "", "-lead"):
            with self.subTest(bad=bad):
                artifact = valid_artifacts()["precedent"]
                artifact["id"] = bad
                errors = validate("precedent", artifact)
                self.assertTrue(any("precedent.id" in e for e in errors), (bad, errors))

    def test_graduation_report_rejects_canonical_with_unmet_criteria(self):
        artifact = valid_artifacts()["graduation_report"]
        artifact["types"][0]["stage"] = "canonical"
        errors = validate("graduation_report", artifact)
        self.assertTrue(
            any("stage is canonical but unmet criteria are listed" in e for e in errors),
            errors,
        )

    def test_graduation_report_accepts_a_null_kappa_but_not_an_out_of_range_one(self):
        artifact = valid_artifacts()["graduation_report"]
        artifact["types"][0]["kappa"] = None
        self.assertEqual([], validate("graduation_report", artifact))
        artifact["types"][0]["kappa"] = 1.5
        errors = validate("graduation_report", artifact)
        self.assertTrue(any("kappa" in e for e in errors), errors)

    def test_probe_rows_may_not_carry_quoted_provenance(self):
        artifact = valid_artifacts()["probe_row"]
        artifact["origin"] = "primary"
        self.assertIn(
            "probe_row.origin: expected one of %s" % list(config.PROBE_ORIGINS),
            validate("probe_row", artifact),
        )

    def test_timestamps_must_be_orderable_utc_instants(self):
        for bad in ("2026-07-29", "29/07/2026", "2026-07-29T00:00:00+09:00", ""):
            with self.subTest(bad=bad):
                artifact = valid_artifacts()["human_confirm"]
                artifact["confirmed_at"] = bad
                errors = validate("human_confirm", artifact)
                self.assertTrue(
                    any("confirmed_at" in e for e in errors), (bad, errors)
                )

    def test_dialect_decision_hash_must_be_a_sha1(self):
        artifact = valid_artifacts()["dialect_decision"]
        artifact["decision_hash"] = "c" * 64
        errors = validate("dialect_decision", artifact)
        self.assertTrue(any("decision_hash" in e for e in errors), errors)

    def test_profile_dialect_strategy_is_a_closed_vocabulary(self):
        profile = valid_artifacts()["profile"]
        profile["dialect_policy"] = {"target_strategy": "just_wing_it"}
        self.assertIn(
            "profile.dialect_policy.target_strategy: expected one of %s"
            % list(config.DIALECT_STRATEGIES),
            validate("profile", profile),
        )

    def test_realisation_requires_length_cost(self):
        artifact = valid_artifacts()["realisation"]
        del artifact["length_cost"]
        self.assertIn("realisation: missing required key 'length_cost'", validate("realisation", artifact))

    def test_profile_requires_delimiters(self):
        profile = valid_artifacts()["profile"]
        del profile["delimiters"]
        self.assertIn(
            "profile: missing required key 'delimiters'",
            validate("profile", profile),
        )

    def test_profile_requires_delimiters_for_every_profile_language(self):
        profile = valid_artifacts()["profile"]
        pivot_lang = profile["pivot_lang"]
        del profile["delimiters"][pivot_lang]
        self.assertIn(
            "profile.delimiters: missing declaration for pivot_lang %r" % pivot_lang,
            validate("profile", profile),
        )

    def test_profile_requires_non_empty_speech_delimiters(self):
        profile = valid_artifacts()["profile"]
        pivot_lang = profile["pivot_lang"]
        profile["delimiters"][pivot_lang]["speech"] = []
        self.assertIn(
            "profile.delimiters.%s.speech: expected a non-empty list of delimiter pairs"
            % pivot_lang,
            validate("profile", profile),
        )

    def test_pattern_sets_reject_uncompilable_patterns(self):
        for kind, artifact, path in (
            ("type", valid_artifacts()["type"], "pattern_set"),
            ("contract", valid_artifacts()["contract"], "axes"),
        ):
            with self.subTest(kind=kind):
                if path == "pattern_set":
                    artifact[path] = ["("]
                else:
                    artifact[path][0]["pattern_set"] = ["("]
                self.assertTrue(
                    any("invalid regular expression" in error for error in validate(kind, artifact))
                )


    def test_pattern_sets_reject_nested_quantifiers_but_allow_normal_groups(self):
        for pattern in ("(a+)+$", "(a*)*$", "(a+)*$", "(?:x{2,})+$"):
            with self.subTest(pattern=pattern):
                artifact = valid_artifacts()["type"]
                artifact["pattern_set"] = [pattern]
                self.assertTrue(
                    any("nested quantified group" in error for error in validate("type", artifact))
                )
        artifact = valid_artifacts()["type"]
        artifact["pattern_set"] = ["(?:だな|だよ)$"]
        self.assertEqual([], validate("type", artifact))

    def test_profile_requires_at_least_one_speaker_role_in_both_validators(self):
        profile = valid_artifacts()["profile"]
        profile["speaker_roles"] = {
            "term-label": config.ROLE_TERM,
            "system-label": config.ROLE_SYSTEM,
            "close-label": config.ROLE_CLOSE,
        }
        errors = validate("profile", profile)
        self.assertTrue(any("at least one speaker role" in error for error in errors))
        with self.assertRaisesRegex(ValueError, "at least one speaker role"):
            config.Profile(profile)
    def test_contract_requires_catalogue_version_and_resolved_axes(self):
        without_version = valid_artifacts()["contract"]
        del without_version["catalogue_version"]
        self.assertIn(
            "contract: missing required key 'catalogue_version'",
            validate("contract", without_version),
        )

        reference_only = valid_artifacts()["contract"]
        del reference_only["axes"]
        reference_only["type_id"] = "ja-ending-nya"
        errors = validate("contract", reference_only)
        self.assertIn("contract: missing required key 'axes'", errors)
        self.assertIn("contract: unknown key 'type_id'", errors)

    def test_precedent_rejects_each_missing_join_column(self):
        precedent = valid_artifacts()["precedent"]
        for join_column in (
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
        ):
            with self.subTest(join_column=join_column):
                incomplete = copy.deepcopy(precedent)
                del incomplete[join_column]
                self.assertTrue(validate("precedent", incomplete))

    def test_corpus_quote_length_is_recomputed(self):
        sample = valid_artifacts()["corpus_sample"]
        sample["quote_len"] += 1
        self.assertIn(
            "corpus_sample.quote_len: must equal len(quote)",
            validate("corpus_sample", sample),
        )


class DelimiterCoherenceTests(unittest.TestCase):
    """A delimiter declaration must be able to mean what its author intends.

    Two combinations are incoherent rather than merely unusual, and an incoherent
    declaration that validates is worse than one that fails: it silently decides by
    scan order or reclassifies every quoted span as speech.
    """

    def _profile(self):
        return {
            "work": "coherence",
            "voice_enforcement_mode": "voice_critical",
            "evidence_lang": "ko",
            "pivot_lang": "ko",
            "target_lang": "ko",
            "speaker_roles": {"speaker1": "speaker"},
            "delimiters": {
                "ko": {
                    "speech": [['"', '"']],
                    "term": [["\u300c", "\u300d"]],
                    "speech_is_positional": False,
                }
            },
        }

    def test_non_positional_without_term_delimiters_is_rejected(self):
        data = self._profile()
        data["delimiters"]["ko"]["term"] = []
        errors = validate("profile", data)
        self.assertTrue(any("speech_is_positional" in e for e in errors), errors)

    def test_pair_declared_as_both_speech_and_term_is_rejected(self):
        data = self._profile()
        data["delimiters"]["ko"]["term"] = [['"', '"']]
        errors = validate("profile", data)
        self.assertTrue(any("both speech and term" in e for e in errors), errors)

    def test_coherent_declaration_is_accepted(self):
        self.assertEqual([], validate("profile", self._profile()))
