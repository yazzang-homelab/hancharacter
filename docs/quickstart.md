# Quickstart

Run from a checkout with Python 3.9 or newer. There is no installation step and no network step:

```sh
cd /root/tmp/hancharacter
./bin/hancharacter version
```

**Top-level commands:** `version`, `profile`, `schema`, `measure`, `segment`, `types`, `corpus`, `precedents`, `dialect`, `review`, `budget`, `e2e`.

Run `./bin/hancharacter --help` for option help. The command list above is intentionally checked against `cli.build_parser()` by `tests/test_docs.py`; adding or removing a parser command requires updating this page.

## Inspect the shipped evidence

These commands do not write into the checkout. They validate the declared inputs and publish what the shipped catalogue can and cannot support.

```sh
./bin/hancharacter profile --profile profiles/crimson_fixture.json
./bin/hancharacter measure
./bin/hancharacter types --lint --target ko
./bin/hancharacter corpus --json --generated-at 2026-07-30T00:00:00Z
./bin/hancharacter precedents --lint --target ko
./bin/hancharacter dialect --lint
./bin/hancharacter review --out /tmp/hancharacter-review --format html \
  --generated-at 2026-07-30T00:00:00Z
```

The current `corpus` result is an honest stop: no shipped type is canonical, so a real contract cannot seal. Use the review output to file evidence; do not lower a graduation floor to make this command appear complete.

## Worked authored synthetic fixture

This short fixture contains only newly authored generic text. It exercises profile validation and segmentation without copying a game or script. It is not evidence for the shipped catalogue and does not demonstrate sealing.

```sh
work=/tmp/hancharacter-authored-fixture
mkdir -p "$work"
python3 - <<'PY'
import json
from pathlib import Path

work = Path("/tmp/hancharacter-authored-fixture")
profile = {
    "work": "authored-fixture",
    "voice_enforcement_mode": "voice_critical",
    "evidence_lang": "en",
    "pivot_lang": "en",
    "target_lang": "ko",
    "speaker_roles": {"speaker": "speaker", "close": "close"},
    "delimiters": {
        "en": {"speech": [["\"", "\""]], "term": []},
        "ko": {"speech": [["\"", "\""]], "term": [["「", "」"]], "speech_is_positional": False},
    },
}
rows = [{
    "key": "authored-001",
    "evidence": "<color=speaker>hello<color=close>",
    "pivot": "\"hello\"",
    "target": "\"안녕\"",
}]
(work / "profile.json").write_text(json.dumps(profile, ensure_ascii=False), encoding="utf-8")
(work / "rows.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
PY

./bin/hancharacter profile --profile "$work/profile.json"
./bin/hancharacter segment --profile "$work/profile.json" --rows "$work/rows.json" --json
```

The source and pivot are the same language in this fixture, so it is single-standard. That only permits a hard density result after a sealed contract exists; it does not create a contract or authorise a marker.

## End-to-end runs

`e2e` writes all artifacts below its required `--out` directory and prints a short summary. Keep the directory outside the repository.

`e2e --rows` reads every declared adapter format, not just JSON, so a real `.srt`, `.ass`, `.po`, `.vtt`, `.xlf`, `.csv`, `.epub`, or `.txt` reaches a full verdict. Use `--format` to force the format when the extension is wrong or absent; an undeclared extension is refused rather than silently read as JSON. A run whose input is not the pinned crimson fixture is labelled `"fixture": "operator_input"`, so an operator report can never be mistaken for the shipped evidence.

```sh
./bin/hancharacter e2e \
  --profile profiles/crimson_fixture.json \
  --rows "$HANCHARACTER_FIXTURE" \
  --out /tmp/hancharacter-e2e/crimson \
  --generated-at 2026-07-30T00:00:00Z
```

This is the real-catalogue run. It must publish the contract-seal stop and the unmet graduation criteria; it must not claim sealed contracts.

For a mechanics-only sealed run, use the built-in authored synthetic suite. It writes its synthetic catalogue, profile, rows, graduation report, seal report, and both gate-case reports under `--out`:

```sh
./bin/hancharacter e2e \
  --scenario voice-critical \
  --out /tmp/hancharacter-e2e/synthetic \
  --generated-at 2026-07-30T00:00:00Z
```

The suite constructs its catalogue outside the repository and independently reaches the exact canonical floors in `docs/review-protocol.md`, including accepted occurrences, independent and E1/E2 sources, an adopted precedent, a human confirmation, no open contradiction, and defined kappa. It seals one synthetic contract, proves a seeded LOSS is hard, and proves a faithful intermittent rendering passes without forcing the marker into marker-free scenes. Label this output synthetic; it is not a result for the shipped catalogue.

`--scenario seeded-loss` selects the expected nonzero LOSS case after writing the suite artifacts, while `--scenario faithful-intermittent` selects the expected zero-exit faithful case. `--scenario` cannot be combined with `--profile` or `--rows`.

## Inputs and artifacts

`schema --kind KIND --file FILE` validates one JSON object against a closed artifact schema. `types`, `corpus`, `precedents`, and `dialect` use the shipped catalogue unless a command explicitly accepts another catalogue boundary. `review` renders a digest-bound HTML or text review page into an external output directory.

`segment --profile PROFILE --rows ROWS` and `budget --profile PROFILE --rows ROWS` read any declared input format through the adapters: plain text, JSON, CSV, PO, XLIFF, SRT, VTT, ASS, EPUB, and the read-only host-shaped JSON mapping. The format is inferred from the declared extension, or forced with `--format`. An extension the adapters do not declare **fails loudly** rather than falling back to the JSON reader, because a silent fallback is how a whole format can appear to work while measuring nothing.

`budget` consumes the `budgets` block a profile declares and publishes the capacity report: subtitle CPL by display width and CPS from real timing, balloon character and area budgets, and advisory classes that still publish marker length. A row with no timing has no CPS verdict and is reported as unmeasurable rather than passed, and a declared bound is never widened to make a row fit.

See `docs/catalogue.md` before changing a type or realisation, `docs/review-protocol.md` before filing evidence, and `docs/gates.md` before interpreting a non-clean result.
