"""The producer boundary: hancharacter runs the gates, and says so in one file.

A host pipeline that wants a voice verdict has two bad options and one good one.
It can reimplement marker, density and corpus logic - which is how two
implementations drift until they disagree about the same text. It can shell out
to a CLI and parse prose - which turns a failure into an exit code and loses the
findings. Or it can read a file this module wrote.

This is that file's producer. It owns exactly one thing: assembling a complete,
explicit input set for ``gates.run`` and serialising what came back. It does not
decide anything about voice; ``gates.run`` already does. The serialiser is a
pass-through by design, because a producer that summarises is a second opinion.

Two properties make the result safe to trust across a repository boundary:

**The input set is closed.** ``VoiceRunRequest`` names every argument
``gates.run`` needs. A missing or wrongly typed one is a hard failure here, not
a default quietly supplied. A verdict produced from a partial input set would
still look like a verdict.

**The verdict is bound to what it judged.** The written document carries the
contract's semantic seal hash and, separately, the raw hash of the contract file
on disk. Those answer different questions - "is this the contract that was
sealed" versus "is this the byte stream I read" - and collapsing them into one
field is how a consumer ends up comparing a file hash against a seal and
concluding they disagree for the wrong reason.

v1 binds exactly one contract. Plural support is a real feature with real
questions (which authority applies to which speaker, what an incomplete set
means) and none of them are answered by silently accepting a list.
"""

import datetime as _dt
import hashlib
import json
import os
import tempfile
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence

from hancharacter import contracts as _contracts
from hancharacter import gates as _gates

SCHEMA_VERSION = 1
DOCUMENT_KIND = "hancharacter-voice-verdict"

#: Every ``gates.run`` argument this producer is responsible for supplying.
#: Listed explicitly so a future signature change fails loudly here rather than
#: silently producing a verdict from defaults.
REQUIRED_INPUTS = (
    "contracts",
    "attribution_gate",
    "seal_contract",
    "length_check",
    "observations",
    "catalogue_markers",
    "target_lang",
    "source_scene_densities",
    "measurable_axes",
    "quote_parity_findings",
)

OPTIONAL_INPUTS = (
    "marker_sets",
    "bands",
    "profile",
    "base_register_whitelist",
    "review_decisions",
    "ladder_check",
    "waivers",
)


class VoiceRunError(ValueError):
    """An input set that cannot produce an honest verdict."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_sha256(path: str) -> str:
    with open(path, "rb") as handle:
        return _sha256_bytes(handle.read())


def _canonical_sha256(obj: Any) -> str:
    """Hash a decoded document by canonical JSON, not by its file bytes.

    Two files that differ only in whitespace hold the same contract; two
    contracts that differ in a value do not. Formatting must not change the
    answer, so the semantic hash is taken over canonical JSON.
    """
    return _sha256_bytes(
        json.dumps(obj, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8"))


class VoiceRunRequest:
    """A closed, validated input set for one ``gates.run`` call."""

    def __init__(
        self,
        *,
        contracts: Iterable[Mapping[str, Any]],
        attribution_gate: Callable[[], Any],
        seal_contract: Callable[[Mapping[str, Any]], Any],
        length_check: Callable[[Mapping[str, Any]], Any],
        observations: Iterable[Any],
        catalogue_markers: Optional[Mapping[str, Any]],
        target_lang: str,
        source_scene_densities: Mapping[Any, Sequence[float]],
        measurable_axes: Mapping[str, Sequence[str]],
        quote_parity_findings: Any,
        marker_sets: Optional[Mapping[Any, Sequence[str]]] = None,
        bands: Optional[Mapping[Any, Sequence[float]]] = None,
        profile: Any = None,
        base_register_whitelist: Optional[Sequence[str]] = None,
        review_decisions: Optional[Mapping[str, Any]] = None,
        ladder_check: Optional[Callable[[Mapping[str, Any]], Any]] = None,
        waivers: Iterable[Mapping[str, Any]] = (),
    ) -> None:
        self.contracts = list(contracts)
        self.attribution_gate = attribution_gate
        self.seal_contract = seal_contract
        self.length_check = length_check
        self.observations = list(observations)
        self.catalogue_markers = catalogue_markers
        self.target_lang = target_lang
        self.source_scene_densities = source_scene_densities
        self.measurable_axes = measurable_axes
        self.quote_parity_findings = quote_parity_findings
        self.marker_sets = marker_sets
        self.bands = bands
        self.profile = profile
        self.base_register_whitelist = base_register_whitelist
        self.review_decisions = review_decisions
        self.ladder_check = ladder_check
        self.waivers = list(waivers)
        self._validate()

    def _validate(self) -> None:
        if len(self.contracts) != 1:
            raise VoiceRunError(
                "v1 binds exactly one sealed contract; got %d. Plural support "
                "needs an authority-per-speaker answer, which accepting a list "
                "silently does not provide." % len(self.contracts))

        contract = self.contracts[0]
        if not isinstance(contract, Mapping):
            raise VoiceRunError("the contract must be a mapping; got %s"
                                % type(contract).__name__)

        # `contracts.validate_contract` is the authority, not
        # `schemas.validate("contract")`. The shared schema is the older minimal
        # shape; P2 extends it, so validating an extended sealed contract against
        # the shared shape rejects every meaningful contract. The docstring on
        # validate_contract says so directly.
        errors = _contracts.validate_contract(contract)
        if errors:
            raise VoiceRunError("contract is invalid: %s" % "; ".join(errors))

        if not _contracts._seal_is_current(contract):
            raise VoiceRunError(
                "the contract seal is not current; re-seal before running the "
                "gates. A stale seal describes text that has since changed.")

        for name in ("attribution_gate", "seal_contract", "length_check"):
            value = getattr(self, name)
            if not callable(value):
                raise VoiceRunError("%s must be callable; got %s"
                                    % (name, type(value).__name__))
        if self.ladder_check is not None and not callable(self.ladder_check):
            raise VoiceRunError("ladder_check must be callable when supplied")

        if not self.target_lang or not isinstance(self.target_lang, str):
            raise VoiceRunError("target_lang must be a non-empty string")
        for name in ("source_scene_densities", "measurable_axes"):
            if not isinstance(getattr(self, name), Mapping):
                raise VoiceRunError("%s must be a mapping" % name)
        if self.catalogue_markers is not None and not isinstance(
                self.catalogue_markers, Mapping):
            raise VoiceRunError("catalogue_markers must be a mapping or None")

    @property
    def contract(self) -> Mapping[str, Any]:
        return self.contracts[0]

    def as_run_kwargs(self) -> dict:
        return {
            "contracts": self.contracts,
            "attribution_gate": self.attribution_gate,
            "seal_contract": self.seal_contract,
            "length_check": self.length_check,
            "observations": self.observations,
            "catalogue_markers": self.catalogue_markers,
            "target_lang": self.target_lang,
            "source_scene_densities": self.source_scene_densities,
            "measurable_axes": self.measurable_axes,
            "quote_parity_findings": self.quote_parity_findings,
            "marker_sets": self.marker_sets,
            "bands": self.bands,
            "profile": self.profile,
            "base_register_whitelist": self.base_register_whitelist,
            "review_decisions": self.review_decisions,
            "ladder_check": self.ladder_check,
            "waivers": self.waivers,
        }


def _finding_as_dict(finding: Any) -> dict:
    """Serialise one finding without interpreting it."""
    if isinstance(finding, Mapping):
        return dict(finding)
    out = {}
    for attr in ("code", "message", "scope", "row_key", "severity", "gate"):
        if hasattr(finding, attr):
            out[attr] = getattr(finding, attr)
    if not out:
        out = {"repr": repr(finding)}
    return out


def _findings_as_list(finding_set: Any) -> list:
    for attr in ("hard", "findings", "all"):
        if hasattr(finding_set, attr):
            value = getattr(finding_set, attr)
            if callable(value):
                continue
            try:
                return [_finding_as_dict(f) for f in value]
            except TypeError:
                continue
    try:
        return [_finding_as_dict(f) for f in finding_set]
    except TypeError:
        return [{"repr": repr(finding_set)}]


def produce(request: VoiceRunRequest, contract_path: Optional[str] = None) -> dict:
    """Run the gates and serialise exactly what they returned.

    The pass-through is the point. A producer that condensed findings into a
    verdict would be making the judgement `gates.run` already made, in a second
    place, from less information.
    """
    if not isinstance(request, VoiceRunRequest):
        raise VoiceRunError(
            "produce() takes a VoiceRunRequest so the input set is validated "
            "before the gates run; got %s" % type(request).__name__)

    finding_set, statuses = _gates.run(**request.as_run_kwargs())

    # Fail closed. `getattr(finding_set, "hard", [])` would report a pass for any
    # object that does not carry the attribute - including a future FindingSet
    # that renamed it - which turns an unreadable result into a clean bill of
    # health. If the hard findings cannot be read, nothing can be concluded.
    if not hasattr(finding_set, "hard"):
        raise VoiceRunError(
            "gates.run returned %s, which exposes no 'hard' findings; a verdict "
            "cannot be derived from a result this producer cannot read"
            % type(finding_set).__name__)
    hard = list(finding_set.hard or [])
    document = {
        "schemaVersion": SCHEMA_VERSION,
        "kind": DOCUMENT_KIND,
        "producedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "targetLang": request.target_lang,
        # Two hashes, two questions. The semantic seal identifies the contract;
        # the raw file hash identifies the bytes read. A consumer that compares
        # the wrong one against the wrong thing gets a mismatch for a reason that
        # has nothing to do with voice.
        "contractSha256": _canonical_sha256(request.contract),
        "contractFileSha256": (_read_sha256(contract_path)
                               if contract_path else None),
        "contractPath": contract_path,
        "verdict": "fail" if hard else "pass",
        "hardFindingCount": len(hard),
        "findings": _findings_as_list(finding_set),
        "gateStatuses": statuses,
    }
    return document


def write(document: Mapping[str, Any], path: str) -> str:
    """Atomic replace. A torn verdict still parses, which makes it worse than none."""
    payload = json.dumps(document, indent=2, sort_keys=True,
                         ensure_ascii=False) + "\n"
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".voice-verdict-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path
