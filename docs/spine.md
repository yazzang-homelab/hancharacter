# Segmentation spine

The measurement unit is a per-`(row, speaker)` attributed group. All declared
speaker-colour spans for that speaker in a row are joined into one evidence
unit; all matching speech spans on a pivot or target side are likewise joined
into at most one unit. The source spans remain attached to the group for
report-only per-span and per-sentence analysis. A newline is layout, not a
unit boundary, and control markup is stripped from measurement surfaces.

Evidence attribution is declaration-driven. Only a colour label whose profile
role is `speaker` creates a scope. Pronoun, term, system, and close labels do
not create a speaker scope. A colour label absent from the profile makes the
row ineligible instead of guessing an attribution.

## Quotes and scope extent

Delimiter pairs are matched across markup. H1 inspects the opener in its text
stretch, which is split only by non-layout markup: declared `layout_tags` and
`page_tags` remain in the same stretch and cannot manufacture a new
stretch-initial position. It is speech only when it is the first
non-whitespace content in that stretch. A pair later in the stretch is a term,
as is a pair using an explicitly declared term delimiter. Terms are excluded
before quote parity counts. The quote span, rather than its surrounding stretch,
is the scope extent, keeping an attributive clause in the same stretch out of
the speaker group.

`delimiters` is a required profile key; it must declare a non-empty speech
delimiter list for the evidence, pivot, and target languages. A missing or
malformed per-language declaration is a hard error, never a no-speech result: a
silent zero-span result would make the parity gate unreachable and empty every
density denominator.

There is at most one grouped unit per row, speaker, and side. A 1:0 source to
pivot result is an unrealised scope counter, not an equality failure; it is
reportable loss and does not enter a coverage numerator. Group base text keeps
ruby base characters, while the reading surface keeps base plus reading for
lexical axes.

## Eligibility and published counts

A row with two declared speaker scopes, an undeclared colour label, an
orphaned declared delimiter, or a caller-supplied duplicate-source flag is
ineligible. Pure narration is clean but contributes no scope. The report
publishes `ineligible_rows` separately from the per-reason multiset, and also
publishes `pure_narration_rows`; a reason total is not a row total.

On an eligible row with a target, quote parity is **hard in exactly one case**:
the target has no visible text at all while the pivot carries a speech span. The
utterance was translated to nothing.

Every other count difference is report-only, because a speech-span count is not
comparable across sides as a verdict. Whether a quoted span counts as speech
depends on each language's declared `speech_is_positional`, and the shipped
profile deliberately declares the pivot positional and the target not — so an
attribution-first pivot (`He said, "A."`, whose quote sits mid-stretch and reads
as terminology) counts zero speech spans against a faithful target's one.
Dropping quotation marks is likewise a typographic choice, not lost voice. And on
an eligible row the evidence side always carries a speaker scope, so a pivot with
no quoted span means the *pivot* dropped a line the source has — already
published as `voice_scope_unrealised` — and a target restoring it is faithful to
the source. Detecting a fabricated voice is the job of the catalogue-anchored
invention scan, not of a span count.

Each unit carries a scene **field**, which may be `None`. A declared
`scene_pattern` is searched against the whole row key first and then against the
key's last `/`-separated segment, and the first match wins; only when neither
matches does the report use the row's own `scene` field. The two candidates exist
because a host container builds keys as `family/key`, so a pattern anchored to the
key alone would never match on the command path.

Whether a scene can be read out of the family segment is therefore a property of
the declaration, not of the code: the shipped anchored pattern cannot match the
family segment, but an unanchored one would be searched against the whole key and
could. The schema requires a capture group, not an anchor. Because only the
basename is tried second, two families sharing a key prefix would also share a
scene bucket; the reference corpus has no such collision. Resolution lives in the spine, so a direct
caller and the command agree. A unit whose scene cannot be resolved is invisible to
the per-scene band and therefore caps the density verdict at `report` through
under-sampling, so the count is published as `units_without_scene` rather than
dropped quietly. Per-scope reports publish `scene_counts` and `n_scenes` alongside the
per-speaker evidence, pivot, target, and coverage counts.

For a single-standard work, declared colour runs in the same source text make
scope assignment exact, independent of intervening control markup. That
single-standard exactness is the reason density may be hard-gated there;
dual-standard work uses the same groups but is report-only.

## Fixture hand table

| Row | Scope | Evidence units | Pivot units | Both sides | Note |
| --- | --- | ---: | ---: | --- | --- |
| `mes10_FM_008` | `lippi1` | 1 | 1 | yes | Attributive clause excluded from scope. |
| `mes08_FM_004` | `frea1` | 1 | 1 | yes | One quote holds two sentences. |
| `mes08_FM_002` | `frea1` | 1 | 1 | yes | Two evidence runs collapse to one group. |
| `mes08_FM_005` | `giauque1` | 1 | 0 | no | Pivot-deleted utterance is reported separately. |
| `mes13_FM_004` | `frea1` | 1 | 1 | yes | Quote and unquoted laughter collapse. |
| `mes14_FM_002` | `lippi1` | 1 | 1 | yes |  |
| `mes15_FM_001` | `lippi1` | 1 | 1 | yes | Mid-stretch term quote is excluded. |
| `mes16_FM_002` | `frea1` + `giauque1` | — | — | ineligible | Mixed speaker span. |
| `mes16_FM_001` | none | 0 | 0 | n/a | Pure narration. |

## Deferred to later phases

`precedent`, `corpus_sample`, and `realisation` artifacts have no id or join
columns yet. P1 adds those columns when it writes the catalogue; this is a
gap, not current coverage.

P1 must extend the **closed** `schemas.py` and its tests as well as adding the
catalogue data: an `id` on a `precedent` is rejected today as an unknown key.

P2 owns a band-construction constraint: require a per-scene unit floor (or pool
scenes) and publish per-scene unit counts on every density row. A finely declared
`scene_pattern` can yield roughly one unit per scene, making the band span the
whole range so no unit falls outside it while `n_scenes` still clears
`MIN_SCENES_PER_BAND`. P2 must also declare which segmentation count supplies
`n_units` — `attributed_units` or the `eligible_units` denominator the canonical
density actually divides by. On the reference fixture the two straddle
`MIN_UNITS_PER_SCOPE` for `flint1` (22 against 18), so the choice decides whether
that speaker's density verdict is permanently report-only.

`contract` is a v0 shape. Its provenance (`plugin_version`, `golden_digest`,
and spine/profile digests) and sealed measurement block (`d_src`, band,
`n_units`, `n_scenes`, mode) are added by P2 when a seal exists. These fields
are absent now and are not asserted as coverage.

## Limitations

Pattern evaluation is not time-bounded by the standard-library regex engine. The
schema rejects the common nested-quantifier shape, but that heuristic cannot
recognise every expensive expression. Pattern sets are trusted declarations
sealed by review, not untrusted runtime input.

A validated declaration is frozen (`MappingProxyType`, nested maps wrapped, lists
become tuples), so ordinary mutation of `profile.data` raises. That does not make it
tamper-proof: `object.__setattr__` can still replace the private payload, and no
pure-Python object can prevent it. The threat model is accidental corruption and
model error, not a local editor deliberately defeating the guard — the same model
the artifact digests assume.

An empty target is deliberately not the same as a missing one. A missing target is
work not yet done and has nothing to compare; a target that is present and empty is
an utterance translated to nothing, which is the loss the parity check exists to
catch, so it fails hard.

For target visibility, a **bare** declared `term` tag (`<player>`, `<item>`) counts
as content because it renders a runtime substitution. A colour tag never counts, even
when its declared label carries the `term` role — the reference profile declares the
highlight colour `keyword1` that way, and treating it as content would let a target
reduced to colour markup pass the only hard gate the spine has. Blankness is decided
by Unicode category (`Cf`/`Cc` render nothing) rather than by a list of code points. Declared `speaker`, `pronoun`, `system`, and `close` tags, and
undeclared control or formatting markup, do not count as content; a target made
only of control or formatting markup is judged emptied.

Per-row analysis is recomputed rather than cached: `segment_report` runs
`eligibility`, then `quote_parity` recomputes it and rescans both sides, and
`side_units` scans again. The scan chain therefore repeats for each eligible
row. Measured cost is invisible at the 4052-row reference corpus and is untuned;
the expensive branch is the one with a target column populated, which no shipped
fixture exercises.

Evidence can shrink by declaration, and only the extreme case is rejected. A
plugin may flip an axis to `not_applicable` and still pass conformance, so
`measurable_axes` shrinks with no failure. A declared speaker re-declared `term`
or `system` vanishes entirely: scopes and coverage are built only from
`speaker`-role labels, its rows become `pure_narration_rows`, and the command
exits 0. Only an all-non-speaker profile is refused. The mitigation is a seal
that pins the per-language `measurable_axes`, the plugin `VERSION` and
`golden_digest`, and the declared speaker set, and hard-fails a later shrink.

`closes_on_role_change` closes a pending opener at **any** declared label, not only
at a change of speaker role, which is wider than its name suggests. It is declared
for the evidence language of the reference profile, where the container opens a
quote and never closes it before the colour reset. Enabling it converts a row that
would otherwise be excluded as an orphaned delimiter into a measured one. For a
language whose opener equals its closer the implicit close leaves the following
quote character to be read as a new opener, which would produce a spurious
`unsplittable_payload`; no shipped language declares that combination.
