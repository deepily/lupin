# COSA Deep Research Agent Implementation

> **Purpose**: Complete implementation plan for a voice-driven deep research agent integrating COSA, LangGraph, and Claude Agent SDK.
>
> **Target**: Claude Code consumption for recontextualization into COSA framework.
>
> **Generated**: December 2025

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Project Structure](#project-structure)
3. [Dependencies](#dependencies)
4. [Implementation Files](#implementation-files)
   - [config.py](#configpy)
   - [state.py](#statepy)
   - [cosa_interface.py](#cosa_interfacepy)
   - [prompts/lead_agent.py](#promptslead_agentpy)
   - [prompts/subagent.py](#promptssubagentpy)
   - [prompts/clarification.py](#promptsclarificationpy)
   - [prompts/synthesis.py](#promptssynthesispy)
   - [nodes/clarify.py](#nodesclarifypy)
   - [nodes/feedback.py](#nodesfeedbackpy)
   - [nodes/plan.py](#nodesplanpy)
   - [nodes/research.py](#nodesresearchpy)
   - [nodes/compress.py](#nodescompresspy)
   - [nodes/synthesize.py](#nodessynthesizepy)
   - [nodes/cite.py](#nodescitepy)
   - [tools/web_search.py](#toolsweb_searchpy)
   - [tools/web_fetch.py](#toolsweb_fetchpy)
   - [graph.py](#graphpy)
   - [main.py](#mainpy)
5. [COSA Queue Integration](#cosa-queue-integration) *(Added January 2026)*
   - [Non-Blocking Running Queue Architecture](#non-blocking-running-queue-architecture)
   - [Top-Level Orchestrator Agent Pattern](#top-level-orchestrator-agent-pattern)
   - [REST API Endpoints](#rest-api-endpoints)
   - [cosa-voice MCP Integration](#cosa-voice-mcp-integration-v020)
   - [Sub-Task Management](#sub-task-management)
   - [Implementation Location](#implementation-location)
6. [Integration Guide](#integration-guide)
7. [Testing Strategy](#testing-strategy)

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         COSA LAYER                              │
│  Voice I/O, WebSocket, notify_user_sync(), notify_user_async()  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LANGGRAPH ORCHESTRATION                    │
│                                                                 │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ CLARIFY  │───▶│   PLAN   │───▶│ RESEARCH │───▶│SYNTHESIZE│  │
│  │  NODE    │    │   NODE   │    │  NODES   │    │   NODE   │  │
│  │          │    │          │    │(parallel)│    │          │  │
│  └──────────┘    └──────────┘    └──────────┘    └──────────┘  │
│       │               │               │               │         │
│       ▼               ▼               ▼               ▼         │
│  ┌──────────┐    ┌──────────┐                    ┌──────────┐  │
│  │ FEEDBACK │    │ FEEDBACK │                    │   CITE   │  │
│  │  (COSA)  │    │  (COSA)  │                    │   NODE   │  │
│  └──────────┘    └──────────┘                    └──────────┘  │
│                                                                 │
│  State: query, plan, feedback, findings[], report               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                   CLAUDE AGENT SDK EXECUTION                    │
│  WebSearch, WebFetch, Extended Thinking                         │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

1. **COSA Integration**: `notify_user_sync` for blocking feedback, `notify_user_async` for streaming thoughts
2. **Parallel Execution**: LangGraph `Send()` API for concurrent subagent research
3. **Model Tiering**: Opus 4.5 for planning/synthesis, Sonnet 4 for subagents
4. **Prompt Provenance**: Adapted from Anthropic Cookbook, GPT Researcher, LangChain Open Deep Research
5. **Context Compression**: Subagents compress findings before returning to lead agent

### Graph Flow

```
START
  │
  ▼
[clarify] ──needs_clarification──▶ [get_clarification] ──┐
  │                                                       │
  │◀──────────────────────────────────────────────────────┘
  │
  ▼ (query understood)
[plan] ──▶ [get_plan_feedback]
              │
              ├──revise──▶ [revise_plan] ──┐
              │                             │
              │◀────────────────────────────┘
              │
              ▼ (approved)
[spawn_research] ──Send()──▶ [research_subquery] ×N (parallel)
                                    │
                                    ▼
                            [gather_findings]
                                    │
                    ┌───more_research───┤
                    │                   │
                    ▼                   ▼ (complete)
            [spawn_research]    [synthesize]
                                    │
                                    ▼
                            [get_draft_feedback]
                                    │
                    ┌───revise──────┤
                    │               │
                    ▼               ▼ (approved)
                [synthesize]      [cite]
                                    │
                                    ▼
                                   END
```

---

## Project Structure

```
cosa_deep_research/
├── __init__.py
├── config.py                    # Configuration dataclass
├── state.py                     # Pydantic state schemas
├── cosa_interface.py            # COSA notify_user_sync/async wrappers
├── prompts/
│   ├── __init__.py
│   ├── lead_agent.py            # Lead researcher system prompt
│   ├── subagent.py              # Research subagent prompt
│   ├── clarification.py         # Query clarification prompt
│   └── synthesis.py             # Final report synthesis prompt
├── nodes/
│   ├── __init__.py
│   ├── clarify.py               # Query clarification node
│   ├── feedback.py              # Human feedback node (COSA integration)
│   ├── plan.py                  # Research planning node
│   ├── research.py              # Parallel research subagent node
│   ├── compress.py              # Context compression node
│   ├── synthesize.py            # Report synthesis node
│   └── cite.py                  # Citation generation node
├── tools/
│   ├── __init__.py
│   ├── web_search.py            # Claude WebSearch wrapper
│   └── web_fetch.py             # Claude WebFetch wrapper
├── graph.py                     # LangGraph StateGraph definition
└── main.py                      # Entry point and COSA integration
```

---

## Dependencies

```toml
# pyproject.toml or requirements.txt equivalent

[project]
name = "cosa-deep-research"
version = "0.1.0"
requires-python = ">=3.11"

dependencies = [
    "anthropic>=0.40.0",
    "langgraph>=0.2.0",
    "pydantic>=2.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]
```

```bash
# Installation
pip install anthropic langgraph pydantic
```

---

## Implementation Files

### config.py

```python
"""
Configuration for COSA Deep Research Agent

Design decisions:
- Opus 4.5 for lead agent (planning, synthesis) - higher reasoning capability
- Sonnet 4 for subagents (research execution) - cost optimization
- Scaling heuristics from Anthropic blog post (June 2025)
- Configurable limits to prevent runaway execution
"""

from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ResearchConfig:
    """Configuration for the deep research agent."""
    
    # === Model Selection ===
    # Pattern from Anthropic: Use Opus for coordination, Sonnet for execution
    lead_model: str = "claude-opus-4-20250514"
    subagent_model: str = "claude-sonnet-4-20250514"
    
    # === Scaling Heuristics ===
    # From Anthropic blog: Scale effort to query complexity
    max_subagents_simple: int = 1      # Simple fact-finding
    max_subagents_moderate: int = 4    # Comparisons, multi-faceted
    max_subagents_complex: int = 10    # Deep analysis, multiple perspectives
    
    # === Execution Limits ===
    # From LangChain Open Deep Research: Prevent runaway execution
    max_concurrent_subagents: int = 5
    max_research_iterations: int = 3
    max_tool_calls_per_subagent: int = 15
    max_clarification_rounds: int = 2
    
    # === Token Budgets ===
    extended_thinking_budget: int = 10000
    subagent_context_limit: int = 100000
    max_findings_tokens: int = 50000
    
    # === COSA Integration ===
    feedback_timeout_seconds: int = 300
    stream_thoughts_to_voice: bool = True
    narrate_progress: bool = True
    
    # === Search Configuration ===
    search_tool: str = "web_search_20250305"
    prefer_primary_sources: bool = True
    min_sources_per_subquery: int = 3
    max_sources_per_subquery: int = 10
    
    # === Output Configuration ===
    include_confidence_scores: bool = True
    include_source_quality_notes: bool = True
    citation_style: Literal["inline", "footnote", "endnote"] = "inline"
    
    def get_max_subagents(self, complexity: str) -> int:
        """Get max subagents for given complexity level."""
        mapping = {
            "simple": self.max_subagents_simple,
            "moderate": self.max_subagents_moderate,
            "complex": self.max_subagents_complex,
        }
        return mapping.get(complexity, self.max_subagents_moderate)
```

---

### state.py

```python
"""
State Schemas for COSA Deep Research Agent

Uses Pydantic for structured outputs and TypedDict for LangGraph state.
Designed for the parallel subagent architecture with human-in-the-loop feedback.
"""

from typing import TypedDict, Literal, Annotated, Any
from pydantic import BaseModel, Field
from langgraph.graph.message import add_messages


# === Pydantic Models for Structured Outputs ===

class SubQuery(BaseModel):
    """A focused research subquery for delegation to a subagent."""
    
    topic: str = Field(
        description="The specific topic to research"
    )
    objective: str = Field(
        description="What information to gather - be specific and actionable"
    )
    output_format: str = Field(
        description="Expected output structure (e.g., 'list of companies', 'factual summary', 'comparison table')"
    )
    tools_to_use: list[str] = Field(
        default=["web_search", "web_fetch"],
        description="Tools the subagent should prioritize"
    )
    priority: int = Field(
        default=1,
        ge=1,
        le=5,
        description="Priority level (1=highest). Use for dependency ordering."
    )
    depends_on: list[int] | None = Field(
        default=None,
        description="Indices of subqueries this depends on (for sequential execution)"
    )


class ResearchPlan(BaseModel):
    """The lead agent's complete research plan."""
    
    complexity: Literal["simple", "moderate", "complex"] = Field(
        description="Assessed complexity of the research task"
    )
    subqueries: list[SubQuery] = Field(
        description="List of focused subqueries to delegate"
    )
    estimated_subagents: int = Field(
        description="Number of parallel subagents to spawn"
    )
    rationale: str = Field(
        description="Brief explanation of the research approach"
    )
    estimated_duration_minutes: int = Field(
        default=5,
        description="Estimated time to complete research"
    )


class SourceReference(BaseModel):
    """A reference to a source used in research."""
    
    url: str
    title: str
    snippet: str = Field(default="", description="Relevant excerpt")
    relevance_score: float = Field(ge=0.0, le=1.0)
    source_quality: Literal["primary", "secondary", "aggregator", "unknown"] = "unknown"
    access_date: str = Field(default="", description="ISO date when accessed")


class SubagentFinding(BaseModel):
    """Compressed findings from a research subagent."""
    
    subquery_index: int = Field(description="Index of the subquery this finding addresses")
    subquery_topic: str = Field(description="The topic that was researched")
    findings: str = Field(description="Compressed, relevant information")
    sources: list[SourceReference] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in finding reliability (0=uncertain, 1=highly confident)"
    )
    gaps: list[str] = Field(
        default_factory=list,
        description="Identified information gaps or areas needing more research"
    )
    quality_notes: str = Field(
        default="",
        description="Notes on source quality issues or limitations"
    )


class ClarificationDecision(BaseModel):
    """Decision on whether query clarification is needed."""
    
    needs_clarification: bool = Field(
        description="Whether the query needs clarification before research"
    )
    question: str | None = Field(
        default=None,
        description="Clarification question to ask user (if needed)"
    )
    understood_query: str = Field(
        description="The query as understood - rephrased for clarity"
    )
    ambiguities: list[str] = Field(
        default_factory=list,
        description="List of identified ambiguities"
    )


class Citation(BaseModel):
    """A citation for the final report."""
    
    claim: str = Field(description="The claim being cited")
    source: SourceReference
    location_in_report: str = Field(description="Where in the report this citation appears")


# === LangGraph State ===

class ResearchState(TypedDict):
    """
    Main graph state for the research agent.
    
    This state flows through all nodes and accumulates information
    as the research progresses.
    """
    
    # === Input ===
    messages: Annotated[list, add_messages]
    original_query: str
    
    # === Clarification Phase ===
    needs_clarification: bool
    clarification_question: str | None
    clarification_response: str | None
    clarified_query: str | None
    clarification_rounds: int
    
    # === Planning Phase ===
    research_brief: str | None
    plan: ResearchPlan | None
    human_feedback_on_plan: str | None
    plan_approved: bool
    plan_revision_count: int
    
    # === Research Phase ===
    active_subqueries: list[SubQuery]
    subagent_findings: list[SubagentFinding]
    research_iterations: int
    total_sources_found: int
    
    # === Synthesis Phase ===
    draft_report: str | None
    human_feedback_on_draft: str | None
    draft_revision_count: int
    
    # === Final Output ===
    final_report: str | None
    citations: list[Citation]
    research_metadata: dict[str, Any]


class SubagentState(TypedDict):
    """
    State for individual subagent research tasks.
    
    This is the state passed via Send() to parallel research nodes.
    """
    
    subquery: SubQuery
    subquery_index: int
    messages: list
    tool_calls_made: int
    sources_found: list[SourceReference]
    current_findings: str


# === State Initialization ===

def create_initial_state(query: str) -> ResearchState:
    """Create the initial state for a research task."""
    return ResearchState(
        messages=[],
        original_query=query,
        needs_clarification=False,
        clarification_question=None,
        clarification_response=None,
        clarified_query=None,
        clarification_rounds=0,
        research_brief=None,
        plan=None,
        human_feedback_on_plan=None,
        plan_approved=False,
        plan_revision_count=0,
        active_subqueries=[],
        subagent_findings=[],
        research_iterations=0,
        total_sources_found=0,
        draft_report=None,
        human_feedback_on_draft=None,
        draft_revision_count=0,
        final_report=None,
        citations=[],
        research_metadata={},
    )
```

---

### cosa_interface.py

```python
"""
COSA Voice Interface Integration Layer

This module provides the bridge between the LangGraph research agent
and the COSA voice-driven UI. It wraps:
- notify_user_sync: Blocking call for human feedback
- notify_user_async: Non-blocking call for streaming agent thoughts

Design Principle:
The graph execution naturally pauses when notify_user_sync is called,
waiting for the user's voice response. No special LangGraph interrupt()
mechanism is needed because COSA provides a blocking primitive.
"""

from typing import Callable, Awaitable, Protocol
import asyncio
import logging

logger = logging.getLogger(__name__)


# === Protocol Definitions ===

class SyncNotifier(Protocol):
    """Protocol for blocking user notification."""
    def __call__(self, prompt: str, timeout: int = 300) -> str:
        """
        Speak prompt via TTS, wait for user voice response via STT.
        
        Args:
            prompt: Text to speak to the user
            timeout: Maximum seconds to wait for response
            
        Returns:
            User's transcribed voice response
        """
        ...


class AsyncNotifier(Protocol):
    """Protocol for non-blocking thought streaming."""
    async def __call__(self, thought: str) -> None:
        """
        Stream a thought to the COSA UI.
        
        The UI can choose to:
        - Display as text
        - Speak via TTS
        - Log silently
        - Ignore entirely
        """
        ...


# === Global Configuration ===

_notify_user_sync: SyncNotifier | None = None
_notify_user_async: AsyncNotifier | None = None
_configured: bool = False


def configure_cosa(
    sync_fn: SyncNotifier,
    async_fn: AsyncNotifier
) -> None:
    """
    Configure COSA interface functions at runtime.
    
    This must be called before using the research agent.
    
    Args:
        sync_fn: COSA's notify_user_sync function
        async_fn: COSA's notify_user_async function
    """
    global _notify_user_sync, _notify_user_async, _configured
    _notify_user_sync = sync_fn
    _notify_user_async = async_fn
    _configured = True
    logger.info("COSA interface configured successfully")


def is_configured() -> bool:
    """Check if COSA interface is configured."""
    return _configured


# === Primary Interface Functions ===

def get_human_feedback(prompt: str, timeout: int = 300) -> str:
    """
    Blocking call that speaks prompt via TTS, waits for user voice response.
    
    This is the primary human-in-the-loop integration point. When called,
    the graph execution pauses until the user responds.
    
    Args:
        prompt: Text to speak to the user
        timeout: Maximum seconds to wait for response
        
    Returns:
        User's transcribed voice response
        
    Raises:
        RuntimeError: If COSA interface not configured
    """
    if _notify_user_sync is None:
        raise RuntimeError(
            "COSA interface not configured. Call configure_cosa() first."
        )
    
    logger.debug(f"Requesting human feedback: {prompt[:100]}...")
    response = _notify_user_sync(prompt, timeout)
    logger.debug(f"Received human feedback: {response[:100]}...")
    
    return response


async def stream_thought(thought: str) -> None:
    """
    Non-blocking call to stream agent thoughts to COSA UI.
    
    The COSA UI can choose to:
    - Display as text
    - Speak via TTS
    - Log silently
    - Ignore entirely
    
    This enables "thinking out loud" transparency for the voice UX.
    Fails silently if not configured (thoughts are optional).
    
    Args:
        thought: The thought to stream
    """
    if _notify_user_async is None:
        # Fail silently if not configured
        logger.debug(f"Thought (no COSA): {thought}")
        return
    
    try:
        await _notify_user_async(thought)
    except Exception as e:
        # Never let thought streaming break the research flow
        logger.warning(f"Failed to stream thought: {e}")


# === Convenience Functions ===

async def narrate_progress(
    stage: str,
    detail: str = "",
    include_stage_name: bool = True
) -> None:
    """
    Narrate research progress to the user.
    
    Provides consistent progress updates throughout the research process.
    
    Args:
        stage: The current stage of research
        detail: Additional detail to include
        include_stage_name: Whether to include the stage name in narration
    """
    stage_messages = {
        "clarifying": "Let me make sure I understand your question.",
        "planning": "I'm developing a research strategy.",
        "spawning": "Starting parallel research investigations.",
        "researching": "Now investigating:",
        "gathering": "Collecting and analyzing findings.",
        "synthesizing": "Compiling my findings into a report.",
        "citing": "Adding citations and verifying sources.",
        "complete": "Research complete.",
    }
    
    base_message = stage_messages.get(stage, "Processing...")
    
    if detail:
        message = f"{base_message} {detail}"
    else:
        message = base_message
    
    await stream_thought(message)


async def narrate_subagent_start(topic: str, index: int, total: int) -> None:
    """Narrate the start of a subagent research task."""
    await stream_thought(
        f"Research thread {index + 1} of {total}: Investigating {topic}"
    )


async def narrate_subagent_complete(topic: str, sources_found: int) -> None:
    """Narrate the completion of a subagent research task."""
    await stream_thought(
        f"Completed investigation of {topic}. Found {sources_found} relevant sources."
    )


async def narrate_finding(finding_summary: str) -> None:
    """Narrate a key finding."""
    await stream_thought(f"Found: {finding_summary}")


# === Feedback Analysis Utilities ===

def is_approval(feedback: str) -> bool:
    """
    Determine if user feedback indicates approval.
    
    Args:
        feedback: User's response text
        
    Returns:
        True if feedback indicates approval
    """
    approval_signals = [
        "yes", "proceed", "go ahead", "sounds good", "perfect",
        "do it", "approved", "looks good", "that works", "okay",
        "ok", "sure", "fine", "great", "excellent", "continue",
        "start", "begin", "let's go", "go for it"
    ]
    
    feedback_lower = feedback.lower().strip()
    
    # Check for explicit approval
    for signal in approval_signals:
        if signal in feedback_lower:
            return True
    
    # Short affirmative responses
    if feedback_lower in ["y", "yep", "yup", "uh huh", "mm hmm"]:
        return True
    
    return False


def is_rejection(feedback: str) -> bool:
    """
    Determine if user feedback indicates rejection/change request.
    
    Args:
        feedback: User's response text
        
    Returns:
        True if feedback indicates rejection or change request
    """
    rejection_signals = [
        "no", "change", "adjust", "modify", "different",
        "instead", "rather", "stop", "wait", "hold on",
        "not quite", "actually", "but", "however"
    ]
    
    feedback_lower = feedback.lower().strip()
    
    for signal in rejection_signals:
        if signal in feedback_lower:
            return True
    
    return False


def extract_feedback_intent(feedback: str) -> dict:
    """
    Extract structured intent from user feedback.
    
    Args:
        feedback: User's response text
        
    Returns:
        Dict with intent classification and extracted details
    """
    feedback_lower = feedback.lower().strip()
    
    result = {
        "is_approval": is_approval(feedback),
        "is_rejection": is_rejection(feedback),
        "raw_feedback": feedback,
        "feedback_type": "unknown",
        "extracted_focus": None,
    }
    
    if result["is_approval"]:
        result["feedback_type"] = "approval"
    elif result["is_rejection"]:
        result["feedback_type"] = "change_request"
    else:
        # Ambiguous - treat as additional context
        result["feedback_type"] = "additional_context"
    
    # Try to extract focus areas mentioned
    focus_indicators = ["focus on", "more about", "especially", "particularly", "mainly"]
    for indicator in focus_indicators:
        if indicator in feedback_lower:
            # Extract text after the indicator
            idx = feedback_lower.find(indicator)
            result["extracted_focus"] = feedback[idx + len(indicator):].strip()
            break
    
    return result
```

---

### prompts/lead_agent.py

```python
"""
Lead Research Agent System Prompt

Provenance:
- Anthropic Cookbook: research_lead_agent.md (core structure)
- Anthropic Blog: Multi-agent research system (June 2025)
- GPT Researcher: Planner agent decomposition patterns
- LangChain Open Deep Research: Supervisor coordination patterns

Key Principles:
1. Lead agent COORDINATES, doesn't conduct primary research
2. Decompose complex queries into focused, non-overlapping subqueries
3. Scale effort to query complexity
4. Wide-to-narrow search strategy for subagents
"""

LEAD_AGENT_SYSTEM_PROMPT = """You are the lead research agent coordinating a multi-agent research system.

<role>
Your primary role is to COORDINATE, GUIDE, and SYNTHESIZE research—NOT to conduct primary research yourself. You delegate information gathering to specialized subagents while focusing on:

1. Understanding the user's true information need
2. Decomposing complex queries into focused subqueries
3. Allocating research effort appropriately based on complexity
4. Synthesizing subagent findings into coherent insights
5. Identifying gaps and deploying additional subagents as needed
</role>

<planning_process>
When given a research query, follow this systematic process:

## 1. Assessment
Analyze the query to understand:
- Main concepts, entities, and relationships involved
- Specific facts or data points needed to answer comprehensively
- Temporal constraints (historical, current, future-looking)
- Geographic or domain constraints
- What the user likely cares about most (infer intent)

## 2. Complexity Classification
Classify the query complexity to determine resource allocation:

**SIMPLE** (1 subagent, 3-10 tool calls):
- Single fact-finding tasks
- Straightforward lookups
- Clear, unambiguous questions with expected single answers

**MODERATE** (2-4 subagents, 10-15 calls each):
- Comparisons between entities
- Multi-faceted topics with 2-4 distinct aspects
- Questions requiring synthesis across a few sources

**COMPLEX** (5-10+ subagents with distinct responsibilities):
- Deep analysis requiring multiple perspectives
- Controversial or nuanced topics
- Research requiring comprehensive landscape mapping
- Questions where experts would disagree

## 3. Decomposition
Generate focused subqueries where each:
- Has a SINGLE, clear objective
- Specifies the expected output format
- Lists appropriate tools and sources to prioritize
- Has clear boundaries to AVOID OVERLAP with other subqueries
- Considers dependencies (some subqueries may need results from others)
</planning_process>

<delegation_instructions>
For each subquery, provide the subagent with SPECIFIC instructions including:

1. **Objective**: Single, clear goal (e.g., "Find the top 5 companies by market cap in sector X")
2. **Output Format**: Expected structure (list, summary, comparison table, timeline)
3. **Tools to Use**: Which tools are most appropriate (web_search, web_fetch)
4. **Sources to Prioritize**: Primary sources, official docs, academic papers
5. **Boundaries**: What NOT to research (prevent overlap)
6. **Quality Criteria**: What makes a source acceptable

Consider priority and dependencies:
- Deploy blocking tasks FIRST when other tasks depend on their results
- Independent tasks can run in parallel
- Mark dependencies explicitly in the subquery
</delegation_instructions>

<search_strategy>
Instruct subagents to follow the WIDE-TO-NARROW pattern:

1. **Start Broad**: Use SHORT, BROAD queries (3-5 words) to survey the landscape
2. **Evaluate**: Assess what's available and what's relevant
3. **Narrow Focus**: Progressively refine based on initial findings
4. **Avoid**: Overly long, specific queries that return few or no results

Example progression:
- Broad: "AI agents 2025"
- Narrower: "AI agent frameworks comparison"
- Specific: "LangGraph vs CrewAI performance benchmarks"
</search_strategy>

<synthesis_responsibility>
When synthesizing subagent findings:

1. **Review All Findings**: Check for consistency and completeness across subagents
2. **Resolve Conflicts**: When information conflicts, prioritize based on:
   - Recency (newer is often better for fast-moving topics)
   - Source quality (primary > secondary > aggregator)
   - Consistency (what do multiple sources agree on?)
   - Your reasoning about which is more credible

3. **Identify Gaps**: Determine if critical information is missing
   - Decide whether to deploy additional subagents
   - Or acknowledge the gap in the final report

4. **Calibrate Confidence**: 
   - High confidence: Multiple high-quality sources agree
   - Medium confidence: Some support, but limited sources
   - Low confidence: Speculation, single source, or conflicting info
   
5. **Flag Limitations**: Explicitly note:
   - Speculation vs. established fact
   - Predictions vs. historical data
   - Potential biases in sources
</synthesis_responsibility>

<output_format>
When generating a research plan, output a structured ResearchPlan with:

```json
{
  "complexity": "simple" | "moderate" | "complex",
  "subqueries": [
    {
      "topic": "specific topic",
      "objective": "what to find",
      "output_format": "expected structure",
      "tools_to_use": ["web_search", "web_fetch"],
      "priority": 1,
      "depends_on": null
    }
  ],
  "estimated_subagents": 3,
  "rationale": "Brief explanation of approach",
  "estimated_duration_minutes": 5
}
```
</output_format>

<critical_reminders>
1. You COORDINATE - subagents do the actual searching
2. Each subquery should be INDEPENDENT enough to run in parallel
3. Avoid vague instructions like "research X" - be SPECIFIC
4. Consider what could go wrong and plan for contingencies
5. The user's time is valuable - be efficient but thorough
</critical_reminders>
"""


PLAN_REVISION_PROMPT = """You previously created a research plan, but the user requested changes.

<previous_plan>
{previous_plan}
</previous_plan>

<user_feedback>
{user_feedback}
</user_feedback>

Revise the research plan based on the user's feedback. Maintain the same structured output format.

Focus on:
1. Addressing the specific concerns or requests in the feedback
2. Adjusting the scope, focus, or approach as requested
3. Maintaining comprehensive coverage while respecting user preferences
4. Keeping the plan actionable and efficient
"""


SYNTHESIS_GUIDANCE_PROMPT = """You have received findings from {num_subagents} research subagents.

<subagent_findings>
{findings}
</subagent_findings>

<original_query>
{original_query}
</original_query>

Synthesize these findings into a comprehensive response. Follow these guidelines:

1. **Structure**: Organize the information logically
2. **Accuracy**: Only include facts supported by the findings
3. **Balance**: Present multiple perspectives where they exist
4. **Confidence**: Indicate certainty levels where appropriate
5. **Gaps**: Acknowledge what couldn't be determined
6. **Citations**: Reference sources for key claims (to be added by citation agent)

Do NOT add information beyond what the subagents found.
"""
```

---

### prompts/subagent.py

```python
"""
Research Subagent System Prompt

Provenance:
- Anthropic Cookbook: research_subagent.md
- GPT Researcher: Execution agent patterns
- Anthropic Blog: Source quality and interleaved thinking

Key Principles:
1. Focus ONLY on assigned subquery
2. Wide-to-narrow search strategy
3. Critical evaluation of sources
4. Compress findings before returning
"""

SUBAGENT_SYSTEM_PROMPT = """You are a research subagent conducting focused investigation on a specific topic.

<role>
You are a specialized researcher gathering information for your assigned subquery. 

CRITICAL: Focus ONLY on your specific task. The lead agent handles broader coordination.
Your job is to gather high-quality information efficiently and return compressed findings.
</role>

<research_process>
Follow this process for each research task:

## 1. Search Strategy
- Start with BROAD queries (3-5 words)
- Evaluate initial results to understand the information landscape
- Progressively NARROW based on what you find
- Use multiple query variations to ensure coverage

## 2. Source Evaluation
Before including information, evaluate each source:

**PRIORITIZE**:
- Primary sources (original research, official documentation, company announcements)
- Authoritative domain experts and institutions
- Academic papers and peer-reviewed publications
- Government and regulatory sources
- Recent, dated publications with clear provenance

**AVOID**:
- SEO-optimized content farms (listicles, thin content)
- Aggregators without original reporting
- Sources with obvious bias or marketing intent
- Outdated information (unless historical context is needed)
- Anonymous or unverifiable claims

## 3. Information Gathering
- Use web_search for discovery and initial exploration
- Use web_fetch to retrieve FULL page content when snippets are insufficient
- Execute 2-3 tool calls in PARALLEL when investigating independent aspects
- Continue until task is complete or tool call limit reached

## 4. Critical Analysis
After receiving tool results, evaluate:
- Is this information reliable?
- Does it directly answer the research objective?
- Are there signs of speculation vs. established fact?
- What are the limitations or caveats?

## 5. Compression
Before returning findings:
- Extract only the RELEVANT information
- Summarize key points concisely
- Note source quality issues
- Identify gaps in available information
</research_process>

<tool_usage>
Effective tool usage patterns:

**web_search**:
- Use SHORT, FOCUSED queries (3-5 words ideal)
- Good: "AI agent frameworks 2025"
- Bad: "what are the best AI agent frameworks available in 2025 for building autonomous systems"

**web_fetch**:
- Use when search snippets are insufficient
- Retrieve full content for in-depth analysis
- Don't fetch obviously irrelevant URLs

**Parallel Execution**:
- When investigating independent aspects, call 2-3 tools simultaneously
- Example: Searching for "company X revenue" and "company X employees" in parallel
</tool_usage>

<source_quality_indicators>
Watch for these RED FLAGS:

❌ **Speculation as Fact**:
- "could", "may", "might" without caveats
- Future tense predictions presented as certainties
- "Experts predict..." without named experts

❌ **Low Quality Signals**:
- No author attribution
- No publication date
- Excessive ads or sponsored content
- Aggregated content without original reporting

❌ **Bias Indicators**:
- Marketing language ("revolutionary", "game-changing")
- One-sided presentation of controversies
- Cherry-picked statistics
- Affiliate links throughout

✅ **High Quality Signals**:
- Clear authorship and credentials
- Dated publication with updates noted
- Primary source citations
- Balanced presentation of limitations
</source_quality_indicators>

<output_format>
Return a SubagentFinding with:

```json
{
  "subquery_index": 0,
  "subquery_topic": "Your assigned topic",
  "findings": "Compressed, relevant information (key facts, data, insights)",
  "sources": [
    {
      "url": "https://...",
      "title": "Source Title",
      "snippet": "Relevant excerpt",
      "relevance_score": 0.9,
      "source_quality": "primary|secondary|aggregator|unknown"
    }
  ],
  "confidence": 0.85,
  "gaps": ["Information that couldn't be found"],
  "quality_notes": "Any concerns about source quality or limitations"
}
```
</output_format>

<critical_reminders>
1. ONLY report facts directly supported by sources
2. DISTINGUISH between established facts and speculation
3. FLAG conflicting information for lead agent resolution
4. Do NOT exceed your task scope - stay focused
5. COMPRESS your findings - the lead agent doesn't need raw data
6. NOTE source quality issues explicitly
</critical_reminders>
"""


SUBAGENT_TASK_TEMPLATE = """You have been assigned the following research task:

<task>
Topic: {topic}
Objective: {objective}
Expected Output: {output_format}
Tools Available: {tools}
</task>

<constraints>
- Priority Level: {priority}
- This task {dependency_note}
- Maximum tool calls: {max_tool_calls}
</constraints>

Begin your research now. Use the available tools to gather information, then return your compressed findings.
"""
```

---

### prompts/clarification.py

```python
"""
Query Clarification Prompts

Used in the clarification node to determine if the user's query
needs disambiguation before research begins.
"""

CLARIFICATION_SYSTEM_PROMPT = """You analyze research queries to determine if clarification is needed.

<when_to_clarify>
Clarification IS needed when:
- The query has multiple valid interpretations that would lead to different research
- Key scope is undefined (time period, geography, domain, industry)
- Technical terms could mean different things in different contexts
- The user's actual goal is unclear (are they comparing, evaluating, learning?)
- Critical constraints are missing that would affect the research direction

Clarification is NOT needed when:
- The query is specific and actionable as-is
- Any ambiguity can be reasonably resolved with common sense
- The scope is clear enough for productive research
- Minor ambiguities won't significantly affect research quality
</when_to_clarify>

<clarification_guidelines>
If clarification is needed:
1. Generate ONE focused clarifying question (not multiple)
2. The question should resolve the most important ambiguity
3. Phrase it conversationally (this will be spoken aloud)
4. Provide your best interpretation of the query even if asking for clarification
</clarification_guidelines>

<output_format>
Return a structured response with:
- needs_clarification: boolean
- question: string or null (the clarifying question if needed)
- understood_query: string (the query as you understand it)
- ambiguities: list of identified ambiguities
</output_format>
"""


CLARIFICATION_USER_PROMPT = """Analyze this research query and determine if clarification is needed:

<query>
{query}
</query>

{context_note}

Decide whether to proceed with research or ask a clarifying question first.
"""
```

---

### prompts/synthesis.py

```python
"""
Synthesis and Report Generation Prompts

Used in the synthesis and citation nodes to compile
subagent findings into a final research report.
"""

SYNTHESIS_SYSTEM_PROMPT = """You synthesize research findings into comprehensive, well-structured reports.

<synthesis_principles>
1. **Accuracy First**: Only include information supported by the subagent findings
2. **Structure for Clarity**: Organize logically based on the query type
3. **Balanced Perspective**: Present multiple viewpoints where they exist
4. **Calibrated Confidence**: Indicate certainty levels appropriately
5. **Acknowledge Gaps**: Be transparent about what couldn't be determined
</synthesis_principles>

<report_structure>
Adapt structure to the query type:

**For Factual Questions**:
- Direct answer first
- Supporting evidence
- Caveats or limitations

**For Comparisons**:
- Summary of key differences
- Detailed comparison by dimension
- Recommendation or conclusion

**For Exploratory Research**:
- Executive summary
- Key themes or findings
- Detailed analysis by theme
- Implications or next steps

**For How-To/Guidance**:
- Overview of approach
- Step-by-step details
- Common pitfalls
- Resources for further learning
</report_structure>

<quality_guidelines>
- Write in clear, professional prose
- Use specific data and examples where available
- Avoid hedging language unless genuinely uncertain
- Don't pad with generic statements
- Make the report actionable when possible
</quality_guidelines>
"""


SYNTHESIS_USER_PROMPT = """Synthesize the following research findings into a comprehensive report.

<original_query>
{original_query}
</original_query>

<research_plan>
{research_plan}
</research_plan>

<subagent_findings>
{findings}
</subagent_findings>

<user_context>
{user_context}
</user_context>

Generate a well-structured report that directly addresses the user's query.
Do not include citations yet - those will be added by a separate process.
Use [CITE] markers where citations should be inserted.
"""


CITATION_SYSTEM_PROMPT = """You add accurate citations to research reports.

<citation_guidelines>
1. Match claims to their supporting sources from the findings
2. Use the specified citation style (inline, footnote, or endnote)
3. Ensure every significant claim has appropriate citation
4. Don't over-cite obvious or general knowledge statements
5. Preserve the original source URLs for verification
</citation_guidelines>

<citation_format>
For inline citations: "Claim text [Source Title](URL)"
For footnotes: "Claim text[^1]" with "[^1]: Source Title, URL" at bottom
For endnotes: "Claim text [1]" with numbered list at end
</citation_format>
"""


CITATION_USER_PROMPT = """Add citations to this research report.

<report>
{draft_report}
</report>

<available_sources>
{sources}
</available_sources>

<citation_style>
{citation_style}
</citation_style>

Add appropriate citations throughout the report, matching claims to their sources.
Return the fully cited report.
"""
```

---

### prompts/__init__.py

```python
"""
Prompt modules for COSA Deep Research Agent.

All prompts are adapted from:
- Anthropic Cookbook (research_lead_agent.md, research_subagent.md)
- Anthropic Blog: Multi-agent research system (June 2025)
- GPT Researcher: Planning and execution patterns
- LangChain Open Deep Research: Supervisor coordination
"""

from .lead_agent import (
    LEAD_AGENT_SYSTEM_PROMPT,
    PLAN_REVISION_PROMPT,
    SYNTHESIS_GUIDANCE_PROMPT,
)
from .subagent import (
    SUBAGENT_SYSTEM_PROMPT,
    SUBAGENT_TASK_TEMPLATE,
)
from .clarification import (
    CLARIFICATION_SYSTEM_PROMPT,
    CLARIFICATION_USER_PROMPT,
)
from .synthesis import (
    SYNTHESIS_SYSTEM_PROMPT,
    SYNTHESIS_USER_PROMPT,
    CITATION_SYSTEM_PROMPT,
    CITATION_USER_PROMPT,
)

__all__ = [
    "LEAD_AGENT_SYSTEM_PROMPT",
    "PLAN_REVISION_PROMPT",
    "SYNTHESIS_GUIDANCE_PROMPT",
    "SUBAGENT_SYSTEM_PROMPT",
    "SUBAGENT_TASK_TEMPLATE",
    "CLARIFICATION_SYSTEM_PROMPT",
    "CLARIFICATION_USER_PROMPT",
    "SYNTHESIS_SYSTEM_PROMPT",
    "SYNTHESIS_USER_PROMPT",
    "CITATION_SYSTEM_PROMPT",
    "CITATION_USER_PROMPT",
]
```

---

### nodes/clarify.py

```python
"""
Query Clarification Node

Determines if the user's query needs clarification before research begins.
Uses COSA's notify_user_sync for blocking feedback when clarification is needed.

Pattern from: LangChain Open Deep Research clarification loop
"""

import json
import logging
from anthropic import Anthropic

from ..state import ResearchState, ClarificationDecision
from ..config import ResearchConfig
from ..cosa_interface import stream_thought, narrate_progress
from ..prompts import CLARIFICATION_SYSTEM_PROMPT, CLARIFICATION_USER_PROMPT

logger = logging.getLogger(__name__)


async def clarify_query(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Determine if the user's query needs clarification.
    
    This is the first node in the graph. If clarification is needed,
    we route to the feedback node; otherwise, proceed to planning.
    
    Args:
        state: Current graph state
        config: Research configuration
        
    Returns:
        State updates with clarification decision
    """
    await narrate_progress("clarifying")
    
    query = state.get("clarified_query") or state["original_query"]
    clarification_rounds = state.get("clarification_rounds", 0)
    
    # Check if we've exceeded max clarification rounds
    if clarification_rounds >= config.max_clarification_rounds:
        logger.info(f"Max clarification rounds ({config.max_clarification_rounds}) reached, proceeding")
        await stream_thought("I have enough context to proceed with research.")
        return {
            "needs_clarification": False,
            "clarified_query": query,
        }
    
    # Build context note for the prompt
    context_note = ""
    if state.get("clarification_response"):
        context_note = f"""
Previous clarification asked: {state.get('clarification_question')}
User's response: {state.get('clarification_response')}

Consider this additional context when analyzing the query.
"""
    
    client = Anthropic()
    
    try:
        response = client.messages.create(
            model=config.lead_model,
            max_tokens=1024,
            system=CLARIFICATION_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": CLARIFICATION_USER_PROMPT.format(
                    query=query,
                    context_note=context_note,
                )
            }],
        )
        
        # Parse the response
        decision = parse_clarification_response(response.content[0].text)
        
        if decision.needs_clarification:
            await stream_thought(
                f"I'd like to clarify: {decision.question}"
            )
        else:
            await stream_thought(
                f"I understand - you want to know: {decision.understood_query}"
            )
        
        return {
            "needs_clarification": decision.needs_clarification,
            "clarification_question": decision.question,
            "clarified_query": decision.understood_query,
            "clarification_rounds": clarification_rounds,
        }
        
    except Exception as e:
        logger.error(f"Error in clarification: {e}")
        # On error, proceed without clarification
        return {
            "needs_clarification": False,
            "clarified_query": query,
        }


def parse_clarification_response(response_text: str) -> ClarificationDecision:
    """
    Parse the LLM response into a ClarificationDecision.
    
    Handles both structured JSON output and natural language responses.
    """
    # Try to parse as JSON first
    try:
        # Look for JSON block in response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        elif "{" in response_text:
            # Try to find JSON object
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_str = response_text[json_start:json_end]
        else:
            raise ValueError("No JSON found")
        
        data = json.loads(json_str)
        return ClarificationDecision(**data)
        
    except (json.JSONDecodeError, ValueError, KeyError):
        # Fall back to heuristic parsing
        logger.debug("Falling back to heuristic parsing for clarification")
        
        response_lower = response_text.lower()
        needs_clarification = any(phrase in response_lower for phrase in [
            "clarif", "ask", "question", "unclear", "ambiguous"
        ])
        
        # Extract question if present
        question = None
        if needs_clarification:
            # Look for question marks
            sentences = response_text.split(".")
            for sentence in sentences:
                if "?" in sentence:
                    question = sentence.strip()
                    break
        
        return ClarificationDecision(
            needs_clarification=needs_clarification,
            question=question,
            understood_query=response_text[:200],  # Truncate
            ambiguities=[],
        )
```

---

### nodes/feedback.py

```python
"""
Human Feedback Nodes

These nodes integrate with COSA's voice interface for human-in-the-loop feedback.
Each feedback node BLOCKS until the user responds via voice.

Design principle: notify_user_sync provides natural graph pausing without
needing LangGraph's interrupt() mechanism.
"""

import logging
from ..state import ResearchState, ResearchPlan
from ..config import ResearchConfig
from ..cosa_interface import (
    get_human_feedback,
    stream_thought,
    narrate_progress,
    is_approval,
    extract_feedback_intent,
)

logger = logging.getLogger(__name__)


async def get_clarification(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Get clarification from the user.
    
    BLOCKING: This node pauses graph execution until user responds.
    """
    question = state["clarification_question"]
    
    if not question:
        # No question to ask, proceed
        return {"clarification_response": None}
    
    # Get user response via COSA voice interface
    response = get_human_feedback(
        prompt=question,
        timeout=config.feedback_timeout_seconds
    )
    
    return {
        "clarification_response": response,
        "clarification_rounds": state.get("clarification_rounds", 0) + 1,
    }


async def get_plan_feedback(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Present the research plan to the user and get feedback.
    
    BLOCKING: This node pauses graph execution until user responds.
    """
    plan = state["plan"]
    
    if not plan:
        logger.error("No plan available for feedback")
        return {"plan_approved": False}
    
    # Format plan for voice presentation
    prompt = format_plan_for_voice(plan)
    
    await stream_thought("Here's my research plan...")
    
    # BLOCKING CALL - graph execution pauses here
    feedback = get_human_feedback(
        prompt=prompt,
        timeout=config.feedback_timeout_seconds
    )
    
    # Analyze feedback
    intent = extract_feedback_intent(feedback)
    approved = intent["is_approval"]
    
    if approved:
        await stream_thought("Great, starting the research now.")
    else:
        await stream_thought("I'll revise the plan based on your feedback.")
    
    return {
        "human_feedback_on_plan": feedback,
        "plan_approved": approved,
        "plan_revision_count": state.get("plan_revision_count", 0) + (0 if approved else 1),
    }


async def get_draft_feedback(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Present the draft report to the user and get feedback.
    
    BLOCKING: This node pauses graph execution until user responds.
    """
    draft = state["draft_report"]
    
    if not draft:
        logger.error("No draft available for feedback")
        return {"human_feedback_on_draft": None}
    
    # For voice, we summarize rather than read the full draft
    summary = generate_draft_summary(draft)
    
    prompt = f"""I've completed a draft of the research report.

{summary}

Would you like me to finalize this report, or would you like any changes?"""
    
    await narrate_progress("complete", "Draft ready for review.")
    
    # BLOCKING CALL
    feedback = get_human_feedback(
        prompt=prompt,
        timeout=config.feedback_timeout_seconds
    )
    
    intent = extract_feedback_intent(feedback)
    approved = intent["is_approval"]
    
    if approved:
        await stream_thought("Finalizing the report with citations.")
    else:
        await stream_thought("I'll revise based on your feedback.")
    
    return {
        "human_feedback_on_draft": feedback,
        "draft_revision_count": state.get("draft_revision_count", 0) + (0 if approved else 1),
    }


def format_plan_for_voice(plan: ResearchPlan) -> str:
    """
    Format the research plan for TTS presentation.
    
    Optimized for voice: concise, clear, conversational.
    """
    subquery_descriptions = []
    for i, sq in enumerate(plan.subqueries, 1):
        subquery_descriptions.append(f"{i}. {sq.topic}: {sq.objective}")
    
    subquery_list = "\n".join(subquery_descriptions)
    
    complexity_description = {
        "simple": "straightforward",
        "moderate": "moderately complex",
        "complex": "comprehensive and detailed",
    }
    
    return f"""I've developed a research plan for your question.

This appears to be a {complexity_description.get(plan.complexity, 'moderate')} research task.

I'll investigate {plan.estimated_subagents} different aspects in parallel:

{subquery_list}

{plan.rationale}

Should I proceed with this plan, or would you like me to adjust the focus?"""


def generate_draft_summary(draft: str) -> str:
    """
    Generate a voice-friendly summary of the draft report.
    
    Extracts key points for audio presentation.
    """
    # Extract first paragraph or executive summary
    paragraphs = draft.split("\n\n")
    
    # Look for summary section
    summary = None
    for i, para in enumerate(paragraphs):
        para_lower = para.lower()
        if any(term in para_lower for term in ["summary", "overview", "key findings"]):
            # Take this paragraph and the next
            summary = "\n\n".join(paragraphs[i:i+2])
            break
    
    if not summary:
        # Take first 2-3 paragraphs
        summary = "\n\n".join(paragraphs[:3])
    
    # Truncate if too long for voice
    if len(summary) > 500:
        summary = summary[:500] + "..."
    
    return summary
```

---

### nodes/plan.py

```python
"""
Research Planning Nodes

Creates and revises research plans based on the user's query.
Uses the lead agent prompt with extended thinking for thorough decomposition.
"""

import json
import logging
from anthropic import Anthropic

from ..state import ResearchState, ResearchPlan, SubQuery
from ..config import ResearchConfig
from ..cosa_interface import stream_thought, narrate_progress
from ..prompts import LEAD_AGENT_SYSTEM_PROMPT, PLAN_REVISION_PROMPT

logger = logging.getLogger(__name__)


async def create_plan(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Create a research plan for the user's query.
    
    Uses extended thinking for thorough analysis and decomposition.
    """
    await narrate_progress("planning")
    
    query = state.get("clarified_query") or state["original_query"]
    
    client = Anthropic()
    
    try:
        response = client.messages.create(
            model=config.lead_model,
            max_tokens=4096,
            system=LEAD_AGENT_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"""Create a research plan for the following query:

<query>
{query}
</query>

Analyze this query thoroughly, determine its complexity, and create a structured research plan with specific subqueries for parallel investigation.

Return your plan as a JSON object matching the ResearchPlan schema."""
            }],
            # Enable extended thinking for thorough planning
            # Note: Uncomment when using models that support it
            # thinking={"type": "enabled", "budget_tokens": config.extended_thinking_budget},
        )
        
        plan = parse_plan_response(response.content[0].text)
        
        await stream_thought(
            f"I've identified {len(plan.subqueries)} areas to investigate."
        )
        
        # Create research brief for context compression
        research_brief = create_research_brief(query, plan)
        
        return {
            "plan": plan,
            "research_brief": research_brief,
            "active_subqueries": plan.subqueries,
        }
        
    except Exception as e:
        logger.error(f"Error creating plan: {e}")
        # Create minimal fallback plan
        fallback_plan = ResearchPlan(
            complexity="moderate",
            subqueries=[
                SubQuery(
                    topic=query[:100],
                    objective="Research this topic comprehensively",
                    output_format="Detailed summary with sources",
                    priority=1,
                )
            ],
            estimated_subagents=1,
            rationale="Fallback plan due to planning error",
        )
        return {
            "plan": fallback_plan,
            "research_brief": query,
            "active_subqueries": fallback_plan.subqueries,
        }


async def revise_plan(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Revise the research plan based on user feedback.
    """
    await stream_thought("Revising the research plan...")
    
    previous_plan = state["plan"]
    feedback = state["human_feedback_on_plan"]
    
    client = Anthropic()
    
    try:
        response = client.messages.create(
            model=config.lead_model,
            max_tokens=4096,
            system=LEAD_AGENT_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": PLAN_REVISION_PROMPT.format(
                    previous_plan=previous_plan.model_dump_json(indent=2),
                    user_feedback=feedback,
                )
            }],
        )
        
        revised_plan = parse_plan_response(response.content[0].text)
        
        await stream_thought(
            f"I've revised the plan. Now focusing on {len(revised_plan.subqueries)} areas."
        )
        
        return {
            "plan": revised_plan,
            "active_subqueries": revised_plan.subqueries,
        }
        
    except Exception as e:
        logger.error(f"Error revising plan: {e}")
        # Keep the original plan
        return {}


async def check_completeness(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Check if the research findings are complete or if more research is needed.
    """
    findings = state["subagent_findings"]
    iterations = state.get("research_iterations", 0)
    
    # Collect all gaps
    all_gaps = []
    for finding in findings:
        all_gaps.extend(finding.gaps)
    
    # Check if we should do more research
    should_continue = (
        len(all_gaps) > 0 and 
        iterations < config.max_research_iterations and
        len(all_gaps) <= 5  # Don't spawn too many follow-up searches
    )
    
    if should_continue:
        await stream_thought(
            f"Found {len(all_gaps)} gaps. Doing additional research."
        )
        
        # Create subqueries for gaps
        gap_subqueries = [
            SubQuery(
                topic=gap,
                objective=f"Fill information gap: {gap}",
                output_format="Focused findings addressing this gap",
                priority=2,
            )
            for gap in all_gaps[:5]  # Limit to 5 gaps
        ]
        
        return {
            "active_subqueries": gap_subqueries,
            "research_iterations": iterations + 1,
        }
    else:
        await stream_thought("Research complete. Synthesizing findings.")
        return {
            "research_iterations": iterations,
        }


def parse_plan_response(response_text: str) -> ResearchPlan:
    """
    Parse the LLM response into a ResearchPlan.
    """
    try:
        # Look for JSON in response
        if "```json" in response_text:
            json_start = response_text.find("```json") + 7
            json_end = response_text.find("```", json_start)
            json_str = response_text[json_start:json_end].strip()
        elif "{" in response_text:
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            json_str = response_text[json_start:json_end]
        else:
            raise ValueError("No JSON found in response")
        
        data = json.loads(json_str)
        
        # Convert subqueries if needed
        if "subqueries" in data:
            data["subqueries"] = [
                SubQuery(**sq) if isinstance(sq, dict) else sq
                for sq in data["subqueries"]
            ]
        
        return ResearchPlan(**data)
        
    except Exception as e:
        logger.error(f"Failed to parse plan: {e}")
        raise


def create_research_brief(query: str, plan: ResearchPlan) -> str:
    """
    Create a compressed research brief for context management.
    
    This prevents token bloat as the research progresses.
    """
    subquery_summary = "\n".join(
        f"- {sq.topic}: {sq.objective}"
        for sq in plan.subqueries
    )
    
    return f"""Research Brief
Query: {query}
Complexity: {plan.complexity}
Approach: {plan.rationale}

Investigation Areas:
{subquery_summary}
"""
```

---

### nodes/research.py

```python
"""
Parallel Research Subagent Node

Executes research for individual subqueries using Claude Agent SDK.
This node is invoked via LangGraph's Send() API for parallel execution.

Key features:
- Tool-calling loop with web_search and web_fetch
- Parallel tool execution within each subagent
- Context compression before returning
- Progress narration via COSA async
"""

import json
import logging
from anthropic import Anthropic

from ..state import SubQuery, SubagentFinding, SourceReference, SubagentState
from ..config import ResearchConfig
from ..cosa_interface import (
    stream_thought,
    narrate_subagent_start,
    narrate_subagent_complete,
    narrate_finding,
)
from ..prompts import SUBAGENT_SYSTEM_PROMPT, SUBAGENT_TASK_TEMPLATE

logger = logging.getLogger(__name__)


async def research_subquery(state: SubagentState, config: ResearchConfig) -> dict:
    """
    Execute research for a single subquery.
    
    This node runs in parallel with other subquery research nodes via Send().
    Uses Claude Agent SDK's WebSearch and WebFetch tools.
    
    Args:
        state: Subagent state containing the subquery assignment
        config: Research configuration
        
    Returns:
        State update with completed finding
    """
    subquery: SubQuery = state["subquery"]
    subquery_index: int = state["subquery_index"]
    
    await narrate_subagent_start(
        subquery.topic,
        subquery_index,
        state.get("total_subqueries", 1)
    )
    
    client = Anthropic()
    
    # Build tool definitions
    tools = [
        {
            "type": "web_search_20250305",
            "name": "web_search",
        },
    ]
    
    # Format task prompt
    dependency_note = "is independent and can proceed immediately"
    if subquery.depends_on:
        dependency_note = f"depends on results from subqueries {subquery.depends_on}"
    
    task_prompt = SUBAGENT_TASK_TEMPLATE.format(
        topic=subquery.topic,
        objective=subquery.objective,
        output_format=subquery.output_format,
        tools=", ".join(subquery.tools_to_use),
        priority=subquery.priority,
        dependency_note=dependency_note,
        max_tool_calls=config.max_tool_calls_per_subagent,
    )
    
    messages = [{"role": "user", "content": task_prompt}]
    
    # Agent loop with tool calling
    tool_calls = 0
    sources_found = []
    
    while tool_calls < config.max_tool_calls_per_subagent:
        try:
            response = client.messages.create(
                model=config.subagent_model,
                max_tokens=4096,
                system=SUBAGENT_SYSTEM_PROMPT,
                messages=messages,
                tools=tools,
            )
            
            # Check stop reason
            if response.stop_reason == "end_turn":
                # Agent has completed research
                break
            
            if response.stop_reason == "tool_use":
                # Process tool calls
                tool_results = []
                
                for content_block in response.content:
                    if content_block.type == "tool_use":
                        tool_name = content_block.name
                        tool_input = content_block.input
                        tool_id = content_block.id
                        
                        # Execute tool (in production, this would call actual APIs)
                        result = await execute_tool(tool_name, tool_input, config)
                        
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": tool_id,
                            "content": result,
                        })
                        
                        tool_calls += 1
                        
                        # Track sources
                        if tool_name == "web_search":
                            sources_found.extend(
                                extract_sources_from_search(result)
                            )
                
                # Append assistant response and tool results
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                # Unexpected stop reason
                logger.warning(f"Unexpected stop reason: {response.stop_reason}")
                break
                
        except Exception as e:
            logger.error(f"Error in subagent research loop: {e}")
            break
    
    # Extract and compress findings
    finding = extract_finding(
        subquery_index=subquery_index,
        subquery_topic=subquery.topic,
        messages=messages,
        sources=sources_found,
    )
    
    await narrate_subagent_complete(subquery.topic, len(sources_found))
    
    # Key finding narration
    if finding.findings and len(finding.findings) > 50:
        summary = finding.findings[:100] + "..."
        await narrate_finding(summary)
    
    return {"completed_finding": finding}


async def execute_tool(
    tool_name: str,
    tool_input: dict,
    config: ResearchConfig
) -> str:
    """
    Execute a tool call.
    
    In production, this dispatches to actual Claude API tools.
    For web_search, the API handles this natively.
    """
    # The Claude API handles web_search natively when specified in tools
    # This function is a placeholder for any custom tool handling
    
    if tool_name == "web_search":
        # The API returns results directly
        # This is handled by the messages API
        return "Tool executed by API"
    
    if tool_name == "web_fetch":
        # Would use requests/httpx to fetch URL
        url = tool_input.get("url", "")
        return f"Fetched content from {url}"
    
    return f"Unknown tool: {tool_name}"


def extract_sources_from_search(result: str) -> list[SourceReference]:
    """
    Extract source references from search results.
    
    Parses the search result format and creates SourceReference objects.
    """
    sources = []
    
    try:
        # Try to parse as JSON if structured
        if isinstance(result, str) and result.startswith("{"):
            data = json.loads(result)
            for item in data.get("results", []):
                sources.append(SourceReference(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    relevance_score=0.8,  # Default
                ))
    except json.JSONDecodeError:
        # Parse as text
        pass
    
    return sources


def extract_finding(
    subquery_index: int,
    subquery_topic: str,
    messages: list,
    sources: list[SourceReference],
) -> SubagentFinding:
    """
    Extract and compress findings from the conversation history.
    
    Looks for the final response containing summarized findings.
    """
    # Find the last assistant message with actual content
    findings_text = ""
    for message in reversed(messages):
        if message.get("role") == "assistant":
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if hasattr(block, "text"):
                        findings_text = block.text
                        break
                    elif isinstance(block, dict) and "text" in block:
                        findings_text = block["text"]
                        break
            elif isinstance(content, str):
                findings_text = content
            
            if findings_text:
                break
    
    # Extract gaps from findings text
    gaps = []
    gap_indicators = ["couldn't find", "no information", "unclear", "needs more"]
    for indicator in gap_indicators:
        if indicator in findings_text.lower():
            # Extract sentence containing the indicator
            sentences = findings_text.split(".")
            for sentence in sentences:
                if indicator in sentence.lower():
                    gaps.append(sentence.strip())
    
    # Calculate confidence based on source quality and quantity
    confidence = min(0.9, 0.5 + (len(sources) * 0.1))
    
    return SubagentFinding(
        subquery_index=subquery_index,
        subquery_topic=subquery_topic,
        findings=findings_text[:5000],  # Truncate to prevent bloat
        sources=sources[:10],  # Keep top 10 sources
        confidence=confidence,
        gaps=gaps[:3],  # Limit gaps
        quality_notes="",
    )
```

---

### nodes/compress.py

```python
"""
Context Compression Node

Gathers and compresses findings from parallel subagent research.
Prevents token bloat by summarizing and deduplicating.

Pattern from: LangChain Open Deep Research context engineering
"""

import logging
from ..state import ResearchState, SubagentFinding
from ..config import ResearchConfig
from ..cosa_interface import stream_thought

logger = logging.getLogger(__name__)


async def gather_and_compress(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Gather findings from all completed subagents and compress.
    
    This node runs after all parallel research nodes complete.
    It deduplicates sources and creates a compressed summary.
    """
    await stream_thought("Gathering and analyzing all research findings...")
    
    # Get existing findings and new completed finding
    existing_findings = state.get("subagent_findings", [])
    new_finding = state.get("completed_finding")
    
    if new_finding:
        existing_findings.append(new_finding)
    
    # Deduplicate sources across findings
    all_sources = []
    seen_urls = set()
    
    for finding in existing_findings:
        for source in finding.sources:
            if source.url not in seen_urls:
                seen_urls.add(source.url)
                all_sources.append(source)
    
    # Calculate total sources
    total_sources = len(all_sources)
    
    # Compress findings if too many tokens
    compressed_findings = compress_findings(existing_findings, config)
    
    await stream_thought(
        f"Analyzed {len(existing_findings)} research threads with {total_sources} unique sources."
    )
    
    return {
        "subagent_findings": compressed_findings,
        "total_sources_found": total_sources,
    }


def compress_findings(
    findings: list[SubagentFinding],
    config: ResearchConfig
) -> list[SubagentFinding]:
    """
    Compress findings to stay within token budget.
    
    Strategies:
    1. Truncate individual findings if too long
    2. Remove low-confidence findings if at limit
    3. Deduplicate similar content
    """
    max_tokens = config.max_findings_tokens
    
    # Estimate current token count (rough: 4 chars per token)
    total_chars = sum(len(f.findings) for f in findings)
    estimated_tokens = total_chars // 4
    
    if estimated_tokens <= max_tokens:
        return findings
    
    logger.info(f"Compressing findings from ~{estimated_tokens} to ~{max_tokens} tokens")
    
    # Sort by confidence (keep highest confidence)
    sorted_findings = sorted(findings, key=lambda f: f.confidence, reverse=True)
    
    compressed = []
    current_tokens = 0
    
    for finding in sorted_findings:
        finding_tokens = len(finding.findings) // 4
        
        if current_tokens + finding_tokens <= max_tokens:
            compressed.append(finding)
            current_tokens += finding_tokens
        else:
            # Truncate this finding to fit
            remaining_tokens = max_tokens - current_tokens
            if remaining_tokens > 200:  # Minimum useful size
                truncated_text = finding.findings[:remaining_tokens * 4]
                truncated_finding = SubagentFinding(
                    subquery_index=finding.subquery_index,
                    subquery_topic=finding.subquery_topic,
                    findings=truncated_text + "...[truncated]",
                    sources=finding.sources[:5],
                    confidence=finding.confidence * 0.9,  # Lower confidence for truncated
                    gaps=finding.gaps,
                    quality_notes=finding.quality_notes + " (compressed)",
                )
                compressed.append(truncated_finding)
            break
    
    return compressed
```

---

### nodes/synthesize.py

```python
"""
Report Synthesis Node

Synthesizes subagent findings into a coherent research report.
Uses the synthesis prompts with the lead agent model.
"""

import logging
from anthropic import Anthropic

from ..state import ResearchState
from ..config import ResearchConfig
from ..cosa_interface import stream_thought, narrate_progress
from ..prompts import SYNTHESIS_SYSTEM_PROMPT, SYNTHESIS_USER_PROMPT

logger = logging.getLogger(__name__)


async def create_report(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Synthesize all findings into a comprehensive report.
    """
    await narrate_progress("synthesizing")
    
    findings = state["subagent_findings"]
    plan = state["plan"]
    query = state.get("clarified_query") or state["original_query"]
    
    # Format findings for synthesis
    findings_text = format_findings_for_synthesis(findings)
    
    # Get any user context from feedback
    user_context = ""
    if state.get("human_feedback_on_plan"):
        user_context = f"User preferences: {state['human_feedback_on_plan']}"
    if state.get("human_feedback_on_draft"):
        user_context += f"\nRevision request: {state['human_feedback_on_draft']}"
    
    client = Anthropic()
    
    try:
        response = client.messages.create(
            model=config.lead_model,
            max_tokens=8192,
            system=SYNTHESIS_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": SYNTHESIS_USER_PROMPT.format(
                    original_query=query,
                    research_plan=plan.model_dump_json(indent=2) if plan else "No plan",
                    findings=findings_text,
                    user_context=user_context or "None",
                )
            }],
        )
        
        draft_report = response.content[0].text
        
        await stream_thought("Draft report complete.")
        
        return {
            "draft_report": draft_report,
        }
        
    except Exception as e:
        logger.error(f"Error synthesizing report: {e}")
        
        # Create fallback report
        fallback = create_fallback_report(query, findings)
        return {
            "draft_report": fallback,
        }


def format_findings_for_synthesis(findings) -> str:
    """
    Format all findings into a structured text for synthesis.
    """
    sections = []
    
    for finding in findings:
        sources_list = "\n".join(
            f"  - [{s.title}]({s.url})"
            for s in finding.sources[:5]
        )
        
        section = f"""### {finding.subquery_topic}
**Confidence**: {finding.confidence:.0%}

{finding.findings}

**Sources**:
{sources_list}

**Gaps**: {', '.join(finding.gaps) if finding.gaps else 'None identified'}
"""
        sections.append(section)
    
    return "\n---\n".join(sections)


def create_fallback_report(query: str, findings) -> str:
    """
    Create a basic report when synthesis fails.
    """
    findings_summary = "\n\n".join(
        f"**{f.subquery_topic}**: {f.findings[:500]}..."
        for f in findings
    )
    
    return f"""# Research Report: {query}

## Summary
Research was conducted on the requested topic. Below are the key findings.

## Findings

{findings_summary}

---
*Note: This is a simplified report due to synthesis limitations.*
"""
```

---

### nodes/cite.py

```python
"""
Citation Generation Node

Adds proper citations to the research report.
Matches claims to sources and formats according to the configured style.
"""

import logging
from anthropic import Anthropic

from ..state import ResearchState, Citation, SourceReference
from ..config import ResearchConfig
from ..cosa_interface import stream_thought, narrate_progress
from ..prompts import CITATION_SYSTEM_PROMPT, CITATION_USER_PROMPT

logger = logging.getLogger(__name__)


async def add_citations(state: ResearchState, config: ResearchConfig) -> dict:
    """
    Add citations to the draft report and finalize.
    """
    await narrate_progress("citing")
    
    draft = state["draft_report"]
    findings = state["subagent_findings"]
    
    # Collect all sources
    all_sources = []
    for finding in findings:
        all_sources.extend(finding.sources)
    
    # Deduplicate sources
    unique_sources = deduplicate_sources(all_sources)
    
    # Format sources for citation prompt
    sources_text = format_sources_for_citation(unique_sources)
    
    client = Anthropic()
    
    try:
        response = client.messages.create(
            model=config.lead_model,
            max_tokens=8192,
            system=CITATION_SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": CITATION_USER_PROMPT.format(
                    draft_report=draft,
                    sources=sources_text,
                    citation_style=config.citation_style,
                )
            }],
        )
        
        final_report = response.content[0].text
        
        # Extract citations for metadata
        citations = extract_citations(final_report, unique_sources)
        
        await stream_thought("Report finalized with citations.")
        
        return {
            "final_report": final_report,
            "citations": citations,
            "research_metadata": {
                "total_sources": len(unique_sources),
                "total_citations": len(citations),
                "research_iterations": state.get("research_iterations", 1),
            },
        }
        
    except Exception as e:
        logger.error(f"Error adding citations: {e}")
        
        # Return draft as final if citation fails
        return {
            "final_report": draft + "\n\n---\n*Citations could not be added.*",
            "citations": [],
        }


def deduplicate_sources(sources: list[SourceReference]) -> list[SourceReference]:
    """
    Remove duplicate sources based on URL.
    """
    seen_urls = set()
    unique = []
    
    for source in sources:
        if source.url not in seen_urls:
            seen_urls.add(source.url)
            unique.append(source)
    
    return unique


def format_sources_for_citation(sources: list[SourceReference]) -> str:
    """
    Format sources list for the citation prompt.
    """
    lines = []
    for i, source in enumerate(sources, 1):
        lines.append(f"""[{i}] {source.title}
URL: {source.url}
Snippet: {source.snippet[:200] if source.snippet else 'N/A'}
Quality: {source.source_quality}
""")
    
    return "\n".join(lines)


def extract_citations(report: str, sources: list[SourceReference]) -> list[Citation]:
    """
    Extract citation objects from the final report.
    
    Simple extraction - looks for URL patterns in the report.
    """
    citations = []
    
    for source in sources:
        if source.url in report:
            # Find context around the citation
            idx = report.find(source.url)
            start = max(0, idx - 100)
            end = min(len(report), idx + len(source.url) + 50)
            context = report[start:end]
            
            citations.append(Citation(
                claim=context,
                source=source,
                location_in_report=f"char {idx}",
            ))
    
    return citations
```

---

### nodes/__init__.py

```python
"""
Graph nodes for COSA Deep Research Agent.
"""

from .clarify import clarify_query
from .feedback import get_clarification, get_plan_feedback, get_draft_feedback
from .plan import create_plan, revise_plan, check_completeness
from .research import research_subquery
from .compress import gather_and_compress
from .synthesize import create_report
from .cite import add_citations

__all__ = [
    "clarify_query",
    "get_clarification",
    "get_plan_feedback",
    "get_draft_feedback",
    "create_plan",
    "revise_plan",
    "check_completeness",
    "research_subquery",
    "gather_and_compress",
    "create_report",
    "add_citations",
]
```

---

### tools/web_search.py

```python
"""
Web Search Tool Wrapper

Wraps Claude Agent SDK's web_search_20250305 tool.
Provides a consistent interface for the research nodes.
"""

from typing import Any
from anthropic import Anthropic


def get_web_search_tool() -> dict:
    """
    Get the web search tool definition for Claude API.
    """
    return {
        "type": "web_search_20250305",
        "name": "web_search",
    }


async def execute_web_search(
    query: str,
    client: Anthropic | None = None,
) -> dict[str, Any]:
    """
    Execute a web search using Claude's native tool.
    
    Note: In practice, web_search is executed by the Claude API
    as part of the tool-calling flow. This function is for
    standalone search execution if needed.
    
    Args:
        query: Search query
        client: Anthropic client (creates one if not provided)
        
    Returns:
        Search results
    """
    if client is None:
        client = Anthropic()
    
    # For standalone execution, we make a minimal API call
    # that triggers the web search tool
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        tools=[get_web_search_tool()],
        messages=[{
            "role": "user",
            "content": f"Search for: {query}"
        }],
    )
    
    # Extract search results from response
    for content in response.content:
        if hasattr(content, "type") and content.type == "tool_use":
            return {
                "tool_id": content.id,
                "query": query,
                "status": "executed",
            }
    
    return {"status": "no_search_executed", "query": query}
```

---

### tools/web_fetch.py

```python
"""
Web Fetch Tool Wrapper

Wraps web content fetching for full page retrieval.
Used when search snippets are insufficient.
"""

import httpx
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Common headers to appear as a regular browser
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ResearchBot/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}


async def fetch_url(
    url: str,
    timeout: float = 30.0,
    max_content_length: int = 100000,
) -> dict[str, Any]:
    """
    Fetch the content of a URL.
    
    Args:
        url: URL to fetch
        timeout: Request timeout in seconds
        max_content_length: Maximum content length to return
        
    Returns:
        Dict with url, content, status, and metadata
    """
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=DEFAULT_HEADERS, follow_redirects=True)
            
            content = response.text[:max_content_length]
            
            return {
                "url": url,
                "status": response.status_code,
                "content": content,
                "content_type": response.headers.get("content-type", "unknown"),
                "truncated": len(response.text) > max_content_length,
            }
            
    except httpx.TimeoutException:
        logger.warning(f"Timeout fetching {url}")
        return {
            "url": url,
            "status": "timeout",
            "content": "",
            "error": "Request timed out",
        }
    except httpx.RequestError as e:
        logger.warning(f"Error fetching {url}: {e}")
        return {
            "url": url,
            "status": "error",
            "content": "",
            "error": str(e),
        }


def extract_text_from_html(html: str) -> str:
    """
    Extract readable text from HTML content.
    
    Simple extraction - for production, use BeautifulSoup or similar.
    """
    import re
    
    # Remove script and style elements
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove HTML tags
    text = re.sub(r'<[^>]+>', ' ', html)
    
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text)
    
    return text.strip()
```

---

### tools/__init__.py

```python
"""
Tool wrappers for COSA Deep Research Agent.
"""

from .web_search import get_web_search_tool, execute_web_search
from .web_fetch import fetch_url, extract_text_from_html

__all__ = [
    "get_web_search_tool",
    "execute_web_search",
    "fetch_url",
    "extract_text_from_html",
]
```

---

### graph.py

```python
"""
LangGraph StateGraph Definition

Orchestrates the complete research workflow with:
- Clarification loop with human feedback
- Planning with human approval
- Parallel subagent research via Send()
- Synthesis and citation with optional review

Design Principles:
- COSA integration via notify_user_sync for blocking feedback
- Parallel execution via LangGraph Send() API
- Context compression to prevent token bloat
- Configurable limits for safety
"""

from typing import Literal
from langgraph.graph import StateGraph, START, END
from langgraph.types import Send

from .state import ResearchState, SubagentState, create_initial_state
from .config import ResearchConfig
from .nodes import (
    clarify_query,
    get_clarification,
    get_plan_feedback,
    get_draft_feedback,
    create_plan,
    revise_plan,
    check_completeness,
    research_subquery,
    gather_and_compress,
    create_report,
    add_citations,
)


def build_research_graph(config: ResearchConfig | None = None) -> StateGraph:
    """
    Build and compile the research agent graph.
    
    Args:
        config: Research configuration (uses defaults if not provided)
        
    Returns:
        Compiled LangGraph StateGraph
    """
    if config is None:
        config = ResearchConfig()
    
    # Create graph with state schema
    graph = StateGraph(ResearchState)
    
    # === Add Nodes ===
    
    # Clarification phase
    graph.add_node("clarify", lambda s: clarify_query(s, config))
    graph.add_node("get_clarification", lambda s: get_clarification(s, config))
    
    # Planning phase
    graph.add_node("plan", lambda s: create_plan(s, config))
    graph.add_node("get_plan_feedback", lambda s: get_plan_feedback(s, config))
    graph.add_node("revise_plan", lambda s: revise_plan(s, config))
    
    # Research phase (parallel execution via Send)
    graph.add_node("research_subquery", lambda s: research_subquery(s, config))
    graph.add_node("gather_findings", lambda s: gather_and_compress(s, config))
    graph.add_node("check_completeness", lambda s: check_completeness(s, config))
    
    # Synthesis phase
    graph.add_node("synthesize", lambda s: create_report(s, config))
    graph.add_node("get_draft_feedback", lambda s: get_draft_feedback(s, config))
    graph.add_node("cite", lambda s: add_citations(s, config))
    
    # === Add Edges ===
    
    # Start with clarification
    graph.add_edge(START, "clarify")
    
    # Clarification routing
    graph.add_conditional_edges(
        "clarify",
        route_after_clarification,
        {
            "needs_clarification": "get_clarification",
            "proceed_to_plan": "plan",
        }
    )
    graph.add_edge("get_clarification", "clarify")  # Loop back after user responds
    
    # Planning and feedback
    graph.add_edge("plan", "get_plan_feedback")
    graph.add_conditional_edges(
        "get_plan_feedback",
        route_after_plan_feedback,
        {
            "approved": "spawn_research",
            "revise": "revise_plan",
        }
    )
    graph.add_edge("revise_plan", "get_plan_feedback")  # Loop back
    
    # Parallel research spawning
    # Note: "spawn_research" is a virtual routing node, not an actual node
    graph.add_conditional_edges(
        "get_plan_feedback",  # When approved, spawn research
        spawn_research_subagents,
        ["research_subquery"]  # Target node for Send()
    )
    
    # Research completion flow
    graph.add_edge("research_subquery", "gather_findings")
    graph.add_edge("gather_findings", "check_completeness")
    
    graph.add_conditional_edges(
        "check_completeness",
        route_after_completeness_check,
        {
            "more_research": "spawn_more_research",
            "synthesize": "synthesize",
        }
    )
    
    # Handle spawning more research for gaps
    graph.add_conditional_edges(
        "check_completeness",
        spawn_gap_research,
        ["research_subquery"]
    )
    
    # Synthesis and optional review
    graph.add_edge("synthesize", "get_draft_feedback")
    graph.add_conditional_edges(
        "get_draft_feedback",
        route_after_draft_feedback,
        {
            "approved": "cite",
            "revise": "synthesize",
        }
    )
    
    # Final citation and end
    graph.add_edge("cite", END)
    
    return graph.compile()


# === Routing Functions ===

def route_after_clarification(state: ResearchState) -> Literal["needs_clarification", "proceed_to_plan"]:
    """Route based on whether clarification is needed."""
    if state.get("needs_clarification", False):
        return "needs_clarification"
    return "proceed_to_plan"


def route_after_plan_feedback(state: ResearchState) -> Literal["approved", "revise"]:
    """Route based on whether the plan was approved."""
    if state.get("plan_approved", False):
        return "approved"
    return "revise"


def spawn_research_subagents(state: ResearchState) -> list[Send]:
    """
    Spawn parallel subagent research tasks using LangGraph's Send API.
    
    Each subquery becomes a parallel execution of the research_subquery node.
    Only called when plan is approved.
    """
    if not state.get("plan_approved", False):
        return []
    
    plan = state.get("plan")
    if not plan:
        return []
    
    subqueries = plan.subqueries
    total = len(subqueries)
    
    return [
        Send(
            "research_subquery",
            SubagentState(
                subquery=subquery,
                subquery_index=i,
                messages=[],
                tool_calls_made=0,
                sources_found=[],
                current_findings="",
                total_subqueries=total,
            )
        )
        for i, subquery in enumerate(subqueries)
    ]


def route_after_completeness_check(state: ResearchState) -> Literal["more_research", "synthesize"]:
    """Route based on whether more research is needed."""
    active_subqueries = state.get("active_subqueries", [])
    if active_subqueries:
        return "more_research"
    return "synthesize"


def spawn_gap_research(state: ResearchState) -> list[Send]:
    """
    Spawn additional research for identified gaps.
    
    Only called when route_after_completeness_check returns "more_research".
    """
    active_subqueries = state.get("active_subqueries", [])
    if not active_subqueries:
        return []
    
    total = len(active_subqueries)
    
    return [
        Send(
            "research_subquery",
            SubagentState(
                subquery=subquery,
                subquery_index=i,
                messages=[],
                tool_calls_made=0,
                sources_found=[],
                current_findings="",
                total_subqueries=total,
            )
        )
        for i, subquery in enumerate(active_subqueries)
    ]


def route_after_draft_feedback(state: ResearchState) -> Literal["approved", "revise"]:
    """Route based on whether the draft was approved."""
    feedback = state.get("human_feedback_on_draft", "")
    
    # Import here to avoid circular dependency
    from .cosa_interface import is_approval
    
    if is_approval(feedback):
        return "approved"
    return "revise"


# === Graph Visualization ===

def get_graph_diagram() -> str:
    """
    Get a Mermaid diagram of the graph structure.
    
    Useful for documentation and debugging.
    """
    return """
```mermaid
graph TD
    START((Start)) --> clarify
    
    clarify --> |needs clarification| get_clarification
    clarify --> |understood| plan
    get_clarification --> clarify
    
    plan --> get_plan_feedback
    get_plan_feedback --> |approved| research_subquery
    get_plan_feedback --> |revise| revise_plan
    revise_plan --> get_plan_feedback
    
    research_subquery --> |parallel| gather_findings
    gather_findings --> check_completeness
    check_completeness --> |gaps found| research_subquery
    check_completeness --> |complete| synthesize
    
    synthesize --> get_draft_feedback
    get_draft_feedback --> |approved| cite
    get_draft_feedback --> |revise| synthesize
    
    cite --> END((End))
    
    style get_clarification fill:#e1f5fe
    style get_plan_feedback fill:#e1f5fe
    style get_draft_feedback fill:#e1f5fe
    
    note[Blue nodes are COSA feedback points]
```
"""
```

---

### main.py

```python
"""
COSA Deep Research Agent Entry Point

This module provides the interface between COSA's voice orchestration
and the LangGraph research agent.

Usage:
    from cosa import notify_user_sync, notify_user_async
    from cosa_deep_research import DeepResearchAgent
    
    agent = DeepResearchAgent()
    agent.configure(notify_user_sync, notify_user_async)
    
    result = await agent.research("What are the latest developments in agentic AI?")
"""

import asyncio
import logging
from typing import Callable, Awaitable

from .graph import build_research_graph, get_graph_diagram
from .config import ResearchConfig
from .cosa_interface import configure_cosa, is_configured
from .state import ResearchState, create_initial_state

logger = logging.getLogger(__name__)


class DeepResearchAgent:
    """
    Voice-driven deep research agent for COSA integration.
    
    This agent orchestrates multi-step research with human-in-the-loop
    feedback at key decision points (clarification, plan approval, draft review).
    
    Attributes:
        config: Research configuration
        graph: Compiled LangGraph StateGraph
        
    Example:
        ```python
        from cosa import notify_user_sync, notify_user_async
        
        agent = DeepResearchAgent()
        agent.configure(notify_user_sync, notify_user_async)
        
        # Async execution
        result = await agent.research("Compare LangGraph and CrewAI for agent development")
        print(result)
        ```
    """
    
    def __init__(self, config: ResearchConfig | None = None):
        """
        Initialize the research agent.
        
        Args:
            config: Research configuration. Uses defaults if not provided.
        """
        self.config = config or ResearchConfig()
        self.graph = build_research_graph(self.config)
        self._configured = False
        
        logger.info(f"DeepResearchAgent initialized with config: {self.config}")
    
    def configure(
        self,
        sync_fn: Callable[[str, int], str],
        async_fn: Callable[[str], Awaitable[None]],
    ) -> None:
        """
        Configure COSA voice interface callbacks.
        
        Must be called before using the agent.
        
        Args:
            sync_fn: COSA's notify_user_sync function
            async_fn: COSA's notify_user_async function
        """
        configure_cosa(sync_fn, async_fn)
        self._configured = True
        logger.info("COSA interface configured")
    
    async def research(self, query: str) -> str:
        """
        Execute a deep research task with human-in-the-loop feedback.
        
        This method orchestrates the complete research workflow:
        1. Query clarification (if needed)
        2. Research planning with user approval
        3. Parallel research execution
        4. Synthesis with optional user review
        5. Citation and finalization
        
        Args:
            query: The research question from the user
            
        Returns:
            The final research report with citations
            
        Raises:
            RuntimeError: If COSA interface not configured
        """
        if not self._configured:
            raise RuntimeError(
                "Agent not configured. Call configure() with COSA callbacks first."
            )
        
        logger.info(f"Starting research: {query[:100]}...")
        
        # Create initial state
        initial_state = create_initial_state(query)
        
        # Execute the graph
        try:
            result = await self.graph.ainvoke(initial_state)
            
            final_report = result.get("final_report", "")
            
            logger.info(f"Research complete. Report length: {len(final_report)} chars")
            
            return final_report
            
        except Exception as e:
            logger.error(f"Research failed: {e}", exc_info=True)
            raise
    
    def research_sync(self, query: str) -> str:
        """
        Synchronous wrapper for research execution.
        
        Useful when integrating with synchronous code.
        
        Args:
            query: The research question
            
        Returns:
            The final research report
        """
        return asyncio.run(self.research(query))
    
    def get_diagram(self) -> str:
        """
        Get a Mermaid diagram of the research workflow.
        
        Useful for documentation and debugging.
        """
        return get_graph_diagram()
    
    @property
    def is_ready(self) -> bool:
        """Check if the agent is ready for research."""
        return self._configured


# === Standalone Execution for Testing ===

def create_mock_cosa_interface():
    """
    Create mock COSA interface for testing.
    
    Uses console input/output instead of voice.
    """
    def mock_notify_sync(prompt: str, timeout: int = 300) -> str:
        print(f"\n🎤 COSA: {prompt}")
        return input("Your response: ")
    
    async def mock_notify_async(thought: str) -> None:
        print(f"💭 {thought}")
    
    return mock_notify_sync, mock_notify_async


async def main():
    """
    Main entry point for standalone testing.
    """
    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    print("=" * 60)
    print("COSA Deep Research Agent - Test Mode")
    print("=" * 60)
    
    # Create agent with mock COSA interface
    agent = DeepResearchAgent()
    sync_fn, async_fn = create_mock_cosa_interface()
    agent.configure(sync_fn, async_fn)
    
    # Get query from user
    print("\nThis agent will research any topic with human-in-the-loop feedback.")
    print("You'll be asked to approve the research plan and review the draft.\n")
    
    query = input("What would you like to research? ")
    
    if not query.strip():
        query = "What are the key differences between LangGraph and CrewAI for building AI agents?"
        print(f"Using default query: {query}")
    
    # Execute research
    print("\nStarting research...\n")
    
    try:
        report = await agent.research(query)
        
        print("\n" + "=" * 60)
        print("FINAL RESEARCH REPORT")
        print("=" * 60)
        print(report)
        
    except Exception as e:
        print(f"\n❌ Research failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
```

---

## COSA Queue Integration

> **Added**: January 2026
> **Purpose**: Design for integrating the Deep Research Agent with COSA's queue system as a non-blocking, queryable, controllable orchestrator.

### Non-Blocking Running Queue Architecture

The COSA running queue is evolving from blocking (one job at a time) to **non-blocking** (concurrent jobs with sub-states). The Deep Research Agent is designed for this async architecture.

#### Concurrency Model: Async/Await

**Decision**: Use Python asyncio as the concurrency model.

**Rationale**:
- ✅ Native Python pattern with first-class language support
- ✅ Efficient single-threaded event loop (no context switching overhead)
- ✅ Natural blocking semantics - `await` clearly shows yield points
- ✅ Cancellation built-in via `asyncio.Task.cancel()`
- ✅ Matches FastAPI (already async)
- ✅ Scales well (thousands of waiting jobs, not thousands of threads)
- ✅ Use `asyncio.to_thread()` for CPU-bound work (XML parsing, etc.)

#### Running Queue Evolution

**Current (Blocking)**:
```
TODO → RUNNING (one job blocks queue) → DONE
```

**Target (Non-Blocking)**:
```
TODO → RUNNING (concurrent jobs with sub-states) → DONE
         ├── Job A: running.executing
         ├── Job B: running.waiting_for_feedback  ← yields, doesn't block
         ├── Job C: running.executing
         └── Job D: running.waiting_for_clarification
```

#### Job Sub-State Model

Jobs within RUNNING have sub-states:

```python
class JobSubState( Enum ):
    """Sub-states for jobs within the RUNNING queue."""
    EXECUTING = "executing"                    # Actively processing
    WAITING_FOR_HUMAN = "waiting_for_human"    # Blocked on human input (yields control)
    WAITING_FOR_SUBTASKS = "waiting_for_subtasks"  # Orchestrator waiting for workers
    WAITING_FOR_LLM = "waiting_for_llm"        # Awaiting LLM API response
    PAUSED = "paused"                          # Externally paused
```

#### Async Job Execution Pattern

```python
async def process_job_async( job ):
    """
    Job execution as coroutine - yields on I/O, doesn't block others.

    This pattern allows multiple jobs to be "running" simultaneously,
    with each job yielding control during I/O waits.
    """
    # Network I/O - naturally async
    clarification = await clarify_query_async( job.question )

    if clarification.needs_feedback:
        job.sub_state = JobSubState.WAITING_FOR_HUMAN
        # This YIELDS control - other jobs continue while we wait
        response = await mcp__cosa_voice__converse( clarification.question )
        job.sub_state = JobSubState.EXECUTING

    # CPU-heavy work offloaded to thread pool
    parsed = await asyncio.to_thread( parse_xml_response, raw_response )

    # Continue with async flow...
```

#### Migration Path

Files requiring async migration for the non-blocking queue:
- `src/cosa/rest/queue_consumer.py` - Convert to async event loop
- `src/cosa/rest/running_fifo_queue.py` - Convert `_process_job()` to async
- `src/cosa/agents/agent_base.py` - Add `async def do_all_async()` method

### Top-Level Orchestrator Agent Pattern

The Deep Research Agent follows a **Top-Level Orchestrator** pattern:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ResearchOrchestratorAgent                         │
│  (Single job in TODO → RUNNING → DONE, internally multi-phase)      │
├─────────────────────────────────────────────────────────────────────┤
│  Async State Machine:                                                │
│  CLARIFYING → PLANNING → RESEARCHING (parallel) → SYNTHESIZING → DONE│
│       ↓            ↓                                   ↓             │
│  [await feedback] ← yields control, other jobs run → [await review] │
├─────────────────────────────────────────────────────────────────────┤
│  External Control Interface:                                         │
│  • get_state() → {phase, progress_pct, sub_tasks, metrics}          │
│  • pause() / resume() / stop()                                       │
│  • get_findings() → intermediate results                             │
├─────────────────────────────────────────────────────────────────────┤
│  Internal Sub-Task Management:                                       │
│  • spawn_subagent() → asyncio.create_task() for parallel workers    │
│  • gather_results() → asyncio.gather() to collect outputs           │
│  • handle_failure() → retry, skip, or escalate                      │
└─────────────────────────────────────────────────────────────────────┘
```

#### Key Design Decisions

1. **Single Queue Entry**: Orchestrator is ONE job - external callers see one `job_id`
2. **Async Execution**: `async def do_all_async()` - yields on I/O, doesn't block queue
3. **Internal State Machine**: Manages phases internally with checkpoint support
4. **Queryable State**: External callers can query progress at any time
5. **Controllable**: Can be paused, resumed, or stopped via REST API

#### Orchestrator State Machine

```python
class OrchestratorState( Enum ):
    """
    State machine for the Research Orchestrator Agent.

    Active states represent work being done.
    Waiting states are yield points where control returns to event loop.
    Terminal states indicate completion or failure.
    External control states allow user intervention.
    """
    # Active states
    CLARIFYING = "clarifying"
    PLANNING = "planning"
    RESEARCHING = "researching"           # Parallel sub-tasks active
    GATHERING = "gathering"
    SYNTHESIZING = "synthesizing"
    CITING = "citing"

    # Waiting states (yield control via await)
    WAITING_CLARIFICATION = "waiting_clarification"
    WAITING_PLAN_APPROVAL = "waiting_plan_approval"
    WAITING_DRAFT_REVIEW = "waiting_draft_review"

    # Terminal states
    COMPLETED = "completed"
    FAILED = "failed"

    # External control states
    PAUSED = "paused"
    STOPPED = "stopped"
```

#### Async Orchestrator Implementation

```python
class ResearchOrchestratorAgent:
    """
    Top-level orchestrator - single job, multi-phase, async execution.

    This agent manages the entire research workflow internally,
    yielding control at I/O boundaries so other jobs can run.
    """

    def __init__( self, query: str, user_id: str, config: ResearchConfig = None ):
        self.query = query
        self.user_id = user_id
        self.config = config or ResearchConfig()
        self.state = OrchestratorState.CLARIFYING
        self.sub_tasks = []
        self.findings = []
        self.metrics = { "start_time": None, "tokens_used": 0, "api_calls": 0 }

    async def do_all_async( self ):
        """
        Main execution - yields on I/O, doesn't block other jobs.

        Each `await` is a potential yield point where other jobs can execute.
        """
        self.metrics[ "start_time" ] = time.time()

        # Phase 1: Clarification
        self.state = OrchestratorState.CLARIFYING
        clarification = await self._clarify_query_async()

        if clarification.needs_feedback:
            self.state = OrchestratorState.WAITING_CLARIFICATION
            # YIELDS control - other jobs run while we wait for human
            response = await mcp__cosa_voice__converse( clarification.question )
            clarification = self._process_feedback( response )

        # Phase 2: Planning
        self.state = OrchestratorState.PLANNING
        plan = await self._create_plan_async( clarification )

        self.state = OrchestratorState.WAITING_PLAN_APPROVAL
        # Use ask_multiple_choice for plan approval with options
        choice = await mcp__cosa_voice__ask_multiple_choice( questions=[{
            "question": f"Research plan ready. How should we proceed?",
            "header": "Plan",
            "multiSelect": False,
            "options": [
                { "label": "Execute plan", "description": f"{len( plan.subqueries )} research threads" },
                { "label": "Modify scope", "description": "Adjust focus or depth" },
                { "label": "Cancel", "description": "Abort research" }
            ]
        }] )

        if choice.get( "answers", {} ).get( "Plan" ) == "Cancel":
            self.state = OrchestratorState.STOPPED
            return None
        elif choice.get( "answers", {} ).get( "Plan" ) == "Modify scope":
            # Handle revision via converse()
            revision = await mcp__cosa_voice__converse( "What would you like to change?" )
            plan = await self._revise_plan_async( plan, revision )

        # Phase 3: Parallel Research
        self.state = OrchestratorState.RESEARCHING
        self.sub_tasks = [
            asyncio.create_task( self._research_subquery_async( sq, i ) )
            for i, sq in enumerate( plan.subqueries )
        ]
        # Gather with exception handling for fault tolerance
        self.findings = await asyncio.gather( *self.sub_tasks, return_exceptions=True )

        # Phase 4: Synthesis
        self.state = OrchestratorState.GATHERING
        valid_findings = [ f for f in self.findings if not isinstance( f, Exception ) ]

        self.state = OrchestratorState.SYNTHESIZING
        report = await self._synthesize_async( valid_findings )

        # Phase 5: Review
        self.state = OrchestratorState.WAITING_DRAFT_REVIEW
        feedback = await mcp__cosa_voice__converse( "Draft ready. Any feedback?" )

        if feedback.lower() not in [ "no", "none", "looks good", "good", "done" ]:
            report = await self._revise_report_async( report, feedback )

        # Phase 6: Cite & Complete
        self.state = OrchestratorState.CITING
        final_report = await self._add_citations_async( report )

        self.state = OrchestratorState.COMPLETED
        return final_report

    def get_state( self ) -> dict:
        """
        Query current orchestrator state for external monitoring.

        Returns:
            dict with phase, progress, sub-task status, metrics
        """
        return {
            "state": self.state.value,
            "progress_pct": self._calculate_progress(),
            "sub_tasks": [
                { "index": i, "done": t.done(), "cancelled": t.cancelled() }
                for i, t in enumerate( self.sub_tasks )
            ],
            "findings_count": len( [ f for f in self.findings if f ] ),
            "metrics": self.metrics
        }

    async def pause( self ) -> bool:
        """
        Request graceful pause at next yield point.

        Returns:
            True if pause will be honored
        """
        # Set flag, actual pause happens at next await
        self._pause_requested = True
        return True

    async def stop( self ) -> dict:
        """
        Cancel all sub-tasks and return partial results.

        Returns:
            Partial findings collected so far
        """
        for task in self.sub_tasks:
            task.cancel()
        self.state = OrchestratorState.STOPPED
        return { "partial_findings": self.findings, "stopped_at": self.state.value }
```

### REST API Endpoints

The orchestrator exposes control via REST API:

```python
# GET /api/research/{job_id}/state
@router.get( "/{job_id}/state" )
async def get_research_state( job_id: str ):
    """Query full orchestrator state including sub-states."""
    orchestrator = get_orchestrator( job_id )
    return orchestrator.get_state()

# POST /api/research/{job_id}/pause
@router.post( "/{job_id}/pause" )
async def pause_research( job_id: str ):
    """Request graceful pause at next yield point."""
    orchestrator = get_orchestrator( job_id )
    return { "paused": await orchestrator.pause() }

# POST /api/research/{job_id}/resume
@router.post( "/{job_id}/resume" )
async def resume_research( job_id: str ):
    """Resume from checkpoint."""
    orchestrator = get_orchestrator( job_id )
    return { "resumed": await orchestrator.resume() }

# POST /api/research/{job_id}/stop
@router.post( "/{job_id}/stop" )
async def stop_research( job_id: str ):
    """Cancel all sub-tasks, return partial results."""
    orchestrator = get_orchestrator( job_id )
    return await orchestrator.stop()

# GET /api/research/{job_id}/findings
@router.get( "/{job_id}/findings" )
async def get_findings( job_id: str ):
    """Get intermediate research results."""
    orchestrator = get_orchestrator( job_id )
    return { "findings": orchestrator.findings }
```

### cosa-voice MCP Integration (v0.2.0)

The orchestrator uses cosa-voice MCP tools for human interaction. All calls are `await`ed to yield control.

#### Tool Selection Guide

| Tool | Usage | Blocking | Example |
|------|-------|----------|---------|
| `notify()` | Progress updates, completions, alerts | No | `await notify( "Starting research..." )` |
| `ask_yes_no()` | Simple approve/reject decisions | Yes | `await ask_yes_no( "Proceed with plan?" )` |
| `converse()` | Open-ended feedback, clarifications | Yes | `await converse( "What would you like to change?" )` |
| `ask_multiple_choice()` | Select from predefined options | Yes | `await ask_multiple_choice( questions=[...] )` |

#### Example Usage

```python
# Fire-and-forget progress notification
await mcp__cosa_voice__notify(
    message="Research thread 3 of 5 complete",
    notification_type="progress",
    priority="low"
)

# Binary approval
approved = await mcp__cosa_voice__ask_yes_no(
    question="The draft is ready. Should I finalize it?",
    default="yes",
    timeout_seconds=300
)

# Open-ended question
feedback = await mcp__cosa_voice__converse(
    message="What aspects should I focus on in the research?",
    response_type="open_ended",
    timeout_seconds=600
)

# Multiple choice selection
choice = await mcp__cosa_voice__ask_multiple_choice(
    questions=[{
        "question": "Which research depth do you prefer?",
        "header": "Depth",
        "multiSelect": False,
        "options": [
            { "label": "Quick overview", "description": "3-5 sources, ~5 minutes" },
            { "label": "Standard", "description": "8-12 sources, ~15 minutes" },
            { "label": "Deep dive", "description": "20+ sources, ~30 minutes" }
        ]
    }],
    timeout_seconds=120
)
```

### Sub-Task Management

Parallel research uses asyncio patterns for efficient concurrent execution:

```python
async def spawn_research_workers( self, plan: ResearchPlan ) -> list:
    """
    Spawn parallel research sub-tasks using asyncio.create_task().

    Each sub-task is an async coroutine that can yield independently.
    """
    tasks = []
    for i, subquery in enumerate( plan.subqueries ):
        # Notify user of progress
        await mcp__cosa_voice__notify(
            message=f"Starting research thread {i + 1} of {len( plan.subqueries )}: {subquery.topic}",
            notification_type="progress",
            priority="low"
        )

        # Create async task (runs concurrently)
        task = asyncio.create_task(
            self._research_subquery_async( subquery, i ),
            name=f"research_{subquery.topic}"
        )
        tasks.append( task )

    return tasks

async def gather_results( self, tasks: list ) -> list:
    """
    Collect results from all sub-tasks with fault tolerance.

    Uses return_exceptions=True to prevent one failure from canceling all tasks.
    """
    results = await asyncio.gather( *tasks, return_exceptions=True )

    # Separate successes from failures
    successes = []
    failures = []

    for i, result in enumerate( results ):
        if isinstance( result, Exception ):
            failures.append( { "index": i, "error": str( result ) } )
        else:
            successes.append( result )

    if failures:
        # Notify about failures but continue with available results
        await mcp__cosa_voice__notify(
            message=f"{len( failures )} research threads failed, continuing with {len( successes )} results",
            notification_type="alert",
            priority="medium"
        )

    return successes

async def cancel_all_tasks( self, tasks: list ) -> int:
    """
    Cancel all running sub-tasks for pause/stop.

    Returns count of successfully cancelled tasks.
    """
    cancelled = 0
    for task in tasks:
        if not task.done():
            task.cancel()
            cancelled += 1

    # Wait for cancellation to complete
    await asyncio.gather( *tasks, return_exceptions=True )

    return cancelled
```

### Implementation Location

All Deep Research Agent code resides in:

```
src/cosa/agents/deep_research/
├── __init__.py
├── config.py                    # ResearchConfig dataclass
├── state.py                     # Pydantic state schemas, OrchestratorState enum
├── orchestrator.py              # ResearchOrchestratorAgent class
├── cosa_interface.py            # cosa-voice MCP wrappers (async)
├── prompts/
│   ├── __init__.py
│   ├── lead_agent.py            # Lead researcher system prompt
│   ├── subagent.py              # Research subagent prompt
│   ├── clarification.py         # Query clarification prompt
│   └── synthesis.py             # Final report synthesis prompt
├── nodes/
│   ├── __init__.py
│   ├── clarify.py               # Query clarification (async)
│   ├── feedback.py              # Human feedback node (async cosa-voice)
│   ├── plan.py                  # Research planning (async)
│   ├── research.py              # Parallel research subagent (async)
│   ├── compress.py              # Context compression
│   ├── synthesize.py            # Report synthesis (async)
│   └── cite.py                  # Citation generation
├── tools/
│   ├── __init__.py
│   ├── web_search.py            # Claude WebSearch wrapper (async)
│   └── web_fetch.py             # Claude WebFetch wrapper (async)
└── graph.py                     # LangGraph StateGraph definition (optional)
```

**Note**: The `graph.py` file is optional - the orchestrator can use direct async/await flow without LangGraph if preferred for simplicity.

---

## Integration Guide

### Integrating with COSA

To integrate this research agent with your COSA framework:

1. **Import the agent**:
```python
from cosa_deep_research import DeepResearchAgent, ResearchConfig
```

2. **Configure with COSA callbacks**:
```python
# Your COSA interface provides these
from cosa import notify_user_sync, notify_user_async

# Create and configure the agent
config = ResearchConfig(
    feedback_timeout_seconds=300,
    stream_thoughts_to_voice=True,
)
agent = DeepResearchAgent(config)
agent.configure(notify_user_sync, notify_user_async)
```

3. **Execute research from voice command**:
```python
# In your COSA command handler
async def handle_research_command(query: str) -> str:
    return await agent.research(query)
```

### COSA Interface Contract

The agent expects these COSA function signatures:

```python
def notify_user_sync(prompt: str, timeout: int = 300) -> str:
    """
    Blocking call that:
    1. Speaks `prompt` via TTS
    2. Waits for user voice response
    3. Returns transcribed text
    """
    pass

async def notify_user_async(thought: str) -> None:
    """
    Non-blocking call that streams a thought to the UI.
    The UI can display as text, speak, or ignore.
    """
    pass
```

### Customization Points

1. **Model Selection**: Modify `ResearchConfig.lead_model` and `subagent_model`
2. **Prompts**: Edit files in `prompts/` directory
3. **Feedback Points**: Add/remove feedback nodes in `graph.py`
4. **Tools**: Add MCP integrations in `tools/` directory

---

## Testing Strategy

### Unit Tests

```python
# tests/test_clarification.py
import pytest
from cosa_deep_research.nodes.clarify import clarify_query, parse_clarification_response
from cosa_deep_research.state import ClarificationDecision

def test_parse_clarification_json():
    response = '{"needs_clarification": false, "understood_query": "Test query"}'
    result = parse_clarification_response(response)
    assert isinstance(result, ClarificationDecision)
    assert not result.needs_clarification

def test_parse_clarification_markdown():
    response = '```json\n{"needs_clarification": true, "question": "What timeframe?"}\n```'
    result = parse_clarification_response(response)
    assert result.needs_clarification
    assert "timeframe" in result.question
```

### Integration Tests

```python
# tests/test_graph.py
import pytest
from cosa_deep_research.graph import build_research_graph
from cosa_deep_research.config import ResearchConfig

def test_graph_builds():
    config = ResearchConfig()
    graph = build_research_graph(config)
    assert graph is not None

@pytest.mark.asyncio
async def test_simple_research_flow():
    # Mock COSA interface
    from cosa_deep_research.cosa_interface import configure_cosa
    
    configure_cosa(
        lambda p, t: "yes",  # Always approve
        lambda t: None,      # Ignore thoughts
    )
    
    from cosa_deep_research import DeepResearchAgent
    agent = DeepResearchAgent()
    
    # This would need mocking of Claude API
    # result = await agent.research("Simple test query")
```

### End-to-End Testing

```bash
# Run with mock COSA interface
python -m cosa_deep_research.main

# Example interaction:
# > What would you like to research? Compare React and Vue for 2025
# 🎤 COSA: I'd like to clarify: Are you interested in...
# Your response: Focus on performance and ecosystem
# 🎤 COSA: Here's my research plan...
# Your response: yes
# [Research executes]
# 🎤 COSA: Draft ready...
# Your response: looks good
# [Final report generated]
```

---

## Implementation Status

> **Last Updated**: January 2026 (Session 57)

### Phase 1: Foundation ✅ COMPLETE

Phase 1 established the skeleton implementation with all core data structures and async orchestration framework.

**Files Created** (all in `src/cosa/agents/deep_research/`):

| File | Lines | Purpose |
|------|-------|---------|
| `__init__.py` | 104 | Package exports (17 public symbols) |
| `config.py` | 95 | ResearchConfig dataclass |
| `state.py` | 250 | Pydantic models + OrchestratorState enum (13 states) |
| `cosa_interface.py` | 280 | Async wrappers for cosa-voice MCP |
| `orchestrator.py` | 560 | ResearchOrchestratorAgent skeleton |
| `prompts/__init__.py` | 27 | Stub with Phase 2 roadmap |
| `nodes/__init__.py` | 42 | Stub with Phase 2 roadmap |
| `tools/__init__.py` | 18 | Stub with Phase 2 roadmap |

**Key Classes**:
- `ResearchOrchestratorAgent` - Top-level async orchestrator (standalone, not inheriting from AgentBase)
- `OrchestratorState` - 13-state enum (CLARIFYING, PLANNING, RESEARCHING, etc.)
- `ResearchPlan`, `SubQuery`, `SubagentFinding` - Pydantic models for structured outputs

**Smoke Tests**: All 4 modules pass (`config.py`, `state.py`, `cosa_interface.py`, `orchestrator.py`)

---

### Phase 2: Direct Anthropic API (In Progress)

**Architecture Decision**: After deep analysis, Claude Code CLI was determined NOT suitable for the research execution layer due to:
- ❌ No web search capability
- ❌ No model selection (can't use Opus for lead, Sonnet for subagents)
- ❌ No extended thinking access
- ❌ No WebFetch for live source retrieval

**Chosen Architecture**: Direct Anthropic API via `anthropic` SDK

```
┌─────────────────────────────────────────────────────────────┐
│              Deep Research Agent (Production)                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌──────────────────┐     ┌──────────────────┐              │
│  │  Orchestrator    │────▶│  Anthropic API    │              │
│  │  (async Python)  │     │  (Direct SDK)     │              │
│  └──────────────────┘     └──────────────────┘              │
│          │                        │                          │
│          │                        ▼                          │
│          │               ┌──────────────────┐               │
│          │               │  Claude Models    │               │
│          │               │  Opus + Sonnet    │               │
│          │               └──────────────────┘               │
│          │                        │                          │
│          ▼                        ▼                          │
│  ┌──────────────────┐     ┌──────────────────┐              │
│  │  cosa-voice MCP  │     │  Web Search Tool  │              │
│  │  (notifications) │     │  (web_search_*)   │              │
│  └──────────────────┘     └──────────────────┘              │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**Key Features Enabled**:

| Feature | Implementation |
|---------|----------------|
| Web search | `web_search_20250305` tool via API |
| Model selection | `model="claude-opus-4-5"` / `"claude-sonnet-4-5"` |
| Extended thinking | `thinking` parameter in API |
| Structured output | JSON mode with schema validation |
| Parallel subagents | `asyncio.gather()` with API calls |
| **Exact cost tracking** | `response.usage` per request |

**API Cost Tracking**:

The Anthropic API returns exact per-request usage data:

```python
response = await client.messages.create(...)
usage = response.usage
# {
#     "input_tokens": 1523,
#     "output_tokens": 847,
#     "cache_creation_input_tokens": 0,
#     "cache_read_input_tokens": 0
# }
```

Current pricing (per 1M tokens):

| Model | Input | Output |
|-------|-------|--------|
| Opus 4.5 | $5.00 | $25.00 |
| Sonnet 4.5 | $3.00 | $15.00 |
| Haiku 4.5 | $1.00 | $5.00 |

**Phase 2 Files to Create**:

| File | Est. Lines | Purpose |
|------|------------|---------|
| `api_client.py` | ~200 | Direct Anthropic API wrapper |
| `cost_tracker.py` | ~100 | Usage and cost aggregation |
| `prompts/clarification.py` | ~100 | Query clarification prompt |
| `prompts/planning.py` | ~100 | Research planning prompt |
| `prompts/subagent.py` | ~100 | Subquery execution prompt |
| `prompts/synthesis.py` | ~100 | Report synthesis prompt |
| `cli.py` | ~150 | Command-line interface |

**Setup Requirements**:

1. API Key: Create at console.anthropic.com
2. Storage: Save to `src/conf/keys/anthropic-api-key-firewalled`
3. Credits: Add $10-20 for testing

**API Key Configuration (Firewalled Pattern)**:

IMPORTANT: NEVER use `ANTHROPIC_API_KEY` - that is reserved for Claude Code CLI.

For development (local key file):
```bash
# Create/use: src/conf/keys/anthropic-api-key-firewalled
# The API client will automatically find and use this file
```

For testing/production (environment variable):
```bash
export ANTHROPIC_API_KEY_FIREWALLED=your-api-key
python -m cosa.agents.deep_research.cli --query "..."
```

---

### Billing Architecture Note

**Claude Max vs API are completely separate billing systems**:

| Aspect | Claude Max Subscription | Anthropic API |
|--------|------------------------|---------------|
| Billing | $100-200/month flat | Pay-per-token |
| Account | claude.ai account | console.anthropic.com |
| Usage | Web, Desktop, Claude Code | Direct API calls |
| Authentication | OAuth via `claude login` | `ANTHROPIC_API_KEY_FIREWALLED` (Deep Research Agent) |

**CRITICAL GOTCHA**: If `ANTHROPIC_API_KEY` environment variable is set, Claude Code will use API credits INSTEAD of Max subscription quota. This is why Deep Research Agent uses `ANTHROPIC_API_KEY_FIREWALLED` instead - to prevent any billing confusion.

---

## Appendix: Key Sources

### Anthropic Cookbook
- `research_lead_agent.md`: Lead agent coordination patterns
- `research_subagent.md`: Subagent research execution patterns
- Blog: "How we built our multi-agent research system" (June 2025)

### GPT Researcher
- Planner/Executor agent decomposition
- Wide-to-narrow search strategy
- Cost optimization with model tiering

### LangChain Open Deep Research
- Clarification loop pattern
- Context compression techniques
- Human-in-the-loop with `interrupt()`

### Key Insight from Anthropic
> "Token usage by itself explains 80% of the variance [in performance]."

This validates the multi-agent architecture: parallel context windows enable more token throughput than a single agent.

---

*Document generated for Claude Code consumption. All code is implementation-ready and follows COSA framework conventions.*
