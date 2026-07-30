# hancharacter

`hancharacter` measures a source character's speech-style markers, records the evidence that justifies them, and refuses a target rendering that loses or invents that measured voice. On the shipped catalogue, no contract can seal: 0 of 10 types are canonical. `ja_hao_gozaru` is `provisional` and now meets every canonical criterion except one — it has no adopted precedent, because the only candidate was corrected down to `contested` for consistency with its siblings. It is a Python 3.9+ standard-library-only command-line tool; run it from a checkout with `./bin/hancharacter` and do not install a package or contact a service.

**한국어 가이드: [GUIDE.ko.md](GUIDE.ko.md)**

## Slash-command install (GJC / Claude Code / Codex)

All three read a `SKILL.md` with `name` + `description` frontmatter, so the single
canonical file at `skills/hancharacter/SKILL.md` is symlinked into each tool's skill
root. Pulling the repo updates every tool at once.

```sh
./bin/install-skill            # install for each tool that is present
./bin/install-skill --check    # report only
./bin/install-skill --copy     # copy instead of symlink
./bin/install-skill --project  # install into ./.gjc ./.claude ./.codex
./bin/install-skill --uninstall
```

`GJC_HOME` and `CODEX_HOME` are honoured. A tool whose config root is absent is
skipped rather than created. Then invoke `/hancharacter <task>`.


The tool separates three claims that must not be confused:

1. A source-side marker and a target realisation are catalogue claims.
2. A per-character contract is a sealed claim made only after the catalogue and work evidence meet their floors.
3. A gate verdict is an artifact-derived result over a sealed contract and canonical target units.

A model may help produce material for review, but it never authorises a gate. Re-derive every result from the emitted artifacts and the inputs named by their hashes.

## What it checks

- Attribution determines which rows belong to which speaker before voice measurement. Undeclared labels, mixed speaker spans, duplicate source rows, pending T2 guesses, and missing target text stay visible rather than becoming a clean denominator.
- The catalogue records source types, target realisations, authored probes, independently filed corpus reviews, published-edition precedents, human confirmations, and dialect decisions.
- Contract sealing requires source measurement availability, a feasible layout, usable glyphs, per-speaker coverage, and a resolved dialect decision where a dialect pair is declared. What it requires of the *evidence* depends on the declared authority: a `precedent_backed` contract needs a canonical type, a `translator_declared` one needs the source-side evidence only. See **Two authorities** below.
- Corpus gates check marker presence, forbidden markers, exclusivity, density, recurrent novel final forms, quote parity, and a priority-ladder drop ledger. LOSS and INVENTION are both defects.

On a `prose_fidelity` work, voice-loss DENSITY is report-only and the presence-class gates carry the guarantee. The default coverage floor is X=0.70 (`config.COVERAGE_FLOOR_X`); a profile may declare a lower per-work floor, and both the declared floor and the applied contract floor are published. The voice-LOSS classes v1 cannot detect: dialect semantic fidelity, and anything on ineligible or duplicate-source rows. "처음부터 끝까지" means the contract governs every line of the work, NOT that the marker appears on 100% of lines — the faithful realisation is the measured, often intermittent source density, and forcing a marker onto every line is itself a defect that the invention and saturation lints reject. The narrow residual on mixed rows carrying both attributed speech and narration is reported, not hard.


Density is `matched eligible units / eligible units` for one `(scope, axis)`. It uses a source p10–p90 per-scene band, a Wilson 95% interval, `OUTER_TOL=0.15`, `MIN_UNITS_PER_SCOPE=20`, and `MIN_SCENES_PER_BAND=5`. A dual-standard work widens its band by `DUAL_STD_WIDEN=0.10`; it does not turn a density report into a hard verdict.

## Two authorities

Every contract declares what entitles it to enforce a rendering. There is no default: a contract that declares neither authority is refused, because a guard that defaults to the weaker route is not a guard.

`precedent_backed` is the stronger claim. It requires a canonical type, which requires a cited published edition that actually shipped this rendering. Such a contract asserts that the rendering is the established convention.

`translator_declared` is a deliberately weaker, separately labelled route. It requires the source-side evidence only: the marker is real and measurable. It asserts nothing about which Korean rendering is correct, only that the rendering the translator declared is applied at the source's measured density, consistently and exclusively.

The weaker route exists because requiring an adopted precedent made the tool unable to govern the **first** translation of a novel marker — a new game, a first-translated webtoon, an original character — which is the common real case. Detecting that a marker was deleted never needed to know what the correct replacement was.

Two properties keep it honest:

- Dropping the *adopted*-precedent requirement does not drop the *rejected*-precedent refusal. A translator may not declare a rendering that a published precedent already shows to be a flattening.
- The authority is bound into the seal hash and stamped onto every gate summary, so a declared contract can never be edited into, or read as, a precedent-backed one.

Enforcement itself never branches on authority. LOSS, INVENTION, consistency and exclusivity behave identically under both routes by construction, and `tests/test_shipped_evidence.py` asserts by AST that no conditional in `gates.py` reads the authority.

## Evidence status of the shipped catalogue

The shipped catalogue is useful for inspection and linting but is not evidence sufficient to enforce a real work. Run `./bin/hancharacter corpus --json` to reproduce its graduation report. Its current closure is intentional: evidence is missing, not silently assumed.

- The catalogue has 14 source types and 9 Korean realisations, while the 10 types counted in the current graduation report are the types with corpus evidence joins.
- Contracts do not seal from a merely observed or provisional type; adding a bypass, changing a floor, or inventing a graduation stage would falsify the result.
- Use the authored synthetic fixture route described in `docs/quickstart.md` when a test needs a sealed contract. Label its result synthetic; it does not change the shipped catalogue's status.

## Scope

Host-pipeline composition (P5/P6b) is NOT part of v1 and is report-level only until separately approved. `hancharacter` never imports a host pipeline; the import-direction test enforces it. The standalone tool accepts declared rows and artifacts, but it does not read, invoke, or depend on a host localisation pipeline.

The project does not claim to judge literary quality, to infer a speaker from a guess, or to decide whether mapping one regional dialect to another preserves its social meaning. It records where those decisions require evidence or a human ruling.

## Documentation map

- `docs/quickstart.md` gives checkout-only commands and an authored synthetic fixture.
- `docs/catalogue.md` lists the closed measurement axes and generated catalogue reference.
- `docs/review-protocol.md` describes corpus, precedent, and human-confirmation review.
- `docs/gates.md` gives the ordered gate and waiver semantics.
- `docs/spine.md` defines segmentation and eligibility.
- `docs/evidence.md` explains the shipped evidence state and its derivation.
- `GUIDE.ko.md` is the Korean guide and leads with what the tool cannot do.
- `catalogue/SOURCES.md` lists every cited source **and every source that could not be verified and was therefore excluded**.
- `skills/hancharacter/SKILL.md` is the slash-command skill definition; `SKILL.md` at the root is the operator discipline note.

## Declared limitations

A `translator_declared` contract asserts only that the translator's own declared rendering is applied faithfully; it makes no claim that the rendering is correct Korean. The authority is bound into the seal hash and stamped on every gate summary so the weaker claim cannot be read as the stronger one.

Dual-standard density is report-only.

Engine-wrapped and freeform rows have no structurally provable length bound.

Dialect semantic fidelity is unmeasurable.

Duplicate-source rows cost coverage because the host TM keys on the source string.

Reviewer identity is unauthenticated and corpus artifacts are unsigned.

The mixed-row smear residual is reported rather than hard.

0 of 10 catalogue types are canonical, so no contract can seal against the shipped catalogue. `ja_hao_gozaru` reached `provisional` with occurrences 12, independent sources 4, `e1e2_sources` 1 and kappa 0.600, and fails canonical on one criterion only: no adopted precedent. Its kappa is exactly 3/5, on the 0.60 floor rather than above it, and it reached that floor by dilution rather than by improved reliability — kappa was 1/2 over the original eight rows, and eight new rows on which both reviewers agreed diluted the two existing disagreements until kappa hit exactly 0.60. Remove any one of those eight and it is 0.5946. Because `KAPPA_FLOOR` alone is clearable that way, a stability requirement was added: a kappa may satisfy the floor only if the floor verdict survives any single verdict flip. It is one-directional and can only remove a pass, never create one. It disqualifies `ja_hao_gozaru` (56 destabilising flips) and `ja_elder_lexicon` (26), and it was landed while that cost was zero because both types were already blocked on their missing precedent. The requirement is satisfiable rather than an infinite bar: eight agreed acceptances, six agreed rejections and one disagreement in each direction give kappa 0.746 with no destabilising flip.

The single adopted precedent behind the only near-canonical type was corrected down to `contested` because it rested on one wiki list with no broadcast or publication record, which is the same standard already applied to `prec_fleur_ieung_ko` and `prec_gozaru_haoche_ko`. Applying one standard cost that type its canonical status.

Overall inter-rater kappa is 87/143 (0.6084) across 42 reviewed rows. No type is canonical, so no canonical kappa exists; the nearest type, `ja_hao_gozaru`, sits at exactly 3/5.

`e1e2_sources` is 0 for seven of ten types; three are supported by one secondary academic source, a non-refereed departmental bulletin paper.

9 shipped patterns match no probe row and are enforced without verification.

`ja_chuunibyou_frame` cannot be sealed because `measure/ja.py` declares `utterance_frame` `not_applicable`.

An unmodelled `edition_medium` is reported as an unmodelled-medium limitation rather than a measured verdict.

`Profile.term_quote_min_len` is currently an unused declaration; it does not affect segmentation, gating, or contract sealing.

The catalogue's source and precedent claims are checked for internal consistency and provenance shape, not independently authenticated against the outside world. A deletion-only rejected precedent cannot be positively pattern-matched; it is recorded as an unmatchable coverage gap, while density and presence checks handle detectable loss. Pattern evaluation uses the standard-library regular-expression engine and has no general execution-time bound.
