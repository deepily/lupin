"""
DM compression — arm 4 of the DM verbosity experiment.

Phase 1 is the *freeze protocol*: the deterministic, zero-API-spend kernel that
makes a lossy rewrite safe for the literals it carries.

    extract -> placehold -> (rewrite, elsewhere) -> validate -> restore

Nothing in this package calls a model. The rewriter lands in phase 2; this
package exists so that when it does, a corrupted line number cannot reach a
recipient.

Scope note, per the expert review (2026-08-06): this package guarantees
"exact preservation of selected byte spans through a lossy rewrite." It does
NOT guarantee that the surrounding claim kept its meaning. Semantic
preservation is a separate layer and a separate measurement.

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
