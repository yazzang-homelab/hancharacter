"""hancharacter — voice-preserving localisation with mechanical gates.

The premise: translation flattens a character's voice, and the flattening is
individually invisible and collectively fatal. A 무사 말투 becomes 평어체, a
`~냥` gets bolted onto every line of a character who only used it sometimes, and
nobody can tell which happened because nobody measured the original.

This package measures the original, seals the measurement into a per-character
contract, and refuses to ship when the target text drifts out of the measured
band in *either* direction.

Two rules the whole design hangs from:

1. Every verdict is re-derived from artifacts. A model may propose markers,
   speakers, or translations; none of those authorise a gate.
2. Both directions are defects. Losing a marker the source used is a defect, and
   adding one the source never used is also a defect.

`hancharacter` never imports a host localisation pipeline. Composition with one
is a separately approved milestone; v1 is standalone.
"""

__version__ = "0.1.0"
