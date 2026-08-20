"""Native manifest reader: verify the seal, join strictly, leave the host alone.

The reader re-derives the manifest digest instead of reading the recorded one,
which catches a manifest whose text moved while its recorded digest did not. It
does NOT catch a forgery: the rule is published, so a recomputed digest is
accepted, and a test below pins that limitation so it cannot be re-described as
protection. The join is strict in both directions because a reviewer judging a
different set of lines than the build ships is worse than one who judges nothing.
"""

import hashlib
import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hancharacter import manifest_adapter as ma  # noqa: E402

ENTRIES = {'dialogue/1': '용사가 왔다', 'dialogue/2': '문이 열렸다'}
EVIDENCE = {'dialogue/1': '勇者が来た', 'dialogue/2': '扉が開いた'}


def digest_of(entries):
    h = hashlib.sha256()
    for key in sorted(entries):
        h.update(key.encode())
        h.update(b'\0')
        h.update(entries[key].encode())
        h.update(b'\0')
    return h.hexdigest()


def write_pair(base, entries=None, ruleset='3', host_overrides=None,
               family_overrides=None):
    entries = entries or ENTRIES
    manifest = {'entries': entries, 'digest': digest_of(entries),
                'ruleset': ruleset}
    manifest_path = os.path.join(base, 'manifest.json')
    with open(manifest_path, 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh)

    families = {'dialogue': [
        {'key': '1', 'evidence': EVIDENCE['dialogue/1'], 'target': entries.get('dialogue/1', '')},
        {'key': '2', 'evidence': EVIDENCE['dialogue/2'], 'target': entries.get('dialogue/2', '')},
    ]}
    if family_overrides is not None:
        families = family_overrides
    host = {'schemaVersion': 1, 'kind': ma.HOST_ROWS_KIND,
            'languages': {'evidence': 'ja', 'pivot': None, 'target': 'ko'},
            'direction': 'ja->ko',
            'manifestDigest': manifest['digest'], 'manifestRuleset': ruleset,
            'families': families}
    host.update(host_overrides or {})
    host_path = os.path.join(base, 'rows.json')
    with open(host_path, 'w', encoding='utf-8') as fh:
        json.dump(host, fh)
    return manifest_path, host_path


class DigestIsReDerived(unittest.TestCase):
    def test_a_valid_manifest_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, _ = write_pair(tmp)
            doc = ma.read_manifest(manifest_path, expected_ruleset='3')
            self.assertEqual(doc['entries'], ENTRIES)

    def test_edited_text_with_a_stale_digest_is_caught(self):
        # The case re-derivation exists for: the text moved, the recorded digest
        # did not.
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = os.path.join(tmp, 'manifest.json')
            tampered = dict(ENTRIES, **{'dialogue/1': '다른 문장'})
            with open(manifest_path, 'w', encoding='utf-8') as fh:
                json.dump({'entries': tampered, 'digest': digest_of(ENTRIES),
                           'ruleset': '3'}, fh)
            with self.assertRaisesRegex(ma.ManifestAdapterError, 'digest mismatch'):
                ma.read_manifest(manifest_path)

    def test_a_recomputed_digest_is_accepted_because_this_is_not_a_signature(self):
        # Stated as a test so the limitation cannot be forgotten and then
        # described as protection. The rule is published; anyone who edits the
        # text can recompute the digest. Provenance has to come from elsewhere.
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path = os.path.join(tmp, 'manifest.json')
            forged = dict(ENTRIES, **{'dialogue/1': '개조된 대사'})
            with open(manifest_path, 'w', encoding='utf-8') as fh:
                json.dump({'entries': forged, 'digest': digest_of(forged),
                           'ruleset': '3'}, fh)
            doc = ma.read_manifest(manifest_path, expected_ruleset='3')
            self.assertEqual(doc['entries']['dialogue/1'], '개조된 대사')

    def test_ruleset_mismatch_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, _ = write_pair(tmp, ruleset='2')
            with self.assertRaisesRegex(ma.ManifestAdapterError, 'ruleset'):
                ma.read_manifest(manifest_path, expected_ruleset='3')

    def test_missing_fields_and_bad_types_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'manifest.json')
            for doc in ({'entries': ENTRIES},
                        {'digest': 'x'},
                        {'entries': [], 'digest': 'x'},
                        {'entries': {'a/b': 42}, 'digest': 'x'}):
                with open(path, 'w', encoding='utf-8') as fh:
                    json.dump(doc, fh)
                with self.assertRaises(ma.ManifestAdapterError):
                    ma.read_manifest(path)

    def test_list_shaped_file_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'manifest.json')
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump([], fh)
            with self.assertRaisesRegex(ma.ManifestAdapterError, 'JSON object'):
                ma.read_manifest(path)


class HostRowsShape(unittest.TestCase):
    def test_wrong_kind_or_version_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, host = write_pair(tmp, host_overrides={'kind': 'other'})
            with self.assertRaises(ma.ManifestAdapterError):
                ma.read_host_rows(host)
        with tempfile.TemporaryDirectory() as tmp:
            _, host = write_pair(tmp, host_overrides={'schemaVersion': 9})
            with self.assertRaises(ma.ManifestAdapterError):
                ma.read_host_rows(host)

    def test_unnamed_axes_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, host = write_pair(tmp, host_overrides={'languages': {}})
            with self.assertRaisesRegex(ma.ManifestAdapterError, 'axes are a guess'):
                ma.read_host_rows(host)


class JoinIsStrictBothWays(unittest.TestCase):
    def test_a_matching_pair_joins(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, host_path = write_pair(tmp)
            rows = ma.load_joined(manifest_path, host_path, expected_ruleset='3')
            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0]['row_key'], 'dialogue/1')
            self.assertEqual(rows[0]['evidence_lang'], 'ja')
            self.assertEqual(rows[0]['target_lang'], 'ko')

    def test_target_comes_from_the_manifest_not_the_row(self):
        # The exporter's copy of the target is a view; the seal is authority.
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, host_path = write_pair(
                tmp, family_overrides={'dialogue': [
                    {'key': '1', 'evidence': EVIDENCE['dialogue/1'],
                     'target': 'STALE COPY'},
                    {'key': '2', 'evidence': EVIDENCE['dialogue/2'],
                     'target': 'STALE COPY'}]})
            rows = ma.load_joined(manifest_path, host_path)
            self.assertEqual(rows[0]['target'], ENTRIES['dialogue/1'])

    def test_an_extra_row_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, host_path = write_pair(
                tmp, family_overrides={'dialogue': [
                    {'key': '1', 'evidence': 'a', 'target': 'x'},
                    {'key': '2', 'evidence': 'b', 'target': 'y'},
                    {'key': '99', 'evidence': 'c', 'target': 'z'}]})
            with self.assertRaisesRegex(ma.ManifestAdapterError,
                                        'not in the sealed manifest'):
                ma.load_joined(manifest_path, host_path)

    def test_a_missing_row_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, host_path = write_pair(
                tmp, family_overrides={'dialogue': [
                    {'key': '1', 'evidence': 'a', 'target': 'x'}]})
            with self.assertRaisesRegex(ma.ManifestAdapterError, 'absent from'):
                ma.load_joined(manifest_path, host_path)

    def test_duplicate_rows_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, host_path = write_pair(
                tmp, family_overrides={'dialogue': [
                    {'key': '1', 'evidence': 'a', 'target': 'x'},
                    {'key': '1', 'evidence': 'a', 'target': 'x'},
                    {'key': '2', 'evidence': 'b', 'target': 'y'}]})
            with self.assertRaisesRegex(ma.ManifestAdapterError, 'duplicate'):
                ma.load_joined(manifest_path, host_path)

    def test_malformed_family_and_row_shapes_are_refused(self):
        for families in ({'dialogue': 'not a list'},
                         {'dialogue': ['not an object']},
                         {'dialogue': [{'evidence': 'a'}]},
                         {'dialogue': [{'key': '1'}]}):
            with tempfile.TemporaryDirectory() as tmp:
                manifest_path, host_path = write_pair(
                    tmp, family_overrides=families)
                with self.assertRaises(ma.ManifestAdapterError):
                    ma.load_joined(manifest_path, host_path)

    def test_host_rows_describing_another_manifest_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, host_path = write_pair(
                tmp, host_overrides={'manifestDigest': 'f' * 64})
            with self.assertRaisesRegex(ma.ManifestAdapterError, 'describe manifest'):
                ma.load_joined(manifest_path, host_path)


class TheHostIsLeftAlone(unittest.TestCase):
    def _source(self):
        with open(os.path.join(ROOT, 'hancharacter', 'manifest_adapter.py'),
                  encoding='utf-8') as fh:
            return fh.read()

    def test_no_hanpatch_import(self):
        import ast
        modules = set()
        for node in ast.walk(ast.parse(self._source())):
            if isinstance(node, ast.Import):
                modules.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules.add(node.module)
        self.assertFalse([m for m in modules if 'hanpatch' in m])

    def test_reader_never_writes(self):
        import ast
        for node in ast.walk(ast.parse(self._source())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == 'open':
                mode = None
                for arg in node.args[1:]:
                    if isinstance(arg, ast.Constant):
                        mode = arg.value
                for kw in node.keywords:
                    if kw.arg == 'mode' and isinstance(kw.value, ast.Constant):
                        mode = kw.value.value
                self.assertIn(mode, ('r',),
                              'the native reader must not open for writing')

    def test_existing_host_adapter_is_untouched(self):
        # read_host_json remains the general path; this module is a separate door.
        from hancharacter import io_adapters
        self.assertTrue(hasattr(io_adapters, 'read_host_json'))


if __name__ == '__main__':
    unittest.main()
