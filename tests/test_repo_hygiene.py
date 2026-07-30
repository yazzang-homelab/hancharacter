"""Repository hygiene gates.

These are cheap and they pin six promises the project makes out loud:

1. `hancharacter` never imports a host localisation pipeline. Composition with
   one is a separately approved milestone; if that dependency ever creeps in,
   the standalone claim becomes false silently.
2. The working name used during planning is gone. A half-renamed tree is how a
   package ends up shipping two identities.
3. No third-party runtime dependency. Every gate verdict must be reproducible on
   a bare interpreter, so an import of something not in the standard library is
   a supply-chain surface the doctrine does not accept.
4. No game text, script dumps, or font binaries inside the repo.
5. An in-package import cannot be optional, because optionality turns proof
   failures into silent skips.
6. The external corpus's documented availability guard is the only test skip;
   a new skip can silently evade proof.
"""
import json
import ast
import os
import sys
import unittest

from hancharacter import config, schemas

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PKG = os.path.join(ROOT, "hancharacter")

# Modules the project is allowed to import at runtime. Anything else is either a
# third-party dependency or a host-pipeline import.
STDLIB_ALLOW = {
    "argparse", "ast", "base64", "collections", "contextlib", "copy", "csv",
    "dataclasses", "datetime", "difflib", "enum", "fnmatch", "functools",
    "glob", "hashlib", "html", "importlib", "io", "itertools", "json", "math",
    "os", "pathlib",
    "posixpath", "random", "re", "shutil", "statistics", "string", "subprocess",
    "sys", "tempfile", "textwrap", "time", "types", "typing", "unicodedata",
    "unittest", "urllib", "uuid", "warnings", "xml", "zipfile",
}

FORBIDDEN_TEXT = (
    "voice" + "lock",  # the planning-era working name (R7)
)

BINARY_SUFFIXES = (
    ".cia", ".3ds", ".nsp", ".xci", ".bcfnt", ".ttf", ".otf", ".mbin", ".bin",
)


def _py_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", ".venv", "e2e-out"}]
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(base, name)


def _all_files(root):
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in {"__pycache__", ".git", ".venv", "e2e-out"}]
        for name in files:
            yield os.path.join(base, name)


class TestNoHostPipelineImport(unittest.TestCase):
    def test_no_hanpatch_import_anywhere(self):
        offenders = []
        for path in _py_files(ROOT):
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            tree = ast.parse(src, filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name.split(".")[0] == "hanpatch":
                            offenders.append((path, node.lineno))
                elif isinstance(node, ast.ImportFrom):
                    if (node.module or "").split(".")[0] == "hanpatch":
                        offenders.append((path, node.lineno))
        self.assertEqual([], offenders, "hancharacter must not import a host pipeline")

    def test_no_sys_path_injection_of_a_host_tree(self):
        # An import-direction test is worthless if a module reaches the host by
        # appending its directory to sys.path instead of importing it by name.
        offenders = []
        # Scoped to shipped package code: a test harness may legitimately put
        # the repo root on sys.path, but runtime code never needs to.
        for path in _py_files(PKG):
            with open(path, "r", encoding="utf-8") as fh:
                src = fh.read()
            if "sys.path.insert" in src or "sys.path.append" in src:
                offenders.append(path)
        self.assertEqual([], offenders, "no module may inject a path to reach a host tree")


class TestNoPlanningEraName(unittest.TestCase):
    def test_forbidden_identifiers_absent(self):
        hits = []
        for path in _all_files(ROOT):
            if path.endswith(BINARY_SUFFIXES) or os.path.basename(path) == os.path.basename(__file__):
                continue
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    text = fh.read().lower()
            except (UnicodeDecodeError, IsADirectoryError):
                continue
            for needle in FORBIDDEN_TEXT:
                if needle in text:
                    hits.append((os.path.relpath(path, ROOT), needle))
        self.assertEqual([], hits, "the planning-era working name must not ship")


class TestStdlibOnly(unittest.TestCase):
    def test_runtime_imports_are_stdlib_or_local(self):
        offenders = []
        for path in _py_files(PKG):
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import inside the package
                        continue
                    mods = [(node.module or "").split(".")[0]]
                for mod in mods:
                    if mod in ("hancharacter", ""):
                        continue
                    if mod not in STDLIB_ALLOW:
                        offenders.append((os.path.relpath(path, ROOT), mod))
        self.assertEqual([], offenders, "runtime code must stay standard-library only")

class TestNoSkippableProofs(unittest.TestCase):
    def test_in_package_imports_are_not_guarded_by_import_error(self):
        offenders = []
        for path in _py_files(PKG):
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for guarded in ast.walk(tree):
                if not isinstance(guarded, ast.Try):
                    continue
                catches_import_error = any(
                    isinstance(handler.type, ast.Name) and handler.type.id == "ImportError"
                    or isinstance(handler.type, ast.Tuple)
                    and any(
                        isinstance(error, ast.Name) and error.id == "ImportError"
                        for error in handler.type.elts
                    )
                    for handler in guarded.handlers
                )
                if not catches_import_error:
                    continue
                for statement in guarded.body:
                    for imported in ast.walk(statement):
                        if isinstance(imported, ast.Import):
                            in_package = any(
                                alias.name == "hancharacter"
                                or alias.name.startswith("hancharacter.")
                                for alias in imported.names
                            )
                        elif isinstance(imported, ast.ImportFrom):
                            module = imported.module or ""
                            in_package = bool(imported.level) or (
                                module == "hancharacter"
                                or module.startswith("hancharacter.")
                            )
                        else:
                            continue
                        if in_package:
                            offenders.append(
                                (os.path.relpath(path, ROOT), imported.lineno)
                            )
        self.assertEqual(
            [],
            offenders,
            "in-package imports must not become skippable proof dependencies",
        )

    def test_external_corpus_guard_is_the_only_skip_site(self):
        sites = []
        for path in _py_files(os.path.join(ROOT, "tests")):
            with open(path, "r", encoding="utf-8") as fh:
                tree = ast.parse(fh.read(), filename=path)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in {
                    "SkipTest", "skipIf", "skipUnless"
                }:
                    sites.append((os.path.relpath(path, ROOT), node))
                elif isinstance(node, ast.Name) and node.id in {
                    "SkipTest", "skipIf", "skipUnless"
                }:
                    sites.append((os.path.relpath(path, ROOT), node))
        # Asserted by REASON, not by count. The invariant that matters is that the
        # only thing permitted to skip a test is the absence of the external
        # read-only corpus; any other skip is a proof quietly switching itself off.
        # An earlier version asserted exactly one site and one file, which fired the
        # moment a second module legitimately needed the same guard -- a gate firing
        # on faithful work, which this project treats as broken as one that never
        # fires.
        self.assertTrue(sites, "the external-corpus guard must still exist")
        for path in sorted({p for p, _ in sites}):
            with self.subTest(path=path):
                with open(os.path.join(ROOT, path), encoding="utf-8") as handle:
                    source = handle.read()
                for chunk in source.split("SkipTest")[1:]:
                    self.assertIn(
                        "fixture",
                        chunk[:200],
                        "a skip may only guard the external fixture, and must say so",
                    )
                self.assertTrue(
                    "fixture_path()" in source,
                    "the guard must key on config.fixture_path(), so it cannot be "
                    "a skip for some other reason that merely says 'fixture'",
                )


class TestNoGameTextInRepo(unittest.TestCase):
    def test_no_container_or_font_binaries(self):
        hits = [
            os.path.relpath(p, ROOT)
            for p in _all_files(ROOT)
            if p.endswith(BINARY_SUFFIXES)
        ]
        self.assertEqual([], hits, "never vendor ROM, container, or font binaries")

    def test_no_vendored_source_script_dump(self):
        # The external fixture is read-only input referenced by path. A copy of
        # it inside the repo would be redistribution of somebody else's script.
        hits = []
        for path in _all_files(ROOT):
            name = os.path.basename(path)
            if name in {"text_src.json", "text_ko.json", "tm.json"}:
                hits.append(os.path.relpath(path, ROOT))
        self.assertEqual([], hits, "no host-pipeline script artifacts in the repo")

def _catalogue_files():
    """Every shipped catalogue artifact path, paired with the kind it must satisfy."""
    root = config.typology_root()
    groups = []
    types_dir = os.path.join(root, "types")
    if os.path.isdir(types_dir):
        for name in sorted(os.listdir(types_dir)):
            if name.endswith(".json"):
                groups.append(("type", os.path.join(types_dir, name), None))
    real_root = os.path.join(root, "realisations")
    if os.path.isdir(real_root):
        for target in sorted(os.listdir(real_root)):
            target_dir = os.path.join(real_root, target)
            if not os.path.isdir(target_dir):
                continue
            for name in sorted(os.listdir(target_dir)):
                if name.endswith(".json"):
                    groups.append(("realisation", os.path.join(target_dir, name), None))
    for kind, rel in (
        ("corpus_draft", "samples.draft.jsonl"),
        ("precedent", "precedents.jsonl"),
        ("human_confirm", "human_confirm.jsonl"),
        ("dialect_decision", "dialect_decisions.jsonl"),
    ):
        path = os.path.join(root, rel)
        if os.path.isfile(path):
            groups.append((kind, path, "jsonl"))
    for sub, kind in (("probe", "probe_row"), ("reviews", "corpus_review")):
        sub_dir = os.path.join(root, sub)
        if os.path.isdir(sub_dir):
            for name in sorted(os.listdir(sub_dir)):
                if name.endswith(".jsonl"):
                    groups.append((kind, os.path.join(sub_dir, name), "jsonl"))
    return groups


def _catalogue_records():
    """Yield ``(kind, path, index, obj)`` for every shipped catalogue record."""
    for kind, path, mode in _catalogue_files():
        with open(path, "r", encoding="utf-8") as fh:
            if mode == "jsonl":
                for index, line in enumerate(fh, start=1):
                    if line.strip():
                        yield kind, path, index, json.loads(line)
            else:
                yield kind, path, 0, json.load(fh)


class TestCatalogueHygiene(unittest.TestCase):
    """Integration guards over the shipped evidence catalogue.

    Deliberately separate from each module's own lint. A module lint proves the
    loader rejects a bad row; these prove that what is actually committed to this
    repository is clean, which is a different claim.
    """

    def setUp(self):
        self.root = config.typology_root()
        if not os.path.isdir(self.root):
            self.fail(
                "the evidence catalogue is missing at %s; P1 ships it, and a "
                "hygiene suite that passes because the data is absent is exactly "
                "the vacuous gate this project forbids" % self.root
            )

    def test_catalogue_is_not_empty(self):
        self.assertTrue(
            list(_catalogue_records()),
            "catalogue directory exists but ships no records to check",
        )

    def test_every_shipped_catalogue_record_validates(self):
        failures = []
        for kind, path, index, obj in _catalogue_records():
            errors = schemas.validate(kind, obj)
            if errors:
                where = os.path.relpath(path, ROOT)
                if index:
                    where = "%s:%d" % (where, index)
                failures.append("%s (%s): %s" % (where, kind, "; ".join(errors)))
        self.assertEqual([], failures)

    def test_quotation_ceilings_hold_on_shipped_rows(self):
        per_work = {}
        over_row = []
        mismatched = []
        for kind, path, index, obj in _catalogue_records():
            if kind not in ("corpus_draft", "corpus_sample"):
                continue
            quote = obj.get("quote") or ""
            where = "%s:%d" % (os.path.relpath(path, ROOT), index)
            if len(quote) != obj.get("quote_len"):
                mismatched.append(where)
            if len(quote) > config.QUOTE_MAX_CHARS_PER_ROW:
                over_row.append((where, len(quote)))
            per_work[obj.get("work")] = per_work.get(obj.get("work"), 0) + len(quote)
        self.assertEqual([], mismatched, "declared quote_len must equal len(quote)")
        self.assertEqual([], over_row, "per-row quotation ceiling breached")
        over_work = [
            (work, total)
            for work, total in sorted(per_work.items())
            if total > config.QUOTE_MAX_CHARS_PER_WORK
        ]
        self.assertEqual([], over_work, "per-work quotation cap breached")

    def test_no_shipped_quote_is_a_paste_of_the_external_fixture(self):
        """The read-only fixture is input by path; a quote of it is a copy of it.

        A row may legitimately cite the fixture, but only by declaring
        ``source.class == "fixture"``. Any other row whose quote appears verbatim
        in the external script is script text that entered this repository under a
        different label.
        """
        fixture = config.fixture_path()
        if not os.path.isfile(fixture):
            self.skipTest(
                "external corpus %s is unavailable; this is the single declared "
                "skip site for tests that require it" % fixture
            )
        with open(fixture, "r", encoding="utf-8") as fh:
            haystack = fh.read()
        leaked = []
        for kind, path, index, obj in _catalogue_records():
            if kind not in ("corpus_draft", "corpus_sample"):
                continue
            quote = obj.get("quote") or ""
            if (obj.get("source") or {}).get("class") == config.SOURCE_FIXTURE:
                continue
            # A short marker legitimately recurs in any Japanese text; only a run
            # long enough to be a passage is evidence of a paste.
            if len(quote) >= config.DUMP_NGRAM_TOKENS and quote in haystack:
                leaked.append("%s:%d" % (os.path.relpath(path, ROOT), index))
        self.assertEqual(
            [], leaked, "a non-fixture row quotes the external script verbatim"
        )

    def test_probe_corpus_is_authored_and_never_quoted(self):
        origins = set()
        count = 0
        for kind, path, index, obj in _catalogue_records():
            if kind == "probe_row":
                count += 1
                origins.add(obj.get("origin"))
        self.assertTrue(
            count,
            "no probe rows shipped; the distinguishability lint would have "
            "nothing to compare on",
        )
        self.assertEqual(
            {config.PROBE_ORIGIN_AUTHORED},
            origins,
            "probe rows must be authored, never quoted from a source work",
        )


def _valid_profile():
    """A minimal profile satisfying every required declaration.

    Spelled out here rather than loaded from disk so a test that mutates one key
    cannot accidentally inherit the shipped profile's unrelated choices.
    """
    return {
        "work": "unit_test",
        "voice_enforcement_mode": "voice_critical",
        "evidence_lang": "ko",
        "pivot_lang": "ko",
        "target_lang": "ko",
        "speaker_roles": {"frea1": "speaker"},
        "delimiters": {"ko": {"speech": [['"', '"']], "term": []}},
    }


class TestPackageImports(unittest.TestCase):
    def test_package_imports_clean(self):
        if ROOT not in sys.path:
            sys.path.insert(0, ROOT)
        import hancharacter  # noqa: F401
        from hancharacter import config

        self.assertEqual(0.70, config.COVERAGE_FLOOR_X)
        self.assertEqual(0.15, config.OUTER_TOL)
        self.assertEqual(20, config.MIN_UNITS_PER_SCOPE)
        self.assertEqual(5, config.MIN_SCENES_PER_BAND)
        self.assertEqual(0.10, config.DUAL_STD_WIDEN)
        self.assertEqual(3, config.NOVELTY_RECURRENCE_K)
        self.assertEqual(0.60, config.KAPPA_FLOOR)
        self.assertEqual(120, config.QUOTE_MAX_CHARS_PER_ROW)
        self.assertEqual(1000, config.QUOTE_MAX_CHARS_PER_WORK)

    def test_profile_rejects_undeclared_key(self):
        from hancharacter import config

        with self.assertRaises(ValueError):
            config.Profile(dict(_valid_profile(), typo_key=1))

    def test_scene_pattern_requires_a_capture_group_and_is_compiled(self):
        from hancharacter import config

        valid = _valid_profile()
        valid["scene_pattern"] = r"^(mes\d+)"
        self.assertEqual(
            "mes08", config.Profile(valid).scene_pattern.search("mes08_FM_004").group(1)
        )
        for pattern in (r"mes\d+", r"("):
            with self.subTest(pattern=pattern):
                invalid = _valid_profile()
                invalid["scene_pattern"] = pattern
                with self.assertRaisesRegex(ValueError, "scene_pattern"):
                    config.Profile(invalid)

    def test_profile_rejects_invalid_speaker_role_values(self):
        from hancharacter import config

        data = _valid_profile()
        data["speaker_roles"] = {"frea1": "speeker"}
        with self.assertRaisesRegex(ValueError, "frea1.*speeker"):
            config.Profile(data)
        data["speaker_roles"] = ["speaker"]
        with self.assertRaisesRegex(ValueError, "speaker_roles"):
            config.Profile(data)

    def test_profile_rejects_only_non_speaker_roles(self):
        from hancharacter import config

        data = _valid_profile()
        data["speaker_roles"] = {
            "metadata": config.ROLE_TERM,
            "system": config.ROLE_SYSTEM,
            "close": config.ROLE_CLOSE,
        }
        with self.assertRaisesRegex(ValueError, "at least one speaker role"):
            config.Profile(data)


    def test_profile_requires_every_declaration_it_would_otherwise_guess(self):
        """A guessed language or an empty role map silently unmeasures a character."""
        from hancharacter import config

        for key in config.PROFILE_REQUIRED:
            data = _valid_profile()
            data.pop(key)
            with self.assertRaisesRegex(ValueError, key):
                config.Profile(data)

    def test_profile_validators_agree(self):
        """`config.Profile` and the closed schema must never disagree about one file.

        Two validators for one artifact is how a profile comes to pass the loader
        every command uses while failing the schema nobody calls.
        """
        from hancharacter import config, schemas

        cases = {"valid": _valid_profile()}
        for key in config.PROFILE_REQUIRED:
            case = _valid_profile()
            case.pop(key)
            cases["missing_%s" % key] = case
        bad_role = _valid_profile()
        bad_role["speaker_roles"] = {"frea1": "speeker"}
        cases["bad_role_value"] = bad_role
        no_speaker_role = _valid_profile()
        no_speaker_role["speaker_roles"] = {"frea1": config.ROLE_TERM}
        cases["no_speaker_role"] = no_speaker_role
        cases["unknown_key"] = dict(_valid_profile(), typo_key=1)
        cases["underscore_note"] = dict(_valid_profile(), _note="not a declaration")
        cases["comment_key"] = dict(_valid_profile(), _comment="documentation")
        cases["bad_mode_value"] = dict(
            _valid_profile(), voice_enforcement_mode="voice-critical"
        )
        # The delimiter dimension is where a schema rule can exist while the loader
        # every command actually uses ignores it. Each shape below yields the silent
        # zero-span result the spine forbids, so both validators must reject all of
        # them or the agreement claim is decoration.
        for label, declaration in (
            ("delimiters_empty_map", {}),
            ("delimiters_missing_declared_language", {"en": {"speech": [['"', '"']], "term": []}}),
            ("delimiters_missing_speech_term", {"ko": {}}),
            ("delimiters_malformed_pair", {"ko": {"speech": [['"']], "term": []}}),
            ("delimiters_empty_speech", {"ko": {"speech": [], "term": []}}),
        ):
            case = _valid_profile()
            case["delimiters"] = declaration
            cases[label] = case

        for name, data in cases.items():
            with self.subTest(case=name):
                schema_ok = schemas.validate("profile", data) == []
                try:
                    config.Profile(data)
                    loader_ok = True
                except ValueError:
                    loader_ok = False
                self.assertEqual(
                    schema_ok,
                    loader_ok,
                    "schema and loader disagree on %r (schema_ok=%s loader_ok=%s)"
                    % (name, schema_ok, loader_ok),
                )

    def test_shipped_profile_satisfies_schema_validation(self):
        from hancharacter import schemas

        with open(os.path.join(ROOT, "profiles", "crimson_fixture.json"), encoding="utf-8") as handle:
            profile = json.load(handle)
        self.assertEqual([], schemas.validate("profile", profile))

    def test_profile_rejects_an_invalid_enforcement_mode_value(self):
        """Pin the loader's own mode branch, not merely the reject behaviour.

        The earlier version passed a profile missing every required key, so the
        required-key check raised first and the mode branch was never reached: the
        test would still have passed with that branch deleted. Matching the
        loader's distinctive wording keeps it pinned even though the closed schema
        would also reject this profile.
        """
        from hancharacter import config

        with self.assertRaisesRegex(ValueError, "must be one of"):
            config.Profile(dict(_valid_profile(), voice_enforcement_mode="voice-critical"))

    def test_shipped_fixture_profile_is_declared_and_dual_standard(self):
        from hancharacter import config

        prof = config.load_profile(os.path.join(ROOT, "profiles", "crimson_fixture.json"))
        self.assertEqual(config.MODE_PROSE_FIDELITY, prof.mode)
        self.assertTrue(prof.dual_standard)
        self.assertTrue(prof.is_speaker("lippi1"))
        self.assertFalse(prof.is_speaker("secondperson1"))
        self.assertEqual(config.ROLE_TERM, prof.role("keyword1"))
        self.assertEqual(config.ROLE_SYSTEM, prof.role("otherline2"))
        self.assertIsNone(prof.role("undeclared9"))


if __name__ == "__main__":
    unittest.main()
