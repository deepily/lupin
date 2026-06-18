#!/usr/bin/env python3
"""
Presentation Generator Agent — Transform research documents into slide decks.

Agentic process (Claude SDK) that transforms ~1200-word research documents
or technical blog posts into 10-20 minute slide decks with presenter notes.
Single orchestrator pattern following Podcast Generator architecture.

Bounded-CC migration (Phase 2 — 2026-06-18, D9 banner)
------------------------------------------------------
The content phase (`PresentationAPIClient`'s seven LLM methods) was migrated
from the direct firewalled Anthropic SDK (`AsyncAnthropic.messages.create`) to
the in-process Claude Agent SDK (`claude_agent_sdk.query`), matching the shipped
BFE/TFE/Podcast bounded-CC pattern (ratified D-DR1 Option X). This is a
COST-SHIFT to the already-paid Max plan, NOT "free": the SDK reports
`total_cost_usd` telemetry, but the firewalled Anthropic console balance does
not move. D6=STRICT parsers (fail-loud on unrecoverable/empty structured
content). The Gemini image/video path (`gemini_client.py`, NanoBanana/Veo) is
NON-Anthropic and UNTOUCHED; the pptx/Marp assembly + diagram rendering phases
are unchanged. The firewalled-key prose elsewhere in this package is HISTORICAL
for the content phase.
  - Scope:        src/rnd/v0.1.8/2026.06.18-presentation-phase2-bounded-cc-scope.md
  - Ratification: src/rnd/v0.1.8/2026.06.18-bounded-cc-d1d9-ratification-package.md
  - Cost model:   src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md
"""

__version__ = "0.2.0"   # 0.2.0: bounded-CC content-phase migration (in-process sdk_query)
