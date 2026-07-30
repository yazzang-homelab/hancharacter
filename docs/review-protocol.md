# Corpus and precedent review protocol

This protocol produces evidence artifacts; it does not let a reviewer declare a contract sealed. Keep producer drafts, reviewer verdicts, precedent records, and human confirmations separate so each claim remains auditable.

## Corpus review

1. A producer adds a `corpus_draft` row to `catalogue/samples.draft.jsonl`. Its source declaration includes class, citation, how it was consulted, an independent-source key, and a passage locator. The stored quote length must equal the actual quote length and stay within 120 characters per row and 1000 characters per work.
2. Each reviewer independently reads the cited material and files one `corpus_review` JSON line in `catalogue/reviews/<reviewer-id>.jsonl`. The filename stem must equal every row's `reviewer` field. A producer must not review their own draft.
3. Use `accept` only when the row, marker, quote, and provenance declaration are supported; use `reject` when they are not; use `needs_review` when the claim is unresolved. Do not use a majority vote to erase disagreement.
4. Run `./bin/hancharacter corpus --lint` and then `./bin/hancharacter corpus --json --generated-at TIMESTAMP`. The merge preserves disagreement as `needs_review`, publishes third-reviewer information, and reports every unmet graduation condition.

A minimal reviewer line is:

```json
{"sample_id":"sample-id","reviewer":"reviewer-id","verdict":"accept","note":"checked marker, quotation, citation, and provenance"}
```

The only accepted verdict values are `accept`, `reject`, and `needs_review`. The optional note is for the reviewer’s audit trail, not an unvalidated authority. A reviewer files a line; the software joins it to a producer row and decides whether it counts.

`independent_key` counts independent sources, while `locator` detects consecutive-passage dumping. Mirrors of one publication share an independent key. A source class cannot outrank how it was consulted: `primary` requires direct reading or a fixture file; `secondary` may be direct-read, mirror, search-snippet, or fixture-file evidence; `cited_by` does not count as E1/E2 evidence.

## Precedent review

A precedent says what a published edition shipped; it is not a corpus-transcription verdict. Add a closed `precedent` row to `catalogue/precedents.jsonl` with its type, source and target languages, marker, rendering, edition channel, verdict, citation, and any contradiction links.

- Use `adopted` only for a rendering actually supported as shipped by an edition.
- Use `contested` when a rendering is proposed, incompletely verified, or editorially disputed.
- Use `rejected` for a documented bad rendering. Supply a target pattern set only when the bad rendering can be positively detected; deletion is absence, so a deletion-only precedent has no positive target pattern and remains an explicitly reported gap.

A contradiction blocks canonical graduation until a named human confirmation resolves it. A resolution id that is absent from the human-confirmation log is not a resolution. The precedent lint also rejects a claimed publication channel that lacks an adopted precedent for the same type.

## Graduation ladder

A type starts `observed`. It reaches `provisional` only with at least 3 accepted occurrences from at least 2 independent sources. It reaches `canonical` only when **all** of the following are true:

| Canonical criterion | Exact floor or condition |
| --- | --- |
| Accepted corpus occurrences | at least 8 |
| Independent sources | at least 3 |
| E1/E2 independent sources | at least 1 primary or secondary source |
| Adopted precedents | at least 1 |
| Open precedent contradictions | 0 |
| Dual-review agreement | at least 1 row with both reviewers agreeing |
| Human confirmation | at least 1 confirmation for that type |
| Inter-rater reliability | Cohen’s kappa is defined and at least 0.60 |

Kappa is undefined, not perfect, when reviewers have no disagreement opportunity. Accepted rows alone count as occurrences; `reject` and `needs_review` stay in the artifact but count toward no occurrence floor. A type that reaches provisional while missing a canonical criterion remains provisional, and a type with missing provisional criteria remains observed.

## Human confirmation: bounded work

A canonical type needs at least one human confirmation that names the type in its `confirms` list. The bounded workload is **at least one confirmation per canonical type**; it is not a demand to confirm every corpus row. Per-row human confirmation is required only for contested rows or to resolve a recorded contradiction. A confirmation must state its scope, the artifact read, its SHA-256, who confirmed it, and when; scope is not blanket approval of unrelated corpus rows, precedents, or target patterns.

File the confirmation as one closed `human_confirm` JSON line in `catalogue/human_confirm.jsonl`. For a review page that shows the currently pending corpus and confirmation work, run:

```sh
./bin/hancharacter review --out /tmp/hancharacter-review --format html \
  --generated-at 2026-07-30T00:00:00Z
```

The renderer binds the page to a canonical-JSON SHA-256 digest and refuses an unbound or stale payload. Verify the page’s displayed digest before filing a verdict; the renderer makes reviewable rows and the filing action visible, but it does not authenticate reviewer identity.

## What review cannot decide

Review can establish the recorded artifact claims and make disagreement visible. It cannot establish dialect semantic fidelity, authenticate a reviewer, verify the truth of an external citation without opening it, or turn unmeasurable axes into measured evidence. Record those limits rather than presenting their absence as a clean review result.
