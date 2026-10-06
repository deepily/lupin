#!/usr/bin/env python3
"""
Presentation Generator Agent — Transform research documents into slide decks.

Agentic process (Claude SDK) that transforms ~1200-word research documents
or technical blog posts into 10-20 minute slide decks with presenter notes.
Single orchestrator pattern following Podcast Generator architecture.

Content generation runs on bounded Claude Code
----------------------------------------------
The seven LLM methods of `PresentationAPIClient` call the in-process Claude Agent
SDK (`claude_agent_sdk.query`). The BFE, TFE and Podcast agents do the same.
They no longer use the firewalled Anthropic SDK (`AsyncAnthropic.messages.create`).
This shifts cost to the already-paid Max plan; it is not free. The SDK reports
`total_cost_usd` telemetry, but the firewalled Anthropic console balance does
not move. The parsers are strict: they fail loudly on unrecoverable or empty
structured content.

The Gemini image and video path (`gemini_client.py`) uses a non-Anthropic model
and is unchanged, as is the pptx and Marp assembly. The Mermaid, matplotlib and
d2 renderers do get their diagram code from `api_client.call_for_mermaid`,
`call_for_matplotlib` and `call_for_d2`, so those calls go through `sdk_query`.
Only what happens to the returned code (extraction, the d2 CLI, the sandboxed
matplotlib run) calls no LLM. Firewalled-key prose elsewhere in this package
describes the older content phase.
  - Cost model:   src/docs/cost-model-bounded-cc-vs-firewalled-sdk.md
"""

__version__ = "0.2.0"   # 0.2.0: bounded-CC content-phase migration (in-process sdk_query)
