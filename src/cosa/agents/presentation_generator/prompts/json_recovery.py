#!/usr/bin/env python3
"""
JSON recovery for the Presentation Generator (bounded-CC strict policy).

The content phase runs through the in-process Claude Agent SDK (`sdk_query`).
Its completions can be chattier than the old `messages.create` path: leading
prose, trailing remarks, stray fences. `recover_json_object` recovers the JSON
object best-effort. The call sites enforce the strict policy and fail loudly on
unrecoverable, missing or empty content. The structured output feeds pptx
rendering downstream, so an empty deck is a real defect.

The implementation lives in the shared helper
`cosa.agents.io_models.utils.json_object_recovery`, which the podcast generator
imports too. This module re-exports the shared names so the four Presentation
callers (api_client.py + prompts/{narrative,outline,elaboration}.py) are unchanged.

The shared helper prefers a fenced block (it drops trailing prose after the
closing code fence). It also logs loudly on failure: the full raw body at `ERROR`
on an unrecoverable response. That logging never raises and never substitutes a
default, so the caller-owns-raise policy of Presentation is preserved.
"""

from cosa.agents.io_models.utils.json_object_recovery import (
    extract_json_object,
    recover_json_object,
)

__all__ = [ "extract_json_object", "recover_json_object" ]
