"""Read-only adapters for common localisation containers.

Every reader returns dictionaries with the same measurement fields.  Control
syntax is removed before it reaches measurement, while :mod:`tag_grammar`
remains available to compare raw source and translated skeletons at an input
boundary.
"""
import io
import csv
import html
import json
import math
import os
import posixpath
import re
import zipfile
import unicodedata
from collections.abc import Mapping
from typing import Any, Dict, Iterable, List, Optional
from xml.etree import ElementTree as ET

from . import config, findings
from .tag_grammar import grammar_for, strip_tags


class AdapterError(ValueError):
    """A load failure with an auditable hard finding."""

    def __init__(self, code: str, detail: str, *, row_key: Optional[str] = None):
        self.finding = findings.hard(code, detail, row_key=row_key)
        self.findings = (self.finding,)
        super().__init__(detail)


class LoadedRows(list):
    """List-compatible rows carrying adapter counters needed by ``load_report``."""

    def __init__(
        self,
        rows: Iterable[Dict[str, Any]] = (),
        *,
        fmt: str,
        obsolete_skipped: int = 0,
        untranslated_skipped: int = 0,
        fuzzy_skipped: int = 0,
        encoding: Optional[str] = None,
        reported_findings: Iterable[findings.Finding] = (),
    ):
        super().__init__(rows)
        self.format = fmt
        self.obsolete_skipped = obsolete_skipped
        self.untranslated_skipped = untranslated_skipped
        self.fuzzy_skipped = fuzzy_skipped
        self.encoding = encoding
        self.reported_findings = tuple(reported_findings)




_EXTENSION_FORMATS = {
    ".txt": "plain_text",
    ".text": "plain_text",
    ".json": "json",
    ".csv": "csv",
    ".po": "po",
    ".xlf": "xliff",
    ".xlif": "xliff",
    ".xliff": "xliff",
    ".srt": "srt",
    ".vtt": "vtt",
    ".ass": "ass",
    ".epub": "epub",
}
_LANGUAGE_ALIASES = {
    "ja": ("ja", "jp", "jpn"),
    "en": ("en", "eng"),
    "ko": ("ko", "kr", "kor"),
}

_MAX_EPUB_ARCHIVE_MEMBERS = 10_000
_MAX_EPUB_ENTRY_BYTES = 64 * 1024 * 1024
_MAX_EPUB_TOTAL_BYTES = 256 * 1024 * 1024
_MAX_EPUB_COMPRESSION_RATIO = 1000

_BOM_ENCODINGS = (
    (b"\x00\x00\xfe\xff", "utf-32", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig", "utf-8"),
    (b"\xfe\xff", "utf-16", "utf-16-be"),
    (b"\xff\xfe", "utf-16", "utf-16-le"),
)
_XML_ENCODING = re.compile(br"^\s*<\?xml[^>]*\bencoding\s*=\s*['\"]([A-Za-z0-9._-]+)['\"]", re.I)
_PO_ENCODING = re.compile(br"content-type\s*:[^\r\n\"]*\bcharset\s*=\s*['\"]?([A-Za-z0-9._-]+)", re.I)
_ENCODING_ALIASES = {
    "utf8": "utf-8",
    "utf-8": "utf-8",
    "utf-8-sig": "utf-8-sig",
    "utf16": "utf-16",
    "utf-16": "utf-16",
    "utf-16-le": "utf-16-le",
    "utf-16-be": "utf-16-be",
    "utf32": "utf-32",
    "utf-32": "utf-32",
    "utf-32-le": "utf-32-le",
    "utf-32-be": "utf-32-be",
    "cp949": "cp949",
    "euc-kr": "euc_kr",
    "shift-jis": "shift_jis",
}


def _declared_xml_encoding(data: bytes) -> Optional[str]:
    match = _XML_ENCODING.search(data)
    return match.group(1).decode("ascii") if match else None


def _declared_po_encoding(data: bytes) -> Optional[str]:
    match = _PO_ENCODING.search(data)
    return match.group(1).decode("ascii") if match else None


def _validated_encoding(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        _failure("adapter_encoding_invalid", "%s has an invalid declared encoding" % path)
    selected = _ENCODING_ALIASES.get(value.lower().replace("_", "-"), value)
    try:
        b"".decode(selected)
    except LookupError:
        _failure("adapter_encoding_invalid", "%s declares unknown encoding %r" % (path, value))
    return selected


def _decode_text(data: bytes, path: str, *, encoding: Optional[str] = None, declaration=None):
    bom = next((entry for entry in _BOM_ENCODINGS if data.startswith(entry[0])), None)
    declared = declaration(data) if declaration is not None else None
    if encoding is not None:
        requested = _validated_encoding(encoding, path)
        if bom is not None and requested not in (bom[1], bom[2]):
            _failure(
                "adapter_encoding_conflict",
                "%s has a BOM that conflicts with encoding=%r" % (path, encoding),
            )
        selected = bom[1] if bom is not None else requested
        reported = bom[2] if bom is not None else requested
    elif bom is not None:
        selected = bom[1]
        reported = bom[2]
    elif declared is not None:
        selected = _validated_encoding(declared, path)
        reported = selected
    else:
        selected = "utf-8"
        reported = "utf-8"

    try:
        return data.decode(selected), reported
    except UnicodeDecodeError as error:
        if encoding is None and bom is None and declared is None:
            _failure(
                "adapter_encoding_undeclared",
                "%s is not UTF-8; supply encoding= for a non-BOM input" % path,
            )
        _failure("adapter_read_failed", "%s: %s" % (path, error))




def _trim_surface_padding(text: str) -> str:
    """Remove edge whitespace and declared invisible formatting controls."""
    start = 0
    end = len(text)
    while start < end and (
        text[start].isspace()
        or unicodedata.category(text[start]) in config.TARGET_VISIBILITY_BLANK_CATEGORIES
    ):
        start += 1
    while end > start and (
        text[end - 1].isspace()
        or unicodedata.category(text[end - 1]) in config.TARGET_VISIBILITY_BLANK_CATEGORIES
    ):
        end -= 1
    return text[start:end]


def _failure(code: str, detail: str, *, row_key: Optional[str] = None):
    raise AdapterError(code, detail, row_key=row_key)


def _canonical_format(fmt: str) -> str:
    return grammar_for(fmt).name


def _read_text(path: str, *, encoding: Optional[str] = None, declaration=None):
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as error:
        _failure("adapter_read_failed", "%s: %s" % (path, error))
    return _decode_text(data, path, encoding=encoding, declaration=declaration)


def _required_string(value: Any, label: str, row_key: str) -> str:
    if not isinstance(value, str):
        _failure("adapter_row_malformed", "%s must be a string" % label, row_key=row_key)
    return value

def _strip_profile_tags(text: str, profile: Any) -> str:
    """Remove work markup without consuming ruby needed by the segmenter."""
    def strip_fragment(fragment: str) -> str:
        for layout_tag in profile.layout_tags:
            fragment = fragment.replace(layout_tag, "")
        return profile.tag_re.sub("", fragment)

    parts = []
    start = 0
    for match in profile.ruby_re.finditer(text):
        parts.append(strip_fragment(text[start:match.start()]))
        parts.append(match.group(0))
        start = match.end()
    parts.append(strip_fragment(text[start:]))
    return "".join(parts)


def _strip_trailing_closers(
    surface: str,
    pairs: Iterable[tuple],
    lang: str,
    row_key: str,
    reported_findings: List[findings.Finding],
) -> str:
    """Remove any residual trailing declared closer.

    A closer sitting between the last character of speech and the end of the
    string is the ``$``-anchor hazard in its purest form: it silences an
    anchored marker whatever its pairing.  Pairing is the wrong question here.

    - ``그가 「명이오」`` has a *matched* pair, is not stripped by the pair loop
      because the row does not start with the opener, and used to pass while
      the trailing closer blocked the marker.
    - ``대사다.」`` is an *unpaired* closer, which is the ordinary shape of the
      second row of an utterance continued across rows, and used to hard-fail.
      That is a gate firing on faithful work.

    Both are normalised the same way and the removal is published.
    """

    pairs = tuple(pairs)
    stripped = []
    changed = True
    while changed and surface:
        changed = False
        for _opening, closing in pairs:
            if closing and surface.endswith(closing):
                surface = _trim_surface_padding(surface[: -len(closing)])
                stripped.append(closing)
                changed = True
                break
    if stripped:
        reported_findings.append(
            findings.report(
                "adapter_surface_trailing_closer_removed",
                "row %r language %r had trailing declared delimiter(s) %s removed "
                "so an anchored marker can reach the end of the surface"
                % (row_key, lang, "".join(stripped)),
                row_key=row_key,
            )
        )
    return surface


def _check_residual_delimiters(
    surface: str,
    pairs: Iterable[tuple],
    lang: str,
    row_key: str,
    reported_findings: List[findings.Finding],
) -> None:
    """Publish a residual leading opener.

    There is no trailing counterpart: :func:`_strip_trailing_closers` runs
    first and removes every declared closer at the end of the surface, so a
    hard "still not normalised" branch here could never fire.  A branch that
    cannot fire is not a guard, so it is not kept.

    A leading opener is deliberately report-only and is deliberately *not*
    stripped: it cannot hide a ``$``-anchored marker, and hard-failing it
    fires on thousands of rows of faithful baseline text.
    """

    for opening, closing in pairs:
        if surface.startswith(opening) and closing not in surface[len(opening):]:
            reported_findings.append(
                findings.report(
                    "adapter_surface_leading_opener",
                    "row %r language %r retains leading delimiter in surface %r; "
                    "a leading opener cannot hide a $-anchored marker"
                    % (row_key, lang, surface),
                    row_key=row_key,
                )
            )

def _optional_string(value: Any, label: str, row_key: str) -> Optional[str]:
    if value is None:
        return None
    return _required_string(value, label, row_key)


def _delimiter_surface(
    text: str,
    profile: Any,
    lang: str,
    row_key: str,
    *,
    require_complete: bool = False,
    reported_findings: Optional[List[findings.Finding]] = None,
) -> str:

    try:
        declared = profile.delimiters(lang)
    except (AttributeError, KeyError, TypeError) as error:
        _failure(
            "adapter_delimiters_undeclared",
            "row language %r has no declared delimiter map: %s" % (lang, error),
            row_key=row_key,
        )
    if not isinstance(declared, Mapping):
        _failure(
            "adapter_delimiters_undeclared",
            "row language %r has no declared delimiter map" % lang,
            row_key=row_key,
        )

    pairs = []
    for kind in ("speech", "term"):
        values = declared.get(kind, ())
        if not isinstance(values, (list, tuple)):
            _failure(
                "adapter_delimiters_malformed",
                "delimiter map for %r has non-list %s delimiters" % (lang, kind),
                row_key=row_key,
            )
        for pair in values:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2 or not all(isinstance(item, str) and item for item in pair):
                _failure(
                    "adapter_delimiters_malformed",
                    "delimiter map for %r has an invalid %s pair" % (lang, kind),
                    row_key=row_key,
                )
            pairs.append((pair[0], pair[1]))

    surface = _trim_surface_padding(text)
    changed = True
    while changed and surface:
        changed = False
        for opening, closing in pairs:
            if (
                surface.startswith(opening)
                and surface.endswith(closing)
                and len(surface) >= len(opening) + len(closing)
            ):
                surface = _trim_surface_padding(surface[len(opening):-len(closing)])
                changed = True
                break
    if require_complete:
        surface = _strip_trailing_closers(
            surface,
            pairs,
            lang,
            row_key,
            [] if reported_findings is None else reported_findings,
        )
        _check_residual_delimiters(
            surface,
            pairs,
            lang,
            row_key,
            [] if reported_findings is None else reported_findings,
        )

    return surface




def _surface(
    value: Any,
    grammar,
    profile: Any,
    lang: str,
    row_key: str,
    label: str,
    reported_findings: List[findings.Finding],
) -> str:
    text = _required_string(value, label, row_key)
    surface = _delimiter_surface(strip_tags(text, grammar), profile, lang, row_key)
    surface = _strip_profile_tags(surface, profile)
    return _delimiter_surface(
        surface,
        profile,
        lang,
        row_key,
        require_complete=True,
        reported_findings=reported_findings,
    )


def normalise_measurement_surface(
    text: Any, profile: Any, lang: str, *, row_key: str = "<measurement>"
) -> str:
    """Return the declared measurement surface for an adapter or raw gate value.

    This is the one delimiter normaliser used by adapters and raw gate observations.
    It removes only declared profile markup and paired declared delimiters, so
    anchored marker patterns retain their intended meaning.
    """
    return _surface(
        text,
        grammar_for("plain_text"),
        profile,
        lang,
        row_key,
        "measurement surface",
        [],
    )


def _structural_speech_surface(surface: str, profile: Any, lang: str, row_key: str) -> str:
    """Frame a structural speaker record with its declared speech delimiter."""
    try:
        declared = profile.delimiters(lang)
    except (AttributeError, KeyError, TypeError) as error:
        _failure(
            "adapter_delimiters_undeclared",
            "row language %r has no declared delimiter map: %s" % (lang, error),
            row_key=row_key,
        )
    pairs = declared.get("speech") if isinstance(declared, Mapping) else None
    if not isinstance(pairs, (list, tuple)) or not pairs:
        _failure(
            "adapter_delimiters_malformed",
            "delimiter map for %r has no declared speech pair" % lang,
            row_key=row_key,
        )
    opener, closer = pairs[0]
    if not all(isinstance(value, str) and value for value in (opener, closer)):
        _failure(
            "adapter_delimiters_malformed",
            "delimiter map for %r has an invalid speech pair" % lang,
            row_key=row_key,
        )
    return "%s%s%s" % (opener, surface, closer)




def _number(value: Any, label: str, row_key: str) -> float:
    if isinstance(value, bool):
        _failure("adapter_row_malformed", "%s must be a number" % label, row_key=row_key)
    try:
        result = float(value)
    except (TypeError, ValueError):
        _failure("adapter_row_malformed", "%s must be a number" % label, row_key=row_key)
    if not math.isfinite(result):
        _failure("adapter_row_malformed", "%s must be finite" % label, row_key=row_key)
    return result


def _make_row(
    fmt: str,
    profile: Any,
    *,
    key: Any,
    evidence: Any,
    pivot: Any,
    target: Any = None,
    speaker: Any = None,
    scene: Any = None,
    start: Any = None,
    end: Any = None,
    evidence_lang: Any = None,
    pivot_lang: Any = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    grammar = grammar_for(fmt)
    row_key = _required_string(key, "key", "<unknown>").strip()
    if not row_key:
        _failure("adapter_row_malformed", "key must not be empty", row_key="<unknown>")
    evidence_lang = profile.evidence_lang if evidence_lang is None else _required_string(evidence_lang, "evidence_lang", row_key)
    pivot_lang = profile.pivot_lang if pivot_lang is None else _required_string(pivot_lang, "pivot_lang", row_key)
    reported_findings = []
    evidence_surface = _surface(
        evidence, grammar, profile, evidence_lang, row_key, "evidence", reported_findings
    )
    pivot_surface = _surface(
        pivot, grammar, profile, pivot_lang, row_key, "pivot", reported_findings
    )
    target_surface = None
    if target is not None:
        target_surface = _surface(
            target,
            grammar,
            profile,
            profile.target_lang,
            row_key,
            "target",
            reported_findings,
        )
    speaker = _optional_string(speaker, "speaker", row_key)
    structural_speaker = speaker.strip() if speaker is not None and speaker.strip() else None
    adapter_structural = grammar.name in ("srt", "ass", "po", "csv")
    spine_pivot = _required_string(pivot, "pivot", row_key)
    spine_target = _optional_string(target, "target", row_key)
    if structural_speaker is not None and adapter_structural:
        # A record-level speaker declaration supplies the source scope; frame the
        # paired sides with the profile's declared speech delimiter so the shared
        # segment spine, rather than an adapter-only unit model, owns the group.
        spine_pivot = _structural_speech_surface(pivot_surface, profile, pivot_lang, row_key)
        if target_surface is not None:
            spine_target = _structural_speech_surface(
                target_surface, profile, profile.target_lang, row_key
            )
    row = {
        "key": row_key,
        # Preserve structural source markup and declared delimiters for the spine.
        # The paired canonical fields remain available for direct measurement and
        # raw gate surfaces use ``normalise_measurement_surface`` above.
        "evidence": _required_string(evidence, "evidence", row_key),
        "pivot": spine_pivot,
        "evidence_surface": evidence_surface,
        "pivot_surface": pivot_surface,
        "evidence_lang": evidence_lang,
        "pivot_lang": pivot_lang,
        "tag_grammar": grammar.name,
        "adapter": grammar.name,
    }
    if spine_target is not None:
        row["target"] = spine_target
        row["target_surface"] = target_surface
    if reported_findings:
        row["_adapter_report_findings"] = tuple(reported_findings)
    if structural_speaker is not None:
        row["speaker"] = structural_speaker
    scene = _optional_string(scene, "scene", row_key)
    if scene is not None and scene.strip():
        row["scene"] = scene.strip()
    if (start is None) != (end is None):
        _failure("adapter_timing_incomplete", "start and end must occur together", row_key=row_key)
    if start is not None:
        start_seconds = _number(start, "start", row_key)
        end_seconds = _number(end, "end", row_key)
        if end_seconds < start_seconds:
            _failure("adapter_timing_invalid", "end precedes start", row_key=row_key)
        row["start"] = start_seconds
        row["end"] = end_seconds
    if extra:
        row.update(extra)
    return row


def _loaded(
    fmt: str,
    rows: Iterable[Dict[str, Any]],
    *,
    obsolete_skipped: int = 0,
    untranslated_skipped: int = 0,
    fuzzy_skipped: int = 0,
    encoding: Optional[str] = None,
) -> LoadedRows:
    reported_findings = []
    materialised = list(rows)
    for row in materialised:
        if isinstance(row, dict):
            reported_findings.extend(row.pop("_adapter_report_findings", ()))
    result = LoadedRows(
        materialised,
        fmt=fmt,
        obsolete_skipped=obsolete_skipped,
        untranslated_skipped=untranslated_skipped,
        fuzzy_skipped=fuzzy_skipped,
        encoding=encoding,
        reported_findings=reported_findings,
    )
    if not result and not (untranslated_skipped or fuzzy_skipped):
        _failure(
            "adapter_rows_empty",
            "%s produced no rows; an empty input cannot be a clean measurement" % fmt,
        )


    return result


def _value_for_lang(record: Mapping[str, Any], lang: str, generic: str) -> Any:
    for name in _LANGUAGE_ALIASES.get(lang, (lang,)) + (generic,):
        if name in record:
            return record[name]
    return None


def _generic_values(record: Mapping[str, Any], profile: Any, row_key: str):
    evidence = record.get("evidence")
    if evidence is None:
        evidence = _value_for_lang(record, profile.evidence_lang, "source")
    pivot = record.get("pivot")
    target_supplies_pivot = False
    if pivot is None:
        pivot = _value_for_lang(record, profile.pivot_lang, "translation")
    if pivot is None and "target" in record:
        pivot = record["target"]
        target_supplies_pivot = True
    if pivot is None:
        pivot = record.get("text")
    if evidence is None and pivot is not None:
        evidence = pivot
    if pivot is None and evidence is not None:
        pivot = evidence
    if evidence is None or pivot is None:
        _failure(
            "adapter_row_malformed",
            "row needs evidence/pivot, language columns, source/translation, or text",
            row_key=row_key,
        )
    if target_supplies_pivot:
        target = None
    else:
        target = record.get("target") if "target" in record else _value_for_lang(record, profile.target_lang, "target")
    return evidence, pivot, target


def read_plain_text(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read one non-blank text line as one single-language measurement row."""
    grammar_for("plain_text")
    text, source_encoding = _read_text(path, encoding=encoding)
    rows = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if line.strip():
            rows.append(
                _make_row(
                    "plain_text", profile, key="plain:%d" % line_number,
                    evidence=line, pivot=line,
                )
            )
    return _loaded("plain_text", rows, encoding=source_encoding)


def read_json(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read explicit normalised records or a ``rows`` list from JSON."""
    try:
        text, source_encoding = _read_text(path, encoding=encoding)
        data = json.loads(text)
    except json.JSONDecodeError as error:
        _failure("adapter_json_malformed", "%s: %s" % (path, error))

    keyed = None
    if isinstance(data, list):
        records = data
    elif isinstance(data, Mapping) and isinstance(data.get("rows"), list):
        records = data["rows"]
    elif isinstance(data, Mapping) and all(isinstance(value, list) for value in data.values()):
        return _loaded_host_json(data, profile=profile, encoding=source_encoding)
    elif isinstance(data, Mapping) and all(isinstance(value, (Mapping, str)) for value in data.values()):
        keyed = data
        records = list(data.values())
    else:
        _failure("adapter_json_malformed", "JSON must be a list, a rows list, a key-to-record map, or a host rows map")


    rows = []
    for index, record in enumerate(records, start=1):
        map_key = list(keyed)[index - 1] if keyed is not None else None
        if isinstance(record, str):
            record = {"key": map_key or "json:%d" % index, "text": record}
        if not isinstance(record, Mapping):
            _failure("adapter_row_malformed", "JSON record %d is not an object" % index)
        key = record.get("key", record.get("id", map_key or "json:%d" % index))
        row_key = str(key) if isinstance(key, str) else "json:%d" % index
        evidence, pivot, target = _generic_values(record, profile, row_key)
        rows.append(
            _make_row(
                "json", profile, key=key, evidence=evidence, pivot=pivot, target=target,
                speaker=record.get("speaker"), scene=record.get("scene"),
                start=record.get("start"), end=record.get("end"),
                evidence_lang=record.get("evidence_lang"), pivot_lang=record.get("pivot_lang"),
            )
        )
    return _loaded("json", rows, encoding=source_encoding)


def read_csv(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read CSV rows without guessing a structural speaker column."""
    try:
        text, source_encoding = _read_text(path, encoding=encoding)
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            _failure("adapter_csv_malformed", "CSV has no header row")
        records = list(reader)
    except csv.Error as error:
        _failure("adapter_csv_malformed", "%s: %s" % (path, error))

    profile_data = getattr(profile, "data", {})
    speaker_column = profile_data.get("csv_speaker_column") if isinstance(profile_data, Mapping) else None
    if speaker_column is not None and speaker_column not in reader.fieldnames:
        _failure(
            "adapter_csv_speaker_column_missing",
            "declared csv_speaker_column %r is absent" % speaker_column,
        )

    rows = []
    for index, record in enumerate(records, start=2):
        if None in record:
            _failure("adapter_csv_malformed", "CSV row %d has too many columns" % index)
        key = record.get("key", record.get("id", "csv:%d" % index))
        row_key = str(key) if isinstance(key, str) else "csv:%d" % index
        evidence, pivot, target = _generic_values(record, profile, row_key)
        speaker = record.get(speaker_column) if speaker_column is not None else None
        extra = {}
        if speaker_column is not None:
            extra.update({"speaker_column": speaker_column, "csv_speaker": speaker})
        rows.append(
            _make_row(
                "csv", profile, key=key, evidence=evidence, pivot=pivot, target=target,
                speaker=speaker, scene=record.get("scene"),
                evidence_lang=record.get("evidence_lang"), pivot_lang=record.get("pivot_lang"),
                extra=extra,
            )
        )
    return _loaded("csv", rows, encoding=source_encoding)


def _po_quoted(value: str, row_key: str) -> str:
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError as error:
        _failure("adapter_po_malformed", "invalid PO string: %s" % error, row_key=row_key)
    if not isinstance(decoded, str):
        _failure("adapter_po_malformed", "PO value is not a string", row_key=row_key)
    return decoded


def read_po(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read gettext entries, including continuations, without loading obsolete rows."""
    grammar_for("po")
    text, source_encoding = _read_text(
        path, encoding=encoding, declaration=_declared_po_encoding
    )
    entries = []
    current: Dict[str, Any] = {}
    active = None
    obsolete_skipped = 0
    untranslated_skipped = 0
    fuzzy_skipped = 0

    def flush():
        nonlocal current, active, obsolete_skipped, untranslated_skipped, fuzzy_skipped
        if not current:
            active = None
            return
        if current.get("obsolete"):
            obsolete_skipped += 1
        elif "msgid" in current and current.get("msgid") != "":
            if "msgstr" not in current:
                _failure("adapter_po_malformed", "PO entry has no msgstr")
            if current.get("fuzzy"):
                fuzzy_skipped += 1
            elif current["msgstr"] == "":
                untranslated_skipped += 1
            else:
                entries.append(current)
        elif "msgid" not in current:
            _failure("adapter_po_malformed", "PO entry has no msgid")
        current = {}
        active = None

    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#~"):
            current["obsolete"] = True
            active = None
            continue
        if line.startswith("#,"):
            current["fuzzy"] = current.get("fuzzy", False) or "fuzzy" in {
                flag.strip() for flag in line[2:].split(",")
            }
            continue
        if line.startswith("#"):
            continue
        match = re.match(r"^(msgctxt|msgid|msgstr)\s+(\".*\")$", line)
        if match:
            active = match.group(1)
            current[active] = _po_quoted(match.group(2), "po:%d" % number)
            continue
        if line.startswith('"') and line.endswith('"'):
            if active is None or active not in current:
                _failure("adapter_po_malformed", "PO continuation has no preceding field", row_key="po:%d" % number)
            current[active] += _po_quoted(line, "po:%d" % number)
            continue
        _failure("adapter_po_malformed", "unrecognised PO syntax", row_key="po:%d" % number)
    flush()

    rows = []
    for index, entry in enumerate(entries, start=1):
        key = entry.get("msgctxt") or "po:%d" % index
        context = entry.get("msgctxt")
        speaker = context
        if isinstance(speaker, str) and speaker.startswith("speaker:"):
            speaker = speaker[len("speaker:"):]
        extra = {"msgctxt": context} if context is not None else None
        rows.append(
            _make_row(
                "po", profile, key=key, evidence=entry["msgid"], pivot=entry.get("msgstr", ""),
                speaker=speaker, extra=extra,
            )
        )
    return _loaded(
        "po",
        rows,
        obsolete_skipped=obsolete_skipped,
        untranslated_skipped=untranslated_skipped,
        fuzzy_skipped=fuzzy_skipped,
        encoding=source_encoding,
    )



def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_fragment(element: ET.Element) -> str:
    """Serialise only declared XLIFF inline syntax, preserving its skeleton."""
    name = _local_name(element.tag)
    if name not in {"g", "x", "ph", "bpt", "ept"}:
        _failure("adapter_xliff_inline_unknown", "XLIFF inline element %r has no declared grammar" % name)
    attrs = "".join(
        " %s=\"%s\"" % (_local_name(key), html.escape(value, quote=True))
        for key, value in sorted(element.attrib.items())
    )
    children = list(element)
    body = element.text or ""
    for child in children:
        body += _xml_fragment(child)
        body += child.tail or ""
    if name == "x" and not children and not body:
        return "<x%s/>" % attrs
    return "<%s%s>%s</%s>" % (name, attrs, body, name)


def _xliff_text(element: ET.Element) -> str:
    value = element.text or ""
    for child in list(element):
        value += _xml_fragment(child)
        value += child.tail or ""
    return value


def read_xliff(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read XLIFF ``trans-unit`` source/target pairs and protect inline markup."""
    text, source_encoding = _read_text(
        path, encoding=encoding, declaration=_declared_xml_encoding
    )
    try:
        root = ET.fromstring(text)
    except ET.ParseError as error:
        _failure("adapter_xliff_malformed", "%s: %s" % (path, error))

    rows = []
    for index, unit in enumerate((item for item in root.iter() if _local_name(item.tag) == "trans-unit"), start=1):
        source = next((item for item in unit if _local_name(item.tag) == "source"), None)
        target = next((item for item in unit if _local_name(item.tag) == "target"), None)
        key = unit.get("id") or "xliff:%d" % index
        if source is None or target is None:
            _failure("adapter_xliff_malformed", "trans-unit needs source and target", row_key=key)
        rows.append(
            _make_row(
                "xliff", profile, key=key, evidence=_xliff_text(source), pivot=_xliff_text(target),
            )
        )
    return _loaded("xliff", rows, encoding=source_encoding)


def _srt_seconds(value: str, row_key: str) -> float:
    match = re.fullmatch(r"(\d{2,}):([0-5]\d):([0-5]\d),(\d{3})", value.strip())
    if match is None:
        _failure("adapter_srt_timing_malformed", "invalid SRT timestamp %r" % value, row_key=row_key)
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + int(match.group(4)) / 1000.0


def _vtt_seconds(value: str, row_key: str) -> float:
    match = re.fullmatch(r"(?:(\d{2,}):)?([0-5]\d):([0-5]\d)\.(\d{3})", value.strip())
    if match is None:
        _failure("adapter_vtt_timing_malformed", "invalid VTT timestamp %r" % value, row_key=row_key)
    hours = int(match.group(1) or 0)
    return hours * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + int(match.group(4)) / 1000.0


def _cue_times(line: str, parser, row_key: str):
    if "-->" not in line:
        _failure("adapter_cue_malformed", "cue timing line lacks -->", row_key=row_key)
    start, end = line.split("-->", 1)
    end_value = end.strip().split(None, 1)[0] if end.strip() else ""
    return parser(start.strip(), row_key), parser(end_value, row_key)


def read_srt(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read SubRip cues with real start/end seconds."""
    text, source_encoding = _read_text(path, encoding=encoding)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    rows = []
    for cue_index, block in enumerate(re.split(r"\n\s*\n", text.strip()), start=1):
        lines = block.split("\n")
        if lines and lines[0].strip().isdigit():
            cue_id = lines.pop(0).strip()
        else:
            cue_id = str(cue_index)
        row_key = "srt:%s" % cue_id
        if not lines or "-->" not in lines[0]:
            _failure("adapter_srt_malformed", "SRT cue has no timing line", row_key=row_key)
        start, end = _cue_times(lines.pop(0), _srt_seconds, row_key)
        if not lines:
            _failure("adapter_srt_malformed", "SRT cue has no text", row_key=row_key)
        text_value = "\n".join(lines)
        rows.append(_make_row("srt", profile, key=row_key, evidence=text_value, pivot=text_value, start=start, end=end))
    return _loaded("srt", rows, encoding=source_encoding)


def read_vtt(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read WebVTT cues with settings-independent real start/end seconds."""
    text, source_encoding = _read_text(path, encoding=encoding)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    if not blocks or not blocks[0].startswith("WEBVTT"):
        _failure("adapter_vtt_malformed", "WebVTT input must start with WEBVTT")

    rows = []
    for cue_index, block in enumerate(blocks[1:], start=1):
        lines = block.split("\n")
        if not lines or lines[0].startswith(("NOTE", "STYLE", "REGION")):
            continue
        timing_index = 0 if "-->" in lines[0] else 1
        if timing_index >= len(lines) or "-->" not in lines[timing_index]:
            _failure("adapter_vtt_malformed", "WebVTT cue has no timing line", row_key="vtt:%d" % cue_index)
        cue_id = lines[0].strip() if timing_index else str(cue_index)
        row_key = "vtt:%s" % cue_id
        start, end = _cue_times(lines[timing_index], _vtt_seconds, row_key)
        payload = lines[timing_index + 1:]
        if not payload:
            _failure("adapter_vtt_malformed", "WebVTT cue has no text", row_key=row_key)
        text_value = "\n".join(payload)
        rows.append(_make_row("vtt", profile, key=row_key, evidence=text_value, pivot=text_value, start=start, end=end))
    return _loaded("vtt", rows, encoding=source_encoding)


def _ass_seconds(value: str, row_key: str) -> float:
    match = re.fullmatch(r"(\d+):([0-5]\d):([0-5]\d)\.(\d{1,2})", value.strip())
    if match is None:
        _failure("adapter_ass_timing_malformed", "invalid ASS timestamp %r" % value, row_key=row_key)
    centiseconds = int(match.group(4).ljust(2, "0"))
    return int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3)) + centiseconds / 100.0


def read_ass(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read ASS Dialogue rows and use the declared Name field as speaker metadata."""
    fields = None
    in_events = False
    rows = []
    text, source_encoding = _read_text(path, encoding=encoding)
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip("\ufeff")
        if line.startswith("[") and line.endswith("]"):
            in_events = line.lower() == "[events]"
            continue
        if not in_events or not line or line.startswith(";"):
            continue
        if line.lower().startswith("format:"):
            fields = [field.strip().lower() for field in line.split(":", 1)[1].split(",")]
            required = {"start", "end", "name", "text"}
            if not required.issubset(fields) or fields[-1] != "text":
                _failure("adapter_ass_malformed", "ASS Events Format must contain Start, End, Name, and final Text")
            continue
        if line.lower().startswith("dialogue:"):
            if fields is None:
                _failure("adapter_ass_malformed", "Dialogue appears before Events Format", row_key="ass:%d" % number)
            values = line.split(":", 1)[1].lstrip().split(",", len(fields) - 1)
            if len(values) != len(fields):
                _failure("adapter_ass_malformed", "Dialogue has fewer fields than Events Format", row_key="ass:%d" % number)
            record = dict(zip(fields, values))
            row_key = "ass:%d" % number
            start = _ass_seconds(record["start"], row_key)
            end = _ass_seconds(record["end"], row_key)
            rows.append(
                _make_row(
                    "ass", profile, key=row_key, evidence=record["text"], pivot=record["text"],
                    speaker=record["name"], start=start, end=end,
                )
            )
            continue
        if line.lower().startswith(("comment:", "picture:", "sound:", "movie:", "command:")):
            continue
        _failure(
            "adapter_ass_malformed",
            "unrecognised ASS Events record",
            row_key="ass:%d" % number,
        )
    return _loaded("ass", rows, encoding=source_encoding)


def _guard_epub_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if len(infos) > _MAX_EPUB_ARCHIVE_MEMBERS:
        _failure(
            "adapter_epub_archive_unsafe",
            "EPUB archive has more than %d members" % _MAX_EPUB_ARCHIVE_MEMBERS,
        )

    total = 0
    for info in infos:
        if info.is_dir():
            continue
        if info.file_size > _MAX_EPUB_ENTRY_BYTES:
            _failure(
                "adapter_epub_archive_unsafe",
                "EPUB member %r exceeds the %d byte limit" % (info.filename, _MAX_EPUB_ENTRY_BYTES),
            )
        total += info.file_size
        if total > _MAX_EPUB_TOTAL_BYTES:
            _failure(
                "adapter_epub_archive_unsafe",
                "EPUB archive exceeds the %d byte uncompressed limit" % _MAX_EPUB_TOTAL_BYTES,
            )
        if info.file_size and (
            info.compress_size <= 0
            or info.file_size > info.compress_size * _MAX_EPUB_COMPRESSION_RATIO
        ):
            _failure(
                "adapter_epub_archive_unsafe",
                "EPUB member %r exceeds the compression-ratio limit" % info.filename,
            )


def _archive_xml(
    archive: zipfile.ZipFile,
    member: str,
    *,
    encoding: Optional[str],
):
    try:
        data = archive.read(member)
    except (KeyError, zipfile.BadZipFile) as error:
        _failure("adapter_epub_malformed", "EPUB member %r is unavailable: %s" % (member, error))
    return _decode_text(data, member, encoding=encoding, declaration=_declared_xml_encoding)


def _epub_rootfile(archive: zipfile.ZipFile, *, encoding: Optional[str]):
    try:
        text, source_encoding = _archive_xml(
            archive, "META-INF/container.xml", encoding=encoding
        )
        root = ET.fromstring(text)
    except ET.ParseError as error:
        _failure("adapter_epub_malformed", "EPUB container.xml is malformed: %s" % error)
    rootfile = next((item for item in root.iter() if _local_name(item.tag) == "rootfile"), None)
    if rootfile is None or not rootfile.get("full-path"):
        _failure("adapter_epub_malformed", "EPUB container has no OPF rootfile")
    return rootfile.get("full-path"), source_encoding


def read_epub(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read XHTML paragraphs in OPF spine order, one paragraph per row."""
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as error:
        _failure("adapter_epub_malformed", "%s: %s" % (path, error))
    with archive:
        _guard_epub_archive(archive)
        opf_path, container_encoding = _epub_rootfile(archive, encoding=encoding)
        try:
            opf_text, opf_encoding = _archive_xml(archive, opf_path, encoding=encoding)
            opf = ET.fromstring(opf_text)
        except ET.ParseError as error:
            _failure("adapter_epub_malformed", "EPUB OPF is malformed: %s" % error)
        manifest = {}
        for item in (node for node in opf.iter() if _local_name(node.tag) == "item"):
            item_id = item.get("id")
            href = item.get("href")
            if item_id and href:
                manifest[item_id] = href
        spine = [item.get("idref") for item in opf.iter() if _local_name(item.tag) == "itemref"]
        if not spine:
            _failure("adapter_epub_malformed", "EPUB OPF spine has no itemref")

        encodings = {container_encoding, opf_encoding}
        rows = []
        for spine_index, item_id in enumerate(spine, start=1):
            if item_id not in manifest:
                _failure("adapter_epub_malformed", "EPUB spine idref %r is absent from manifest" % item_id)
            chapter_path = posixpath.normpath(posixpath.join(posixpath.dirname(opf_path), manifest[item_id]))
            try:
                chapter_text, chapter_encoding = _archive_xml(
                    archive, chapter_path, encoding=encoding
                )
                chapter = ET.fromstring(chapter_text)
            except ET.ParseError as error:
                _failure(
                    "adapter_epub_malformed",
                    "EPUB spine item %r is malformed: %s" % (item_id, error),
                )
            encodings.add(chapter_encoding)
            paragraph_index = 0
            for paragraph in (node for node in chapter.iter() if _local_name(node.tag) == "p"):
                text_value = " ".join("".join(paragraph.itertext()).split())
                if not text_value:
                    continue
                paragraph_index += 1
                rows.append(
                    _make_row(
                        "epub", profile, key="epub:%d:%d" % (spine_index, paragraph_index),
                        evidence=text_value, pivot=text_value,
                    )
                )
    return _loaded("epub", rows, encoding=",".join(sorted(encodings)))


def _loaded_host_json(data: Mapping[str, Any], *, profile: Any, encoding: str) -> LoadedRows:
    """Normalise a host family map after the JSON adapter has identified it."""
    rows = []
    for family, records in data.items():
        if not isinstance(family, str) or not isinstance(records, list):
            _failure("adapter_host_json_malformed", "every host family must contain a row list")
        for index, record in enumerate(records, start=1):
            if not isinstance(record, Mapping) or "key" not in record:
                _failure("adapter_host_json_malformed", "host row %s:%d lacks key" % (family, index))
            key = "%s/%s" % (family, record["key"])
            evidence = _value_for_lang(record, profile.evidence_lang, "evidence")
            pivot = _value_for_lang(record, profile.pivot_lang, "pivot")
            if evidence is None or pivot is None:
                _failure("adapter_host_json_malformed", "host row needs declared evidence and pivot language columns", row_key=key)
            target = _value_for_lang(record, profile.target_lang, "target")
            rows.append(
                _make_row(
                    "host_json", profile, key=key, evidence=evidence, pivot=pivot, target=target,
                    scene=record.get("scene"),
                )
            )
    return _loaded("host_json", rows, encoding=encoding)


def read_host_json(path: str, *, profile: Any, encoding: Optional[str] = None) -> LoadedRows:
    """Read a host-shaped family map without importing or writing any host code."""
    try:
        text, source_encoding = _read_text(path, encoding=encoding)
        data = json.loads(text)
    except json.JSONDecodeError as error:
        _failure("adapter_host_json_malformed", "%s: %s" % (path, error))
    if not isinstance(data, Mapping):
        _failure("adapter_host_json_malformed", "host JSON must be a family-to-rows object")
    return _loaded_host_json(data, profile=profile, encoding=source_encoding)


# Short aliases match common extension and container terminology without adding
# another dispatch path.
read_plain = read_plain_text
read_txt = read_plain_text
read_xlf = read_xliff


def load(
    path: str,
    *,
    profile: Any,
    fmt: Optional[str] = None,
    encoding: Optional[str] = None,
) -> LoadedRows:
    """Dispatch a declared input format; unknown extensions fail as hard findings."""
    requested = fmt
    if requested is None:
        requested = _EXTENSION_FORMATS.get(os.path.splitext(path)[1].lower())
        if requested is None:
            _failure("adapter_format_undeclared", "cannot infer a declared adapter format from %s" % path)
    canonical = _canonical_format(requested)
    readers = {
        "plain_text": read_plain_text,
        "json": read_json,
        "csv": read_csv,
        "po": read_po,
        "xliff": read_xliff,
        "srt": read_srt,
        "vtt": read_vtt,
        "ass": read_ass,
        "epub": read_epub,
        "host_json": read_host_json,
    }
    return readers[canonical](path, profile=profile, encoding=encoding)


def load_report(rows: Iterable[Mapping[str, Any]], fmt: str) -> Dict[str, Any]:
    """Summarise adapter output, including zero counters and hard validation gaps."""
    canonical = _canonical_format(fmt)
    materialised = list(rows)
    found = list(getattr(rows, "reported_findings", ()))
    if not materialised:
        found.append(
            findings.hard(
                "adapter_rows_empty",
                "%s produced no rows; an empty input cannot be a clean measurement" % canonical,
            )
        )

    with_timing = 0
    with_speaker = 0
    required = {"key", "evidence", "pivot", "evidence_lang", "pivot_lang", "tag_grammar"}
    for index, row in enumerate(materialised, start=1):
        if not isinstance(row, Mapping):
            found.append(findings.hard("adapter_row_malformed", "row %d is not an object" % index))
            continue
        missing = sorted(required - set(row))
        if missing:
            found.append(findings.hard("adapter_row_malformed", "row %d lacks %s" % (index, ", ".join(missing))))
            continue
        if row.get("tag_grammar") != canonical:
            found.append(
                findings.hard(
                    "adapter_tag_grammar_mismatch",
                    "row %s declares tag grammar %r, expected %r" % (row.get("key"), row.get("tag_grammar"), canonical),
                    row_key=row.get("key") if isinstance(row.get("key"), str) else None,
                )
            )
        if isinstance(row.get("speaker"), str) and row["speaker"].strip():
            with_speaker += 1
        has_start = "start" in row
        has_end = "end" in row
        if has_start != has_end:
            found.append(findings.hard("adapter_timing_incomplete", "row %s has only one timing bound" % row.get("key")))
        elif has_start:
            try:
                start = _number(row["start"], "start", str(row.get("key")))
                end = _number(row["end"], "end", str(row.get("key")))
            except AdapterError as error:
                found.extend(error.findings)
            else:
                if end < start:
                    found.append(findings.hard("adapter_timing_invalid", "row %s ends before it starts" % row.get("key")))
                else:
                    with_timing += 1

    counters = {}
    for name in ("obsolete_skipped", "untranslated_skipped", "fuzzy_skipped"):
        value = getattr(rows, name, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            found.append(findings.hard("adapter_report_malformed", "%s counter is invalid" % name))
            value = 0
        counters[name] = value
    leading_openers = sum(
        finding.code == "adapter_surface_leading_opener" for finding in found
    )

    return {
        "format": canonical,
        "rows": len(materialised),
        "with_timing": with_timing,
        "with_speaker": with_speaker,
        "obsolete_skipped": counters["obsolete_skipped"],
        "untranslated_skipped": counters["untranslated_skipped"],
        "fuzzy_skipped": counters["fuzzy_skipped"],
        "tag_grammar": grammar_for(canonical).name,
        "encoding": getattr(rows, "encoding", None),
        "leading_openers": leading_openers,
        "findings": [finding.to_json() for finding in found],
    }
