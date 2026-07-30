"""Documentation contracts that must track the executable surface."""
import argparse
import ast
import os
import re
import unittest

from hancharacter import cli, gates, schemas


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(ROOT, "hancharacter")
README = os.path.join(ROOT, "README.md")
SKILL = os.path.join(ROOT, "SKILL.md")
QUICKSTART = os.path.join(ROOT, "docs", "quickstart.md")
CATALOGUE = os.path.join(ROOT, "docs", "catalogue.md")
GATES = os.path.join(ROOT, "docs", "gates.md")

PINNED_SENTENCES = (
    "On a `prose_fidelity` work, voice-loss DENSITY is report-only and the presence-class gates carry the guarantee.",
    "The default coverage floor is X=0.70 (`config.COVERAGE_FLOOR_X`); a profile may declare a lower per-work floor, and both the declared floor and the applied contract floor are published.",

    "The voice-LOSS classes v1 cannot detect: dialect semantic fidelity, and anything on ineligible or duplicate-source rows.",
    '"처음부터 끝까지" means the contract governs every line of the work, NOT that the marker appears on 100% of lines — the faithful realisation is the measured, often intermittent source density, and forcing a marker onto every line is itself a defect that the invention and saturation lints reject.',
    "The narrow residual on mixed rows carrying both attributed speech and narration is reported, not hard.",
)

DECLARED_LIMITATIONS = (
    "Dual-standard density is report-only.",
    "Engine-wrapped and freeform rows have no structurally provable length bound.",
    "Dialect semantic fidelity is unmeasurable.",
    "Duplicate-source rows cost coverage because the host TM keys on the source string.",
    "Reviewer identity is unauthenticated and corpus artifacts are unsigned.",
    "The mixed-row smear residual is reported rather than hard.",
    "A `translator_declared` contract asserts only that the translator's own declared rendering is applied faithfully; it makes no claim that the rendering is correct Korean. The authority is bound into the seal hash and stamped on every gate summary so the weaker claim cannot be read as the stronger one.",
    "0 of 10 catalogue types are canonical, so no contract can seal against the shipped catalogue. `ja_hao_gozaru` reached `provisional` with occurrences 12, independent sources 4, `e1e2_sources` 1 and kappa 0.600, and fails canonical on one criterion only: no adopted precedent. Its kappa is exactly 3/5, on the 0.60 floor rather than above it, and it reached that floor by dilution rather than by improved reliability — kappa was 1/2 over the original eight rows, and eight new rows on which both reviewers agreed diluted the two existing disagreements until kappa hit exactly 0.60. Remove any one of those eight and it is 0.5946. Because `KAPPA_FLOOR` alone is clearable that way, a stability requirement was added: a kappa may satisfy the floor only if the floor verdict survives any single verdict flip. It is one-directional and can only remove a pass, never create one. It disqualifies `ja_hao_gozaru` (56 destabilising flips) and `ja_elder_lexicon` (26), and it was landed while that cost was zero because both types were already blocked on their missing precedent. The requirement is satisfiable rather than an infinite bar: eight agreed acceptances, six agreed rejections and one disagreement in each direction give kappa 0.746 with no destabilising flip.",
    "The single adopted precedent behind the only near-canonical type was corrected down to `contested` because it rested on one wiki list with no broadcast or publication record, which is the same standard already applied to `prec_fleur_ieung_ko` and `prec_gozaru_haoche_ko`. Applying one standard cost that type its canonical status.",
    "Overall inter-rater kappa is 87/143 (0.6084) across 42 reviewed rows, and the canonical type's own kappa is exactly 3/5.",
    "`e1e2_sources` is 0 for seven of ten types; three are supported by one secondary academic source, a non-refereed departmental bulletin paper.",
    "9 shipped patterns match no probe row and are enforced without verification.",
    "`ja_chuunibyou_frame` cannot be sealed because `measure/ja.py` declares `utterance_frame` `not_applicable`.",
    "An unmodelled `edition_medium` is reported as an unmodelled-medium limitation rather than a measured verdict.",
    "`Profile.term_quote_min_len` is currently an unused declaration; it does not affect segmentation, gating, or contract sealing.",

)


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _emitted_codes():
    """Return finding code -> observed AST severities for package modules."""
    emitted = {}
    for base, directories, filenames in os.walk(PACKAGE):
        directories[:] = [name for name in directories if name != "__pycache__"]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(base, filename)
            with open(path, encoding="utf-8") as handle:
                tree = ast.parse(handle.read(), filename=path)
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                function = node.func
                severity = None
                if (
                    isinstance(function, ast.Attribute)
                    and isinstance(function.value, ast.Name)
                    and function.value.id == "findings"
                    and function.attr in {"hard", "report"}
                ):
                    severity = function.attr
                elif isinstance(function, ast.Name) and function.id in {"hard", "report"}:
                    severity = function.id
                code = node.args[0]
                if (
                    severity is not None
                    and isinstance(code, ast.Constant)
                    and isinstance(code.value, str)
                ):
                    emitted.setdefault(code.value, set()).add(severity)
    return emitted


def _parser_commands():
    parser = cli.build_parser()
    subparsers = [
        action
        for action in parser._actions
        if isinstance(action, argparse._SubParsersAction)
    ]
    if len(subparsers) != 1:
        raise AssertionError("CLI must expose exactly one top-level subparser action")
    return set(subparsers[0].choices)


class DocumentationContractTests(unittest.TestCase):
    def test_pinned_sentences_are_verbatim(self):
        text = _read(README) + "\n" + _read(SKILL)
        for sentence in PINNED_SENTENCES:
            with self.subTest(sentence=sentence):
                self.assertIn(sentence, text)

    def test_opening_claim_is_qualified_by_the_shipped_catalogue_closure(self):
        first_paragraph = _read(README).split("\n\n", 2)[1]
        self.assertIn(
            "On the shipped catalogue, no contract can seal: 0 of 10 types are canonical. `ja_hao_gozaru` is `provisional` and now meets every canonical criterion except one — it has no adopted precedent, because the only candidate was corrected down to `contested` for consistency with its siblings.",
            first_paragraph,
        )

    def test_skill_does_not_prescribe_unimplemented_contract_commands(self):
        text = _read(SKILL)
        self.assertNotIn("4. Seal only contracts", text)
        self.assertNotIn("5. Run capacity and character-corpus gates", text)
        self.assertIn(
            "The current CLI has no operator command to create or seal a contract, or to run capacity and character-corpus gates over one.",
            text,
        )

    def test_declared_limitations_are_explicit(self):
        text = _read(README)
        self.assertIn("## Declared limitations", text)
        for limitation in DECLARED_LIMITATIONS:
            with self.subTest(limitation=limitation):
                self.assertIn(limitation, text)

    def test_host_composition_scope_is_explicit(self):
        text = _read(README)
        self.assertIn(
            "Host-pipeline composition (P5/P6b) is NOT part of v1 and is report-level only until separately approved.",
            text,
        )
        self.assertIn(
            "`hancharacter` never imports a host pipeline; the import-direction test enforces it.",
            text,
        )

    def test_planning_era_name_is_absent_from_every_repository_file(self):
        needle = "voice" + "lock"
        hits = []
        for base, directories, filenames in os.walk(ROOT):
            directories[:] = [
                name for name in directories if name not in {".git", "__pycache__", ".venv"}
            ]
            for filename in filenames:
                path = os.path.join(base, filename)
                with open(path, "rb") as handle:
                    if needle.encode("utf-8") in handle.read().lower():
                        hits.append(os.path.relpath(path, ROOT))
        self.assertEqual([], hits)

    def test_quickstart_and_parser_have_exactly_the_same_commands(self):
        text = _read(QUICKSTART)
        line = next(
            (line for line in text.splitlines() if line.startswith("**Top-level commands:**")),
            None,
        )
        self.assertIsNotNone(line, "quickstart must name every top-level command on one line")
        documented = set(re.findall(r"`([a-z0-9-]+)`", line or ""))
        self.assertSetEqual(_parser_commands(), documented)

    def test_catalogue_axes_match_the_closed_schema(self):
        text = _read(CATALOGUE)
        axes_section = text.split("## Axes\n", 1)[1].split("\n## Reproduce this reference", 1)[0]
        documented = set(re.findall(r"^- `([^`]+)`$", axes_section, flags=re.MULTILINE))
        self.assertSetEqual(set(schemas.AXES), documented)

    def test_documented_gate_codes_are_emitted_with_the_documented_severity(self):
        text = _read(GATES)
        rows = re.findall(
            r"^\| `([A-Za-z][A-Za-z0-9_-]+)` \| (hard|report|both) \|",
            text,
            flags=re.MULTILINE,
        )
        self.assertTrue(rows, "gates documentation must contain a finding table")
        documented = dict(rows)
        self.assertEqual(len(rows), len(documented), "a finding code may have one table row")
        emitted = _emitted_codes()
        for code, severity in documented.items():
            with self.subTest(code=code):
                self.assertIn(code, emitted)
                expected = emitted[code]
                expected_label = "both" if expected == {"hard", "report"} else next(iter(expected))
                self.assertEqual(expected_label, severity)

    def test_non_waivable_table_matches_the_closed_gate_set(self):
        text = _read(GATES)
        section = text.split("## Non-waivable findings\n", 1)[1]
        documented = set(re.findall(r"^- `([^`]+)`$", section, flags=re.MULTILINE))
        self.assertSetEqual(set(gates._NON_WAIVABLE_CODES), documented)


if __name__ == "__main__":
    unittest.main()
