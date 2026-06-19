"""
Graph nodes for COSA Deep Research Agent.

Phase 2 will add:
- clarify.py: Query clarification node
  - Invokes clarification prompt with LLM
  - Returns ClarificationDecision model
  - Handles multi-round clarification

- feedback.py: Human feedback node
  - Wraps cosa_interface calls
  - Handles timeout and default responses
  - Extracts structured intent from voice

- plan.py: Research planning node
  - Generates ResearchPlan with subqueries
  - Determines complexity level
  - Handles plan revision based on feedback

- research.py: Parallel research subagent node
  - Spawns async tasks for each subquery
  - Manages concurrent execution
  - Handles partial failures gracefully

- compress.py: Context compression node
  - Reduces token usage in subagent findings
  - Preserves essential information
  - Adds quality metadata

- synthesize.py: Report synthesis node
  - Combines compressed findings
  - Generates coherent narrative
  - Identifies gaps and limitations

- cite.py: Citation generation node
  - Maps claims to sources
  - Formats citations per configured style
  - Adds confidence scores
"""

__all__ = []
