"""Command line entry point.

Subcommands land as their phase lands. A subcommand that is not implemented yet
is absent rather than stubbed: a stub that exits zero is indistinguishable from a
gate that passed, and this project's whole argument is that a check you cannot
fail is not a check.
"""
from collections.abc import Mapping

import argparse
import json
import os
import sys

from . import __version__, budgets, config, io_adapters


def _segment_rows(adapter_rows, profile):
    """Convert validated adapter records into the spine's row value type."""
    from .segment import Row, resolve_scene

    rows = []
    for item in adapter_rows:
        row = Row(
            key=item["key"],
            evidence=item["evidence"],
            pivot=item["pivot"],
            evidence_lang=item["evidence_lang"],
            pivot_lang=item["pivot_lang"],
            scene=item.get("scene"),
            target=item.get("target"),
        )
        row.scene = resolve_scene(row, profile)
        rows.append(row)
    return rows


def _load_rows(path, profile, *, fmt=None):
    """Load adapter records for the segment spine without a second JSON reader.

    Host-shaped JSON remains supported through the ``host_json`` branch inside
    the declared JSON adapter; no source rows are written or copied.
    """
    return _segment_rows(io_adapters.load(path, profile=profile, fmt=fmt), profile)


def _adapter_hard_findings(report):
    return [finding for finding in report["findings"] if finding["severity"] == "hard"]


def _print_adapter_hard_findings(report):
    for finding in _adapter_hard_findings(report):
        print(
            "%s %s %s"
            % (finding["severity"].upper(), finding["code"], finding["detail"])
        )


def _budget_declaration(profile):
    """Select a declared work medium without inferring numeric layout bounds."""
    declaration = profile.budgets()
    if (
        "class" not in declaration
        and "edition_medium" not in declaration
        and profile.edition_medium is not None
    ):
        declaration["edition_medium"] = profile.edition_medium
    return declaration


def _json_value(value):
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value



def cmd_version(args):
    print("hancharacter %s" % __version__)
    return 0


def cmd_profile(args):
    profile = config.load_profile(args.profile)
    speakers = sorted(k for k, v in profile.speaker_roles.items() if v == config.ROLE_SPEAKER)
    non_speakers = sorted(
        "%s=%s" % (k, v) for k, v in profile.speaker_roles.items() if v != config.ROLE_SPEAKER
    )
    print("work                  %s" % profile.work)
    print("enforcement mode      %s" % profile.mode)
    print("evidence -> pivot     %s -> %s" % (profile.evidence_lang, profile.pivot_lang))
    print("target                %s" % profile.target_lang)
    print("dual standard         %s" % ("yes (density verdicts are report-only)" if profile.dual_standard else "no (density verdicts can be hard)"))
    print("coverage floor        %.2f" % profile.coverage_floor)
    print("declared speakers     %s" % (", ".join(speakers) or "(none)"))
    print("declared non-speakers %s" % (", ".join(non_speakers) or "(none)"))
    return 0


def cmd_schema(args):
    from . import schemas

    with open(args.file, "r", encoding="utf-8") as fh:
        obj = json.load(fh)
    errors = schemas.validate(args.kind, obj)
    if errors:
        for err in errors:
            print("FAIL %s" % err)
        return 1
    print("OK %s validates as %s" % (args.file, args.kind))
    return 0


def cmd_measure(args):
    from . import measure

    langs = [args.lang] if args.lang else measure.languages()
    rc = 0
    for lang in langs:
        try:
            plugin = measure.get_plugin(lang)
        except LookupError as exc:
            print("FAIL %s" % exc)
            rc = 1
            continue
        axes = measure.measurable_axes(lang)
        findings = measure.conformance(lang)
        status = "OK" if not findings else "FAIL"
        print(
            "%s %-3s version=%s golden=%s measurable_axes=%d"
            % (status, lang, plugin.VERSION, measure.golden_digest(lang)[:16], len(axes))
        )
        for finding in findings:
            print("     %s %s" % (finding.severity, finding.detail))
        if findings:
            rc = 1
    return rc


def _segment_failure_reasons(report, profile, *, allow_partial_coverage=False):
    """Return visible early-exit reasons for a structurally unmeasurable run."""
    reasons = []
    if report["hard_findings"]:
        reasons.append("%d hard finding(s) published" % report["hard_findings"])
    if report["rows"] > 0 and report["eligible_rows"] == 0:
        reasons.append("rows are present but none carries a speaker scope")
    if report["unmeasured_scopes"] and not allow_partial_coverage:
        reasons.append(
            "declared speaker scope(s) had no attributed unit: %s"
            % ", ".join(sorted(report["unmeasured_scopes"]))
        )
    for scope, coverage in sorted(report["coverage"].items()):
        ratio = coverage["ratio"]
        if coverage["attributed_units"] and ratio == 0.0:
            reasons.append(
                "%s has attributed units but no realised pivot spans" % scope
            )
        if ratio is not None and ratio < profile.coverage_floor:
            reasons.append(
                "%s coverage %.3f is below declared floor %.2f"
                % (scope, ratio, profile.coverage_floor)
            )
    return reasons



def cmd_segment(args):
    """Publish segmentation facts and fail early on structurally unmeasurable runs.

    The authoritative coverage gate belongs to contract sealing. This deliberately
    stricter early exit prevents a command that prints a problem and exits zero
    from teaching operators to ignore it.
    """
    from . import segment

    profile = config.load_profile(args.profile)
    input_rows = io_adapters.load(args.rows, profile=profile, fmt=args.input_format)
    adapter_report = io_adapters.load_report(input_rows, input_rows.format)
    if _adapter_hard_findings(adapter_report):
        _print_adapter_hard_findings(adapter_report)
        return 1
    rows = _segment_rows(input_rows, profile)

    if args.key:
        wanted = set(args.key)
        rows = [r for r in rows if r.key in wanted or r.key.split("/")[-1] in wanted]
        if not rows:
            # A --key slice suppresses the coverage reasons, so a typo'd key would
            # otherwise print an all-zero report and exit clean — every check
            # silenced by a filter that selected nothing.
            print(
                "error: --key selected no rows (checked %d requested key(s))"
                % len(wanted),
                file=sys.stderr,
            )
            return 2
    report = segment.segment_report(rows, profile)
    # A --key slice intentionally omits other declared speakers, so treating their
    # absent attribution as a whole-corpus failure would make focused diagnosis fail.
    failure_reasons = _segment_failure_reasons(
        report, profile, allow_partial_coverage=bool(args.key)
    )
    rc = 1 if failure_reasons else 0
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
        for reason in failure_reasons:
            print("FAIL %s" % reason, file=sys.stderr)
        return rc

    ineligible_total = sum(report["ineligible"].values())
    print("rows                       %d" % report["rows"])
    print("rows with a speaker scope  %d" % report["eligible_rows"])
    print("ineligible rows            %d" % report["ineligible_rows"])
    print("ineligibility reasons      %d" % ineligible_total)
    print("pure narration rows        %d" % report["pure_narration_rows"])
    for reason, count in sorted(report["ineligible"].items()):
        if count:
            print("  %-26s %d" % (reason, count))
    for counter, count in sorted(report["counters"].items()):
        print("counter %-19s %d" % (counter, count))
    print("coverage (per speaker, floor %.2f):" % profile.coverage_floor)
    for scope, cov in sorted(report["coverage"].items()):
        ratio = cov["ratio"]
        if ratio is None:
            print("  --  %-14s no attributed unit measured" % scope)
            continue
        mark = "ok " if ratio >= profile.coverage_floor else "LOW"
        print(
            "  %s %-14s eligible=%d attributed=%d ratio=%.3f"
            % (mark, scope, cov["eligible_units"], cov["attributed_units"], ratio)
        )
    for finding in report["findings"]:
        print(
            "%s %s %s"
            % (finding["severity"].upper(), finding["code"], finding["detail"])
        )
    for reason in failure_reasons:
        print("FAIL %s" % reason)
    return rc


def cmd_budget(args):
    """Publish the declared work layout-budget verdict for adapter-loaded rows."""
    profile = config.load_profile(args.profile)
    input_rows = io_adapters.load(args.rows, profile=profile, fmt=args.input_format)
    adapter_report = io_adapters.load_report(input_rows, input_rows.format)
    declaration = _budget_declaration(profile)
    result, report = budgets.check(input_rows, budgets=declaration)
    published = {
        "adapter": adapter_report,
        "budget_declaration": _json_value(declaration),
        "budget": report,
    }
    hard = bool(_adapter_hard_findings(adapter_report) or result.hard)
    if args.json:
        print(json.dumps(published, ensure_ascii=False, indent=1, sort_keys=True))
        return 1 if hard else 0

    print("input format               %s" % adapter_report["format"])
    print("input rows                 %d" % adapter_report["rows"])
    print("budget class               %s" % report["class"])
    print("measured rows              %d" % report["measured"])
    print("unmeasurable rows          %d" % report["unmeasurable"])
    _print_adapter_hard_findings(adapter_report)
    _print_findings(result, "budget")
    return 1 if hard else 0




def _print_findings(result, label):
    """Print a finding set and return the exit code its severities imply."""
    for finding in result.to_json():
        print(
            "%-6s %s %s"
            % (finding["severity"].upper(), finding["code"], finding["detail"])
        )
    hard = len(result.hard)
    print("%s: %d hard, %d report-only" % (label, hard, len(result.reported)))
    return 1 if hard else 0


def _load_confirms():
    """Validated human confirmations, or an empty log when none exist yet."""
    from . import schemas

    path = os.path.join(config.typology_root(), "human_confirm.jsonl")
    rows = []
    if not os.path.isfile(path):
        return rows
    with open(path, "r", encoding="utf-8") as fh:
        for index, line in enumerate(fh, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            errors = schemas.validate("human_confirm", row)
            if errors:
                raise ValueError("%s:%d: %s" % (path, index, "; ".join(errors)))
            rows.append(row)
    return rows


def _axis_status():
    """Per-language axis-status map, taken from the frozen measure plugins.

    Injected rather than imported inside `typology` so the catalogue layer keeps
    not depending on the measurement layer.
    """
    from . import measure

    return lambda lang: dict(measure.get_plugin(lang).AXES)


def cmd_types(args):
    from . import typology

    if args.lint:
        return _print_findings(
            typology.lint(
                target_lang=args.target,
                axis_status=_axis_status(),
                measurable=config.MEASURABLE_AXIS_STATUSES,
                # `dialect_policy` is owned editorially by `dialect.py` rather than
                # by density, so density measurability is the wrong question for it.
                exempt_axes=("dialect_policy",),
            ),
            "types --lint",
        )
    types = typology.load_types()
    realisations = typology.load_realisations(args.target)
    print("catalogue version    %s" % typology.catalogue_version())
    print("types                %d" % len(types))
    print("%s realisations      %d" % (args.target, len(realisations)))
    print("seed types           %d" % len(typology.SEED_TYPE_IDS))
    for type_id in sorted(types):
        source = types[type_id]
        seed = "seed" if type_id in typology.SEED_TYPE_IDS else "aux "
        print(
            "  %s %-24s %-24s %s"
            % (seed, type_id, source["axis"], source["source_marker"])
        )
    return 0


def _graduation(args):
    """Build the graduation report from the catalogue, joining the three tables."""
    from . import corpus, precedents, typology

    drafts = corpus.load_drafts()
    samples, merge_findings = corpus.merge(drafts, corpus.load_reviews())
    confirms = _load_confirms()
    confirm_ids = {row["id"] for row in confirms}
    confirms_by_type = {}
    for row in confirms:
        for type_id in row["confirms"]:
            confirms_by_type[type_id] = confirms_by_type.get(type_id, 0) + 1
    grouped = precedents.by_type(precedents.load())
    facts = {
        type_id: {
            "adopted": len(precedents.adopted(rows)),
            "unresolved_contradictions": len(
                precedents.unresolved_contradictions(rows, confirm_ids)
            ),
        }
        for type_id, rows in grouped.items()
    }
    type_ids = sorted(set(typology.SEED_TYPE_IDS) | {r["type_id"] for r in drafts})
    report = corpus.graduation_report(
        samples,
        catalogue_version=typology.catalogue_version(),
        generated_at=args.generated_at,
        type_ids=type_ids,
        precedent_facts=facts,
        confirms_by_type=confirms_by_type,
        notes=(
            "Stage is computed from the evidence actually collected. A type below "
            "canonical lists every unmet criterion, and none of them is waived."
        ),
    )
    return report, merge_findings


def cmd_corpus(args):
    from . import corpus

    if args.lint:
        return _print_findings(corpus.lint(), "corpus --lint")

    report, merge_findings = _graduation(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, sort_keys=True))
    else:
        print(
            "catalogue %s   generated %s"
            % (report["catalogue_version"], report["generated_at"])
        )
        print(
            "%-24s %-12s %4s %4s %4s %4s %7s"
            % ("type", "stage", "occ", "src", "e12", "adp", "kappa")
        )
        for entry in report["types"]:
            print(
                "%-24s %-12s %4d %4d %4d %4d %7s"
                % (
                    entry["type_id"],
                    entry["stage"],
                    entry["occurrences"],
                    entry["independent_sources"],
                    entry["e1e2_sources"],
                    entry["adopted_precedents"],
                    "undef" if entry["kappa"] is None else "%.3f" % entry["kappa"],
                )
            )
            for reason in entry["unmet"]:
                print("    unmet: %s" % reason)
        canonical = [e for e in report["types"] if e["stage"] == "canonical"]
        print(
            "canonical %d of %d type(s); a type below canonical cannot back a "
            "sealed contract" % (len(canonical), len(report["types"]))
        )
    for finding in merge_findings:
        print("%-6s %s %s" % (finding.severity.upper(), finding.code, finding.detail))
    return 0


def cmd_precedents(args):
    from . import precedents, typology

    confirm_ids = {row["id"] for row in _load_confirms()}
    if args.lint:
        return _print_findings(
            precedents.lint(
                known_confirm_ids=confirm_ids,
                matched_markers=typology.matched_markers,
            ),
            "precedents --lint",
        )
    rows = precedents.load()
    print("%-36s %-24s %-10s %s" % ("id", "type", "verdict", "target"))
    for row in sorted(rows, key=lambda r: r["id"]):
        print(
            "%-36s %-24s %-10s %s"
            % (row["id"], row["type_id"], row["verdict"], row["target_realisation"])
        )
    # The seal-time rejected-precedent matcher, run against every shipped
    # realisation. Running it here makes its state visible before a contract
    # exists to fail, rather than only at seal time.
    grouped = precedents.by_type(rows)
    realisations = typology.load_realisations(args.target)
    matcher_findings = []
    for realisation in sorted(realisations.values(), key=lambda r: r["id"]):
        matcher_findings.extend(
            precedents.rejected_match(
                realisation,
                grouped.get(realisation["type_id"], []),
                matched_markers=typology.matched_markers,
                containment=typology.containment,
            )
        )
    for finding in matcher_findings:
        print("%-6s %s %s" % (finding.severity.upper(), finding.code, finding.detail))
    hard = [f for f in matcher_findings if f.severity == "hard"]
    print(
        "rejected-precedent matcher: %d hard, %d recorded gap(s)"
        % (len(hard), len(matcher_findings) - len(hard))
    )
    return 1 if hard else 0


def cmd_dialect(args):
    from . import dialect

    decisions = dialect.load_decisions()
    if args.lint or not args.profile:
        return _print_findings(dialect.lint(), "dialect --lint")
    from . import corpus, precedents

    profile = config.load_profile(args.profile)
    # Both evidence inputs are derived from the shipped artifacts. They used to be
    # command-line integers, which made the R3 floor whatever the invoker typed.
    adopted_ids = {
        row["id"]: (row.get("source_dialect"), row.get("target_dialect"))
        for row in precedents.adopted(precedents.load())
    }
    try:
        samples, _ = corpus.merge(corpus.load_drafts(), corpus.load_reviews())
        accepted = sum(
            1 for row in samples if row["verdict"] == config.REVIEW_ACCEPT
        )
    except corpus.CorpusError:
        accepted = 0
    result = dialect.gate(
        profile.dialect_policy(),
        profile.work,
        decisions=decisions,
        adopted_precedent_ids=adopted_ids,
        sample_count=accepted,
    )
    for finding in result:
        print("%-6s %s %s" % (finding.severity.upper(), finding.code, finding.detail))
    if not result:
        print(
            "dialect gate clear: work %r declares no dialect pair, so no operator "
            "ruling is required" % profile.work
        )
    return 1 if any(f.severity == "hard" for f in result) else 0


def cmd_review(args):
    from . import corpus, review, typology

    drafts = corpus.load_drafts()
    samples, _ = corpus.merge(drafts, corpus.load_reviews())
    pending = [row for row in samples if row["verdict"] != config.REVIEW_ACCEPT]
    payload = review.bind_digest(
        review.build_payload(
            title="hancharacter review: corpus, attribution and confirmation",
            corpus=pending,
            confirmation=_load_confirms(),
            catalogue_version=typology.catalogue_version(),
            generated_at=args.generated_at,
            notes=(
                "Rows listed here did not reach a unanimous accept. They count "
                "toward no graduation floor until a reviewer resolves them."
            ),
        )
    )
    path = review.write(payload, args.out, fmt=args.format)
    print("wrote %s" % path)
    print("bound digest %s" % payload["digest"])
    print("%d corpus row(s) awaiting review" % len(pending))
    return 0
def cmd_e2e(args):
    """Run reproducible real-fixture or synthetic end-to-end evidence."""
    from . import e2e

    if args.scenario:
        if args.profile or args.rows:
            raise ValueError("--scenario cannot be combined with --profile or --rows")
        suite, rc = e2e.run_voice_critical(
            args.out, args.generated_at, invocation_scenario=args.scenario
        )
        selected = {
            "voice-critical": 0,
            "seeded-loss": suite["runs"]["seeded_loss"]["exit_code"],
            "faithful-intermittent": suite["runs"]["faithful_intermittent"]["exit_code"],
        }[args.scenario]
        print("wrote %s" % os.path.join(args.out, "synthetic-artifacts", "report.json"))
        print("voice-critical suite: %s" % suite["status"])
        return selected if selected else rc
    if not args.profile or not args.rows:
        raise ValueError("e2e requires --profile and --rows unless --scenario is selected")
    profile = config.load_profile(args.profile)
    # Loaded here so an undeclared extension fails loudly before any artifact
    # directory is created.  run_real_fixture re-reads through the same
    # adapter-backed cli._load_rows, so every declared format reaches a verdict.
    io_adapters.load(args.rows, profile=profile, fmt=args.input_format)
    report, rc = e2e.run_real_fixture(
        args.profile,
        args.rows,
        args.out,
        args.generated_at,
        input_format=args.input_format,
    )

    print("wrote %s" % os.path.join(args.out, "report.json"))
    print("real fixture: %s" % report["status"])
    return rc




def build_parser():
    parser = argparse.ArgumentParser(
        prog="hancharacter",
        description=(
            "Measure a source character's speech-style markers, seal them into a "
            "per-character voice contract, and refuse to ship a translation that "
            "drifts out of the measured band in either direction."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("version", help="print the package version")
    p.set_defaults(func=cmd_version)

    p = sub.add_parser("profile", help="validate and summarise a work profile")
    p.add_argument("--profile", required=True)
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("schema", help="validate one artifact against its schema")
    p.add_argument("--kind", required=True)
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_schema)

    p = sub.add_parser("measure", help="run measure-plugin golden conformance")
    p.add_argument("--lang", help="limit to one source or target language")
    p.set_defaults(func=cmd_measure)

    p = sub.add_parser("segment", help="segment rows and publish the attribution report")
    p.add_argument("--profile", required=True)
    p.add_argument("--rows", required=True, help="source rows in a declared adapter format")
    p.add_argument("--format", dest="input_format", help="override the input file extension")
    p.add_argument("--key", action="append", help="limit to one or more row keys")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_segment)

    p = sub.add_parser("budget", help="check declared layout budgets for adapter-loaded rows")
    p.add_argument("--profile", required=True)
    p.add_argument("--rows", required=True, help="source rows in a declared adapter format")
    p.add_argument("--format", dest="input_format", help="override the input file extension")
    p.add_argument("--json", action="store_true", help="publish the full budget report as JSON")
    p.set_defaults(func=cmd_budget)

    p = sub.add_parser("types", help="list the type catalogue, or lint it")
    p.add_argument("--lint", action="store_true")
    p.add_argument("--target", default="ko", help="target language for realisations")
    p.set_defaults(func=cmd_types)

    p = sub.add_parser(
        "corpus", help="publish the graduation report, or lint the corpus"
    )
    p.add_argument("--lint", action="store_true")
    p.add_argument("--json", action="store_true")
    # Injected rather than read from the clock, so the published report is
    # reproducible and its digest is stable across runs.
    p.add_argument(
        "--generated-at",
        default="1970-01-01T00:00:00Z",
        dest="generated_at",
        help="ISO-8601 UTC stamp recorded in the report (default is fixed so the "
             "artifact is reproducible)",
    )
    p.set_defaults(func=cmd_corpus)

    p = sub.add_parser(
        "precedents",
        help="list the precedent table and run the rejected-precedent matcher",
    )
    p.add_argument("--lint", action="store_true")
    p.add_argument("--target", default="ko")
    p.set_defaults(func=cmd_precedents)

    p = sub.add_parser("dialect", help="run the dialect gate for a work, or lint")
    p.add_argument("--profile")
    p.add_argument("--lint", action="store_true")
    p.set_defaults(func=cmd_dialect)

    p = sub.add_parser("review", help="render the review page bound to its digest")
    p.add_argument("--out", required=True, help="output directory (outside the repo)")
    p.add_argument("--format", choices=("html", "text"), default="html")
    p.add_argument(
        "--generated-at", default="1970-01-01T00:00:00Z", dest="generated_at"
    )
    p.set_defaults(func=cmd_review)
    p = sub.add_parser("e2e", help="run a reproducible end-to-end evidence report")
    p.add_argument("--profile", help="validated profile for a real read-only rows input")
    p.add_argument("--rows", help="source rows in a declared adapter format")
    p.add_argument("--format", dest="input_format", help="override the input file extension")
    p.add_argument(
        "--scenario",
        choices=("voice-critical", "seeded-loss", "faithful-intermittent"),
        help="run the authored synthetic sealed-contract evidence suite or one asserted case",
    )
    p.add_argument("--out", required=True, help="output directory outside the repository")
    p.add_argument(
        "--generated-at", default="1970-01-01T00:00:00Z", dest="generated_at",
        help="ISO-8601 UTC stamp recorded in reports; defaults to a fixed value",
    )
    p.set_defaults(func=cmd_e2e)

    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, LookupError) as exc:
        finding = getattr(exc, "finding", None)
        if finding is not None:
            print("error: %s: %s" % (finding.code, finding.detail), file=sys.stderr)
        else:
            print("error: %s" % exc, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
