"""Declared control-token grammars for supported localisation formats.

The adapter never treats undeclared control syntax as ordinary prose.  A grammar
identifies every control token that is removed before measurement and retained
in an ordered skeleton for a later source/translation comparison.
"""
from dataclasses import dataclass, field
import re
from typing import Dict, Iterable, Tuple

from . import findings


class TagGrammarError(ValueError):
    """A hard, serialisable failure to select a declared tag grammar."""

    def __init__(self, fmt: object):
        self.finding = findings.hard(
            "tag_grammar_undeclared",
            "format %r has no declared tag grammar; its control syntax cannot be "
            "protected" % (fmt,),
        )
        self.findings = (self.finding,)
        super().__init__(self.finding.detail)


@dataclass(frozen=True)
class TagGrammar:
    """The syntax protected for one input container format."""

    name: str
    tag_patterns: Tuple[str, ...] = ()
    placeholder_patterns: Tuple[str, ...] = ()
    # Syntax that is not markup but layout: it carries no meaning of its own
    # yet occupies a real position in the utterance.  Deleting it welds the
    # neighbouring text together, which both destroys a "$"-anchored marker at
    # the end of a display line and can fabricate a word that was never
    # written.  Each entry maps a pattern to the literal it becomes.
    layout_substitutions: Tuple[Tuple[str, str], ...] = ()
    _matcher: re.Pattern = field(init=False, repr=False, compare=False)
    _layout: Tuple[Tuple[re.Pattern, str], ...] = field(
        init=False, repr=False, compare=False
    )

    def __post_init__(self):
        patterns = self.tag_patterns + self.placeholder_patterns
        matcher = re.compile("|".join("(?:%s)" % pattern for pattern in patterns)) if patterns else re.compile(r"(?!x)x")
        object.__setattr__(self, "_matcher", matcher)
        object.__setattr__(
            self,
            "_layout",
            tuple(
                (re.compile(pattern), literal)
                for pattern, literal in self.layout_substitutions
            ),
        )

    @property
    def matcher(self):
        return self._matcher

    def apply_layout(self, text: str) -> str:
        """Replace layout syntax with the literal it stands for.

        Applied before tag stripping so a layout break survives as a real
        break instead of being deleted along with markup.
        """

        for pattern, literal in self._layout:
            text = pattern.sub(literal, text)
        return text


# The patterns deliberately name format syntax rather than using one universal
# angle-bracket rule.  A format not listed here fails at lookup instead of
# silently receiving a permissive default.
GRAMMARS: Dict[str, TagGrammar] = {
    "plain_text": TagGrammar("plain_text"),
    "json": TagGrammar("json"),
    "csv": TagGrammar("csv"),
    "po": TagGrammar(
        "po",
        placeholder_patterns=(
            r"(?<!%)%(?:\d+\$)?[-+#0 ']*\d*(?:\.\d+)?[diuoxXfFeEgGaAcspn]",
            r"(?<!\{)\{(?:[A-Za-z_][A-Za-z0-9_]*|\d+)\}",
        ),
    ),
    "xliff": TagGrammar(
        "xliff",
        tag_patterns=(
            r"<(?:bpt|ept|ph)\b[^>\n]*(?:/>|>[\s\S]*?</(?:bpt|ept|ph)\s*>)",
            r"</?(?:g|x)\b[^>\n]*/?>",
        ),
    ),
    "srt": TagGrammar(
        "srt",
        tag_patterns=(r"</?(?:i|b|u|font)\b[^>\n]*/?>",),
    ),
    "vtt": TagGrammar(
        "vtt",
        tag_patterns=(
            r"<\d{2}:\d{2}:\d{2}\.\d{3}>",
            r"</?(?:c(?:\.[A-Za-z0-9_-]+)*|v(?:\s+[^>\n]*)?|lang(?:\s+[^>\n]*)?|ruby|rt|b|i|u)\s*>",
        ),
    ),
    "ass": TagGrammar(
        "ass",
        # Only the override block is markup.  "\N", "\n" and "\h" are layout,
        # so they are substituted below rather than stripped: deleting a hard
        # break fused two display lines and destroyed a marker anchored to the
        # end of the first one.
        tag_patterns=(r"\{\\[^}]*\}",),
        layout_substitutions=(
            (r"\\N", "\n"),
            (r"\\n", "\n"),
            (r"\\h", "\u00a0"),
        ),
    ),
    "epub": TagGrammar(
        "epub",
        tag_patterns=(r"</?[A-Za-z][^>\n]*>",),
    ),
    "host_json": TagGrammar(
        "host_json",
        tag_patterns=(r"<[^>\n]*>",),
    ),
}

# Extension and public-format aliases are declarations too; they do not create
# a fallback grammar.
ALIASES = {
    "plain": "plain_text",
    "text": "plain_text",
    "txt": "plain_text",
    "xlf": "xliff",
    "xlif": "xliff",
    "host": "host_json",
}


def grammar_for(fmt: str) -> TagGrammar:
    """Return the required grammar for *fmt*, or raise a hard failure."""
    canonical = ALIASES.get(fmt, fmt) if isinstance(fmt, str) else fmt
    try:
        return GRAMMARS[canonical]
    except (KeyError, TypeError) as error:
        raise TagGrammarError(fmt) from error


def _require_grammar(grammar: TagGrammar) -> TagGrammar:
    if not isinstance(grammar, TagGrammar):
        raise TagGrammarError(getattr(grammar, "name", grammar))
    return grammar


def tag_skeleton(text: str, grammar: TagGrammar) -> Tuple[str, ...]:
    """Return protected tags and placeholders in their source order."""
    grammar = _require_grammar(grammar)
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return tuple(match.group(0) for match in grammar.matcher.finditer(text))


def strip_tags(text: str, grammar: TagGrammar) -> str:
    """Remove protected control syntax to produce the measurable surface.

    Layout syntax is substituted for the literal it stands for before markup
    is removed, so a hard line break survives as a break.  Stripping it would
    weld the neighbouring display lines into one token.
    """
    grammar = _require_grammar(grammar)
    if not isinstance(text, str):
        raise TypeError("text must be a string")
    return grammar.matcher.sub("", grammar.apply_layout(text))
