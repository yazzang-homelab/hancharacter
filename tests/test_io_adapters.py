import hashlib

import json
import os
import re
import tempfile
import unittest
import zipfile

from hancharacter import attribution, cli, config, findings, gates, io_adapters, segment, tag_grammar
from hancharacter.measure import pattern_match




ROOT = config.repo_root()
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
PROFILE_PATH = os.path.join(ROOT, "profiles", "crimson_fixture.json")
REQUIRED = {
    "key",
    "evidence",
    "pivot",
    "evidence_surface",
    "pivot_surface",
    "evidence_lang",
    "pivot_lang",
    "tag_grammar",
}



class IOAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.profile = config.load_profile(PROFILE_PATH)
        data = json.loads(cls.profile.to_json())
        data["csv_speaker_column"] = "speaker"
        cls.csv_profile = config.Profile(data)

    def fixture(self, name):
        return os.path.join(FIXTURES, name)

    @staticmethod
    def write_epub(path, paragraphs):
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr(
                "META-INF/container.xml",
                "<container><rootfiles><rootfile full-path=\"OEBPS/content.opf\"/></rootfiles></container>",
            )
            archive.writestr(
                "OEBPS/content.opf",
                "<package><manifest><item id=\"chapter\" href=\"chapter.xhtml\"/>"
                "</manifest><spine><itemref idref=\"chapter\"/></spine></package>",
            )
            archive.writestr(
                "OEBPS/chapter.xhtml",
                "<html><body>%s</body></html>" % "".join("<p>%s</p>" % paragraph for paragraph in paragraphs),
            )

    def assert_hard_failure(self, operation):
        with self.assertRaises((io_adapters.AdapterError, tag_grammar.TagGrammarError)) as raised:
            operation()
        self.assertEqual("hard", raised.exception.finding.severity)
        self.assertEqual((raised.exception.finding,), raised.exception.findings)

    def assert_normalised(self, rows, fmt):
        self.assertTrue(rows)
        self.assertEqual(fmt, rows.format)
        for row in rows:
            self.assertTrue(REQUIRED.issubset(row), row)
            self.assertEqual(fmt, row["tag_grammar"])
            self.assertIsInstance(row["evidence_surface"], str)
            self.assertIsInstance(row["pivot_surface"], str)


    def test_every_text_fixture_dispatches_to_the_normalised_shape(self):
        cases = (
            ("sample.txt", "plain_text", self.profile),
            ("sample.json", "json", self.profile),
            ("sample.csv", "csv", self.csv_profile),
            ("sample.po", "po", self.profile),
            ("sample.srt", "srt", self.profile),
            ("sample.vtt", "vtt", self.profile),
            ("sample.ass", "ass", self.profile),
            ("sample.xlf", "xliff", self.profile),
        )
        for name, fmt, profile in cases:
            with self.subTest(fmt=fmt):
                self.assert_normalised(io_adapters.load(self.fixture(name), profile=profile), fmt)

    def test_timed_formats_have_exact_float_seconds(self):
        srt = io_adapters.read_srt(self.fixture("sample.srt"), profile=self.profile)
        vtt = io_adapters.read_vtt(self.fixture("sample.vtt"), profile=self.profile)
        ass = io_adapters.read_ass(self.fixture("sample.ass"), profile=self.profile)
        self.assertEqual((1.5, 3.25), (srt[0]["start"], srt[0]["end"]))
        self.assertEqual((2.0, 4.5), (vtt[0]["start"], vtt[0]["end"]))
        self.assertEqual((3.25, 5.75), (ass[0]["start"], ass[0]["end"]))
        self.assertEqual("frea1", ass[0]["speaker"])
        for rows in (srt, vtt, ass):
            self.assertEqual(len(rows), io_adapters.load_report(rows, rows.format)["with_timing"])


    def test_authored_po_adapter_row_reaches_a_gate_verdict(self):
        profile = config.Profile(
            {
                "work": "adapter-spine-fixture",
                "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
                "evidence_lang": "ja",
                "pivot_lang": "ko",
                "target_lang": "ko",
                "speaker_roles": {"hero": config.ROLE_SPEAKER, "close": config.ROLE_CLOSE},
                "delimiters": {
                    "ja": {"speech": [["「", "」"]], "term": []},
                    "ko": {
                        "speech": [['"', '"']],
                        "term": [["「", "」"]],
                        "speech_is_positional": False,
                    },
                },
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "authored.po")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    'msgctxt "speaker:hero"\n'
                    'msgid "「これは主命でござる。」"\n'
                    'msgstr "이것은 주인의 명이다."\n'
                )
            rows = io_adapters.load(path, profile=profile)
        rows[0]["scene"] = "scene-1"
        units = attribution.attributed_for_gating(rows, profile)
        self.assertEqual(1, len(units))
        self.assertEqual("「これは主命でござる。」", units[0].source_text)
        self.assertEqual('"이것은 주인의 명이다."', rows[0]["pivot"])
        marker_patterns = [r"이오[.。！？!?…]*$"]
        contract = {
            "speaker": "hero",
            "axes": [{"axis": "ending_transform"}],
            "required_markers": marker_patterns,
            "forbidden_markers": [],
            "measured_source_density": {"ending_transform": 1.0},
            "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
            "exclusivity": {"exclusive_with": []},
            "bands": {"all": {"ending_transform": [1.0, 1.0]}},
            "scope_overrides": {},
            "marker_sets": {"ending_transform": marker_patterns},
            "catalogue_markers": {"fixture": marker_patterns},
            "review_decisions": {},
            "seal": {"hash": hashlib.sha256(b"adapter-spine").hexdigest()},
            "measurable_axes": ["ending_transform"],
        }
        found, _report = gates.corpus(
            [
                {
                    "row_key": unit.row_key,
                    "scope": unit.scope,
                    "text": unit.target_text,
                    "scene": unit.scene,
                    "eligible": True,
                    "pending": False,
                    "attributed_spans": 1,
                }
                for unit in units
            ],
            [contract],
            catalogue_markers={"fixture": marker_patterns},
            target_lang="ko",
            source_scene_densities={("hero", "ending_transform"): [1.0] * 5},
            measurable_axes={"hero": ["ending_transform"]},
            quote_parity_findings=findings.FindingSet(),
            ladder_findings=findings.FindingSet(),
            profile=profile,
        )
        self.assertIn("voice_required_marker_absent", [finding.code for finding in found.hard])
    def test_po_context_continuations_escapes_and_obsolete_report(self):
        rows = io_adapters.read_po(self.fixture("sample.po"), profile=self.profile)
        self.assertEqual(1, len(rows))
        self.assertEqual("orbit", rows[0]["speaker"])
        self.assertEqual("orbit", rows[0]["msgctxt"])
        self.assertEqual('Pilot says "ready" now.', rows[0]["evidence_surface"])
        self.assertEqual('Guide says "set" now .', rows[0]["pivot_surface"])

        report = io_adapters.load_report(rows, "po")
        self.assertEqual(1, report["obsolete_skipped"])
        self.assertEqual(1, report["with_speaker"])
        self.assertEqual([], report["findings"])
        self.assertEqual(0, report["untranslated_skipped"])
        self.assertEqual(0, report["fuzzy_skipped"])

    def test_po_untranslated_and_fuzzy_entries_are_excluded_and_counted(self):
        rows = io_adapters.read_po(
            self.fixture("po_classification.po"), profile=self.profile
        )
        self.assertEqual(1, len(rows))
        self.assertEqual(["Synthetic completed entry"], [row["evidence"] for row in rows])
        self.assertEqual(
            ["Synthetic completed translation"], [row["pivot"] for row in rows]
        )
        report = io_adapters.load_report(rows, "po")
        self.assertEqual(1, report["rows"])
        self.assertEqual(1, report["untranslated_skipped"])
        self.assertEqual(1, report["fuzzy_skipped"])
        self.assertEqual([], report["findings"])

    def test_po_only_unfinished_entries_publish_counts_before_empty_measurement_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "unfinished.po")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    'msgid "Synthetic unfinished entry"\n'
                    'msgstr ""\n\n'
                    '#, fuzzy\n'
                    'msgid "Synthetic draft entry"\n'
                    'msgstr "Synthetic draft"\n'
                )
            rows = io_adapters.read_po(path, profile=self.profile)
        self.assertEqual([], rows)
        report = io_adapters.load_report(rows, "po")
        self.assertEqual(1, report["untranslated_skipped"])
        self.assertEqual(1, report["fuzzy_skipped"])
        self.assertEqual(["adapter_rows_empty"], [item["code"] for item in report["findings"]])

    def test_xliff_inline_markup_is_protected_not_measured(self):
        rows = io_adapters.read_xliff(self.fixture("sample.xlf"), profile=self.profile)
        self.assertEqual("Start pilot.", rows[0]["evidence_surface"])
        self.assertEqual("End guide.", rows[0]["pivot_surface"])
        self.assertNotIn("<", rows[0]["pivot_surface"])
        self.assertNotIn('id="1"', rows[0]["pivot_surface"])
        self.assertNotIn("CODE", rows[0]["pivot_surface"])
        self.assertNotIn("&lt;b&gt;", rows[0]["pivot_surface"])

        grammar = tag_grammar.grammar_for("xliff")
        raw = 'End <g id="1">guide</g><x id="2"/><ph id="3">CODE</ph>.'
        self.assertEqual(
            ('<g id="1">', "</g>", '<x id="2"/>', '<ph id="3">CODE</ph>'),
            tag_grammar.tag_skeleton(raw, grammar),
        )
        self.assertEqual("End guide.", tag_grammar.strip_tags(raw, grammar))

    def test_epub_spine_order_and_paragraph_rows(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "sample.epub")
            with zipfile.ZipFile(path, "w") as archive:
                archive.writestr(
                    "META-INF/container.xml",
                    "<container><rootfiles><rootfile full-path=\"OEBPS/content.opf\"/></rootfiles></container>",
                )
                archive.writestr(
                    "OEBPS/content.opf",
                    "<package><manifest>"
                    "<item id=\"first\" href=\"first.xhtml\"/>"
                    "<item id=\"second\" href=\"second.xhtml\"/>"
                    "</manifest><spine><itemref idref=\"second\"/><itemref idref=\"first\"/>"
                    "</spine></package>",
                )
                archive.writestr(
                    "OEBPS/first.xhtml",
                    "<html><body><aside>Ignored lead.</aside><p>First leaf.</p></body></html>",
                )
                archive.writestr(
                    "OEBPS/second.xhtml",
                    "<html><body>Ignored text.<p>Second leaf.</p><p>Second tail.</p></body></html>",
                )
            rows = io_adapters.load(path, profile=self.profile)
        self.assert_normalised(rows, "epub")
        self.assertEqual(["Second leaf.", "Second tail.", "First leaf."], [row["pivot_surface"] for row in rows])


    def test_unknown_grammar_fails_loudly(self):
        with self.assertRaises(tag_grammar.TagGrammarError) as raised:
            tag_grammar.grammar_for("made-up-container")
        self.assertEqual("hard", raised.exception.finding.severity)
        self.assertEqual("tag_grammar_undeclared", raised.exception.finding.code)

    def test_tag_grammar_preserves_plain_text_and_po_placeholders(self):
        plain = tag_grammar.grammar_for("plain_text")
        self.assertEqual((), tag_grammar.tag_skeleton("Ordinary prose.", plain))
        self.assertEqual("Ordinary prose.", tag_grammar.strip_tags("Ordinary prose.", plain))
        grammar = tag_grammar.grammar_for("po")
        source = "Launch %1$s for {name}."
        translated = "Arrive %1$s near {name}."
        self.assertEqual(
            tag_grammar.tag_skeleton(source, grammar),
            tag_grammar.tag_skeleton(translated, grammar),
        )
        self.assertEqual(("%1$s", "{name}"), tag_grammar.tag_skeleton(source, grammar))

    def test_po_percent_s_is_protected_without_an_adapter_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "placeholder.po")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write('msgid "Value %s"\nmsgstr "Value %s"\n')
            rows = io_adapters.load(path, profile=self.profile)
        self.assertEqual("Value", rows[0]["pivot_surface"])

        self.assertEqual([], io_adapters.load_report(rows, "po")["findings"])

    def test_anchored_korean_marker_normalises_every_suffix_case_for_every_format(self):
        marker = "확인."
        absent = "부재."
        variants = {
            "bare": marker,
            "quoted": '"%s"' % marker,
            "quoted-zero-width-space": '"%s"\u200b' % marker,
            "quoted-bom": '"%s"\ufeff' % marker,
            "quoted-crlf": '"%s"\r\n' % marker,
            "quoted-nbsp": '"%s"\u00a0' % marker,
            "quoted-trailing-tag": '"%s"<br>' % marker,
            "tag-then-quote": '<br>"%s"' % marker,
        }

        for fmt in sorted(tag_grammar.GRAMMARS):
            for variant, raw in variants.items():
                with self.subTest(fmt=fmt, variant=variant):
                    row = io_adapters._make_row(
                        fmt,
                        self.profile,
                        key="anchor:%s:%s" % (fmt, variant),
                        evidence="source",
                        pivot=raw,
                        target=raw,
                    )
                    for field in ("pivot", "target"):
                        surface = row[field + "_surface"]
                        self.assertEqual(marker, surface)
                        self.assertIsNotNone(re.search(r"확인\.$", surface))
                    absent_row = io_adapters._make_row(
                        fmt,
                        self.profile,
                        key="absent:%s:%s" % (fmt, variant),
                        evidence="source",
                        pivot=raw.replace(marker, absent),
                        target=raw.replace(marker, absent),
                    )
                    for field in ("pivot", "target"):
                        surface = absent_row[field + "_surface"]
                        self.assertEqual(absent, surface)
                        self.assertIsNone(re.search(r"확인\.$", surface))


    def test_json_profile_tag_normalisation_restores_anchored_target_marker(self):
        record = {
            "key": "json-anchor",
            "evidence": "x",
            "pivot": "y",
            "target": '"이것이 주인의 명이오."<br>',
            "evidence_lang": "ja",
            "pivot_lang": "en",
        }
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "rows.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump([record], handle, ensure_ascii=False)
            rows = io_adapters.load(path, profile=self.profile, fmt="json")
        self.assertEqual("이것이 주인의 명이오.", rows[0]["target_surface"])
        self.assertIsNotNone(re.search(r"이오[.!?…]*$", rows[0]["target_surface"]))


    def test_profile_tags_normalise_japanese_evidence_delimiters(self):
        row = io_adapters._make_row(
            "json",
            self.profile,
            key="japanese-anchor",
            evidence="「ござる。」<br>",
            pivot="source",
        )
        self.assertEqual("ござる。", row["evidence_surface"])
        self.assertIsNotNone(re.search(r"ござる。$", row["evidence_surface"]))


    def test_profile_tag_normalisation_preserves_ruby_surfaces(self):
        ruby = "<ruby>字<rt>じ</rt></ruby>"
        row = io_adapters._make_row(
            "json", self.profile, key="ruby", evidence=ruby + "<br>", pivot="source"
        )
        self.assertEqual(ruby, row["evidence_surface"])

        self.assertEqual("字", segment.strip_tags(row["evidence"], self.profile, keep_ruby_reading=False))
        self.assertEqual("字じ", segment.strip_tags(row["evidence"], self.profile, keep_ruby_reading=True))

    def test_leading_opener_is_reported_without_hiding_anchored_marker(self):
        row = io_adapters._make_row(
            "json", self.profile, key="leading", evidence="source", pivot='"확인.'
        )
        rows = io_adapters._loaded("json", [row])
        report = io_adapters.load_report(rows, "json")
        self.assertEqual('"확인.', row["pivot"])
        self.assertIsNotNone(re.search(r"확인\.$", row["pivot"]))
        self.assertEqual(1, report["leading_openers"])
        self.assertEqual(
            ["adapter_surface_leading_opener"],
            [finding["code"] for finding in report["findings"]],
        )
        self.assertEqual("report", report["findings"][0]["severity"])
        self.assertIn("cannot hide a $-anchored marker", report["findings"][0]["detail"])


    def test_unpaired_trailing_closer_is_normalised_not_refused(self):
        # The second row of an utterance continued across rows carries a closer
        # with no opener.  Refusing it was a gate firing on faithful work.
        row = io_adapters._make_row(
            "json", self.profile, key="unpaired", evidence="source", pivot='\ud655\uc778."'
        )
        report = io_adapters.load_report(io_adapters._loaded("json", [row]), "json")
        self.assertEqual("\ud655\uc778.", row["pivot_surface"])
        self.assertIn(
            "adapter_surface_trailing_closer_removed",
            [finding["code"] for finding in report["findings"]],
        )
        self.assertEqual(
            {"report"},
            {finding["severity"] for finding in report["findings"]},
        )

    def test_a_matched_pair_at_the_end_no_longer_blocks_an_anchored_marker(self):
        # \uadf8\uac00 "\uba85\uc774\uc624" has a matched pair, is not stripped by the pair loop
        # because the row does not start with the opener, and silently blocked
        # the marker from ever reaching the anchor.
        row = io_adapters._make_row(
            "json", self.profile, key="embedded", evidence="source",
            pivot='\uadf8\uac00 "\uba85\uc774\uc624"',
        )
        self.assertEqual('\uadf8\uac00 "\uba85\uc774\uc624', row["pivot_surface"])
        self.assertTrue(pattern_match(row["pivot_surface"], [r"\uba85\uc774\uc624[.!?\u2026]*$"]))

    def test_an_inner_quote_inside_ordinary_speech_is_left_intact(self):
        row = io_adapters._make_row(
            "json", self.profile, key="inner", evidence="source",
            pivot='\uadf8\ub294 "\ub124"\ub77c\uace0 \ud588\ub2e4.',
        )
        self.assertEqual('\uadf8\ub294 "\ub124"\ub77c\uace0 \ud588\ub2e4.', row["pivot_surface"])


    def test_plain_surface_without_tags_or_delimiters_is_unchanged(self):
        row = io_adapters._make_row(
            "json",
            self.profile,
            key="plain",
            evidence="plain evidence",
            pivot="plain pivot",
            target="plain target",
        )
        self.assertEqual("plain evidence", row["evidence"])
        self.assertEqual("plain pivot", row["pivot"])
        self.assertEqual("plain target", row["target"])
        report = io_adapters.load_report(io_adapters._loaded("json", [row]), "json")
        self.assertEqual(0, report["leading_openers"])

    def test_ass_multiline_override_is_protected_and_continuation_fails_loudly(self):
        grammar = tag_grammar.grammar_for("ass")
        self.assertEqual(("{\\i1\n\\i0}",), tag_grammar.tag_skeleton("{\\i1\n\\i0}", grammar))
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "split-override.ass")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    "[Events]\n"
                    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
                    "Dialogue: 0,0:00:00.00,0:00:01.00,Default,speaker,0,0,0,,{\\i1\n"
                    "\\i0}visible\n"
                )
            with self.assertRaises(io_adapters.AdapterError) as raised:
                io_adapters.read_ass(path, profile=self.profile)
        self.assertEqual("adapter_ass_malformed", raised.exception.finding.code)

    def test_epub_compression_bomb_fails_before_measurement(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "bomb.epub")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("padding", b"0" * (1024 * 1024))
            with self.assertRaises(io_adapters.AdapterError) as raised:
                io_adapters.read_epub(path, profile=self.profile)
        self.assertEqual("adapter_epub_archive_unsafe", raised.exception.finding.code)

    def test_every_adapter_rejects_empty_malformed_and_zero_row_inputs(self):
        cases = {
            "plain_text": (".txt", b"", b"\xff", b"\n"),
            "json": (".json", b"", b"{", b"[]"),
            "csv": (".csv", b"", b"key,text\nrow,too,many\n", b"key,text\n"),
            "po": (".po", b"", b"not a PO record\n", b'msgid ""\nmsgstr ""\n'),
            "xliff": (".xlf", b"", b"<xliff>", b"<xliff version=\"1.2\"/>"),
            "srt": (".srt", b"", b"1\nbad\ntext\n", b"\n"),
            "vtt": (".vtt", b"", b"NOTVTT\n", b"WEBVTT\n"),
            "ass": (".ass", b"", b"[Events]\nDialogue: text\n", b"[Events]\nFormat: Start, End, Name, Text\n"),
            "host_json": (".json", b"", b"{", b"{}"),
        }
        with tempfile.TemporaryDirectory() as directory:
            for fmt, (suffix, empty, malformed, zero_rows) in cases.items():
                for shape, content in (
                    ("empty", empty),
                    ("malformed", malformed),
                    ("zero-rows", zero_rows),
                ):
                    with self.subTest(fmt=fmt, shape=shape):
                        path = os.path.join(directory, "%s-%s%s" % (fmt, shape, suffix))
                        with open(path, "wb") as handle:
                            handle.write(content)
                        self.assert_hard_failure(
                            lambda path=path, fmt=fmt: io_adapters.load(
                                path, profile=self.profile, fmt=fmt
                            )
                        )

            missing_msgstr = os.path.join(directory, "missing-msgstr.po")
            with open(missing_msgstr, "w", encoding="utf-8") as handle:
                handle.write('msgid "Source"\n')
            self.assert_hard_failure(
                lambda: io_adapters.load(missing_msgstr, profile=self.profile)
            )

            for shape, content in (("empty", b""), ("malformed", b"not a zip")):
                with self.subTest(fmt="epub", shape=shape):
                    path = os.path.join(directory, "epub-%s.epub" % shape)
                    with open(path, "wb") as handle:
                        handle.write(content)
                    self.assert_hard_failure(
                        lambda path=path: io_adapters.load(path, profile=self.profile)
                    )
            zero_epub = os.path.join(directory, "epub-zero.epub")
            self.write_epub(zero_epub, ())
            self.assert_hard_failure(
                lambda: io_adapters.load(zero_epub, profile=self.profile)
            )

            unknown = os.path.join(directory, "unknown.txt")
            with open(unknown, "w", encoding="utf-8") as handle:
                handle.write("ordinary text\n")
            self.assert_hard_failure(
                lambda: io_adapters.load(unknown, profile=self.profile, fmt="undeclared")
            )

    def test_adapter_reports_surface_each_hard_finding(self):
        valid = {
            "key": "valid",
            "evidence": "source",
            "pivot": "pivot",
            "evidence_lang": "ja",
            "pivot_lang": "en",
            "tag_grammar": "srt",
        }
        empty_report = io_adapters.load_report([], "srt")
        self.assertEqual(["adapter_rows_empty"], [item["code"] for item in empty_report["findings"]])
        rows = io_adapters.LoadedRows(
            [
                "not-a-row",
                {"key": "missing"},
                dict(valid, key="wrong-grammar", tag_grammar="po"),
                dict(valid, key="timing-incomplete", start=0),
                dict(valid, key="timing-reversed", start=2, end=1),
                dict(valid, key="timing-nonnumeric", start="never", end=1),
            ],
            fmt="srt",
            obsolete_skipped=-1,
        )
        report = io_adapters.load_report(rows, "srt")
        self.assertEqual(
            {
                "adapter_row_malformed",
                "adapter_tag_grammar_mismatch",
                "adapter_timing_incomplete",
                "adapter_timing_invalid",
                "adapter_report_malformed",
            },
            {item["code"] for item in report["findings"]},
        )
        self.assertTrue(all(item["severity"] == "hard" for item in report["findings"]))

    def test_encoding_is_bom_or_declaration_driven_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            cp949 = os.path.join(directory, "declared-cp949.txt")
            with open(cp949, "wb") as handle:
                handle.write('"확인."\n'.encode("cp949"))
            with self.assertRaises(io_adapters.AdapterError) as raised:
                io_adapters.read_plain_text(cp949, profile=self.profile)
            self.assertEqual("adapter_encoding_undeclared", raised.exception.finding.code)
            rows = io_adapters.read_plain_text(cp949, profile=self.profile, encoding="cp949")
            self.assertEqual("확인.", rows[0]["pivot_surface"])

            self.assertEqual("cp949", io_adapters.load_report(rows, "plain_text")["encoding"])

            utf16 = os.path.join(directory, "bom-utf16.txt")
            with open(utf16, "wb") as handle:
                handle.write('"확인."\n'.encode("utf-16"))
            rows = io_adapters.read_plain_text(utf16, profile=self.profile)
            self.assertEqual("확인.", rows[0]["pivot_surface"])

            self.assertEqual("utf-16-le", io_adapters.load_report(rows, "plain_text")["encoding"])

            po = os.path.join(directory, "declared-cp949.po")
            with open(po, "wb") as handle:
                handle.write(
                    (
                        'msgid ""\nmsgstr ""\n'
                        '"Content-Type: text/plain; charset=CP949\\n"\n\n'
                        'msgid "Source"\nmsgstr "확인"\n'
                    ).encode("cp949")
                )
            rows = io_adapters.read_po(po, profile=self.profile)
            self.assertEqual("확인", rows[0]["pivot_surface"])

            self.assertEqual("cp949", io_adapters.load_report(rows, "po")["encoding"])

            xliff = os.path.join(directory, "declared-shift-jis.xlf")
            with open(xliff, "wb") as handle:
                handle.write(
                    ('<?xml version="1.0" encoding="Shift_JIS"?>'
                     '<xliff><file><body><trans-unit id="x">'
                     '<source>Source</source><target>日本</target>'
                     '</trans-unit></body></file></xliff>').encode("shift_jis")
                )
            rows = io_adapters.read_xliff(xliff, profile=self.profile)
            self.assertEqual("日本", rows[0]["pivot_surface"])
            self.assertEqual("shift_jis", io_adapters.load_report(rows, "xliff")["encoding"])

            invalid = os.path.join(directory, "invalid.txt")
            with open(invalid, "wb") as handle:
                handle.write(b"\x81")
            with self.assertRaises(io_adapters.AdapterError) as raised:
                io_adapters.read_plain_text(invalid, profile=self.profile)
            self.assertEqual("adapter_encoding_undeclared", raised.exception.finding.code)

    def test_host_json_is_read_only_and_matches_existing_loader_count(self):
        fixture = config.fixture_path()
        if not os.path.isfile(fixture):
            self.skipTest(
                "external corpus %s is unavailable; a clone without the pinned "
                "fixture cannot check the host-json row count" % fixture
            )
        rows = io_adapters.read_host_json(fixture, profile=self.profile)
        existing = cli._load_rows(fixture, self.profile)
        self.assertEqual(4052, len(existing))
        self.assertEqual(len(existing), len(rows))
        self.assert_normalised(rows, "host_json")
        report = io_adapters.load_report(rows, "host_json")
        leading_openers = [

            finding
            for finding in report["findings"]
            if finding["code"] == "adapter_surface_leading_opener"

            and finding["severity"] == "report"
        ]
        self.assertTrue(leading_openers)

        self.assertEqual(len(leading_openers), report["leading_openers"])
        self.assertFalse(
            any(finding["severity"] == "hard" for finding in report["findings"])
        )


if __name__ == "__main__":
    unittest.main()
