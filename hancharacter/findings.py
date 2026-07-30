"""Structured findings with severity as the sole authority.

``Finding.severity`` is the only source of whether a finding is hard.  Callers
must inspect that field rather than consulting a separate code-based blocklist:
the replaced design kept such a list in a separately versioned package, which
could silently downgrade a hard finding to a pass.
"""

from dataclasses import dataclass
from typing import Iterable, List, Optional


Severity = str


@dataclass(frozen=True)
class Finding:
    """One auditable result emitted by a gate or report lint."""

    code: str
    severity: Severity
    detail: str
    scope: Optional[str] = None
    row_key: Optional[str] = None
    axis: Optional[str] = None

    def to_json(self) -> dict:
        """Return a stable, JSON-serialisable representation."""
        return {
            "code": self.code,
            "severity": self.severity,
            "detail": self.detail,
            "scope": self.scope,
            "row_key": self.row_key,
            "axis": self.axis,
        }


def hard(code: str, detail: str, **kw: object) -> Finding:
    """Build a hard finding without encoding severity in the code string."""
    return Finding(code=code, severity="hard", detail=detail, **kw)


def report(code: str, detail: str, **kw: object) -> Finding:
    """Build a report-only finding without encoding severity in the code string."""
    return Finding(code=code, severity="report", detail=detail, **kw)


class FindingSet:
    """Ordered collection of findings emitted during one operation."""

    def __init__(self) -> None:
        self._findings: List[Finding] = []

    def add(self, finding: Finding) -> None:
        self._findings.append(finding)

    def extend(self, findings: Iterable[Finding]) -> None:
        self._findings.extend(findings)

    @property
    def hard(self) -> List[Finding]:
        return [finding for finding in self._findings if finding.severity == "hard"]

    @property
    def reported(self) -> List[Finding]:
        return [
            finding for finding in self._findings if finding.severity == "report"
        ]

    def by_code(self) -> dict:
        counts = {}
        for finding in self._findings:
            counts[finding.code] = counts.get(finding.code, 0) + 1
        return counts

    def is_clean(self) -> bool:
        """A report-only finding never blocks an operation."""
        return not any(finding.severity == "hard" for finding in self._findings)

    def to_json(self) -> List[dict]:
        return [finding.to_json() for finding in self._findings]
