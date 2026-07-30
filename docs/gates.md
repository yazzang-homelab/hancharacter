# Gate order, severity, and waivers

A gate result is a `Finding` with a code and a severity. `hard` prevents a clean run; `report` is published and requires interpretation but does not by itself block. Every gate runs from artifacts supplied at its boundary. A mandatory gate that did not run emits a hard finding rather than looking like a pass.

## Fixed order

`gates.run()` executes these stages in this exact order:

1. **character-attribution** — validate attribution facts and reject an attempt to treat a T2-only attribution as confirmed or target-gateable.
2. **contract-seal** — require a sealed contract for every supplied character. A hard failure here marks capacity/length and character-corpus as not run.
3. **capacity/length** — check the declared layout boundary for each sealed contract.
4. **character-corpus** — run presence, narration residual, exclusivity, density, invention, quote-parity, and priority-ladder checks. This stage still runs when capacity/length has hard findings, because a length failure must not hide a voice failure.

After those stages, only current, hash-bound waivers are considered. An unmatched, stale, malformed, category-mismatched, or non-waivable waiver is itself visible; it never silently clears a result.

## Gate findings

The table names the findings emitted by the ordered gate boundary or forwarded to it from its required contract, attribution, density, segmentation, and ladder inputs. `both` means the same code has a hard and a report branch; inspect the emitted finding rather than inferring severity from its spelling.

| Code | Severity | Stage and condition |
| --- | --- | --- |
| `attribution_t2_confirmed` | hard | Attribution; a T2-only record was presented as confirmed or target-gateable. |
| `attribution_undeclared_label` | hard | Attribution input; markup label lacks a declared role. |
| `attribution_rows_empty` | hard | Attribution input; no rows can pass vacuously. |
| `attribution_dead_speaker_role` | report | Attribution input; a declared speaker role appears in no row. |
| `attribution_duplicate_source_deferred` | report | Attribution input; duplicate source is deferred rather than attributed apart. |
| `attribution_t2_pending` | report | Attribution input; heuristic attribution remains outside gating. |
| `contracts_empty` | hard | Contract seal or invention; no contract would make enforcement inert. |
| `contract_seal_missing` | hard | Contract seal; a callback returned no seal and no explanatory hard finding. |
| `contract_schema_invalid` | hard | Contract seal; the closed contract shape or sealed measurement pin is invalid. |
| `contract_type_not_canonical` | hard | Contract seal; a referenced type is not canonical. |
| `contract_source_measurement_unavailable` | hard | Contract seal; the source plugin, measurable axes, version, or golden digest is unavailable. |
| `contract_source_density_zero` | hard | Contract seal; a required axis whose measured source density is 0.0 either mis-measured the source or mis-specified the contract, and sealing it produces a gate that cannot fire. |
| `contract_coverage_floor_below_frozen` | hard | Contract seal; the work declares a `coverage_floor` below the frozen `COVERAGE_FLOOR_X` of 0.70. The lowered floor is refused unless a hash-bound `coverage` waiver clears it, so a bound can never be widened by declaration alone. A declaration at or above the frozen floor is stricter rather than weaker and is never flagged. |


| `contract_source_measurement_changed` | hard | Contract seal or corpus; runtime measurable axes differ from the sealed pin. |
| `contract_length_infeasible` | hard | Capacity/length; required realisation does not fit its declared layout. |
| `contract_required_glyph_unavailable` | hard | Contract seal; a required glyph is unavailable. |
| `contract_rejected_precedent_match` | hard | Contract seal; a selected realisation reproduces a rejected precedent. |
| `contract_speaker_coverage_below_floor` | hard | Contract seal; per-speaker coverage is below the artifact-derived floor. |
| `contract_dialect_pair_undecided` | hard | Contract seal; a declared dialect pair lacks its human ruling. |
| `contract_voice_drop_ledger_absent` | hard | Character corpus; no priority-ladder ledger was supplied. |
| `contract_voice_drop_ledger_invalid` | hard | Character corpus; a priority-ladder ledger entry is structurally unsafe. |
| `contract_ladder_marker_underrun` | hard | Character corpus; a priority ladder dropped a required marker. |
| `voice_observations_empty` | hard | Character corpus; target observations are absent. |
| `voice_observation_unnormalisable` | hard | Character corpus; an observation cannot yield a canonical surface. |
| `voice_enforcement_inert` | hard | Character corpus; a contract has no usable measurable axis, marker, or eligible units. |
| `voice_density_source_artifact_absent` | hard | Character corpus; source density or per-scene density is absent. |
| `voice_source_density_zero` | hard | Character corpus; a sealed contract has a required axis with zero source density, so its presence-class LOSS comparison is inert. |

| `voice_density_target_scenes_absent` | hard | Character corpus; no target scene is resolved for density. |
| `voice_band_unsealed` | hard | Character corpus; a caller-derived density band was used instead of a seal. |
| `voice_required_marker_absent` | hard | Character corpus; non-zero source density has zero required target presence. |
| `voice_forbidden_marker_present` | hard | Character corpus; a forbidden marker appears. |
| `voice-narration-clean` | both | Character corpus; hard on a zero-attribution row and report-only for residual narration beside attributed speech. |
| `voice_exclusivity` | hard | Character corpus; an exclusive marker appears in another protected scope. |
| `DENSITY_VERDICT` | both | Character corpus; report for prose fidelity, under-sampling, near tolerance, or inconclusive interval; hard only when the configured density rule proves it. |
| `voice_invention_catalogue` | hard | Character corpus; a catalogue marker appears without a contract requirement. |
| `voice_invention_novel_recurring` | report | Character corpus; a non-catalogue final form recurs at least the configured threshold. |
| `voice_invention_review_untriaged` | hard | Character corpus; a recurring novel-form review queue entry remains pending. |
| `voice-quote-parity` | both | Character corpus input; hard only when a pivot speech span has no visible target text, otherwise report-only. |
| `gate_input_contradicts_seal` | hard | Character corpus; a caller tries to override sealed marker or review data. |
| `gate_not_run` | hard | Any skipped mandatory stage. |
| `waiver_rejected` | hard | Waiver processing; the waiver is malformed, stale, unbound, mismatched, or forbidden. |
| `waiver_obsolete` | report | Waiver processing; its target finding no longer exists. |

## Density is directional but not saturating

The density metric detects both a marker disappearing and a marker being forced onto too many lines. For a single-standard `voice_critical` contract, only a sufficiently sampled target whose point estimate and Wilson interval lie beyond the p10–p90 band plus `OUTER_TOL=0.15` can produce a hard density verdict. Below `MIN_UNITS_PER_SCOPE=20` or `MIN_SCENES_PER_BAND=5`, the result is report-only. A dual-standard source/pivot pair widens the band by `DUAL_STD_WIDEN=0.10`, and `prose_fidelity` makes density report-only; required-marker presence, forbidden markers, exclusivity, and invention remain hard where their conditions hold.

## Non-waivable findings

The following exact set is taken from the gate implementation’s closed non-waivable classification. No waiver category, including a future category, may clear any of them.

- `voice_required_marker_absent`
- `voice_forbidden_marker_present`
- `voice_exclusivity`
- `voice_invention_catalogue`
- `voice_invention_review_untriaged`
- `contract_ladder_marker_underrun`
- `contract_voice_drop_ledger_absent`
- `contract_voice_drop_ledger_invalid`
- `gate_not_run`
- `contract_source_density_zero`
- `voice_source_density_zero`

A waiver is valid only when it is a closed waiver artifact, names a code that actually arose, binds to the current sealed contract hash, is not stale, and uses a category that permits that code. The only currently waivable code families are density under the `policy_density`, `arc_scope`, `edition_variant`, or `dialect_ruling` categories, and coverage-floor failure under `coverage`. A glyph fallback category records renderer work but clears no gate finding. Waivers are artifacts to publish, not a way to make an absent check disappear.
