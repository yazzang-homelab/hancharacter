# hancharacter operator skill

Use this tool to make an auditable claim about a character's speech-style markers. Treat the repository catalogue as evidence under review, not as a permission slip to seal every type.

## Operating rule

Start with declared source, pivot, and target rows plus a closed work profile. Run the standalone commands in this order:

1. Validate the profile and measurement plugins.
2. Segment rows and publish attribution, eligibility, scenes, and coverage.
3. Lint the type catalogue, corpus graduation report, precedents, and dialect decisions.

The current CLI has no operator command to create or seal a contract, or to run capacity and character-corpus gates over one. Do not represent those unavailable commands as operator steps; the authored synthetic `e2e` suite demonstrates those mechanics without becoming a result for a real work.

Do not fabricate a canonical stage, omit an unmeasured row, use a caller-supplied band in place of a sealed band, lower a floor, or treat a report as a pass. A skipped mandatory gate is a hard result, not an empty result.

Measure the target on the realisation's declared `target_axis`, not on the source axis. They differ: `ja_hao_gozaru` is measured on `speech_level` in Japanese, while the Korean plugin declares that axis `not_applicable` and measures `ending_transform`. Measuring a target on the source axis returns `False` silently, which reads as a total loss when nothing is lost.

## Boundaries

The shipped catalogue has no canonical type, so it cannot seal a `precedent_backed` contract. `ja_hao_gozaru` is one criterion away, lacking an adopted precedent, and an adopted precedent was searched for and not found — `catalogue/SOURCES.md` records what was searched and why each avenue fell short. A synthetic fixture catalogue may demonstrate the sealed-contract mechanics only when it genuinely satisfies the graduation rule; label that run synthetic in its report. Never present it as a result for the shipped catalogue or for a real work.

## Two authorities

A contract must declare what entitles it to enforce a rendering, and there is no default: a contract declaring neither authority is refused.

`precedent_backed` requires a canonical type, meaning a cited published edition shipped this rendering. It asserts the rendering is the established convention.

`translator_declared` requires the source-side evidence only. It asserts **nothing** about which Korean rendering is correct — only that the rendering the translator declared is applied at the source's measured density, consistently and exclusively. Use it for a first translation, a new work, or an original character, which is where an adopted precedent cannot exist.

Never describe a `translator_declared` result as evidence that a rendering is correct Korean. The authority is bound into the seal hash and stamped on every gate summary precisely so the weaker claim cannot be reported as the stronger one. Dropping the adopted-precedent requirement did not drop the rejected-precedent refusal: a declared rendering that matches a published flattening is still refused.

Enforcement does not branch on authority, so LOSS and INVENTION behave identically under both routes.

Use `docs/quickstart.md` for checkout-only invocation, `docs/review-protocol.md` for filing human evidence, and `docs/gates.md` for severity and waiver rules. The actual segmentation and evidence semantics are in `docs/spine.md` and `docs/evidence.md`.

## Human decisions

A declared dialect pair without a recorded ruling stops the work. A reviewer may decide the editorial strategy, but the ruling does not manufacture the adopted precedent or corpus evidence needed by full substitution. Human confirmation records what was reviewed and its hash; it does not erase unrelated unmet graduation criteria.

## Result language

Say “hard”, “report”, “not run”, or “not measurable” exactly as the emitted artifact says. Do not call an incomplete, skipped, synthetic, or report-only result “passed”.
