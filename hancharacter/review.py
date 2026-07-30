"""Dependency-free review renderer, bound to the digest of what it reviews.

Static HTML and plain text, stdlib only, no server and no template engine. It
serves three jobs: corpus dual review, attribution review, and human confirmation.

The load-bearing property is the digest binding. A reviewer's approval is only
worth anything if the page they approved corresponds to the artifacts that ship,
so rendering REFUSES when the digest is absent or does not match the payload. An
unbound render that succeeded would let a reviewer sign off on one thing while a
different thing shipped, which is the failure this binding exists to prevent.

The digest is taken over canonical JSON -- sorted keys, no ASCII escaping, fixed
separators -- because a digest over non-canonical JSON changes with key insertion
order and would then fire on faithful input.

Output is deterministic for a fixed payload: no clock, no randomness, no
dict-order dependence. Any timestamp comes from the payload, never from the
system clock, so two renders of one payload are byte-identical and the artifact's
own digest is stable.
"""
import hashlib
import html
import json
import os
from typing import Any, Dict, List, Optional, Sequence

DIGEST_KEY = "digest"
_SECTIONS = ("corpus", "attribution", "confirmation")


class ReviewError(Exception):
    """A render that must not silently succeed."""


def canonical_json(payload: Dict[str, Any]) -> str:
    """Order-independent serialisation used for digesting."""
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def compute_digest(payload: Dict[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the payload's reviewable content.

    The stored digest is excluded from its own input; including it would make the
    digest unverifiable, since recomputing it would need the value it produces.
    """
    body = {key: value for key, value in payload.items() if key != DIGEST_KEY}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


def build_payload(
    *,
    title: str,
    corpus: Optional[Sequence[Dict[str, Any]]] = None,
    attribution: Optional[Sequence[Dict[str, Any]]] = None,
    confirmation: Optional[Sequence[Dict[str, Any]]] = None,
    generated_at: Optional[str] = None,
    catalogue_version: Optional[str] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble a reviewable payload from explicit, typed sections.

    Keyword-only and section-by-section rather than an untyped blob, so a caller
    cannot accidentally render an attribution list into the corpus lane where the
    reviewer action printed underneath it would be the wrong one.
    """
    return {
        "title": title,
        "generated_at": generated_at,
        "catalogue_version": catalogue_version,
        "notes": notes,
        "corpus": [dict(row) for row in (corpus or [])],
        "attribution": [dict(row) for row in (attribution or [])],
        "confirmation": [dict(row) for row in (confirmation or [])],
    }


def bind_digest(payload: Dict[str, Any], digest: Optional[str] = None) -> Dict[str, Any]:
    """Attach the digest of *payload*, or verify a supplied one."""
    bound = dict(payload)
    computed = compute_digest(bound)
    if digest is not None and digest != computed:
        raise ReviewError(
            "supplied digest %s does not match the payload digest %s; a review "
            "page bound to the wrong digest lets a reviewer approve one thing "
            "while another ships" % (digest, computed)
        )
    bound[DIGEST_KEY] = computed
    return bound


def _require_bound(payload: Dict[str, Any]) -> str:
    digest = payload.get(DIGEST_KEY)
    if not digest:
        raise ReviewError(
            "payload carries no %r; rendering an unbound review page would let a "
            "reviewer approve content that cannot be tied to what ships. Call "
            "bind_digest first." % DIGEST_KEY
        )
    computed = compute_digest(payload)
    if digest != computed:
        raise ReviewError(
            "payload digest %s does not match its content digest %s; the payload "
            "changed after it was bound" % (digest, computed)
        )
    return digest


def _is_empty(payload: Dict[str, Any]) -> bool:
    return not any(payload.get(section) for section in _SECTIONS)


_ACTIONS = {
    "corpus": (
        "To record a verdict, append one line to catalogue/reviews/<your-id>.jsonl: "
        '{"sample_id": "<id>", "reviewer": "<your-id>", "verdict": '
        '"accept|reject|needs_review", "note": "<rubric>"}'
    ),
    "attribution": (
        "To confirm a speaker, append the row key and speaker to the work's "
        "attribution confirmation log; an unconfirmed candidate never gates."
    ),
    "confirmation": (
        "To confirm a type, append one line to catalogue/human_confirm.jsonl "
        "stating the SCOPE of what you are confirming, the artifact you read and "
        "its sha256. A confirmation with no stated scope is read as blanket "
        "approval of everything beneath it."
    ),
}

_EMPTY_STATE = {
    "corpus": "No corpus row is awaiting review. Nothing here has been reviewed.",
    "attribution": "No attributed row is awaiting confirmation. Nothing here has been confirmed.",
    "confirmation": "No type is awaiting human confirmation. Nothing here has been confirmed.",
}


def _row_lines(section: str, row: Dict[str, Any]) -> List[str]:
    """The fields a reviewer needs for one row, per review job."""
    if section == "corpus":
        source = row.get("source") or {}
        return [
            "id: %s" % row.get("id"),
            "type: %s   axis: %s" % (row.get("type_id"), row.get("axis")),
            "work: %s" % row.get("work"),
            "marker: %s" % row.get("marker", "(none recorded)"),
            "quote: %s" % row.get("quote"),
            "cite: %s" % source.get("cite"),
            "provenance: class=%s consulted_via=%s independent_key=%s locator=%s"
            % (
                source.get("class"),
                source.get("consulted_via"),
                source.get("independent_key"),
                source.get("locator"),
            ),
            "producer: %s" % row.get("producer"),
            "notes: %s" % row.get("notes", "(none)"),
        ]
    if section == "attribution":
        return [
            "row: %s" % row.get("row_key"),
            "speaker: %s   scope: %s" % (row.get("speaker"), row.get("scope")),
            "tier: %s" % row.get("tier"),
            "surface: %s" % row.get("surface", "(none)"),
        ]
    return [
        "id: %s" % row.get("id"),
        "confirms: %s" % ", ".join(row.get("confirms", [])),
        "SCOPE: %s" % row.get("scope"),
        "artifact: %s (sha256 %s)"
        % (row.get("artifact_cite"), row.get("artifact_sha256")),
    ]


def render_text(payload: Dict[str, Any]) -> str:
    digest = _require_bound(payload)
    out: List[str] = []
    out.append(payload.get("title") or "hancharacter review")
    out.append("=" * len(out[0]))
    out.append("bound digest: %s" % digest)
    if payload.get("catalogue_version"):
        out.append("catalogue: %s" % payload["catalogue_version"])
    if payload.get("generated_at"):
        out.append("generated: %s" % payload["generated_at"])
    if payload.get("notes"):
        out.append("notes: %s" % payload["notes"])
    for section in _SECTIONS:
        rows = payload.get(section) or []
        out.append("")
        out.append("[%s] %d row(s)" % (section, len(rows)))
        if not rows:
            out.append("  %s" % _EMPTY_STATE[section])
            continue
        out.append("  action: %s" % _ACTIONS[section])
        for row in rows:
            out.append("  " + "-" * 60)
            for line in _row_lines(section, row):
                out.append("  %s" % line)
    out.append("")
    return "\n".join(out)


def render_html(payload: Dict[str, Any]) -> str:
    digest = _require_bound(payload)
    esc = lambda value: html.escape(str(value), quote=True)
    out: List[str] = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        "<title>%s</title>" % esc(payload.get("title") or "hancharacter review"),
        "<style>body{font:14px/1.5 system-ui,sans-serif;margin:2rem;max-width:60rem}"
        "section{border:1px solid #ccc;padding:1rem;margin:1rem 0}"
        ".row{border-top:1px solid #eee;padding:.5rem 0}"
        ".k{color:#555}.empty{color:#a00;font-weight:600}"
        "code{background:#f4f4f4;padding:.1rem .3rem}</style>",
        "</head><body>",
        "<h1>%s</h1>" % esc(payload.get("title") or "hancharacter review"),
        "<p class=\"k\">bound digest <code>%s</code></p>" % esc(digest),
    ]
    for key, label in (
        ("catalogue_version", "catalogue"),
        ("generated_at", "generated"),
        ("notes", "notes"),
    ):
        if payload.get(key):
            out.append(
                '<p class="k">%s: %s</p>' % (esc(label), esc(payload[key]))
            )
    for section in _SECTIONS:
        rows = payload.get(section) or []
        out.append("<section>")
        out.append("<h2>%s <span class=\"k\">(%d)</span></h2>" % (esc(section), len(rows)))
        if not rows:
            out.append('<p class="empty">%s</p>' % esc(_EMPTY_STATE[section]))
            out.append("</section>")
            continue
        out.append('<p class="k">%s</p>' % esc(_ACTIONS[section]))
        for row in rows:
            out.append('<div class="row">')
            for line in _row_lines(section, row):
                out.append("<div>%s</div>" % esc(line))
            out.append("</div>")
        out.append("</section>")
    out.append("</body></html>")
    return "\n".join(out) + "\n"


def write(payload: Dict[str, Any], out_dir: str, *, fmt: str = "html") -> str:
    """Render to disk, refusing a payload with nothing in it.

    An empty payload would render as a page with three clean-looking sections and
    no findings, which a reviewer could reasonably read as "reviewed and clean".
    Refusing is the only honest option.
    """
    if fmt not in ("html", "text"):
        raise ReviewError("unknown review format %r" % fmt)
    if _is_empty(payload):
        raise ReviewError(
            "refusing to write a review page with no corpus, attribution or "
            "confirmation rows; an empty page reads as 'reviewed and clean'"
        )
    _require_bound(payload)
    body = render_html(payload) if fmt == "html" else render_text(payload)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "review.%s" % ("html" if fmt == "html" else "txt"))
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(body)
    return path
