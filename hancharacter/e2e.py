"""Reproducible end-to-end evidence runs.

The real fixture run is deliberately allowed to stop at the contract boundary.  It
must not manufacture a seal from an ungraduated catalogue.  The separate synthetic
run owns its catalogue and corpus evidence so it can exercise the sealed gate path
without claiming anything about the real fixture.
"""
from collections import defaultdict
import hashlib
import json
import os
import re
from types import SimpleNamespace

from . import attribution, config, contracts, corpus, density, findings, gates, io_adapters, measure
from . import segment, typology



_DEFAULT_GENERATED_AT = "1970-01-01T00:00:00Z"
_REPORT_KEYS = {
    "kind",
    "generated_at",
    "run",
    "fixture",

    "status",
    "cli_invocation",
    "profile",
    "segmentation",
    "attribution",
    "density",
    "gates",
    "contracts",
    "intermittent_band",
    "limitations",
    "leader_schema_actions",
    "schema_validation",
}
_SUITE_KEYS = {
    "kind",
    "generated_at",
    "run",
    "fixture",

    "status",
    "cli_invocation",
    "contracts",
    "runs",
    "leader_schema_actions",
    "schema_validation",
}


def _json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _write_json(path, value):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")


def _write_text(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _outside_repository(path):
    root = os.path.realpath(config.repo_root())
    output = os.path.realpath(path)
    if os.path.commonpath((root, output)) == root:
        raise ValueError("e2e output must be outside the repository")
    return output
def _shell_quote(value):
    return "'" + value.replace("'", "'\"'\"'") + "'"




def _require_timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z", value
    ):
        raise ValueError("generated_at must be an ISO-8601 UTC timestamp ending in Z")


def _schema_actions():
    return {
        "config.py": "No frozen constant change is required.",
        "schemas.py": (
            "Add an e2e_report kind and a closed validator for the report shape "
            "published by hancharacter.e2e; schemas.KINDS currently has no e2e_report kind."
        ),
    }


def validate_report(report):
    """Validate the local, closed report boundary until ``schemas`` owns it."""
    errors = []
    if not isinstance(report, dict):
        return ["e2e_report: expected object"]
    if set(report) != _REPORT_KEYS:
        errors.append("e2e_report: keys must be exactly %s" % sorted(_REPORT_KEYS))
    if report.get("kind") != "e2e_report":
        errors.append("e2e_report.kind must be e2e_report")
    try:
        _require_timestamp(report.get("generated_at"))
    except ValueError as exc:
        errors.append(str(exc))
    for key in ("run", "status", "cli_invocation"):
        if not isinstance(report.get(key), str) or not report[key]:
            errors.append("e2e_report.%s must be a non-empty string" % key)
    profile = report.get("profile")
    if not isinstance(profile, dict) or set(profile) != {
        "work", "mode", "dual_standard", "coverage_floor", "target_lang"
    }:
        errors.append("e2e_report.profile has an invalid closed shape")
    elif profile["mode"] not in config.ENFORCEMENT_MODES:
        errors.append("e2e_report.profile.mode is not configured")
    if report.get("fixture") not in ("crimson", "synthetic", "operator_input"):
        errors.append(
            "e2e_report.fixture must identify crimson, synthetic, or operator_input evidence"
        )

    segmentation = report.get("segmentation")
    if not isinstance(segmentation, dict) or set(segmentation) != {
        "coverage", "eligible_segments", "ineligible_by_reason", "counters"
    }:
        errors.append("e2e_report.segmentation has an invalid closed shape")
    else:
        coverage = segmentation["coverage"]
        if not isinstance(coverage, dict) or not coverage:
            errors.append("e2e_report.segmentation.coverage must be non-empty")
        expected_reasons = {
            config.INELIGIBLE_MIXED_SPAN,
            config.INELIGIBLE_DUPLICATE_SOURCE,
            config.INELIGIBLE_PENDING,
            config.INELIGIBLE_UNDECLARED,
            config.INELIGIBLE_UNSPLITTABLE,
        }
        if set(segmentation["ineligible_by_reason"]) != expected_reasons:
            errors.append("e2e_report must publish every ineligibility reason")
    if not isinstance(report.get("attribution"), dict) or "t1_rate" not in report["attribution"]:
        errors.append("e2e_report.attribution must publish t1_rate")
    if not isinstance(report.get("density"), dict) or set(report["density"]) != {
        "scope_verdicts", "under_sampled_scopes", "per_speaker_source_signed_delta"
    }:
        errors.append("e2e_report.density has an invalid closed shape")
    if not isinstance(report.get("gates"), dict) or set(report["gates"]) != {
        "density_policy", "presence_policy", "executed", "invention_count", "narration_clean_count",
        "hard_findings", "report_findings", "summary"
    }:
        errors.append("e2e_report.gates has an invalid closed shape")
    if not isinstance(report.get("contracts"), dict):
        errors.append("e2e_report.contracts must be an object")
    if not isinstance(report.get("intermittent_band"), dict):
        errors.append("e2e_report.intermittent_band must be an object")
    if not isinstance(report.get("limitations"), list):
        errors.append("e2e_report.limitations must be a list")
    if report.get("leader_schema_actions") != _schema_actions():
        errors.append("e2e_report.leader_schema_actions does not name the required owner work")
    schema = report.get("schema_validation")
    if not isinstance(schema, dict) or set(schema) != {
        "validator", "registered_schema_kind", "errors"
    }:
        errors.append("e2e_report.schema_validation has an invalid closed shape")
    return errors


def validate_suite(report):
    errors = []
    if not isinstance(report, dict):
        return ["e2e_suite: expected object"]
    if set(report) != _SUITE_KEYS:
        errors.append("e2e_suite: keys must be exactly %s" % sorted(_SUITE_KEYS))
    if report.get("kind") != "e2e_suite" or report.get("run") != "synthetic-voice-critical":
        errors.append("e2e_suite has the wrong kind or run")
    if report.get("fixture") != "synthetic":
        errors.append("e2e_suite.fixture must be synthetic")
    try:
        _require_timestamp(report.get("generated_at"))
    except ValueError as exc:
        errors.append(str(exc))
    if not isinstance(report.get("runs"), dict) or set(report["runs"]) != {
        "seal", "seeded_loss", "faithful_intermittent"
    }:
        errors.append("e2e_suite must publish all three voice-critical runs")
    if report.get("leader_schema_actions") != _schema_actions():
        errors.append("e2e_suite.leader_schema_actions does not name the required owner work")
    schema = report.get("schema_validation")
    if not isinstance(schema, dict) or set(schema) != {
        "validator", "registered_schema_kind", "errors"
    }:
        errors.append("e2e_suite.schema_validation has an invalid closed shape")
    return errors


def _profile_summary(profile):
    return {
        "work": profile.work,
        "mode": profile.mode,
        "dual_standard": profile.dual_standard,
        "coverage_floor": profile.coverage_floor,
        "target_lang": profile.target_lang,
    }


def _cli_invocation(profile_path, rows_path, out, generated_at):
    return " ".join(
        (
            "python3",
            "-m",
            "hancharacter.cli",
            "e2e",
            "--profile",
            _shell_quote(profile_path),
            "--rows",
            _shell_quote(rows_path),
            "--out",
            _shell_quote(out),
            "--generated-at",
            _shell_quote(generated_at),
        )
    )


def _source_surface(unit, profile, axis):
    """Return a source measurement surface without weakening anchored patterns."""
    source = getattr(unit, "source_text", unit)
    if isinstance(source, segment.Unit):
        return measure.unit_surface(source, axis)
    return io_adapters.normalise_measurement_surface(
        source,
        profile,
        profile.evidence_lang,
        row_key=getattr(unit, "row_key", "<source-unit>"),
    )


def _source_type_matches(rows, profile):
    source_types = {
        type_id: entry
        for type_id, entry in typology.load_types().items()
        if entry["source_lang"] == profile.evidence_lang
    }
    plugin = measure.get_plugin(profile.evidence_lang)
    matched = {scope: defaultdict(int) for scope, role in profile.speaker_roles.items()
               if role == config.ROLE_SPEAKER}
    for unit in attribution.attributed_for_gating(rows, profile):
        for type_id, entry in source_types.items():
            surface = _source_surface(unit, profile, entry["axis"])
            if plugin.match(surface, entry["axis"], entry["pattern_set"]):
                matched[unit.scope][type_id] += 1
    return {scope: dict(sorted(counts.items())) for scope, counts in sorted(matched.items())}



def _real_density_statuses(segmentation, attribution_report, marker_matches):
    scope_verdicts = []
    under_sampled = []
    deltas = []
    for scope in sorted(segmentation["coverage"]):
        units = attribution_report["scopes"].get(scope, {}).get("units", 0)
        scenes = segmentation["scopes"][scope]["n_scenes"]
        sampled = units >= config.MIN_UNITS_PER_SCOPE and scenes >= config.MIN_SCENES_PER_BAND
        reasons = []
        if not marker_matches[scope]:
            reasons.append("no observed source catalogue marker maps to this speaker")
        if segmentation["scopes"][scope]["target_units"] == 0:
            reasons.append("no target-language unit is present in the input")
        row = {
            "scope": scope,
            "n_units": units,
            "n_scenes": scenes,
            "under_sampled": not sampled,
            "status": "not_run",
            "reasons": reasons,
        }
        scope_verdicts.append(row)
        if not sampled:
            under_sampled.append(row)
        deltas.append(
            {
                "speaker": scope,
                "source": profile_source_label(segmentation, scope),
                "signed_delta": None,
                "status": "not_measurable",
                "reason": "; ".join(reasons),
            }
        )
    return {
        "scope_verdicts": scope_verdicts,
        "under_sampled_scopes": under_sampled,
        "per_speaker_source_signed_delta": deltas,
    }


def profile_source_label(segmentation, scope):
    return "target-unavailable" if segmentation["scopes"][scope]["target_units"] == 0 else "unmapped"


def _real_graduation(generated_at):
    # Reuse the CLI's published join.  It is the one source of the shipped
    # corpus/review/precedent facts and validates the graduation artifact itself.
    from . import cli

    return cli._graduation(SimpleNamespace(generated_at=generated_at))


def _summary_text(report):
    lines = [
        "run: %s" % report["run"],
        "status: %s" % report["status"],
        "mode: %s" % report["profile"]["mode"],
        "CLI: %s" % report["cli_invocation"],
    ]
    if report["gates"]["executed"]:
        lines.append("hard findings: %d" % len(report["gates"]["hard_findings"]))
    else:
        lines.append("gates: not executed (this is not a passing result)")
    contracts = report["contracts"]
    if "sealed_count" in contracts:
        lines.append("sealed contracts: %d" % contracts["sealed_count"])
    if "stop_reason" in contracts:
        lines.append("stop: %s" % contracts["stop_reason"])
    return "\n".join(lines) + "\n"


def _real_headline_status(graduation):
    """Derive the pre-seal headline from published graduation findings."""
    result = findings.FindingSet()
    for entry in graduation["types"]:
        if entry["stage"] != config.STAGE_CANONICAL:
            result.add(
                findings.hard(
                    "contract_type_not_canonical",
                    "type %s is at graduation stage %r, not canonical"
                    % (entry["type_id"], entry["stage"]),
                    scope=entry["type_id"],
                )
            )
    return (
        "blocked_at_contract_seal" if result.hard else "ready_for_contract_seal",
        [finding.to_json() for finding in result.hard],
    )




def crimson_fixture_path():
    """The pinned evidence fixture, resolved through config so a clone can relocate it.

    Hardcoding the maintainer's absolute path made the provenance label unusable for
    anyone else and made fixture-dependent tests fail on a fresh clone.
    """

    return config.fixture_path()


def _preseal_stop_reason(graduation, scope_types, target_units=0):
    """Describe why this run stopped, derived from state rather than asserted.

    Two generations of this function were wrong in the same way, so the history
    is worth keeping.  It began as a hardcoded claim that the catalogue had no
    canonical type; once one type graduated, that sentence was false while the
    run still correctly stopped.  The first rewrite then asserted that the
    canonical types "do not cover every type the declared speakers require"
    *without computing the set difference* -- and on the only fixture it
    describes, the speakers require nothing at all, so the empty requirement set
    is trivially covered and the sentence was false again.

    Every clause below is now computed.  A report that misstates its own reason
    for stopping is worse than one that simply stops.
    """

    canonical = sorted(
        entry["type_id"]
        for entry in graduation["types"]
        if entry["stage"] == config.STAGE_CANONICAL
    )
    ungraduated = sorted(
        entry["type_id"]
        for entry in graduation["types"]
        if entry["stage"] != config.STAGE_CANONICAL
    )
    required = sorted({
        type_id
        for entry in scope_types
        for type_id in entry["type_ids"]
    })
    missing = sorted(set(required) - set(canonical))

    clauses = []
    if canonical:
        clauses.append(
            "The shipped graduation report has %d canonical type(s) (%s) and %d that are "
            "not canonical (%s); the pre-seal check refuses on any ungraduated type."
            % (len(canonical), ", ".join(canonical), len(ungraduated), ", ".join(ungraduated))
        )
    else:
        clauses.append("The shipped graduation report has no canonical type.")

    if not required:
        clauses.append(
            "No declared speaker in this input carries any catalogue type, so there is no "
            "per-speaker type requirement to satisfy."
        )
    elif missing:
        clauses.append(
            "The declared speakers require %s, of which %s are not canonical."
            % (", ".join(required), ", ".join(missing))
        )
    else:
        clauses.append(
            "Every type the declared speakers require (%s) is canonical."
            % ", ".join(required)
        )

    clauses.append(
        "%d target-language unit(s) are present."
        % target_units
        if target_units
        else "No target-language unit is present."
    )
    clauses.append("Therefore no contract candidate is fabricated or sealed.")
    return " ".join(clauses)


def run_real_fixture(
    profile_path,
    rows_path,
    out,
    generated_at=_DEFAULT_GENERATED_AT,
    input_format=None,
):
    """Measure the real fixture only through its honest pre-seal boundary."""
    _require_timestamp(generated_at)
    out = _outside_repository(out)
    os.makedirs(out, exist_ok=True)
    from . import cli

    profile = config.load_profile(profile_path)
    rows = cli._load_rows(rows_path, profile, fmt=input_format)
    # e2e accepts any declared adapter format, so the provenance label must be
    # derived from the input actually read.  Hard-coding "crimson" mislabelled
    # every other run and put an untrue label into the evidence tree.
    provenance = (
        "crimson"
        if os.path.realpath(rows_path) == os.path.realpath(crimson_fixture_path())
        else "operator_input"
    )
    segmentation = segment.segment_report(rows, profile)
    attribution_report = attribution.attribution_report(rows, profile)
    marker_matches = _source_type_matches(rows, profile)
    graduation, merge_findings = _real_graduation(generated_at)
    stages = {entry["type_id"]: entry for entry in graduation["types"]}
    scope_types = [
        {
            "speaker": scope,
            "type_ids": sorted(marker_matches[scope]),
            "type_stages": [
                {
                    "type_id": type_id,
                    "stage": stages[type_id]["stage"],
                    "unmet": stages[type_id]["unmet"],
                }
                for type_id in sorted(marker_matches[scope])
            ],
        }
        for scope in sorted(marker_matches)
    ]
    expected_reasons = (
        config.INELIGIBLE_MIXED_SPAN,
        config.INELIGIBLE_DUPLICATE_SOURCE,
        config.INELIGIBLE_PENDING,
        config.INELIGIBLE_UNDECLARED,
        config.INELIGIBLE_UNSPLITTABLE,
    )
    headline_status, preseal_findings = _real_headline_status(graduation)

    report = {
        "kind": "e2e_report",
        "generated_at": generated_at,
        "run": provenance,
        "fixture": provenance,

        "status": headline_status,

        "cli_invocation": _cli_invocation(profile_path, rows_path, out, generated_at),
        "profile": _profile_summary(profile),
        "segmentation": {
            "coverage": segmentation["coverage"],
            "eligible_segments": attribution_report["by_tier"][attribution.T1]
            + attribution_report["by_tier"][attribution.T3],
            "ineligible_by_reason": {
                reason: attribution_report["eligibility"][reason] for reason in expected_reasons
            },
            "counters": {
                config.COUNTER_SCOPE_UNREALISED: attribution_report["eligibility"][
                    config.COUNTER_SCOPE_UNREALISED
                ],
                config.COUNTER_UNITS_WITHOUT_SCENE: segmentation["counters"][
                    config.COUNTER_UNITS_WITHOUT_SCENE
                ],
            },
        },
        "attribution": {
            "t1_rate": attribution.t1_rate(attribution_report),
            "by_tier": attribution_report["by_tier"],
        },
        "density": _real_density_statuses(segmentation, attribution_report, marker_matches),
        "gates": {
            "density_policy": "report_only_in_prose_fidelity",
            "presence_policy": "hard_when_a_sealed_contract_exists",
            "executed": False,
            "invention_count": 0,
            "narration_clean_count": 0,
            "hard_findings": [],
            "report_findings": [],
            "summary": {
                "not_run_reason": (
                    "No sealed contract exists; there are also zero target-language units in this "
                    "source/pivot fixture, so character-corpus gates were not evaluated."
                ),
                "target_observations": 0,
            },
        },
        "contracts": {
            "sealed_count": 0,
            "seal_attempts": [],
            "speaker_marker_types": scope_types,
            "graduation": graduation,
            "graduation_merge_findings": [finding.to_json() for finding in merge_findings],
            "preseal_findings": preseal_findings,
            "all_types_canonical": all(entry["stage"] == config.STAGE_CANONICAL for entry in graduation["types"]),
            "stop_reason": _preseal_stop_reason(
                graduation,
                scope_types,
                target_units=sum(
                    scope["target_units"] for scope in segmentation["scopes"].values()
                ),
            ),
        },
        "intermittent_band": {
            "measured": False,
            "reason": (
                "No speaker has an observed catalogue marker plus target-language units, so no "
                "source/target per-scene marker band can be measured from this fixture."
            ),
            "source_scene_counts": {
                scope: segmentation["scopes"][scope]["scene_counts"]
                for scope in sorted(segmentation["scopes"])
            },
        },
        "limitations": [
            "Density signed deltas, invention, and narration-clean counts are not passed results: "
            "they are not measurable without both a mapped marker and target-language units.",
            "The reported zero invention and narration-clean counts are zero observed target checks, "
            "not a clean gate result.",
        ],
        "leader_schema_actions": _schema_actions(),
        "schema_validation": {
            "validator": "hancharacter.e2e.validate_report",
            "registered_schema_kind": None,
            "errors": [],
        },
    }
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid e2e report: %s" % "; ".join(errors))
    _write_json(os.path.join(out, "report.json"), report)
    _write_text(os.path.join(out, "summary.txt"), _summary_text(report))
    # A blocked real run must not be presented as a successful CLI operation.
    return report, 1


def _synthetic_profile():
    return {
        "work": "synthetic_voice_critical",
        "voice_enforcement_mode": config.MODE_VOICE_CRITICAL,
        "evidence_lang": "ja",
        "pivot_lang": "ja",
        "target_lang": "ko",
        "speaker_roles": {"hero": config.ROLE_SPEAKER, "close": config.ROLE_CLOSE},
        "tag_pattern": r"<[^>\n]*>",
        "delimiters": {
            "ja": {"speech": [["「", "」"]], "term": []},
            "ko": {
                "speech": [['"', '"']],
                "term": [["「", "」"]],
                "speech_is_positional": False,
            },
        },
        "edition_medium": "plain",
    }


def _synthetic_catalogue(root):
    os.makedirs(os.path.join(root, "types"), exist_ok=True)
    os.makedirs(os.path.join(root, "realisations", "ko"), exist_ok=True)
    _write_text(os.path.join(root, "VERSION"), "synthetic-e2e-v1\n")
    _write_json(
        os.path.join(root, "types", "synthetic_nyan.json"),
        {
            "id": "synthetic_nyan",
            "axis": "ending_transform",
            "source_lang": "ja",
            "source_marker": "synthetic ~にゃ",
            "pattern_set": [r"にゃ$"],
            "provenance": {"origin": "character", "notes": "Authored intermittent fixture marker."},
        },
    )
    _write_json(
        os.path.join(root, "realisations", "ko", "synthetic_nyan_ko.json"),
        {
            "id": "synthetic_nyan_ko",
            "type_id": "synthetic_nyan",
            "source_lang": "ja",
            "target_lang": "ko",
            "source_marker": "synthetic ~にゃ",
            "target_realisation": "synthetic ~냥",
            "length_cost": {"model": "append", "value": 0},
            "precedents": ["synthetic_precedent"],
            "density_band_default": [0.2, 0.8],
            "pattern_set": [r"냥$"],
        },
    )


def _synthetic_rows(loss=False):
    rows = []
    # Five scenes, four units each.  Source density is [0, .5, .5, .5, 1], so the
    # fixture proves an intermittent band and includes a marker-free scene.
    marked_per_scene = (0, 2, 2, 2, 4)
    for scene_index, marked_count in enumerate(marked_per_scene, start=1):
        for unit_index in range(4):
            marked = unit_index < marked_count
            source = "合成%d_%d%s" % (
                scene_index,
                unit_index,
                "にゃ" if marked else "です",
            )
            target = "대사%d_%d%s" % (
                scene_index,
                unit_index,
                "다" if loss or not marked else "냥",
            )
            rows.append(
                {
                    "key": "synthetic-%d-%d" % (scene_index, unit_index),
                    "evidence": "<color=hero>%s<color=close>" % source,
                    "pivot": "「%s」" % source,
                    "target": '"%s"' % target,
                    "scene": "scene-%d" % scene_index,
                }
            )
    return rows


def _synthetic_graduation(generated_at):
    samples = []
    source_keys = ("synthetic_source_a", "synthetic_source_b", "synthetic_source_c")
    for index in range(config.CANONICAL_MIN_OCCURRENCES):
        samples.append(
            {
                "type_id": "synthetic_nyan",
                "verdict": config.REVIEW_ACCEPT,
                "source": {
                    "class": config.SOURCE_SECONDARY,
                    "independent_key": source_keys[index % len(source_keys)],
                },
                "reviewer_verdicts": {"review_a": "accept", "review_b": "accept"},
            }
        )
    # Kappa must be a stable verdict, not merely a value clearing the floor, so the
    # synthetic catalogue carries the minimum stable configuration: six agreed
    # rejections for marginal variance plus one disagreement in each direction.
    # This keeps the synthetic fixture honest against the strengthened rule rather
    # than exempt from it.
    for a, b in [("reject", "reject")] * 6 + [
        ("accept", "reject"),
        ("reject", "accept"),
    ]:
        samples.append(
            {
                "type_id": "synthetic_nyan",
                "verdict": (
                    config.REVIEW_REJECT if a == b else config.REVIEW_NEEDS_REVIEW
                ),
                "source": {
                    "class": config.SOURCE_SECONDARY,
                    "independent_key": "synthetic_source_d",
                },
                "reviewer_verdicts": {"review_a": a, "review_b": b},
            }
        )
    for sample in samples:
        sample["reviewer"] = "review_a"
        sample["review2"] = "review_b"
    report = corpus.graduation_report(
        samples,
        catalogue_version="synthetic-e2e-v1",
        generated_at=generated_at,
        type_ids=["synthetic_nyan"],
        precedent_facts={"synthetic_nyan": {"adopted": 1, "unresolved_contradictions": 0}},
        confirms_by_type={"synthetic_nyan": 1},
        notes="All graduation floors are computed from authored synthetic evidence.",
    )
    entry = report["types"][0]
    if entry["stage"] != config.STAGE_CANONICAL:
        raise ValueError("synthetic fixture did not honestly graduate: %s" % entry["unmet"])
    return samples, report, {entry["type_id"]: entry["stage"]}


def _fixture_paths(out):
    fixtures = os.path.join(out, "synthetic-fixtures")

    return {
        "fixtures": fixtures,
        "profile": os.path.join(fixtures, "profile.json"),
        "faithful": os.path.join(fixtures, "faithful-rows.json"),
        "loss": os.path.join(fixtures, "seeded-loss-rows.json"),
        "catalogue": os.path.join(fixtures, "catalogue"),
        "evidence": os.path.join(fixtures, "graduation-evidence.json"),
        "graduation": os.path.join(fixtures, "graduation-report.json"),
    }


def _write_synthetic_fixture(out, generated_at):
    paths = _fixture_paths(out)
    os.makedirs(paths["fixtures"], exist_ok=True)
    _write_json(paths["profile"], _synthetic_profile())
    _write_json(paths["faithful"], _synthetic_rows(loss=False))
    _write_json(paths["loss"], _synthetic_rows(loss=True))
    _synthetic_catalogue(paths["catalogue"])
    samples, graduation, stages = _synthetic_graduation(generated_at)
    _write_json(paths["evidence"], samples)
    _write_json(paths["graduation"], graduation)
    return paths, graduation, stages


def _source_scene_densities(rows, profile, axis, source_patterns):
    plugin = measure.get_plugin(profile.evidence_lang)
    counts = defaultdict(lambda: [0, 0])
    matched_total = 0
    units = attribution.attributed_for_gating(rows, profile)
    for unit in units:
        if unit.scene is None:
            continue
        hit = plugin.match(_source_surface(unit, profile, axis), axis, source_patterns)
        counts[unit.scene][0] += int(hit)
        counts[unit.scene][1] += 1
        matched_total += int(hit)
    if not units or not counts:
        raise ValueError("synthetic fixture has no source units or scenes")
    densities = [counts[scene][0] / counts[scene][1] for scene in sorted(counts)]
    return units, matched_total, densities


def _target_match_count(units, profile, axis, target_patterns):
    plugin = measure.get_plugin(profile.target_lang)
    hits = 0
    by_scene = defaultdict(lambda: [0, 0])
    for unit in units:
        surface = gates._normalise_raw_surface(unit.target_text, profile, profile.target_lang)
        hit = plugin.match(surface, axis, target_patterns)
        hits += int(hit)
        if unit.scene is not None:
            by_scene[unit.scene][0] += int(hit)
            by_scene[unit.scene][1] += 1
    scene_densities = [by_scene[scene][0] / by_scene[scene][1] for scene in sorted(by_scene)]
    return hits, scene_densities


def _contract_candidate(profile, catalogue_root, stages, source_density, source_band, corpus_digest):
    marker_patterns = [r"냥$"]
    candidate = contracts.build(
        profile.work,
        "hero",
        ["synthetic_nyan"],
        "ja",
        "ko",
        attribution={"evidence_tier": "T1", "target_tier": "T1", "status": "attributed"},
        required_markers=marker_patterns,
        forbidden_markers=[r"금지$"],
        measured_source_density={"ending_transform": source_density},
        bands={"hero": {"ending_transform": list(source_band)}},
        scope_overrides={},
        exclusivity={"exclusive_with": []},
        edition_medium=profile.edition_medium or "plain",

        voice_enforcement_mode=profile.mode,
        authority=config.AUTHORITY_PRECEDENT_BACKED,
        coverage_floor=profile.coverage_floor,

        declared_speakers=["hero"],
        corpus_digests={"synthetic_nyan": corpus_digest},
        marker_sets={"ending_transform": marker_patterns},
        catalogue_markers={"synthetic_nyan": marker_patterns},
        review_decisions={},
        required_glyphs=[],
        axis_status=lambda language: dict(measure.get_plugin(language).AXES),
        measurable=config.MEASURABLE_AXIS_STATUSES,
        root=catalogue_root,
    )
    return candidate


def _seal(candidate, stages, coverage, length_ok):
    return contracts.seal(
        candidate,
        schema_validate=contracts.validate_contract,
        graduation_stages=stages,
        length_ok=length_ok,
        plugin_for=measure.get_plugin,
        plugin_measurable_axes=measure.measurable_axes,
        plugin_golden_digest=measure.golden_digest,
        rejected_precedent_match=[],
        glyph_available=lambda glyph: True,
        coverage=coverage,
        dialect_findings=[],
    )


def _length_check(rows, profile, catalogue_root):
    realisations = typology.load_realisations(profile.target_lang, root=catalogue_root)
    targets = {row.key: row.target for row in rows}
    budgets = profile.budgets()

    def check(contract):
        return contracts.length_feasible(
            [{"key": row.key, "medium": profile.edition_medium} for row in rows],
            contract,
            realisations,
            eligible_segments=lambda item: [{"text": targets[item["key"]]}],
            budgets=budgets,
        )

    return check



def _voice_case(name, profile, rows, candidate, stages, source_densities, source_density,
                source_band, catalogue_root, generated_at, invocation, graduation):
    gated_units = attribution.attributed_for_gating(rows, profile)
    target_hits, target_scene_densities = _target_match_count(
        gated_units, profile, "ending_transform", [r"냥$"]
    )
    density_row = density.scope_report(
        "hero",
        "ending_transform",
        source_density,
        target_hits / len(gated_units),
        source_densities,
        n_units=len(gated_units),
        n_scenes=len(target_scene_densities),
        dual_standard=profile.dual_standard,
        mode=profile.mode,
        matched=target_hits,
        total=len(gated_units),
        target_scene_densities=target_scene_densities,
    )
    attr_report = attribution.attribution_report(rows, profile)
    segmentation = segment.segment_report(rows, profile)
    coverage = {
        scope: facts["ratio"] for scope, facts in segmentation["coverage"].items()
    }
    parity = findings.FindingSet()
    for row in rows:
        result = segment.quote_parity(row, profile)
        if result is not None:
            parity.add(result)
    length_check = _length_check(rows, profile, catalogue_root)

    length_ok, _length_failures = length_check(candidate)
    sealed, seal_findings = _seal(candidate, stages, coverage, length_ok)
    if sealed is None or not seal_findings.is_clean():
        raise ValueError("synthetic contract unexpectedly failed direct seal")

    def seal_contract(contract):
        contract_length_ok, _failures = length_check(contract)
        return _seal(contract, stages, coverage, contract_length_ok)

    all_findings, summary = gates.run(
        contracts=[candidate],
        attribution_gate=lambda: attr_report,
        seal_contract=seal_contract,
        length_check=length_check,
        observations=[
            {
                "row_key": unit.row_key,
                "scope": unit.scope,
                "text": unit.target_text,
                "scene": unit.scene,
                "eligible": True,
                "pending": False,
                "attributed_spans": 1,
            }
            for unit in gated_units
        ],
        catalogue_markers={"synthetic_nyan": [r"냥$"]},
        target_lang=profile.target_lang,
        source_scene_densities={("hero", "ending_transform"): source_densities},
        measurable_axes={"hero": measure.measurable_axes(profile.evidence_lang)},
        quote_parity_findings=parity,
        ladder_check=lambda contract: contracts.ladder_ledger_check(contract, []),
        profile=profile,
        review_decisions={},
    )
    hard = [finding.to_json() for finding in all_findings.hard]
    reported = [finding.to_json() for finding in all_findings.reported]
    expected_reasons = (
        config.INELIGIBLE_MIXED_SPAN,
        config.INELIGIBLE_DUPLICATE_SOURCE,
        config.INELIGIBLE_PENDING,
        config.INELIGIBLE_UNDECLARED,
        config.INELIGIBLE_UNSPLITTABLE,
    )
    report = {
        "kind": "e2e_report",
        "generated_at": generated_at,
        "run": "synthetic-voice-critical-%s" % name,

        "fixture": "synthetic",

        "status": "passed" if not hard else "failed_as_expected" if name == "seeded-loss" else "failed",
        "cli_invocation": invocation,
        "profile": _profile_summary(profile),
        "segmentation": {
            "coverage": segmentation["coverage"],
            "eligible_segments": len(gated_units),
            "ineligible_by_reason": {
                reason: attr_report["eligibility"][reason] for reason in expected_reasons
            },
            "counters": {
                config.COUNTER_SCOPE_UNREALISED: attr_report["eligibility"][
                    config.COUNTER_SCOPE_UNREALISED
                ],
                config.COUNTER_UNITS_WITHOUT_SCENE: segmentation["counters"][
                    config.COUNTER_UNITS_WITHOUT_SCENE
                ],
            },
        },
        "attribution": {"t1_rate": attribution.t1_rate(attr_report), "by_tier": attr_report["by_tier"]},
        "density": {
            "scope_verdicts": [density_row],
            "under_sampled_scopes": [density_row] if density_row["under_sampled"] else [],
            "per_speaker_source_signed_delta": [
                {
                    "speaker": "hero",
                    "source": "synthetic_nyan",
                    "signed_delta": density_row["delta"],
                    "status": "measured",
                    "reason": density_row["reason"],
                }
            ],
        },
        "gates": {
            "density_policy": "hard_in_voice_critical_when_density_evidence_clears_the_threshold",
            "presence_policy": "hard",
            "executed": True,
            "invention_count": sum(1 for finding in all_findings.to_json() if finding["code"].startswith("voice_invention")),
            "narration_clean_count": sum(
                1 for finding in all_findings.to_json() if finding["code"] == "voice-narration-clean"
            ),
            "hard_findings": hard,
            "report_findings": reported,
            "summary": summary,
        },
        "contracts": {
            "sealed_count": 1,
            "sealed_hashes": [sealed["seal"]["hash"]],
            "graduation": graduation,
            "direct_seal_findings": seal_findings.to_json(),
        },
        "intermittent_band": {
            "measured": True,
            "source_scene_densities": source_densities,
            "target_scene_densities": target_scene_densities,
            "source_has_marker_free_scene": any(value == 0.0 for value in source_densities),
            "target_has_marker_free_scene": any(value == 0.0 for value in target_scene_densities),
        },
        "limitations": [],
        "leader_schema_actions": _schema_actions(),
        "schema_validation": {
            "validator": "hancharacter.e2e.validate_report",
            "registered_schema_kind": None,
            "errors": [],
        },
    }
    errors = validate_report(report)
    if errors:
        raise ValueError("invalid voice-critical report: %s" % "; ".join(errors))
    return report, 1 if hard else 0


def run_voice_critical(
    out, generated_at=_DEFAULT_GENERATED_AT, *, invocation_scenario="voice-critical"
):
    """Publish the sealed synthetic LOSS and faithful-intermittent evidence runs."""
    _require_timestamp(generated_at)
    root = _outside_repository(out)
    out = os.path.join(root, "synthetic-artifacts")
    os.makedirs(out, exist_ok=True)
    paths, graduation, stages = _write_synthetic_fixture(out, generated_at)

    profile = config.load_profile(paths["profile"])
    from . import cli

    faithful_rows = cli._load_rows(paths["faithful"], profile)
    loss_rows = cli._load_rows(paths["loss"], profile)
    units, source_hits, source_densities = _source_scene_densities(
        faithful_rows, profile, "ending_transform", [r"にゃ$"]
    )
    if source_hits != 10 or len(units) != 20:
        raise ValueError("synthetic source fixture did not produce its declared 10/20 density")
    source_density = source_hits / len(units)
    source_band = density.band(source_densities)
    candidate = _contract_candidate(
        profile,
        paths["catalogue"],
        stages,
        source_density,
        source_band,
        hashlib.sha256(_json_bytes(_synthetic_graduation(generated_at)[0])).hexdigest(),
    )
    faithful_length_check = _length_check(faithful_rows, profile, paths["catalogue"])
    faithful_length_ok, _length_failures = faithful_length_check(candidate)
    faithful_coverage = {
        scope: facts["ratio"]
        for scope, facts in segment.segment_report(faithful_rows, profile)["coverage"].items()
    }
    sealed, seal_findings = _seal(candidate, stages, faithful_coverage, faithful_length_ok)
    if sealed is None or not seal_findings.is_clean():
        raise ValueError("synthetic contract did not seal: %s" % seal_findings.to_json())
    def invocation_for(scenario):
        return " ".join(
            (
                "python3", "-m", "hancharacter.cli", "e2e", "--scenario", scenario,
                "--out", _shell_quote(root), "--generated-at", _shell_quote(generated_at),

            )
        )

    invocation = invocation_for(invocation_scenario)
    seal_report = {
        "sealed": True,
        "fixture": "synthetic",

        "seal_hash": sealed["seal"]["hash"],
        "findings": seal_findings.to_json(),
        "graduation": graduation,
        "source_density": source_density,
        "coverage_floor": sealed["coverage_floor"],
        "source_band": list(source_band),
        "source_scene_densities": source_densities,
    }
    _write_json(os.path.join(out, "seal-report.json"), seal_report)
    loss_report, loss_rc = _voice_case(
        "seeded-loss", profile, loss_rows, candidate, stages, source_densities, source_density,
        source_band, paths["catalogue"], generated_at, invocation_for("seeded-loss"), graduation,
    )
    faithful_report, faithful_rc = _voice_case(
        "faithful-intermittent", profile, faithful_rows, candidate, stages, source_densities,
        source_density, source_band, paths["catalogue"], generated_at,
        invocation_for("faithful-intermittent"), graduation,
    )
    _write_json(os.path.join(out, "seeded-loss-report.json"), loss_report)
    _write_json(os.path.join(out, "faithful-intermittent-report.json"), faithful_report)
    loss_codes = {finding["code"] for finding in loss_report["gates"]["hard_findings"]}
    if loss_rc != 1 or "voice_required_marker_absent" not in loss_codes:
        raise ValueError("seeded LOSS did not fail with a hard required-marker finding")
    if faithful_rc != 0 or faithful_report["gates"]["hard_findings"]:
        raise ValueError("faithful intermittent fixture did not pass")
    if not (
        faithful_report["intermittent_band"]["source_has_marker_free_scene"]
        and faithful_report["intermittent_band"]["target_has_marker_free_scene"]
    ):
        raise ValueError("faithful fixture does not prove marker-free intermittent scenes")
    suite = {
        "kind": "e2e_suite",
        "generated_at": generated_at,
        "run": "synthetic-voice-critical",

        "status": "passed" if loss_rc == 1 and faithful_rc == 0 else "failed",

        "fixture": "synthetic",

        "cli_invocation": invocation,
        "contracts": seal_report,
        "runs": {
            "seal": {
                "report": "seal-report.json",
                "sealed": True,
                "exit_code": 0,
                "cli_invocation": invocation,
            },
            "seeded_loss": {
                "report": "seeded-loss-report.json",
                "exit_code": loss_rc,
                "hard_codes": sorted(loss_codes),
                "cli_invocation": invocation_for("seeded-loss"),
            },
            "faithful_intermittent": {
                "report": "faithful-intermittent-report.json",
                "exit_code": faithful_rc,
                "hard_codes": [
                    finding["code"] for finding in faithful_report["gates"]["hard_findings"]
                ],
                "cli_invocation": invocation_for("faithful-intermittent"),
            },
        },
        "leader_schema_actions": _schema_actions(),
        "schema_validation": {
            "validator": "hancharacter.e2e.validate_suite",
            "registered_schema_kind": None,
            "errors": [],
        },
    }
    errors = validate_suite(suite)
    if errors:
        raise ValueError("invalid e2e suite: %s" % "; ".join(errors))
    _write_json(os.path.join(out, "report.json"), suite)
    _write_text(
        os.path.join(out, "summary.txt"),
        "fixture: synthetic\nrun: synthetic-voice-critical\nstatus: %s\nCLI: %s\nsealed: yes\n"
        "This synthetic suite proves the seal and gate paths on authored data; it is not a result about any real work.\n"
        "seeded LOSS exit: %d\nfaithful intermittent exit: %d\n"
        % (suite["status"], invocation, loss_rc, faithful_rc),
    )
    return suite, 0
