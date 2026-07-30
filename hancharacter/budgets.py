"""Layout-budget checks for translated dialogue.

The caller supplies the work declaration rather than relying on a package-wide
fallback.  A budget declaration is either one model (``{"class": "subtitle",
...}``) or a map from declared ``edition_medium`` to models (with an optional
``edition_medium`` selector).  This keeps an unknown medium from inheriting a
nearby format's limits.

Netflix's timed-text guidance uses 42 characters per line. A profile must
explicitly declare that value and its own CPS; this module never supplies a
numeric bound. Balloon dimensions depend on the work's artwork and advisory
media have no hard bound, so neither has a generic numeric default.
"""
from collections.abc import Mapping
import math
import unicodedata

from hancharacter import findings


SUBTITLE = "subtitle"
BALLOON = "balloon"
ADVISORY = "advisory"
_ADVISORY_MEDIA = frozenset(("novel", "po", "plain"))
_MODEL_CLASSES = frozenset((SUBTITLE, BALLOON, ADVISORY))
_ZERO_WORST = {
    "cpl": 0.0,
    "cps": 0.0,
    "chars": 0.0,
    "area": 0.0,
    "marker_length": 0.0,
}


def display_width(text):
    """Return terminal-style display columns, counting wide East Asian glyphs as two."""
    if not isinstance(text, str):
        raise TypeError("display width requires text")
    return sum(
        0 if unicodedata.combining(char) else
        2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        for char in text
    )


def check(rows, *, budgets, realisations=None):
    """Check translated rows against their declared layout models.

    ``rows`` may contain mappings or normalized ``segment.Row`` values.  A row
    selects catalogue realisations through ``realisation_id``,
    ``realisation_ids``, or ``realisations``; a direct row ``length_cost`` is
    also accepted.  If more than one supplied realisation exists without a row
    selection, the row is recorded as unmeasurable rather than charging a
    guessed marker.

    ``budgets`` is deliberately required.  It may be one model with a ``class``
    or a medium-to-model mapping such as ``{"edition_medium": "srt",
    "srt": {"class": "subtitle", "cpl": 42, "cps": 20}}``.  A model
    selected for an undeclared medium is never inferred.
    """
    result = findings.FindingSet()
    try:
        rows = list(rows)
    except TypeError:
        rows = []
        result.add(findings.hard("budget_rows_invalid", "rows must be an iterable"))

    report = {
        "class": _report_class(budgets),
        "rows": len(rows),
        "measured": 0,
        "unmeasurable": 0,
        "worst": dict(_ZERO_WORST),
        "violations": [],
        "measurements": [],
        "findings": [],
    }
    if not rows:
        result.add(
            findings.hard(
                "budget_rows_absent",
                "layout budget check received no rows and cannot pass vacuously",
            )
        )
        return _finish(result, report)

    if not isinstance(budgets, Mapping):
        result.add(
            findings.hard(
                "budget_declaration_invalid",
                "budgets must be a declared mapping",
            )
        )
        for index, row in enumerate(rows):
            _unmeasurable(
                result,
                report,
                row,
                index,
                "budget_declaration_invalid",
                "the work budget declaration is not a mapping",
            )
        return _finish(result, report)

    classes = set()
    for index, row in enumerate(rows):
        model, medium, model_error = _model_for(row, budgets)
        if model_error is not None:
            _unmeasurable(result, report, row, index, model_error[0], model_error[1])
            continue

        model_class = _model_class(model, medium)
        if model_class is None:
            _unmeasurable(
                result,
                report,
                row,
                index,
                "budget_declaration_invalid",
                "the declared budget model for edition_medium %r has no known class" % medium,
            )
            continue
        classes.add(model_class)

        surface, surface_name = _surface(row)
        if surface is None:
            _unmeasurable(
                result,
                report,
                row,
                index,
                "budget_surface_absent",
                "no string target, text, or pivot surface is available for layout measurement",
                model_class=model_class,
            )
            continue

        costs, cost_error = _costs_for(row, realisations)
        if cost_error is not None:
            _unmeasurable(
                result,
                report,
                row,
                index,
                "budget_realisation_unmodelled",
                cost_error,
                model_class=model_class,
            )
            continue
        try:
            projection = _project(surface, costs)
        except ValueError as exc:
            _unmeasurable(
                result,
                report,
                row,
                index,
                "budget_realisation_unmodelled",
                str(exc),
                model_class=model_class,
            )
            continue

        if model_class == SUBTITLE:
            _check_subtitle(
                result, report, row, index, model, projection, surface_name, model_class
            )
        elif model_class == BALLOON:
            _check_balloon(
                result, report, row, index, model, projection, surface_name, model_class
            )
        else:
            _check_advisory(
                report, row, index, projection, surface_name, model_class
            )

    if len(classes) == 1:
        report["class"] = next(iter(classes))
    elif len(classes) > 1:
        report["class"] = "mixed"
    return _finish(result, report)


def _finish(result, report):
    report["findings"] = result.to_json()
    return result, report

def _report_class(budgets):
    if not isinstance(budgets, Mapping):
        return "unmodelled"
    direct = budgets.get("class")
    if direct in _MODEL_CLASSES:
        return direct
    selected = budgets.get("edition_medium")
    candidates = _budget_models(budgets)
    if selected in candidates:
        declared = _model_class(candidates[selected], selected)
        if declared is not None:
            return declared
    declared = {
        _model_class(model, medium)
        for medium, model in candidates.items()
        if _model_class(model, medium) is not None
    }
    return next(iter(declared)) if len(declared) == 1 else "unmodelled"


def _budget_models(budgets):
    nested = budgets.get("models")
    if isinstance(nested, Mapping):
        return nested
    return {
        key: value
        for key, value in budgets.items()
        if key not in ("edition_medium", "class", "medium") and isinstance(value, Mapping)
    }


def _model_for(row, budgets):
    row_medium = _row_value(row, "edition_medium", _MISSING)
    if row_medium is _MISSING:
        row_medium = _row_value(row, "medium", _MISSING)
    if row_medium is _MISSING:
        row_medium = _row_value(row, "format", _MISSING)
    if isinstance(budgets.get("class"), str):
        model = budgets
        declared_class = budgets["class"]
        accepted_medium = budgets.get("medium", budgets.get("edition_medium", declared_class))
        medium = accepted_medium if row_medium is _MISSING else row_medium
        if medium != accepted_medium:
            return None, medium, (
                "budget_edition_medium_unmodelled",
                "edition_medium %r has no declared layout model" % medium,
            )
        return model, medium, None

    declared_medium = budgets.get("edition_medium")
    medium = declared_medium if row_medium is _MISSING else row_medium
    if not isinstance(medium, str) or not medium:
        return None, None, (
            "budget_edition_medium_absent",
            "edition_medium is absent, so no layout model can be selected",
        )

    models = _budget_models(budgets)
    model = models.get(medium)
    if not isinstance(model, Mapping):
        return None, medium, (
            "budget_edition_medium_unmodelled",
            "edition_medium %r has no declared layout model" % medium,
        )
    return model, medium, None


def _model_class(model, medium):
    if not isinstance(model, Mapping):
        return None
    declared = model.get("class")
    if declared in _MODEL_CLASSES:
        return declared
    lowered = medium.lower() if isinstance(medium, str) else ""
    if lowered == SUBTITLE:
        return SUBTITLE
    if lowered == BALLOON:
        return BALLOON
    if lowered in _ADVISORY_MEDIA:
        return ADVISORY
    return None


def _surface(row):
    for name in ("target", "text", "pivot"):
        value = _row_value(row, name, _MISSING)
        if value is _MISSING or value is None:
            continue
        if isinstance(value, str):
            return value, name
        return None, name
    return None, None


def _costs_for(row, realisations):
    direct = _row_value(row, "length_cost", _MISSING)
    if direct is not _MISSING:
        return [direct], None

    selected = _row_value(row, "realisations", _MISSING)
    if selected is _MISSING:
        selected = _row_value(row, "realisation_ids", _MISSING)
    if selected is _MISSING:
        selected = _row_value(row, "realisation_id", _MISSING)
    if selected is _MISSING:
        selected = _row_value(row, "realisation", _MISSING)

    if selected is _MISSING:
        if realisations is None:
            return [], None
        if isinstance(realisations, Mapping) and "length_cost" in realisations:
            return [realisations["length_cost"]], None
        if isinstance(realisations, (list, tuple)):
            return _costs_from_items(realisations, None)
        if isinstance(realisations, Mapping):
            candidates = [value for value in realisations.values() if isinstance(value, Mapping)]
            if len(candidates) == 1:
                return _costs_from_items(candidates, None)
            return None, "multiple supplied realisations require a row realisation_id selection"
        return None, "realisations must be catalogue mappings or a sequence"

    if isinstance(selected, (str, bytes)):
        selected = [selected]
    elif isinstance(selected, Mapping):
        if "length_cost" in selected:
            selected = [selected]
        else:
            return None, "row realisations mapping must contain length_cost"
    elif not isinstance(selected, (list, tuple)):
        return None, "row realisation selection must be an id or sequence"

    return _costs_from_items(selected, realisations)


def _costs_from_items(items, realisations):
    costs = []
    for item in items:
        if isinstance(item, Mapping):
            cost = item.get("length_cost", item)
        elif isinstance(item, str) and isinstance(realisations, Mapping):
            variant = realisations.get(item)
            if not isinstance(variant, Mapping):
                return None, "realisation %r is not supplied" % item
            cost = variant.get("length_cost")
        else:
            return None, "realisation selection has no length_cost"
        if not isinstance(cost, Mapping):
            return None, "realisation selection has no length_cost"
        costs.append(cost)
    return costs, None


def _project(surface, costs):
    lines = _lines(surface)
    chars = float(sum(len(line) for line in lines))
    width = float(sum(display_width(line) for line in lines))
    line_count = len(lines)
    balloon_line_width = float(max((len(line) for line in lines), default=0))

    for cost in costs:
        model = cost.get("model")
        value = cost.get("value")
        if not _number(value) or value < 0:
            raise ValueError("realisation length_cost.value must be a non-negative finite number")
        value = float(value)
        if model == "append":
            chars += value
            width += value
            balloon_line_width += value
        elif model == "multiply":
            chars *= value
            width *= value
            balloon_line_width *= value
        elif model == "split":
            if not value.is_integer() or value < 1:
                raise ValueError("split length_cost.value must be a positive whole number")
            line_count *= int(value)
            balloon_line_width = float(math.ceil(chars / line_count)) if chars else 0.0
        else:
            raise ValueError("unknown realisation length_cost.model %r" % model)

    return {
        "chars": chars,
        "display_width": width,
        "lines": line_count,
        "cpl": width / line_count,
        "area": balloon_line_width * line_count,
        "marker_length": chars - float(sum(len(line) for line in _lines(surface))),
        "costs": [dict(cost) for cost in costs],
    }


def _check_subtitle(result, report, row, index, model, projection, surface_name, model_class):
    cpl_budget, cpl_error = _budget_number(model, "cpl")
    cps_budget, cps_error = _budget_number(model, "cps")
    if cpl_error or cps_error:
        _invalid_budget(result, report, row, index, model_class, cpl_error or cps_error)
        return

    start = _row_value(row, "start", _MISSING)
    end = _row_value(row, "end", _MISSING)
    duration = None
    if _number(start) and _number(end) and float(end) > float(start):
        duration = float(end) - float(start)

    measurement = _measurement(row, index, model_class, projection, surface_name)
    measurement.update({"cpl_budget": cpl_budget, "cps_budget": cps_budget, "cps": None})
    if duration is None:
        report["measurements"].append(measurement)
        _update_worst(report, projection)
        _violate_if_needed(
            result, report, row, model_class, "cpl", projection["cpl"], cpl_budget
        )
        _unmeasurable(
            result,
            report,
            row,
            index,
            "budget_subtitle_timing_absent",
            "subtitle CPS cannot be measured because start/end timing is absent or invalid",
            model_class=model_class,
            append_measurement=False,
        )
        return

    cps = projection["chars"] / duration
    measurement.update({"duration": duration, "cps": cps})
    report["measurements"].append(measurement)
    report["measured"] += 1
    _update_worst(report, projection, cps=cps)
    _violate_if_needed(result, report, row, model_class, "cpl", projection["cpl"], cpl_budget)
    _violate_if_needed(result, report, row, model_class, "cps", cps, cps_budget)


def _check_balloon(result, report, row, index, model, projection, surface_name, model_class):
    chars_budget, chars_error = _budget_number(model, "chars")
    area_budget, area_error = _budget_number(model, "area")
    if chars_error or area_error:
        _invalid_budget(result, report, row, index, model_class, chars_error or area_error)
        return

    measurement = _measurement(row, index, model_class, projection, surface_name)
    measurement.update({"chars_budget": chars_budget, "area_budget": area_budget})
    report["measurements"].append(measurement)
    report["measured"] += 1
    _update_worst(report, projection)
    _violate_if_needed(
        result, report, row, model_class, "chars", projection["chars"], chars_budget
    )
    _violate_if_needed(
        result, report, row, model_class, "area", projection["area"], area_budget
    )


def _check_advisory(report, row, index, projection, surface_name, model_class):
    report["measurements"].append(
        _measurement(row, index, model_class, projection, surface_name)
    )
    report["measured"] += 1
    _update_worst(report, projection)


def _budget_number(model, name):
    value = model.get(name) if isinstance(model, Mapping) else None
    if not _number(value):
        return None, "declared %s budget must be a non-negative finite number" % name
    if value < 0:
        return None, "declared %s budget must be a non-negative finite number" % name
    return value, None


def _invalid_budget(result, report, row, index, model_class, detail):
    result.add(
        findings.hard(
            "budget_declaration_invalid",
            detail,
            scope=_row_value(row, "speaker", None),
            row_key=_row_key(row, index),
            axis=model_class,
        )
    )
    _unmeasurable(
        result,
        report,
        row,
        index,
        "budget_declaration_invalid",
        detail,
        model_class=model_class,
    )


def _violate_if_needed(result, report, row, model_class, metric, actual, budget):
    if actual <= budget:
        return
    key = _row_key(row, len(report["measurements"]) - 1)
    violation = {
        "row_key": key,
        "class": model_class,
        "metric": metric,
        "actual": actual,
        "budget": budget,
    }
    report["violations"].append(violation)
    result.add(
        findings.hard(
            "budget_%s_%s_exceeded" % (model_class, metric),
            "%s %.3f exceeds declared %s budget %s" % (metric, actual, metric, budget),
            scope=_row_value(row, "speaker", None),
            row_key=key,
            axis=model_class,
        )
    )


def _measurement(row, index, model_class, projection, surface_name):
    return {
        "row_key": _row_key(row, index),
        "class": model_class,
        "surface": surface_name,
        "chars": projection["chars"],
        "display_width": projection["display_width"],
        "lines": projection["lines"],
        "cpl": projection["cpl"],
        "area": projection["area"],
        "marker_length": projection["marker_length"],
        "length_costs": projection["costs"],
    }


def _unmeasurable(
    result,
    report,
    row,
    index,
    code,
    detail,
    *,
    model_class=None,
    append_measurement=True
):
    report["unmeasurable"] += 1
    if append_measurement:
        report["measurements"].append(
            {
                "row_key": _row_key(row, index),
                "class": model_class,
                "status": "unmeasurable",
                "reason": code,
            }
        )
    result.add(
        findings.report(
            code,
            detail,
            scope=_row_value(row, "speaker", None),
            row_key=_row_key(row, index),
            axis=model_class,
        )
    )


def _update_worst(report, projection, *, cps=None):
    worst = report["worst"]
    worst["cpl"] = max(worst["cpl"], projection["cpl"])
    worst["chars"] = max(worst["chars"], projection["chars"])
    worst["area"] = max(worst["area"], projection["area"])
    worst["marker_length"] = max(worst["marker_length"], projection["marker_length"])
    if cps is not None:
        worst["cps"] = max(worst["cps"], cps)


def _lines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _row_key(row, index):
    value = _row_value(row, "key", _MISSING)
    return str(index) if value is _MISSING else str(value)


def _row_value(row, name, default):
    if isinstance(row, Mapping):
        return row.get(name, default)
    return getattr(row, name, default)


_MISSING = object()
