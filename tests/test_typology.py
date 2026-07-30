import json
import os
import shutil
import tempfile
import unittest

from hancharacter import config, schemas, typology


class CatalogueTests(unittest.TestCase):
    def test_every_shipped_type_and_realisation_resolves_and_validates(self):
        types = typology.load_types()
        self.assertTrue(types)
        for type_id, row in sorted(types.items()):
            with self.subTest(type_id=type_id):
                self.assertEqual([], schemas.validate("type", row))
                self.assertEqual(type_id, row["id"])
        realisations = typology.load_realisations("ko")
        self.assertTrue(realisations)
        for realisation_id, row in sorted(realisations.items()):
            with self.subTest(realisation_id=realisation_id):
                self.assertEqual([], schemas.validate("realisation", row))
                self.assertEqual(realisation_id, row["id"])

    def test_every_seed_type_is_present_and_has_a_korean_realisation(self):
        types = typology.load_types()
        realised = {r["type_id"] for r in typology.load_realisations("ko").values()}
        for type_id in typology.SEED_TYPE_IDS:
            with self.subTest(type_id=type_id):
                self.assertIn(type_id, types)
                self.assertIn(type_id, realised)

    def test_exactly_one_seed_type_is_english_sourced(self):
        """R6: measure/en.py must be load-bearing, not decorative."""
        types = typology.load_types()
        english = [
            t for t in typology.SEED_TYPE_IDS if types[t]["source_lang"] == "en"
        ]
        self.assertEqual(["en_eye_dialect_fleur"], english)

    def test_catalogue_version_is_declared(self):
        self.assertTrue(typology.catalogue_version())

    def test_probe_corpora_are_present_for_every_declared_source_language(self):
        langs = {row["source_lang"] for row in typology.load_types().values()}
        for lang in sorted(langs | {"ko"}):
            with self.subTest(lang=lang):
                self.assertTrue(typology.load_probe(lang))


class ResolutionTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="hc-typology-")
        os.makedirs(os.path.join(self.root, "types"))
        with open(os.path.join(self.root, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("test\n")
        self.addCleanup(shutil.rmtree, self.root, True)

    def _write(self, artifact_id, payload):
        payload = dict(payload)
        payload["id"] = artifact_id
        with open(
            os.path.join(self.root, "types", "%s.json" % artifact_id),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(payload, fh, ensure_ascii=False)

    def _base(self, **over):
        row = {
            "axis": "ending_transform",
            "source_lang": "ja",
            "source_marker": "~x",
            "pattern_set": [r"x$"],
            "provenance": {"origin": "character", "notes": "fixture"},
        }
        row.update(over)
        return row

    def test_preset_and_overrides_merge_and_keep_the_deriving_id(self):
        self._write("base_type", self._base())
        self._write(
            "derived_type",
            {"preset": "base_type", "overrides": {"pattern_set": [r"y$"]}},
        )
        types = typology.load_types(self.root)
        self.assertEqual([r"y$"], types["derived_type"]["pattern_set"])
        # Inherited from the preset rather than restated on disk.
        self.assertEqual("~x", types["derived_type"]["source_marker"])
        # Identity is the deriving row's own, so the two remain separate join keys.
        self.assertEqual("derived_type", types["derived_type"]["id"])

    def test_a_list_override_replaces_rather_than_extends(self):
        """Extending would widen a marker a derivation meant to narrow."""
        self._write("base_type", self._base(pattern_set=[r"x$", r"z$"]))
        self._write(
            "derived_type",
            {"preset": "base_type", "overrides": {"pattern_set": [r"y$"]}},
        )
        types = typology.load_types(self.root)
        self.assertEqual([r"y$"], types["derived_type"]["pattern_set"])

    def test_a_preset_cycle_is_an_error(self):
        self._write("a_type", {"preset": "b_type", "overrides": {"source_marker": "~a"}})
        self._write("b_type", {"preset": "a_type", "overrides": {"source_marker": "~b"}})
        with self.assertRaises(typology.CatalogueError) as caught:
            typology.load_types(self.root)
        self.assertIn("cycle", str(caught.exception))

    def test_a_dangling_preset_is_an_error(self):
        self._write("only_type", {"preset": "absent_type", "overrides": {"source_marker": "~a"}})
        with self.assertRaises(typology.CatalogueError):
            typology.load_types(self.root)

    def test_a_filename_that_disagrees_with_the_id_is_an_error(self):
        row = self._base()
        row["id"] = "declared_id"
        with open(
            os.path.join(self.root, "types", "file_stem.json"), "w", encoding="utf-8"
        ) as fh:
            json.dump(row, fh)
        with self.assertRaises(typology.CatalogueError) as caught:
            typology.load_types(self.root)
        self.assertIn("filename stem", str(caught.exception))

    def test_a_derivation_resolving_to_an_incomplete_artifact_is_rejected(self):
        """The resolved artifact is what faces the full schema."""
        self._write("base_type", self._base())
        # `axis` is not a valid value, so the merged artifact must fail even though
        # the derivation row itself is well-formed.
        self._write(
            "derived_type",
            {"preset": "base_type", "overrides": {"axis": "not_an_axis"}},
        )
        with self.assertRaises(typology.CatalogueError) as caught:
            typology.load_types(self.root)
        self.assertIn("after resolution", str(caught.exception))

    def test_an_empty_catalogue_directory_is_an_error(self):
        with self.assertRaises(typology.CatalogueError):
            typology.load_types(self.root)


class SimilarityTests(unittest.TestCase):
    def test_jaccard_is_the_exact_ratio(self):
        # |{a,b} & {b,c}| / |{a,b,c}| = 1/3
        self.assertAlmostEqual(1 / 3, typology.jaccard({"a", "b"}, {"b", "c"}))
        self.assertEqual(1.0, typology.jaccard({"a"}, {"a"}))
        self.assertEqual(0.0, typology.jaccard({"a"}, {"b"}))
        self.assertEqual(0.25, typology.jaccard({"a", "b"}, {"b", "c", "d"}))

    def test_two_unmatchable_pattern_sets_are_not_called_distinct(self):
        """Empty/empty means the probe cannot separate them, not that they differ."""
        self.assertEqual(1.0, typology.jaccard(frozenset(), frozenset()))

    def test_bands_overlap_counts_touching_endpoints(self):
        self.assertTrue(typology.bands_overlap([0.1, 0.5], [0.5, 0.9]))
        self.assertTrue(typology.bands_overlap([0.1, 0.9], [0.2, 0.3]))
        self.assertFalse(typology.bands_overlap([0.1, 0.4], [0.5, 0.9]))
        self.assertFalse(typology.bands_overlap([0.5, 0.9], [0.1, 0.4]))

    def test_chuunibyou_and_otaku_copula_are_distinguishable(self):
        """Named acceptance clause: these two must not collapse into one type."""
        types = typology.load_types()
        probe = typology.load_probe("ja")
        left = typology.matched_markers(
            types["ja_chuunibyou_frame"]["pattern_set"], "ja", probe=probe
        )
        right = typology.matched_markers(
            types["ja_otaku_copula"]["pattern_set"], "ja", probe=probe
        )
        self.assertTrue(left, "chuunibyou frame matches no probe row")
        self.assertTrue(right, "otaku copula matches no probe row")
        similarity = typology.jaccard(left, right)
        self.assertLess(similarity, config.JACCARD_DISTINCT_MAX, similarity)

    def test_no_shipped_pattern_set_matches_nothing(self):
        """A pattern that cannot match is a check that can never fail."""
        empty = []
        for type_id, row in sorted(typology.load_types().items()):
            if not typology.matched_markers(row["pattern_set"], row["source_lang"]):
                empty.append(type_id)
        for realisation_id, row in sorted(typology.load_realisations("ko").items()):
            if not typology.matched_markers(row.get("pattern_set") or [], "ko"):
                empty.append(realisation_id)
        self.assertEqual([], empty)

    def test_identical_patterns_with_overlapping_bands_are_indistinguishable(self):
        items = {
            "left": {
                "axis": "ending_transform",
                "pattern_set": [r"냥[.!?…]*$"],
                "density_band_default": [0.2, 0.8],
            },
            "right": {
                "axis": "ending_transform",
                "pattern_set": [r"냥[.!?…]*$"],
                "density_band_default": [0.3, 0.9],
            },
        }
        found, compared = typology.distinguishability(items, "ko")
        self.assertEqual(1, compared)
        codes = [f.code for f in found]
        self.assertIn("typology_indistinguishable_pair", codes)
        self.assertTrue(all(f.severity == "hard" for f in found), codes)

    def test_a_merged_pair_stops_being_reported(self):
        """The lint must not keep punishing the merge it demanded."""
        items = {
            "left": {"pattern_set": [r"냥[.!?…]*$"], "density_band_default": [0.2, 0.8]},
            "right": {"pattern_set": [r"냥[.!?…]*$"], "density_band_default": [0.3, 0.9]},
        }
        found, _ = typology.distinguishability(
            items, "ko", raw_presets={"right": "left", "left": None}
        )
        self.assertEqual(
            [], [f for f in found if f.code == "typology_indistinguishable_pair"]
        )

    def test_the_plain_reading_of_the_plan_would_force_a_spurious_merge(self):
        """Why the implemented rule is not the plan's literal conjunction.

        The plan says a pair is distinct iff Jaccard < 0.5 AND the bands do not
        overlap. This pair has Jaccard 0.0 -- as different as two markers can be --
        but overlapping bands, so the literal reading calls it indistinguishable
        and demands a merge. The implemented rule leaves it alone.
        """
        items = {
            "left": {"pattern_set": [r"냥[.!?…]*$"], "density_band_default": [0.2, 0.8]},
            "right": {
                "pattern_set": [r"지 말입니다[.!?…]*$"],
                "density_band_default": [0.3, 0.9],
            },
        }
        probe = typology.load_probe("ko")
        left = typology.matched_markers(items["left"]["pattern_set"], "ko", probe=probe)
        right = typology.matched_markers(items["right"]["pattern_set"], "ko", probe=probe)
        similarity = typology.jaccard(left, right)
        self.assertEqual(0.0, similarity)
        overlapping = typology.bands_overlap(
            items["left"]["density_band_default"],
            items["right"]["density_band_default"],
        )
        self.assertTrue(overlapping)
        literal_says_distinct = (
            similarity < config.JACCARD_DISTINCT_MAX and not overlapping
        )
        self.assertFalse(
            literal_says_distinct,
            "the literal AND-reading would force a merge on a pair with zero "
            "marker overlap, which is a lint firing on faithful work",
        )
        found, _ = typology.distinguishability(items, "ko")
        self.assertEqual(
            [], [f for f in found if f.code == "typology_indistinguishable_pair"]
        )

    def test_the_two_jimalimnida_realisations_are_a_declared_merge(self):
        """Two source markers legitimately share one Korean convention."""
        realisations = typology.load_realisations("ko")
        derived = realisations["ko_danakka_jimalimnida"]
        preset = realisations["ko_seumda_jimalimnida"]
        self.assertEqual(derived["target_realisation"], preset["target_realisation"])
        self.assertNotEqual(derived["type_id"], preset["type_id"])
        matched = typology.matched_markers(derived["pattern_set"], "ko")
        self.assertEqual(1.0, typology.jaccard(matched, typology.matched_markers(preset["pattern_set"], "ko")))
        # And the shipped catalogue does not report them, because the merge exists.
        self.assertEqual(
            [],
            [
                f
                for f in typology.lint().hard
                if f.code == "typology_indistinguishable_pair"
            ],
        )


class LintTests(unittest.TestCase):
    @staticmethod
    def _status():
        from hancharacter import measure

        return lambda lang: dict(measure.get_plugin(lang).AXES)

    def _axes(self, type_ids):
        return typology.resolve_axis_set(
            type_ids,
            "ko",
            axis_status=self._status(),
            measurable=config.MEASURABLE_AXIS_STATUSES,
        )

    def test_the_shipped_catalogue_lints_clean(self):
        result = typology.lint()
        self.assertEqual([], [f.detail for f in result.hard])

    def test_a_missing_catalogue_is_hard_rather_than_clean(self):
        root = tempfile.mkdtemp(prefix="hc-typology-absent-")
        shutil.rmtree(root)
        result = typology.lint(root)
        self.assertFalse(result.is_clean())
        self.assertIn("typology_catalogue_missing", [f.code for f in result.hard])

    def test_an_empty_catalogue_is_hard_rather_than_clean(self):
        root = tempfile.mkdtemp(prefix="hc-typology-empty-")
        self.addCleanup(shutil.rmtree, root, True)
        os.makedirs(os.path.join(root, "types"))
        with open(os.path.join(root, "VERSION"), "w", encoding="utf-8") as fh:
            fh.write("test\n")
        result = typology.lint(root)
        self.assertFalse(result.is_clean())

    def _contract(self, axes):
        return {
            "character_id": "x",
            "source_lang": "ja",
            "catalogue_version": typology.catalogue_version(),
            "axes": axes,
        }

    def test_resolve_axis_set_does_not_invent_a_corpus_digest(self):
        """The digest binds a marker to sealed evidence; P1 cannot supply one."""
        axes = self._axes(["ja_hao_gozaru"])
        self.assertEqual(1, len(axes))
        self.assertNotIn("corpus_digest", axes[0])
        # The SPECIFIC error, not merely a non-empty list: asserting truthiness
        # would pass even with the digest present, so it would not test the
        # property it is named for.
        self.assertIn(
            "contract.axes[0]: missing required key 'corpus_digest'",
            schemas.validate("contract", self._contract(axes)),
        )

    def test_the_documented_seam_actually_works(self):
        """Adding only `corpus_digest` must be enough, or the docstring lies.

        An extra convenience key would make the documented instruction impossible
        and would tempt a later phase to widen the closed contract schema.
        """
        axes = self._axes(["ja_hao_gozaru", "ja_elder_lexicon"])
        self.assertEqual({"axis", "marker", "pattern_set"}, set(axes[0]))
        sealed = [dict(entry, corpus_digest="a" * 64) for entry in axes]
        self.assertEqual([], schemas.validate("contract", self._contract(sealed)))

    def test_resolve_axis_set_refuses_a_type_that_cannot_be_sealed(self):
        """Sealing an unmeasurable marker yields a gate that can never fire."""
        with self.assertRaises(typology.CatalogueError) as caught:
            self._axes(["ja_chuunibyou_frame"])
        self.assertIn("cannot be sealed", str(caught.exception))

    def test_sealing_requires_the_axis_check_to_be_supplied(self):
        """A guard that defaults to off is not a guard."""
        with self.assertRaises(TypeError):
            typology.resolve_axis_set(["ja_hao_gozaru"], "ko")

    def test_resolve_axis_set_refuses_two_types_with_identical_patterns(self):
        with self.assertRaises(typology.CatalogueError) as caught:
            self._axes(["ja_seumda_ssu", "ja_seumda_ssu"])
        self.assertIn("identical pattern sets", str(caught.exception))

    def test_resolve_axis_set_rejects_an_unknown_type(self):
        with self.assertRaises(typology.CatalogueError):
            self._axes(["not_a_type"])


if __name__ == "__main__":
    unittest.main()
