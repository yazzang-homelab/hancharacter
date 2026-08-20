"""Voice run producer: a closed input set, and a serialiser that does not judge.

`gates.run` takes ten required arguments and seven optional ones. A caller that
forgets one and gets a default still receives something shaped like a verdict,
which is the failure worth preventing: an incomplete run is indistinguishable
from a complete one once it has been written to a file and handed to another
repository.
"""

import json
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from hancharacter import voice_run as vr  # noqa: E402


def minimal_kwargs(**overrides):
    kwargs = {
        'contracts': [{'character_id': 'x'}],
        'attribution_gate': lambda: None,
        'seal_contract': lambda c: None,
        'length_check': lambda c: None,
        'observations': [],
        'catalogue_markers': None,
        'target_lang': 'ko',
        'source_scene_densities': {},
        'measurable_axes': {},
        'quote_parity_findings': None,
    }
    kwargs.update(overrides)
    return kwargs


class InputSetIsClosed(unittest.TestCase):
    def test_every_gates_run_argument_is_named(self):
        # If gates.run grows an argument, this list must grow with it rather
        # than a default silently appearing in produced verdicts.
        import inspect
        from hancharacter import gates
        actual = set(inspect.signature(gates.run).parameters)
        declared = set(vr.REQUIRED_INPUTS) | set(vr.OPTIONAL_INPUTS)
        self.assertEqual(actual, declared,
                         'REQUIRED_INPUTS/OPTIONAL_INPUTS drifted from gates.run')

    def test_non_callable_hooks_are_refused(self):
        for name in ('attribution_gate', 'seal_contract', 'length_check'):
            with self.assertRaises(vr.VoiceRunError):
                vr.VoiceRunRequest(**minimal_kwargs(**{name: 'not-callable'}))

    def test_empty_target_lang_is_refused(self):
        with self.assertRaises(vr.VoiceRunError):
            vr.VoiceRunRequest(**minimal_kwargs(target_lang=''))

    def test_non_mapping_structures_are_refused(self):
        with self.assertRaises(vr.VoiceRunError):
            vr.VoiceRunRequest(**minimal_kwargs(measurable_axes=[]))


class SingletonCardinality(unittest.TestCase):
    def test_zero_contracts_is_refused(self):
        with self.assertRaisesRegex(vr.VoiceRunError, 'exactly one'):
            vr.VoiceRunRequest(**minimal_kwargs(contracts=[]))

    def test_two_contracts_is_refused(self):
        with self.assertRaisesRegex(vr.VoiceRunError, 'exactly one'):
            vr.VoiceRunRequest(**minimal_kwargs(
                contracts=[{'character_id': 'a'}, {'character_id': 'b'}]))

    def test_non_mapping_contract_is_refused(self):
        with self.assertRaises(vr.VoiceRunError):
            vr.VoiceRunRequest(**minimal_kwargs(contracts=['a string']))


class ContractAuthority(unittest.TestCase):
    def _called_attributes(self):
        """Attribute names the module actually calls, ignoring prose.

        The docstring explains *why* the shared schema is not used; a text scan
        would flag that explanation instead of a real call.
        """
        import ast
        with open(os.path.join(ROOT, 'hancharacter', 'voice_run.py'),
                  encoding='utf-8') as fh:
            tree = ast.parse(fh.read())
        called = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    called.add(func.attr)
                elif isinstance(func, ast.Name):
                    called.add(func.id)
        return called

    def test_validation_uses_the_local_closed_validator(self):
        # contracts.validate_contract is authoritative. schemas.validate('contract')
        # is the older minimal shape and rejects every extended sealed contract,
        # as contracts.py says in its own docstring.
        called = self._called_attributes()
        self.assertIn('validate_contract', called)
        self.assertNotIn('validate', called,
                         'the shared schema validator must not be called here')

    def test_seal_currency_is_checked(self):
        self.assertIn('_seal_is_current', self._called_attributes())

    def test_an_invalid_contract_is_refused(self):
        with self.assertRaisesRegex(vr.VoiceRunError, 'invalid'):
            vr.VoiceRunRequest(**minimal_kwargs(contracts=[{}]))


class SerialiserDoesNotJudge(unittest.TestCase):
    def test_produce_requires_a_validated_request(self):
        with self.assertRaisesRegex(vr.VoiceRunError, 'VoiceRunRequest'):
            vr.produce({'contracts': []})

    def test_two_hashes_answer_two_questions(self):
        doc = {
            'schemaVersion': 1, 'kind': vr.DOCUMENT_KIND,
            'contractSha256': 'a' * 64, 'contractFileSha256': 'b' * 64,
        }
        self.assertNotEqual(doc['contractSha256'], doc['contractFileSha256'])

    def test_canonical_hash_ignores_formatting(self):
        a = vr._canonical_sha256({'b': 1, 'a': 2})
        b = vr._canonical_sha256({'a': 2, 'b': 1})
        self.assertEqual(a, b)

    def test_canonical_hash_notices_a_value_change(self):
        self.assertNotEqual(vr._canonical_sha256({'a': 1}),
                            vr._canonical_sha256({'a': 2}))


class AtomicWrite(unittest.TestCase):
    def test_write_leaves_no_temp_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, 'verdict.json')
            vr.write({'schemaVersion': 1, 'kind': vr.DOCUMENT_KIND}, target)
            leftovers = [f for f in os.listdir(tmp)
                         if f.startswith('.voice-verdict-')]
            self.assertEqual(leftovers, [])

    def test_written_document_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, 'verdict.json')
            doc = {'schemaVersion': 1, 'kind': vr.DOCUMENT_KIND, 'verdict': 'pass'}
            vr.write(doc, target)
            with open(target, encoding='utf-8') as fh:
                self.assertEqual(json.load(fh), doc)


if __name__ == '__main__':
    unittest.main()
