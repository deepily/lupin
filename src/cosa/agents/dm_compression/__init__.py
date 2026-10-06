"""
DM compression, arm 4 of the DM verbosity experiment.

The freeze protocol is a deterministic, zero-API-spend kernel that makes a lossy rewrite safe
for the literals it carries.

    extract -> placehold -> (rewrite, elsewhere) -> validate -> restore

The freeze module calls no model. The rewriter lives in `compressor.py`, so a corrupted
line number cannot reach a recipient.

Scope: this package guarantees exact preservation of selected byte spans through a lossy
rewrite. It does not guarantee that the surrounding claim kept its meaning.
Semantic preservation is a separate layer and a separate measurement.

Canonical docs:
    src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.06-arm-4-silent-compression-plan.md
    src/rnd/v0.2.0/2026.08.04-dm-verbosity-reduction/2026.08.06-arm-4-silent-compression-plan-expert-review.md
"""

from cosa.agents.dm_compression.freeze import (
    Span,
    Placeholder,
    FrozenMessage,
    ValidationResult,
    extract_spans,
    resolve_spans,
    segment_clauses,
    freeze,
    validate,
    restore,
    HARD_KINDS,
    SOFT_KINDS,
)

__all__ = [
    "Span",
    "Placeholder",
    "FrozenMessage",
    "ValidationResult",
    "extract_spans",
    "resolve_spans",
    "segment_clauses",
    "freeze",
    "validate",
    "restore",
    "HARD_KINDS",
    "SOFT_KINDS",
]
