"""Canonical density measurement and bidirectional density verdicts.

The sole density metric is ``d = matched_units / eligible_units`` for one
``(scope, axis)``; source bands, target deltas, intervals, and verdicts are all
derived from that definition.  ``band`` uses linear interpolation on sorted
per-scene densities at index ``q * (n - 1)`` for each percentile ``q``.  Thus
its p10 and p90 values are deterministic, including for short distributions.

Verdict precedence is deliberate: calculate the target point estimate first,
then locate it against the effective band.  A point beyond ``OUTER_TOL`` is a
candidate hard result, but it is hard only when its floored-width Wilson 95%
interval also lies beyond the corresponding tolerance boundary.  The
min-sample rule and prose-fidelity mode can only reduce severity to report;
they never promote it.  This prevents a noisy unit from causing a hard failure
and keeps coarse dual-standard resolution from rejecting faithful prose, where
presence-class gates provide the guarantee.
"""

from dataclasses import dataclass
import math
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

from . import config
from .findings import Finding, hard, report


def _finite_number(value: object, name: str) -> float:
    """Reject non-numeric and non-finite inputs before arithmetic can mask them."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("%s must be a finite number, got %r" % (name, value))
    if not math.isfinite(value):
        raise ValueError("%s must be a finite number, got %r" % (name, value))
    return float(value)


def _density_value(value: object, name: str) -> float:
    """Return one finite density after enforcing its closed [0, 1] domain."""
    value = _finite_number(value, name)
    if value < 0 or value > 1:
        raise ValueError("%s must be a density from 0 through 1, got %r" % (name, value))
    return value



@dataclass(frozen=True)
class DensityVerdict:
    """The verdict and every derived quantity needed by a published row."""

    status: str
    reason: str
    under_sampled: bool
    effective_band: Tuple[float, float]
    delta: Optional[float]
    point_estimate: float
    wilson_interval: Tuple[float, float]


def to_finding(
    verdict: DensityVerdict,
    *,
    scope: str,
    axis: str,
    row_key: Optional[str] = None,
) -> Optional[Finding]:
    """Convert one density verdict to its sole corresponding finding, if any."""
    if verdict.status == config.DENSITY_STATUS_PASS:
        return None
    if verdict.status == config.DENSITY_STATUS_REPORT:
        return report(
            "DENSITY_VERDICT",
            verdict.reason,
            scope=scope,
            axis=axis,
            row_key=row_key,
        )
    if verdict.status == config.DENSITY_STATUS_HARD:
        return hard(
            "DENSITY_VERDICT",
            verdict.reason,
            scope=scope,
            axis=axis,
            row_key=row_key,
        )
    raise ValueError("unknown density verdict status %r" % (verdict.status,))


def density(matched_units: float, total_units: float) -> Optional[float]:
    """Return the canonical density, or ``None`` when no unit is eligible."""
    matched_units = _finite_number(matched_units, "matched_units")
    total_units = _finite_number(total_units, "total_units")
    if total_units < 0:
        raise ValueError("total_units must not be negative, got %r" % total_units)
    if matched_units < 0:
        raise ValueError("matched_units must not be negative, got %r" % matched_units)
    if total_units == 0:
        if matched_units != 0:
            raise ValueError(
                "matched_units %r cannot exceed zero eligible units" % matched_units
            )
        return None
    if matched_units > total_units:
        raise ValueError(
            "matched_units %r cannot exceed total_units %r"
            % (matched_units, total_units)
        )
    return matched_units / total_units



def _percentile(values: Sequence[float], quantile: float) -> float:
    """Interpolate a percentile on the documented ``q * (n - 1)`` position."""
    position = quantile * (len(values) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return values[lower_index]
    fraction = position - lower_index
    return values[lower_index] + (
        (values[upper_index] - values[lower_index]) * fraction
    )


def band(per_scene_densities: Iterable[float]) -> Tuple[float, float]:
    """Return the source p10/p90 band using deterministic linear interpolation."""
    try:
        values = list(per_scene_densities)
    except TypeError:
        raise ValueError(
            "per_scene_densities must be an iterable of finite densities, got %r"
            % (per_scene_densities,)
        )
    if not values:
        raise ValueError("per_scene_densities must not be empty")
    values = [
        _density_value(value, "per_scene_densities[%d]" % index)
        for index, value in enumerate(values)
    ]
    values.sort()
    return (_percentile(values, 0.10), _percentile(values, 0.90))



def _floor_interval_width(lower: float, upper: float) -> Tuple[float, float]:
    """Expand a Wilson interval conservatively to the configured minimum width."""
    width = upper - lower
    if width >= config.WILSON_FLOOR_WIDTH:
        return lower, upper

    expansion = (config.WILSON_FLOOR_WIDTH - width) / 2
    lower -= expansion
    upper += expansion
    if lower < 0:
        upper = min(1.0, upper - lower)
        lower = 0.0
    if upper > 1:
        lower = max(0.0, lower - (upper - 1.0))
        upper = 1.0
    return lower, upper


def wilson_interval(
    matched: float, total: float, z: float = config.WILSON_Z
) -> Tuple[float, float]:
    """Return the floored-width Wilson confidence interval for a density."""
    matched = _finite_number(matched, "matched")
    total = _finite_number(total, "total")
    z = _finite_number(z, "z")
    if total < 0:
        raise ValueError("total must not be negative, got %r" % total)
    if matched < 0 or matched > total:
        raise ValueError(
            "matched %r must be between zero and total %r" % (matched, total)
        )
    if z < 0:
        raise ValueError("z must not be negative, got %r" % z)
    if total == 0:
        return (0.0, 1.0)

    point = matched / total
    z_squared = z * z
    denominator = 1.0 + z_squared / total
    centre = (point + z_squared / (2.0 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            (point * (1.0 - point) / total)
            + (z_squared / (4.0 * total * total))
        )
        / denominator
    )
    lower = max(0.0, centre - margin)
    upper = min(1.0, centre + margin)
    return _floor_interval_width(lower, upper)



def _effective_band(
    source_band: Tuple[float, float], dual_standard: bool
) -> Tuple[float, float]:
    """Validate source bounds before applying the configured dual-standard widen."""
    try:
        lower, upper = source_band
    except (TypeError, ValueError):
        raise ValueError(
            "band must contain exactly two finite density bounds, got %r" % (source_band,)
        )
    lower = _density_value(lower, "band lower edge")
    upper = _density_value(upper, "band upper edge")
    if lower > upper:
        raise ValueError(
            "band lower edge %r must not exceed upper edge %r" % (lower, upper)
        )
    if dual_standard:
        return (
            lower - config.DUAL_STD_WIDEN,
            upper + config.DUAL_STD_WIDEN,
        )
    return lower, upper



def _interval_for_verdict(
    point_estimate: float,
    n_units: int,
    matched: Optional[float],
    total: Optional[float],
) -> Tuple[float, float]:
    """Use observed counts when available, otherwise a conservative proxy."""
    if (matched is None) != (total is None):
        raise ValueError("matched and total must be supplied together")
    if matched is not None and total is not None:
        return wilson_interval(matched, total)
    if n_units == 0:
        return wilson_interval(0, 0)
    return wilson_interval(point_estimate * n_units, n_units)


def verdict(
    d_tgt: float,
    band: Tuple[float, float],
    *,
    n_units: int,
    n_scenes: int,
    dual_standard: bool,
    mode: str,
    matched: Optional[float] = None,
    total: Optional[float] = None,
    d_src: Optional[float] = None,
) -> DensityVerdict:
    """Classify a target density against a source band under stated precedence.

    An in-band target passes only with sufficient units and scenes; otherwise it
    is report-only under the same under-sampling rule that caps out-of-band rows.
    """
    d_tgt = _density_value(d_tgt, "d_tgt")
    if d_src is not None:
        d_src = _density_value(d_src, "d_src")
    n_units = _finite_number(n_units, "n_units")
    n_scenes = _finite_number(n_scenes, "n_scenes")
    if n_units < 0 or n_scenes < 0:
        raise ValueError(
            "sample counts must not be negative, got n_units=%r n_scenes=%r"
            % (n_units, n_scenes)
        )
    if mode not in config.ENFORCEMENT_MODES:
        raise ValueError("mode must be a configured enforcement mode")


    effective_band = _effective_band(band, dual_standard)
    lower, upper = effective_band
    interval = _interval_for_verdict(d_tgt, n_units, matched, total)
    delta = None if d_src is None else d_tgt - d_src
    under_sampled = (
        n_units < config.MIN_UNITS_PER_SCOPE
        or n_scenes < config.MIN_SCENES_PER_BAND
    )

    if d_tgt < lower:
        direction = "below p10"
        distance = lower - d_tgt
        boundary = lower - config.OUTER_TOL
        interval_clears = interval[1] < boundary
        interval_side = "upper"
    elif d_tgt > upper:
        direction = "above p90"
        distance = d_tgt - upper
        boundary = upper + config.OUTER_TOL
        interval_clears = interval[0] > boundary
        interval_side = "lower"
    else:
        if under_sampled:
            reason = (
                "under-sampled: n_units {0} < MIN_UNITS_PER_SCOPE {1} or "
                "n_scenes {2} < MIN_SCENES_PER_BAND {3}; density verdict is "
                "report-only"
            ).format(
                n_units,
                config.MIN_UNITS_PER_SCOPE,
                n_scenes,
                config.MIN_SCENES_PER_BAND,
            )
            return DensityVerdict(
                config.DENSITY_STATUS_REPORT,
                reason,
                True,
                effective_band,
                delta,
                d_tgt,
                interval,
            )
        return DensityVerdict(
            config.DENSITY_STATUS_PASS,
            "inside the effective p10-p90 band [{0:.6f}, {1:.6f}]".format(
                lower, upper
            ),
            False,
            effective_band,
            delta,
            d_tgt,
            interval,
        )

    if under_sampled:
        reason = (
            "under-sampled: n_units {0} < MIN_UNITS_PER_SCOPE {1} or "
            "n_scenes {2} < MIN_SCENES_PER_BAND {3}; {4} by {5:.6f} is "
            "report-only"
        ).format(
            n_units,
            config.MIN_UNITS_PER_SCOPE,
            n_scenes,
            config.MIN_SCENES_PER_BAND,
            direction,
            distance,
        )
        return DensityVerdict(
            config.DENSITY_STATUS_REPORT,
            reason,
            True,
            effective_band,
            delta,
            d_tgt,
            interval,
        )

    if distance <= config.OUTER_TOL:
        reason = "{0} by {1:.6f} <= OUTER_TOL {2:.6f}".format(
            direction, distance, config.OUTER_TOL
        )
        return DensityVerdict(
            config.DENSITY_STATUS_REPORT,
            reason,
            False,
            effective_band,
            delta,
            d_tgt,
            interval,
        )

    interval_value = interval[1] if interval_side == "upper" else interval[0]
    interval_message = (
        "wilson {0} {1:.6f} {2} tolerance boundary {3:.6f}"
    ).format(
        interval_side,
        interval_value,
        "clears" if interval_clears else "does not clear",
        boundary,
    )
    point_message = "{0} by {1:.6f} > OUTER_TOL {2:.6f}".format(
        direction, distance, config.OUTER_TOL
    )

    if not interval_clears:
        return DensityVerdict(
            config.DENSITY_STATUS_REPORT,
            point_message + "; " + interval_message,
            False,
            effective_band,
            delta,
            d_tgt,
            interval,
        )

    if mode == config.MODE_PROSE_FIDELITY:
        reason = (
            point_message
            + "; "
            + interval_message
            + "; MODE_PROSE_FIDELITY caps density verdict at report because "
            "scope resolution is coarser on dual-standard work; presence-class "
            "gates carry the guarantee"
        )
        return DensityVerdict(
            config.DENSITY_STATUS_REPORT,
            reason,
            False,
            effective_band,
            delta,
            d_tgt,
            interval,
        )

    return DensityVerdict(
        config.DENSITY_STATUS_HARD,
        point_message + "; " + interval_message,
        False,
        effective_band,
        delta,
        d_tgt,
        interval,
    )


def scope_report(
    scope: str,
    axis: str,
    d_src: float,
    d_tgt: float,
    source_scene_densities: Iterable[float],
    *,
    n_units: int,
    n_scenes: int,
    dual_standard: bool,
    mode: str,
    matched: Optional[float] = None,
    total: Optional[float] = None,
    target_scene_densities: Optional[Iterable[float]] = None,
) -> dict:
    """Publish one deterministic, JSON-serialisable ``(scope, axis)`` row."""
    source_scenes = list(source_scene_densities)
    target_scenes = (
        [] if target_scene_densities is None else list(target_scene_densities)
    )
    source_band = band(source_scenes)
    result = verdict(
        d_tgt,
        source_band,
        n_units=n_units,
        n_scenes=n_scenes,
        dual_standard=dual_standard,
        mode=mode,
        matched=matched,
        total=total,
        d_src=d_src,
    )
    return {
        "scope": scope,
        "axis": axis,
        "d_src": d_src,
        "d_tgt": d_tgt,
        "point_estimate": result.point_estimate,
        "delta": result.delta,
        "band": [source_band[0], source_band[1]],
        "effective_band": [result.effective_band[0], result.effective_band[1]],
        "wilson": [result.wilson_interval[0], result.wilson_interval[1]],
        "n_units": n_units,
        "n_scenes": n_scenes,
        "under_sampled": result.under_sampled,
        "status": result.status,
        "reason": result.reason,
        "dual_standard": dual_standard,
        "mode": mode,
        "source_scene_densities": source_scenes,
        "target_scene_densities": target_scenes,
    }


def _row_value(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return row.get(name)
    return getattr(row, name, None)


def _target_scene_densities(row: object) -> List[float]:
    values = _row_value(row, "target_scene_densities")
    if values is None:
        values = _row_value(row, "per_scene_densities")
    if values is None:
        return []
    return list(values)


def saturation_findings(scope_rows: Iterable[object]) -> List[Finding]:
    """Report mechanically saturated target densities without changing gate severity."""
    rows = list(scope_rows)
    findings = []
    pinned_by_axis = {}

    for row in rows:
        scope = _row_value(row, "scope")
        axis = _row_value(row, "axis")
        target_scenes = _target_scene_densities(row)
        if len(target_scenes) >= 2 and all(
            0 <= value <= 1 for value in target_scenes
        ) and math.isclose(min(target_scenes), max(target_scenes)):
            findings.append(
                report(
                    "DENSITY_SATURATION",
                    "per-scene target density is approximately constant across "
                    "{0} scenes".format(len(target_scenes)),
                    scope=scope,
                    axis=axis,
                )
            )

        d_tgt = _row_value(row, "d_tgt")
        effective_band = _row_value(row, "effective_band")
        if effective_band is None:
            effective_band = _row_value(row, "band")
        if (
            d_tgt is not None
            and effective_band is not None
            and len(effective_band) == 2
            and math.isclose(d_tgt, effective_band[1])
        ):
            pinned_by_axis.setdefault(axis, []).append(scope)

    for axis, scopes in pinned_by_axis.items():
        unique_scopes = list(dict.fromkeys(scopes))
        if len(unique_scopes) >= 3:
            findings.append(
                report(
                    "DENSITY_BAND_MAX_PINNING",
                    "d_tgt pins to the band maximum across {0} speakers".format(
                        len(unique_scopes)
                    ),
                    row_key=",".join(str(scope) for scope in unique_scopes),
                    axis=axis,
                )
            )
    return findings
