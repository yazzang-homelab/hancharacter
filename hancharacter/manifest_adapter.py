"""Read a hanpatch sealed manifest directly, verifying it rather than trusting it.

`io_adapters.read_host_json` already reads a host-shaped family map, and it stays
exactly as it is: it is the general path and ten formats depend on its behaviour.
This module is a separate, explicitly named door for one specific producer, so a
project that wants the sealed manifest as authority can have it without changing
what every other input format does.

The digest is re-derived here from the entries themselves, using hanpatch's
published rule, rather than read from the file. That catches the common case: a
manifest whose text was edited while the recorded digest was left behind.

**It does not catch a forgery.** The rule is published, so anyone who edits the
text can recompute the digest and this reader will accept the result. The digest
is a checksum, not a signature: it establishes that a file is internally
consistent, never that it came from a build you trust. Treat a manifest the same
way you treat the artifact it describes - as something whose provenance comes
from where you got it, not from a field inside it. Detecting deliberate
substitution needs a signature over the digest, which this format does not have.

Nothing is imported from hanpatch to do the re-derivation - the rule is small,
published, and copying it is safer than coupling two repositories' installs
together.

The join is strict in both directions. A row the manifest does not contain is
refused, and a manifest entry with no row is refused, because either direction
silently tolerated means the reviewer is judging a different set of lines than
the build ships.
"""

import hashlib
import json
import os

SCHEMA_VERSION = 1
HOST_ROWS_KIND = "hanpatch-host-rows"


class ManifestAdapterError(ValueError):
    """A manifest or host-rows document that cannot be used as evidence."""


def manifest_digest(entries):
    """Re-derive hanpatch's manifest digest from the entries.

    The rule is: for each key in sorted order, hash the key, a NUL, the value,
    and a NUL. Re-deriving locally is what makes an edited digest detectable;
    reading the recorded value would only prove the file is self-consistent.
    """
    h = hashlib.sha256()
    for key in sorted(entries):
        h.update(key.encode())
        h.update(b"\0")
        h.update(entries[key].encode())
        h.update(b"\0")
    return h.hexdigest()


def _load_object(path, what):
    if not os.path.isfile(path):
        raise ManifestAdapterError("%s is missing: %s" % (what, path))
    with open(path, "r", encoding="utf-8") as handle:
        try:
            data = json.load(handle)
        except ValueError as err:
            raise ManifestAdapterError("%s is not valid JSON: %s: %s"
                                       % (what, path, err))
    if not isinstance(data, dict):
        raise ManifestAdapterError("%s must be a JSON object: %s holds a %s"
                                   % (what, path, type(data).__name__))
    return data


def read_manifest(path, expected_ruleset=None):
    """Load a sealed manifest and prove its digest describes its entries."""
    doc = _load_object(path, "the sealed manifest")

    for field in ("entries", "digest"):
        if field not in doc:
            raise ManifestAdapterError("the sealed manifest is missing %r" % field)
    entries = doc["entries"]
    if not isinstance(entries, dict):
        raise ManifestAdapterError("manifest entries must be an object; got %s"
                                   % type(entries).__name__)
    for key, value in entries.items():
        if not isinstance(value, str):
            raise ManifestAdapterError("manifest entry %r is not a string" % key)

    actual = manifest_digest(entries)
    if actual != doc["digest"]:
        raise ManifestAdapterError(
            "manifest digest mismatch: recorded %s, re-derived %s"
            % (doc["digest"], actual))

    if expected_ruleset is not None and doc.get("ruleset") != expected_ruleset:
        raise ManifestAdapterError(
            "manifest ruleset %r is not the expected %r"
            % (doc.get("ruleset"), expected_ruleset))
    return doc


def read_host_rows(path):
    """Load a host-rows document produced by hanpatch's exporter."""
    doc = _load_object(path, "the host rows document")
    if doc.get("kind") != HOST_ROWS_KIND:
        raise ManifestAdapterError("host rows kind %r is not %r"
                                   % (doc.get("kind"), HOST_ROWS_KIND))
    if doc.get("schemaVersion") != SCHEMA_VERSION:
        raise ManifestAdapterError("host rows schemaVersion %r is not %d"
                                   % (doc.get("schemaVersion"), SCHEMA_VERSION))
    families = doc.get("families")
    if not isinstance(families, dict):
        raise ManifestAdapterError("host rows families must be an object")
    languages = doc.get("languages")
    if not isinstance(languages, dict) or not languages.get("evidence") \
            or not languages.get("target"):
        raise ManifestAdapterError(
            "host rows must name the evidence and target languages; without "
            "them the axes are a guess")
    return doc


def join(manifest_doc, host_doc):
    """Join rows against the sealed manifest, strictly in both directions.

    Returns rows carrying the manifest's text as `target`, so the reviewer reads
    the value that actually ships rather than the exporter's copy of it.
    """
    entries = manifest_doc["entries"]
    families = host_doc["families"]
    languages = host_doc["languages"]

    seen = set()
    rows = []
    for family in sorted(families):
        members = families[family]
        if not isinstance(members, list):
            raise ManifestAdapterError("family %r must hold a list" % family)
        for member in members:
            if not isinstance(member, dict):
                raise ManifestAdapterError("family %r has a non-object row"
                                           % family)
            key = member.get("key")
            if not isinstance(key, str) or not key:
                raise ManifestAdapterError("family %r has a row without a key"
                                           % family)
            full = "%s/%s" % (family, key)
            if full in seen:
                raise ManifestAdapterError("duplicate row %r" % full)
            seen.add(full)
            if full not in entries:
                raise ManifestAdapterError(
                    "row %r is not in the sealed manifest; the reviewer would "
                    "be judging a line the build does not ship" % full)
            evidence = member.get("evidence")
            if not isinstance(evidence, str):
                raise ManifestAdapterError("row %r has no evidence text" % full)
            row = {
                "row_key": full,
                "family": family,
                "evidence": evidence,
                # The manifest is the authority for shipped text.
                "target": entries[full],
                "evidence_lang": languages.get("evidence"),
                "target_lang": languages.get("target"),
            }
            if languages.get("pivot") is not None:
                pivot = member.get("pivot")
                if not isinstance(pivot, str):
                    raise ManifestAdapterError(
                        "row %r has no pivot text but a pivot language is "
                        "declared" % full)
                row["pivot"] = pivot
                row["pivot_lang"] = languages.get("pivot")
            if member.get("scene") is not None:
                row["scene"] = member["scene"]
            rows.append(row)

    missing = sorted(set(entries) - seen)
    if missing:
        raise ManifestAdapterError(
            "%d sealed entr%s absent from the host rows: %s"
            % (len(missing), 'y is' if len(missing) == 1 else 'ies are',
               ', '.join(missing[:5])))
    return rows


def load_joined(manifest_path, host_rows_path, expected_ruleset=None):
    """The whole read: verify the seal, read the rows, join them strictly."""
    manifest_doc = read_manifest(manifest_path, expected_ruleset=expected_ruleset)
    host_doc = read_host_rows(host_rows_path)

    recorded = host_doc.get("manifestDigest")
    if recorded is not None and recorded != manifest_doc["digest"]:
        raise ManifestAdapterError(
            "the host rows describe manifest %s but this manifest is %s"
            % (recorded, manifest_doc["digest"]))
    return join(manifest_doc, host_doc)
