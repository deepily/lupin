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
   - **Phase 5+**: Create AgenticJob queue wrapper

3. Use TodoWrite with `[LUPIN]` prefix to track progress through phases

4. Run smoke tests after each phase before proceeding to the next

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

## Notes

- This is a **guidance-only** workflow (no auto-scaffolding)
- Each phase has its own TodoWrite template in the canonical document
- All templates use placeholders like `{AgentName}`, `{agent_name}`, `{prefix}`
- Replace placeholders with actual values during implementation
