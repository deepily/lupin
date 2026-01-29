# Agentic Voice Workflow - Full Reference

This is a reference pointer to the complete workflow documentation.

**Full Documentation**: `src/workflow/agentic-voice-workflow.md`

## Document Contents

The full workflow document (~30KB) contains:

### Phase 0: Interactive Discovery
- Complete questionnaire template
- State machine design guidance
- Input/output type selection

### Phase 1-2: Skeletal Foundation
- Directory structure template
- Base class implementation
- Configuration patterns

### Phase 3: Voice Notifications
- cosa-voice MCP integration
- Notification patterns for each state
- Human-in-the-loop checkpoints

### Phase 4: Queue Integration
- RunningFifoQueue hooks
- Job ID generation
- Status update WebSocket events
- Progress tracking

### Phase 5: Testing
- Unit test templates
- Integration test patterns
- End-to-end validation

## Reference Agents

Study these existing implementations:

### deep_research
- Location: `src/cosa/agents/deep_research/`
- Pattern: Web research → LLM synthesis → markdown report
- HITL: Plan approval before research

### podcast_generator
- Location: `src/cosa/agents/podcast_generator/`
- Pattern: Content → script → TTS → audio file
- HITL: Script review before generation

### deep_research_to_podcast
- Location: `src/cosa/agents/deep_research_to_podcast/`
- Pattern: Chained workflow (research → podcast)
- HITL: Multiple checkpoints

## Quick Access

To start the workflow interactively:
```
/lupin-new-claude-agent-sdk-voice-workflow
```

To read the full document:
```
Read src/workflow/agentic-voice-workflow.md
```
