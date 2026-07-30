# `CharacterHook` protocol

`hancharacter.hook.CharacterHook` documents the boundary a host integration
may implement:

- `voice_scope(item)` returns a character scope or `None`.
- `prompt_block(ctx)` returns optional scoped prompt context.
- `system_rules()` returns host-independent rules.
- `validate_line(ctx)` returns line findings.
- `validate_corpus(rows)` returns a serialisable corpus report.
- `seal()` returns a serialisable contract seal.

This is documentation-grade only in v1. Wiring the protocol into any host
pipeline is a separately approved milestone and is out of scope here. The
package does not import or depend on a host package.
