"""Documentation-grade host integration protocol.

This protocol describes the boundary a host may implement.  Wiring it into a
host pipeline is a separately approved milestone and is out of scope for v1.
"""
from typing import Any, Dict, List, Optional, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from hancharacter.findings import Finding


class CharacterHook(Protocol):
    """Optional boundary for a future host integration."""

    def voice_scope(self, item: Any) -> Optional[str]:
        """Return the character scope for an item, or ``None`` when unscoped."""

    def prompt_block(self, ctx: Any) -> Optional[str]:
        """Return optional prompt context for a scoped operation."""

    def system_rules(self) -> List[str]:
        """Return host-independent rules to expose to a caller."""

    def validate_line(self, ctx: Any) -> List["Finding"]:
        """Return findings for one line-level context."""

    def validate_corpus(self, rows: Any) -> Dict[str, Any]:
        """Return a serialisable corpus-level validation report."""

    def seal(self) -> Dict[str, Any]:
        """Return the serialisable contract seal for the hook's scope."""
