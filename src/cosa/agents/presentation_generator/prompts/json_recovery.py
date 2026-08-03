#!/usr/bin/env python3
"""
JSON recovery for the Presentation Generator (bounded-CC D6-STRICT).

The content phase was migrated to in-process Claude Agent SDK (`sdk_query`),
whose completions can be chattier than the old `messages.create` path (leading
prose, trailing remarks, stray fences). `recover_json_object` recovers the JSON
object best-effort; the CALL SITES enforce the D6-STRICT policy (fail-loud on
unrecoverable / missing / empty content — Presentation's structured output is
consumed downstream by pptx rendering, so an empty deck is a real defect).

De-dup (52cde456 / P0 4317efd1): the implementation now lives in the shared
helper `cosa.agents.io_models.utils.json_object_recovery`, which the podcast
generator imports too (its copy was byte-identical). This module re-exports the
shared names so the four Presentation callers
(api_client.py + prompts/{narrative,outline,elaboration}.py) are unchanged.

The shared helper carries the fence-preference fix (drop trailing prose after
the closing code fence) AND loud-None logging (it logs the full raw body at
ERROR on an unrecoverable response). That logging is CONTRACT-NEUTRAL: it never
raises and never substitutes a default, so Presentation's caller-owns-raise
policy is preserved exactly.
"""

from cosa.agents.io_models.utils.json_object_recovery import (
    extract_json_object,
    recover_json_object,
)

__all__ = [ "extract_json_object", "recover_json_object" ]
