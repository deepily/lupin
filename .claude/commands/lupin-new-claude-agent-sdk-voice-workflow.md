# New Claude Agent SDK Voice Workflow

**Project Prefix**: [LUPIN]
**Version**: 1.0
**Type**: Reference Wrapper

---

## Purpose

Interactive workflow for creating new agentic background jobs with voice I/O and queue integration. Guides you through the complete agent development process from discovery to queue registration.

---

## Instructions

1. Read the canonical workflow document:
   **lupin → src/workflow/agentic-voice-workflow.md**

2. Execute the workflow phases in order:
   - **Phase 0**: Answer discovery questions to establish agent characteristics
   - **Phase 1-2**: Create skeletal agent foundation (config, state, orchestrator, CLI)
   - **Phase 3-4**: Add notification integration (cosa_interface, voice_io)
   - **Phase 5**: Create AgenticJob queue wrapper
   - **Phase 5b**: Dedicated FastAPI router + Q&A script for automated testing
   - **Phase 5c** *(v0.1.6)*: Playwright UI E2E tests

3. Use TodoWrite with `[LUPIN]` prefix to track progress through phases

4. Run inline `quick_smoke_test()` after each BUILD phase before proceeding to the next

5. After Phase 5, create an automated live pipeline test:
   - Use `LivePipelineTestBase` for non-interactive agents (submit-and-poll validation)
   - Use `InteractiveSmokeTest` for interactive agents (proxy-driven Q&A automation)
   - See template in `src/tests/smoke/test_calculator_live_pipeline.py`
   - **PREFER automated pipeline tests over manual curl/UI submission**

---

## Quick Start

When invoked, begin with:

> I'll help you create a new agentic service. Let me first read the canonical workflow document, then we'll work through the interactive discovery questions to establish your agent's characteristics.

Then read `src/workflow/agentic-voice-workflow.md` and begin Phase 0 discovery.

---

## Reference Examples

For working implementations, see:
- `src/cosa/agents/deep_research/` - Primary reference (most complete)
- `src/cosa/agents/podcast_generator/` - File input and audio generation
- `src/cosa/agents/deep_research_to_podcast/` - Chained workflow pattern

---

## Testing References

For automated live pipeline and interactive proxy testing:

- `src/tests/smoke/test_calculator_live_pipeline.py` — Non-interactive template (6 scenarios, `LivePipelineTestBase`)
- `src/tests/smoke/test_proxy_integration.py` — Interactive template (12 scenarios, proxy-driven)
- `src/tests/smoke/utilities/live_pipeline_base.py` — Base class for submit-and-poll tests
- `src/tests/smoke/utilities/interactive_smoke_test.py` — Base class for proxy-driven tests
- `src/conf/notification-proxy-scripts/_template.json` — Q&A script template
- `src/docs/automated-interactive-testing.md` — Comprehensive guide
- *(Planned v0.1.6)* Playwright E2E tests — browser-level submit, job card, and notification validation

---

## Notes

- This is a **guidance-only** workflow (no auto-scaffolding)
- Each phase has its own TodoWrite template in the canonical document
- All templates use placeholders like `{AgentName}`, `{agent_name}`, `{prefix}`
- Replace placeholders with actual values during implementation
