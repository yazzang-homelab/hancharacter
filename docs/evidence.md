# The evidence pipeline (P1)

The typology is only legitimate if a marker type has to earn its place. This phase
implements that earning: a source-side type catalogue, target realisations, a
corpus of cited occurrences under independent dual review, a table of what
published editions actually shipped, and a graduation rule that refuses to promote
a type the evidence does not support.

Nothing here decides whether a translation is good. It decides whether a claimed
speech-style type is real enough to enforce.

## Layout

```
catalogue/VERSION                        catalogue version, stored in every contract
catalogue/types/<id>.json                source-side type, language-neutral
catalogue/realisations/<target>/<id>.json  how one type is realised in one target
catalogue/probe/<lang>.jsonl             authored probe utterances
catalogue/samples.draft.jsonl            producer's proposed corpus rows
catalogue/reviews/<reviewer>.jsonl       one reviewer's independent verdicts
catalogue/precedents.jsonl               what published editions shipped
catalogue/human_confirm.jsonl            human confirmations, with stated scope
catalogue/dialect_decisions.jsonl        operator rulings on dialect pairs
catalogue/SOURCES.md                     human-auditable provenance ledger
```

The catalogue lives under `config.typology_root()`, deliberately separate from
`config.catalogue_root()`. Types and precedents are reusable knowledge about a
language pair; a contract is a sealed claim about one character in one work.
Storing them together would make a per-work seal look like catalogue evidence.

## Why drafts and reviews are separate files

`corpus.merge` joins `samples.draft.jsonl` with two or more `reviews/*.jsonl` into
validated `corpus_sample` rows. The split is not organisational. If one author
wrote a row together with both of its reviewer verdicts, "dual review agreeing"
would be one opinion typed three times, and the kappa computed over it would be a
self-agreement score. Reviewer independence is a property of the file layout, and
the loader refuses a review file whose `reviewer` field disagrees with its
filename so nobody can file under another name.

Disagreement resolves to `needs_review` rather than to a majority. A row two
reviewers read differently is exactly the row a human should look at.

## Kappa may be undefined, and undefined is not agreement

Cohen's kappa needs variance. When both reviewers used one identical category on
every row there is no disagreement opportunity, so `cohens_kappa` returns `None`.
It is never coerced to 1.0: a kappa of 1.0 asserted from zero disagreement
opportunities is the strongest possible agreement score manufactured from the
weakest possible evidence. The canonical rule treats `None` as unmet.

## Provenance is cross-checked, not trusted

Every corpus row declares `source.class` (what the row is) separately from
`source.consulted_via` (how it was actually reached), and the schema rejects a
class that outranks the provenance:

- `class: primary` requires `consulted_via` in (`direct_read`, `fixture_file`). A
  wiki mirror is not the work itself.
- `class: secondary` requires `consulted_via` in (`direct_read`, `mirror`,
  `search_snippet`, `fixture_file`). `cited_by` is hearsay, and hearsay that counts
  toward a graduation floor is a fabricated floor.

The rejection is outright rather than a silent downgrade, because a downgrade would
leave the row counting toward a floor its author believed it cleared.

## Two granularities, on purpose

`source.independent_key` answers *is this a separate source*: mirrors and separate
articles of one publication share one key, so four articles on one wiki count once
toward the independent-source floor.

`source.locator` answers *is this the same passage*. Consecutive-row dump detection
keys on the locator, because three rows quoting three different articles are not a
transcription. The n-gram reassembly check keys on the coarser `independent_key`,
because rebuilding a passage across two articles of one publication is still
rebuilding it.

Collapsing the two was a real defect during construction: keying dump detection on
`independent_key` alone made an honest, well-spread corpus unshippable, which is a
rule that punishes faithful collection instead of catching redistribution.

The reassembly check also removes the row's own declared marker before comparing.
Under this tokenisation each Hangul or kana syllable is one token, so an
eight-token run is only about eight characters and a marker string is often longer
than that. Two rows cataloguing `~지 말입니다(~であります)` for two different characters
would otherwise be reported as reassembling a passage, when quoting one marker
twice is precisely what a marker corpus is for.

## Distinguishability, and a deviation from the plan text

Two types or realisations must be separable, or the catalogue asserts a difference
it cannot measure. Separability is decided by one measure over one authored probe
corpus: `matched_markers` gives the set of probe rows a pattern set matches, and
`jaccard` compares two such sets. The same pair backs the rejected-precedent
matcher, so a pair cannot be simultaneously distinct enough to keep and similar
enough to be the rejected rendering.

**The implemented rule.** A pair is *indistinguishable*, and must be merged as
`preset` + `overrides`, iff `jaccard >= 0.5`. The marker measure alone decides it.

**The plan text says** a pair is *distinct* iff `jaccard < 0.5` **and** the bands do
not overlap. Read literally that is inverted: because most bands overlap, a
genuinely distinct pair would be forced to merge, and the lint would fire on
faithful catalogue work. `tests/test_typology.py::
test_the_plain_reading_of_the_plan_would_force_a_spurious_merge` carries the case.

**The De Morgan flip this module first shipped was also wrong**, in the other
direction, and review caught it: `jaccard >= 0.5 AND bands overlap` let `not
overlapping` alone certify distinctness at Jaccard 1.0, so two realisations with
byte-identical pattern sets passed if the author declared disjoint default bands.
The silencing input was a free-choice field in the file the author was writing.

The band could never have carried this decision anyway: `resolve_axis_set` and
`schemas._validate_resolved_axes` carry no band into the sealed contract axis, and
`density_band_default` is a default any per-character contract overrides. A
distinction that evaporates at the seam where enforcement begins is not a
distinction. So the band conjunct is gone, and both cases are pinned by tests — the
faithful pair at Jaccard 0.0 stays silent, and the identical-pattern pair is
reported however the bands are set.

Once a merge exists the pair stops being reported, or the only way to silence the
finding would be to delete a row and the lint would be punishing its own remedy.

**Empty match sets are not distinctness.** Two pattern sets matching nothing means
the probe corpus cannot separate them, so `jaccard` returns 1.0 for empty/empty and
an empty match set is independently hard. A pattern that can match nothing is a
check that can never fail.

## Presets validate twice

A row carrying `preset` is a derivation and may omit what the preset supplies, so
the closed schema relaxes its required set for that row. The **resolved** artifact
then faces the full schema in `typology`. The two checks answer different
questions: is this derivation well-formed, and is what it resolves to complete.

`ko_danakka_jimalimnida` is a real derivation: `~っス` and `~であります` are different
source markers that ship the same Korean convention, so one realisation derives
from the other rather than two rows asserting they differ.

## Deletion cannot be a positive pattern

The rejected-precedent matcher catches a realisation that reproduces a specific
wrong rendering. It cannot catch *deletion*, because deletion is the absence of a
marker.

Encoding a LOSS precedent as a positive pattern was a real defect during
construction: giving the "marker deleted, rendered as plain `~입니다`" precedent a
pattern of `입니다$` made it match every faithful polite Korean line, including the
correctly marked `~지 말입니다`. LOSS precedents therefore carry no
`target_pattern_set`, the matcher emits `precedent_rejected_unmatchable` as a
recorded gap, and detecting deletion is the density metric's job.

## The dialect gate has no default

`flavour_lexicon` is the default target strategy. `full_substitution` — mapping a
source region onto a real target region — requires an adopted precedent for that
specific pair and corpus evidence at the graduation floor. An operator ruling does
not manufacture either.

Where a work declares a dialect pair with no recorded ruling, `gate` emits a hard
`dialect_pair_undecided` and the pipeline stops. This is the one place the project
asks a human, because the choice is editorial rather than measurable, and a default
would be the system quietly making an editorial decision and reporting success.

Rulings are bound by `sha1(source \0 target \0 work)`. The NUL separators are
load-bearing: without them `("a","bc")` and `("ab","c")` hash identically and one
ruling would authorise a different pair. A row whose stored hash disagrees with its
own fields is stale and is not honoured, which is what invalidates a ruling after
an edit.

## Patterns must not match ordinary speech

A pattern set that fires on unmarked speech is worse than useless in both
directions at once: it scores faithful translation as LOSS by inflating the source
density it compares against, and it lets a flattened translation register as
carrying the marker. `ja_otaku_copula` excludes the generic `~だね` for exactly this
reason.

Review found four shipped pattern sets that failed that standard, one of them
provably: `のだ$` matched the probe corpus's own unmarked baseline row
`その荷物は誰のものだ。`. The systemic cause was that the corpus shipped rows authored to
be controls and nothing could use them as controls, and that non-vacuity was
asserted per pattern *set* rather than per pattern, so 11 dead patterns lint
clean inside otherwise-live sets.

Three checks now exist:

- Every probe row declares `markedness`. A pattern matching an `unmarked` row is a
  hard `typology_pattern_matches_unmarked_row`.
- Non-vacuity is reported per pattern index. An unprobed pattern is `report`, not
  hard: a probe corpus need not cover every attested variant, and making it hard
  would punish honest breadth. A wholly empty match set stays hard.
- The probe matcher compiles with the same flags as the frozen enforcement matcher.
  It did not before, so `\bzis\b` failed to match its own sentence-initial probe
  row and two enforced patterns carried no verification at all.

## An axis must be measurable on the side it is measured on

Every measure plugin checks its own `AXES` declaration **before** consulting a
caller's `pattern_set`. So a marker on an axis its plugin calls `not_applicable` has
a constant density and its patterns are never applied — the contract's own pattern
set is dead.

The source axis and the target axis are different questions. Korean renders a
Japanese *speech-level* marker as a sentence-*ending* transform, so a realisation
declares `target_axis` when the mechanism differs. `axis_measurability` reports a
marker whose axis its plugin cannot measure, and `sealable` / `resolve_axis_set`
**refuse to seal** it: cataloguing an unmeasurable marker is honest, sealing one
produces a contract whose gate can never fire.

On the shipped catalogue eight of the nine seed types are sealable.
`ja_chuunibyou_frame` is refused, because `measure/ja.py` declares `utterance_frame`
`not_applicable` and its source density is therefore a constant.

## A publication channel must be backed by a published precedent

`edition_channel` says which kind of edition shipped a rendering. Nothing read the
field until review found six of nine realisations claiming `licensed`, `official` or
`community` for renderings their own cited precedents record as unpublished project
proposals — a false provenance string on the artifact a contract seals.
`channel_backing` now hard-fails a claimed channel no cited *adopted* precedent
supports, and the six were corrected to `unpublished`.

## What the shipped catalogue actually achieves

Run `hancharacter corpus` for the current numbers. As shipped:

- **0 of 10 types are canonical.** Two (`ja_hao_gozaru`, `ja_elder_lexicon`) are
  `provisional`; the rest are `observed`. `ja_hao_gozaru` meets every canonical
  criterion except one: **no adopted precedent**, because the only candidate was
  corrected down to `contested` for consistency with its siblings.
- Overall inter-rater kappa is **87/143 (0.6084)** across 42 reviewed rows against the **0.60** floor. The canonical type's own kappa is **exactly 3/5**, which meets the floor without clearing it.
- `e1e2_sources` is **0 for seven of ten types**. Three (`ja_hao_gozaru`,
  `ja_elder_lexicon`, `ja_nyan_copula`) are each supported by **one** secondary
  source, a departmental bulletin paper (紀要論文, non-refereed). Every type sat at
  zero before this round, which blocked canonical regardless of any other criterion.
- **The canonical type crossed the kappa floor by dilution, not by improved
  reliability.** Its kappa was 1/2 over the eight original rows, which contained two
  disagreements. Eight new rows were added on which both reviewers agreed, and
  because Cohen's kappa rises monotonically when modal-category agreements are
  appended, those two disagreements were diluted until kappa reached exactly 0.60.
  Remove any one of the eight and kappa is 22/37 = 0.5946 and the type is not
  canonical. So `KAPPA_FLOOR` is clearable by anyone willing to add rows that are
  easy to agree on. This is pinned by
  `tests/test_shipped_evidence.py::KappaFloorWasCrossedByDilutionTests`.
- `ja_danakka_dearimasu` additionally carries an **unresolved contradiction** — an
  adopted rendering and a documented deletion of the same marker — awaiting a human
  ruling.
- `dialect_decisions.jsonl` is **empty**, so the dialect gate fires for any work
  declaring a dialect pair.

This is the honest state of the evidence, not a placeholder. P1 is a hard gate
before contracts, and it remains **closed**: no type can back a sealed contract.
What changed is *why*. The evidence-volume and `e1e2_sources` blockers are closed
for `ja_hao_gozaru` — 12 occurrences, 4 independent sources, one secondary source,
kappa 0.600 — and the single remaining gap is precedent verification: no published
edition or broadcast record has been cited for any Korean rendering of this marker.
That is a narrower and more actionable gap than "no evidence at all", but it is
still a closed gate. The remedy is a verified published rendering, and for the
other nine types more independent sources and directly-read editions, not a lower
floor. `catalogue/SOURCES.md` lists exactly what is missing.

The numbers above that a test actually reads are pinned by
`tests/test_shipped_evidence.py`, including the exact kappa (87/143), the
19-of-42 source concentration, the dilution counterfactual and the single open
contradiction. No test parses this file's prose, so the sentences here are
maintained by hand and can drift; the machine-checked statements live in
`README.md`, which `tests/test_docs.py` asserts verbatim. Before that file existed the doctrine's "re-derivable from artifacts"
was satisfied only by a human re-deriving them, so the documents and the code could
have drifted apart silently.

## Declared limitations

- One publication supplies 19 of 42 draft rows, so independent-source floors are
  hard to clear honestly.
- No row claims `primary` provenance; no published edition was opened directly.
- Reviewer identity is unauthenticated and the artifacts are unsigned. Nothing
  cryptographically binds a verdict to a person.
- The schema can check that a claimed source class is *consistent* with a claimed
  provenance; it cannot check that the claimed provenance is true.
- The human confirmation covers the **type list and the Korean realisation
  strategy only**, not any individual marker row, and it is recorded with that
  scope written out.
- Dialect semantic fidelity remains unmeasurable; the gate records a decision, it
  does not evaluate one.
- A rejected precedent with no target pattern set cannot be matched mechanically,
  and that gap is reported per realisation rather than passed over.
- 9 shipped patterns match no probe row (the count is pinned by
  `tests/test_shipped_evidence.py`). They are enforced without
  verification, reported as `typology_pattern_unprobed`, and are a coverage gap
  rather than a defect in the patterns themselves.
- `ja_chuunibyou_frame` cannot be sealed: its source axis is not measurable by the
  current Japanese plugin. It stays in the catalogue because it is a real,
  human-confirmed speech-style type.
- The human confirmation is counted from its `confirms` list; its `scope` is prose
  that no consumer parses. It therefore satisfies the canonical human-confirmation
  criterion for the nine listed types, and the other unmet floors are what actually
  hold those types back.
- `profiles/crimson_fixture.json` declares `edition_medium: game/3ds`, which is not
  an `edition_channel` value, so sibling selection cannot be automated from it.
  `select_sibling` refuses an ambiguous set rather than guessing, which is the safe
  direction, but the mapping from medium to channel does not exist yet.
- Both reviewer files were produced in one automated run applying one rubric. They
  are independent in the sense the file layout enforces — separate files, producer
  excluded, per-reviewer verdicts recorded — but not in the sense of two unrelated
  people, and nothing cryptographically binds either verdict to a reviewer.
- A reviewer records a verdict against a sample id, not against the digest of the
  page they reviewed. `review.py`'s digest binds the page to its own content; it
  cannot bind a verdict to the content it was made about.
