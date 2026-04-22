# Autonomous Multi-Agent Engineering Teams with Claude + Lupin

> **Revised 2026-02-13** — Updated to integrate with the existing Lupin notification system (SSE blocking, WebSocket delivery, Notification Proxy, cosa_interface pattern). Generic notification infrastructure replaced with Lupin-native integration points.

---

## 1. Executive Summary

The Claude Agent SDK (v0.1.35, February 2026) provides subagent spawning, inter-agent messaging, context compaction, and MCP-based tooling — but orchestration, human-in-the-loop routing, and trust management are your responsibility. The Lupin notification system already solves the hardest part: bidirectional human-agent communication with SSE blocking, priority-aware delivery, voice-first UX, offline detection, and a 3-tier auto-responder proxy. The architecture presented here wires the Agent SDK's primitives into Lupin's existing `cosa_interface` pattern, extends the Notification Proxy into a graduated-trust decision proxy, and defines the agent team topology.

**Key architectural insight**: The existing Notification Proxy (`listener.py` + `responder.py` + strategy chain) is the embryonic form of the off-hours AI stand-in. Evolution path: expand its strategy chain from "answer expediter questions" to "make provisional engineering decisions," add per-category trust tracking with ratification feedback, and implement circuit breaker demotion.

---

## 2. Claude Agent SDK: What It Gives You

Anthropic maintains two complementary Python packages:

**`claude-agent-sdk`** (v0.1.35, alpha) — wraps the Claude Code CLI as a subprocess, exposing an async Python API. Key primitives:

- **`AgentDefinition`** — declare named subagents with restricted tools and specialized system prompts, each running in an isolated context window
- **`query()`** — one-shot task execution; **`ClaudeSDKClient`** — interactive sessions
- **Built-in tools**: Read, Write, Edit, Bash, Grep, Glob, Task (delegation)
- **Hooks**: `PreToolUse`, `PostToolUse`, `Notification`, `SubagentStart` — lifecycle interception points where you wire into Lupin
- **Context compaction** — automatic summarization when context approaches limits
- **MCP servers** — in-process custom tools via `@tool` decorator

**`anthropic` SDK** (v0.79.0) — direct Messages API with manual agent loop construction. Full control, more boilerplate. Tool use, advanced tool search, and programmatic tool calling all in beta since November 2025.

**Agent Teams** (experimental, Opus 4.6, February 5 2026) — enables direct inter-agent messaging via `Teammate` tool and shared `TaskList`/`TaskUpdate` tools. Known issues with session resumption. Enable with `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`.

### Subagent Declaration Pattern

```python
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition

async for msg in query(
    prompt="Implement the auth module with full test coverage",
    options=ClaudeAgentOptions(
        allowed_tools=["Read", "Edit", "Bash", "Task"],
        agents={
            "coder": AgentDefinition(
                description="Implements features incrementally, one at a time",
                allowed_tools=["Read", "Edit", "Bash"],
                system_prompt="You are a backend engineer. Write clean, tested code..."
            ),
            "tester": AgentDefinition(
                description="Writes smoke, unit, and integration tests",
                allowed_tools=["Read", "Edit", "Bash"],
                system_prompt="You are a QA engineer. Write comprehensive tests..."
            ),
        }
    )
): print(msg)
```

Each subagent runs in its own context window — the primary architectural advantage. The lead agent delegates via the built-in `Task` tool; Claude routes based on each subagent's `description` field.

### Custom MCP Tools (In-Process)

```python
from claude_agent_sdk import tool, create_sdk_mcp_server

@tool("run_tests", "Execute pytest suite and return results", {"path": str, "markers": str})
async def run_tests(args):
    result = subprocess.run(
        ["pytest", args["path"], "-m", args.get("markers", ""), "-v", "--tb=short"],
        capture_output=True, timeout=300
    )
    return {"content": [{"type": "text", "text": result.stdout.decode()[-4000:]}]}

server = create_sdk_mcp_server(name="dev-tools", version="1.0", tools=[run_tests])
```

---

## 3. Agent Team Topology

### 3.1 Role Taxonomy

The orchestrator-worker pattern — a lead agent decomposes tasks and delegates to specialized subagents — is what Anthropic uses internally, what Agent Teams implements, and what MetaGPT and ChatDev converge on from the research side. Six roles, minimum viable set:

| Role | System Prompt Focus | SDK Tools | Model Tier | Lupin `agent_type` |
|------|-------------------|-----------|------------|-------------------|
| **Lead / PM** | Task decomposition, delegation with detailed instructions, progress tracking, conflict resolution | Read, Glob, Task | Opus 4.6 (extended thinking) | `agent.lead` |
| **Architect** | System design, API specs, data modeling, tech stack decisions | Read, Grep, Glob, Write | Opus 4.6 | `agent.architect` |
| **Coder** | Implement one feature at a time, clean commits, update progress | Read, Edit, Bash, Git | Sonnet 4.5 | `agent.coder` |
| **Reviewer** | Code quality, security audit, SOLID principles, bug detection | Read, Grep, Glob | Sonnet 4.5 | `agent.reviewer` |
| **Tester** | Write tests, run test suites, verify fixes, coverage analysis | Read, Edit, Bash | Sonnet 4.5 | `agent.tester` |
| **Debugger** | Diagnose failures, trace errors, propose minimal fixes | Read, Grep, Bash | Sonnet 4.5 | `agent.debugger` |

**Model tiering rationale** — Opus for planning, Sonnet for execution. The lead agent's extended thinking mode dramatically improves delegation quality. Sonnet handles routine coding at roughly one-fifth the cost.

### 3.2 Communication Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         LUPIN SERVER :7999                       │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌────────────────────────┐ │
│  │ FIFO Queue   │  │ PostgreSQL   │  │ WebSocket Manager      │ │
│  │ (priority)   │  │ (persistent) │  │ (real-time delivery)   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────────┬─────────────┘ │
│         └─────────────────┼─────────────────────┘               │
│                           │                                      │
│                    POST /api/notify                               │
│                    (SSE for blocking)                             │
└───────────────────────────┬──────────────────────────────────────┘
                            │
            ┌───────────────┼───────────────┐
            │               │               │
     ┌──────┴──────┐ ┌─────┴─────┐  ┌──────┴──────┐
     │  Human      │ │ Notif.    │  │ Agent Team  │
     │  Operator   │ │ Proxy     │  │ Orchestrator│
     │  (browser)  │ │ (off-hrs) │  │             │
     └─────────────┘ └───────────┘  └──────┬──────┘
                                           │
                              ┌─────────────┼─────────────┐
                              │             │             │
                        ┌─────┴─────┐ ┌────┴────┐ ┌─────┴─────┐
                        │  Coder    │ │ Tester  │ │ Reviewer  │
                        │  subagent │ │ subagent│ │ subagent  │
                        └───────────┘ └─────────┘ └───────────┘
```

Communication flows through the orchestrator, not peer-to-peer. Anthropic's own findings: "LLM agents are not yet great at coordinating and delegating to other agents in real time." The orchestrator-worker pattern provides traceability, prevents conflicts from concurrent file edits, and enables clean human-in-the-loop integration via Lupin's existing notification channels.

### 3.3 State Management Across Sessions

Three artifacts survive context window resets:

1. **`feature_list.json`** — structured task tracking with pass/fail status per feature
2. **`claude-progress.txt`** — running log of completed work, decisions made, blockers encountered  
3. **Git commits with descriptive messages** — enabling revert on failure

When a new session starts, the agent reads these three artifacts to reconstruct context without requiring the full conversation history.

**Critical delegation rule**: Every task from lead to subagent must include: objective, expected output format, tool usage guidance, explicit scope boundaries. Without this, agents duplicate work, leave gaps, or fail to find necessary information.

---

## 4. Wiring Agents into Lupin's Notification System

### 4.1 Registering New Agent Types

Extend Lupin's known agent types table with the team roles:

| Agent Type | `sender_id` Format | Description |
|---|---|---|
| `agent.lead` | `agent.lead@{project}.deepily.ai#{session_id}` | Orchestrator / PM agent |
| `agent.architect` | `agent.architect@{project}.deepily.ai#{session_id}` | System design agent |
| `agent.coder` | `agent.coder@{project}.deepily.ai#{session_id}` | Implementation agent |
| `agent.reviewer` | `agent.reviewer@{project}.deepily.ai#{session_id}` | Code review agent |
| `agent.tester` | `agent.tester@{project}.deepily.ai#{session_id}` | Test writing/execution agent |
| `agent.debugger` | `agent.debugger@{project}.deepily.ai#{session_id}` | Diagnostic agent |
| `agent.proxy` | `agent.proxy@{project}.deepily.ai` | Off-hours decision proxy |

All conform to the existing `sender_id` regex: `^[a-z]+(\.[a-z]+)+@[a-z]+\.deepily\.ai(#...)?$`

### 4.2 The cosa_interface Pattern for Agent Teams

Each agent role gets a `cosa_interface` module following the established Tier 2 pattern. The orchestrator uses `asyncio.to_thread()` to wrap blocking CLI calls, exactly as Deep Research and Claude Code jobs already do.

```python
# src/cosa/agents/agent_team/cosa_interface.py
"""
Tier 2 cosa_interface for the agent team orchestrator.
Wraps notify_user_sync/async with agent-team-specific defaults.
"""
import asyncio
from cosa.cli.notify_user_async import notify_user_async
from cosa.cli.notify_user_sync import notify_user_sync
from cosa.cli.notification_models import (
    AsyncNotificationRequest, NotificationRequest,
    NotificationType, NotificationPriority, ResponseType
)

DEFAULT_PROJECT = "lupin"
DEFAULT_TARGET  = "ricardo.felipe.ruiz@gmail.com"


def _sender_id(role: str, session_id: str = None) -> str:
    base = f"agent.{role}@{DEFAULT_PROJECT}.deepily.ai"
    return f"{base}#{session_id}" if session_id else base


async def notify_progress(
    message: str,
    role: str = "lead",
    priority: str = "medium",
    abstract: str = None,
    session_id: str = None,
    job_id: str = None,
    queue_name: str = None,
):
    """Fire-and-forget status update from any agent role."""
    request = AsyncNotificationRequest(
        message           = message,
        notification_type = NotificationType.PROGRESS,
        priority          = NotificationPriority(priority),
        target_user       = DEFAULT_TARGET,
        sender_id         = _sender_id(role, session_id),
        abstract          = abstract,
        job_id            = job_id,
        queue_name        = queue_name,
    )
    await asyncio.to_thread(notify_user_async, request)


async def ask_confirmation(
    question: str,
    role: str = "lead",
    default: str = "no",
    timeout: int = 120,
    abstract: str = None,
    session_id: str = None,
    job_id: str = None,
) -> bool:
    """Blocking yes/no — routes through SmartRouter for availability."""
    request = NotificationRequest(
        message           = question,
        response_type     = ResponseType.YES_NO,
        notification_type = NotificationType.CUSTOM,
        priority          = NotificationPriority.HIGH,
        timeout_seconds   = timeout,
        response_default  = default,
        target_user       = DEFAULT_TARGET,
        sender_id         = _sender_id(role, session_id),
        abstract          = abstract,
        job_id            = job_id,
    )
    response = await asyncio.to_thread(notify_user_sync, request)
    return response.response_value and response.response_value.startswith("yes")


async def request_decision(
    question: str,
    options: list[dict],
    role: str = "lead",
    default: str = None,
    timeout: int = 300,
    abstract: str = None,
    session_id: str = None,
) -> dict:
    """Blocking multiple-choice — for architectural/design decisions."""
    import json
    request = NotificationRequest(
        message           = question,
        response_type     = ResponseType.MULTIPLE_CHOICE,
        notification_type = NotificationType.CUSTOM,
        priority          = NotificationPriority.HIGH,
        timeout_seconds   = timeout,
        response_default  = default,
        target_user       = DEFAULT_TARGET,
        sender_id         = _sender_id(role, session_id),
        abstract          = abstract,
        response_options  = {"questions": [{"question": question, "options": options}]},
    )
    response = await asyncio.to_thread(notify_user_sync, request)
    return {"choice": response.response_value, "default_used": response.default_used}
```

### 4.3 Hooking the Agent SDK into Lupin Notifications

The SDK's `Notification` hook is where every subagent's activity gets piped to Lupin. The `PreToolUse` hook gates dangerous operations through the blocking notification path:

```python
from claude_agent_sdk import ClaudeAgentOptions, AgentDefinition
import cosa.agents.agent_team.cosa_interface as team_io

DANGEROUS_COMMANDS = {"rm ", "git push", "docker rm", "DROP TABLE", "DELETE FROM"}

async def notification_hook(event):
    """Pipe all SDK notifications to Lupin as fire-and-forget."""
    await team_io.notify_progress(
        message    = event.message,
        role       = event.agent_name or "lead",
        priority   = "low",
        session_id = SESSION_ID,
    )

async def pre_tool_hook(event):
    """Gate dangerous operations through human/proxy approval."""
    if event.tool_name == "Bash":
        cmd = event.tool_input.get("command", "")
        if any(d in cmd for d in DANGEROUS_COMMANDS):
            approved = await team_io.ask_confirmation(
                question = f"Agent '{event.agent_name}' wants to run: `{cmd[:200]}`",
                role     = event.agent_name or "lead",
                default  = "no",
                timeout  = 300,
                abstract = f"**Tool**: {event.tool_name}\n**Full command**: `{cmd}`",
                session_id = SESSION_ID,
            )
            if not approved:
                return {"blocked": True, "reason": "Human/proxy denied execution"}
    return None  # allow

options = ClaudeAgentOptions(
    allowed_tools=["Read", "Edit", "Bash", "Task"],
    hooks={
        "Notification": notification_hook,
        "PreToolUse":   pre_tool_hook,
    },
    agents={...}  # agent definitions from Section 3.1
)
```

### 4.4 Notification Flow by Agent Action Type

| Agent Action | Lupin Integration | Notification Type | Blocking? |
|---|---|---|---|
| Task started | `notify_progress(role="coder", priority="low")` | `progress` | No |
| Test results | `notify_progress(role="tester", abstract=pytest_output)` | `task` | No |
| Review findings | `notify_progress(role="reviewer", priority="medium", abstract=findings)` | `alert` | No |
| Dangerous command | `ask_confirmation(role="coder", default="no")` | `custom` | **Yes** — SSE blocks |
| Architectural decision | `request_decision(role="architect", options=[...])` | `custom` | **Yes** — SSE blocks |
| Task complete | `notify_progress(role="lead", priority="medium")` | `task` | No |
| Build failure | `notify_progress(role="lead", priority="urgent")` | `alert` | No |
| All tests passing | `notify_progress(role="lead", priority="high")` | `task` | No |

---

## 5. Evolving the Notification Proxy into a Decision Stand-In

### 5.1 What Already Exists

The Notification Proxy (`src/cosa/agents/notification_proxy/`) is a WebSocket client with a 3-tier strategy chain: Phi-4 script matcher → keyword rules → Claude Sonnet fallback. It currently answers Runtime Argument Expediter prompts for automated testing. The infrastructure is already production-ready:

- **`listener.py`**: WebSocket connection with auth, keep-alive, reconnection (exponential backoff, 10 attempts)
- **`responder.py`**: Strategy routing with stats tracking, response submission via `POST /api/notify/response`
- **`config.py`**: Profile system, credential resolution, constants
- **Strategy interface**: `can_handle(notification) → bool`, `respond(notification) → str | None`

### 5.2 Evolution: From Test Automation to Decision Proxy

The proxy needs three new capabilities: (a) handling engineering decisions (not just expediter questions), (b) trust-level-aware authority, and (c) learning from ratification history.

**New strategy tier: Engineering Decision Strategy**

```python
# src/cosa/agents/notification_proxy/strategies/engineering_decisions.py
"""
Tier 0 (highest priority): Engineering decision strategy for agent team notifications.
Routes through trust tracker before responding.
"""
from cosa.agents.notification_proxy.strategies.base import BaseStrategy

# Agent team sender IDs (not expediter)
AGENT_TEAM_SENDERS = {
    "agent.lead", "agent.architect", "agent.coder",
    "agent.reviewer", "agent.tester", "agent.debugger"
}


class EngineeringDecisionStrategy(BaseStrategy):

    def __init__(self, trust_tracker, decision_store, anthropic_key=None, debug=False):
        self.trust      = trust_tracker
        self.store      = decision_store  # PostgreSQL-backed decision history
        self.llm_key    = anthropic_key
        self.debug      = debug

    def can_handle(self, notification: dict) -> bool:
        sender = notification.get("sender_id", "")
        agent_type = sender.split("@")[0] if "@" in sender else ""
        return (
            agent_type in AGENT_TEAM_SENDERS
            and notification.get("response_requested")
        )

    def respond(self, notification: dict) -> dict | None:
        category = self._classify_decision(notification)
        trust_level = self.trust.level_for(category)

        # L1 (observe): predict but don't act — log shadow decision
        if trust_level == 1:
            prediction = self._generate_decision(notification, category)
            self.store.log_shadow(notification, prediction, category)
            return None  # falls through to skip → human gets it in morning

        # L2+ : generate decision with confidence
        decision = self._generate_decision(notification, category)

        if trust_level == 2:
            # Suggest mode: queue as provisional, human ratifies
            decision["authority"] = "provisional"
        elif trust_level >= 3:
            # Act mode: commit the decision
            decision["authority"] = "committed"

        self.store.log_decision(notification, decision, category, trust_level)
        return decision["choice"]

    def _classify_decision(self, notification: dict) -> str:
        """Classify into decision domains for per-category trust tracking."""
        msg = notification.get("message", "").lower()
        if any(w in msg for w in ["deploy", "push", "merge", "release"]):
            return "deployment"
        if any(w in msg for w in ["test", "coverage", "pytest"]):
            return "testing"
        if any(w in msg for w in ["dependency", "package", "upgrade", "version"]):
            return "dependencies"
        if any(w in msg for w in ["design", "architecture", "schema", "api"]):
            return "architecture"
        if any(w in msg for w in ["rm ", "delete", "drop", "destroy"]):
            return "destructive"
        return "general"

    def _generate_decision(self, notification: dict, category: str) -> dict:
        """Generate a decision using past ratification history + Claude."""
        # Check for similar past decisions first
        similar = self.store.find_similar(notification["message"], category, limit=10)
        human_pattern = self._extract_pattern(similar)

        if human_pattern and human_pattern["confidence"] > 0.85:
            return {
                "choice":     human_pattern["most_common"],
                "confidence": human_pattern["confidence"],
                "reasoning":  f"Based on {len(similar)} similar past decisions",
                "source":     "pattern_match",
            }

        # Fall back to Claude Sonnet with context
        return self._llm_decide(notification, category, similar)

    def _extract_pattern(self, similar_decisions: list) -> dict | None:
        if len(similar_decisions) < 5:
            return None
        from collections import Counter
        choices = Counter(d["human_decision"] for d in similar_decisions if d.get("human_decision"))
        if not choices:
            return None
        most_common, count = choices.most_common(1)[0]
        return {
            "most_common": most_common,
            "confidence":  count / len(similar_decisions),
        }

    def _llm_decide(self, notification, category, similar) -> dict:
        """Claude Sonnet decision with past ratification context."""
        import anthropic
        client = anthropic.Anthropic(api_key=self.llm_key)

        history_context = "\n".join(
            f"- Q: {d['question'][:100]} → Human chose: {d['human_decision']}"
            for d in similar[:5]
        ) or "No prior decisions in this category."

        resp = client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=300,
            messages=[{"role": "user", "content": f"""You are a proxy decision-maker for a software engineer.
An AI agent is asking for a decision. Based on the engineer's past decisions in this category, choose the best option.

CATEGORY: {category}
QUESTION: {notification['message']}
OPTIONS: {notification.get('response_options', 'yes/no')}
PAST DECISIONS IN THIS CATEGORY:
{history_context}

Respond with ONLY your choice (e.g., "yes", "no", or the option label). Then a newline and a confidence score 0.0-1.0."""}]
        )
        text = resp.content[0].text.strip()
        lines = text.split("\n")
        return {
            "choice":     lines[0].strip(),
            "confidence": float(lines[1]) if len(lines) > 1 else 0.5,
            "reasoning":  f"LLM decision for {category}",
            "source":     "llm_fallback",
        }
```

### 5.3 Updated Strategy Chain

The proxy's strategy chain becomes:

```
                    ┌──────────────────────────┐
                    │  notification received    │
                    └────────────┬─────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │ Tier 0: Engineering      │  NEW — handles agent team decisions
                    │ Decision Strategy        │  with trust-level gating
                    │ (agent.* senders)        │
                    └────────────┬─────────────┘
                          can_handle?
                         /          \
                       yes           no
                        │             │
                  ┌─────▼────┐  ┌────▼──────────────┐
                  │ Trust    │  │ Tier 1: Phi-4     │  EXISTING — expediter scripts
                  │ gated    │  │ Script Matcher    │
                  │ response │  └────────┬──────────┘
                  └──────────┘       can_handle?
                                    /          \
                                  yes           no
                                   │             │
                             ┌─────▼────┐  ┌────▼──────────────┐
                             │ scripted │  │ Tier 2: Keyword   │  EXISTING
                             │ answer   │  │ Rules             │
                             └──────────┘  └────────┬──────────┘
                                                can_handle?
                                               /          \
                                             yes           no
                                              │             │
                                        ┌─────▼────┐  ┌────▼──────────────┐
                                        │ profile  │  │ Tier 3: Claude    │  EXISTING
                                        │ answer   │  │ Sonnet Fallback   │
                                        └──────────┘  └───────────────────┘
```

### 5.4 Availability-Aware Routing via SmartRouter

The SmartRouter sits between the agent team's `cosa_interface` and Lupin's `POST /api/notify`. It checks human availability before deciding whether to route to the live operator or the proxy.

**Key insight**: Lupin already detects offline users (returns 503 or immediate default). The SmartRouter wraps this by pre-checking availability and redirecting to the proxy when the human is offline *or* outside working hours.

```python
# src/cosa/agents/agent_team/smart_router.py
"""
Availability-aware router: directs blocking notifications to
human (when available) or proxy (off-hours / offline).
"""
from datetime import datetime, time
from zoneinfo import ZoneInfo

SCHEDULE = {
    "tz":       "America/New_York",
    "start":    8,   # 8 AM
    "end":      18,  # 6 PM
    "workdays": {0, 1, 2, 3, 4},  # Mon-Fri
}


def human_available(ws_connection_count: int) -> bool:
    """Check schedule + WebSocket connectivity."""
    if ws_connection_count == 0:
        return False
    now = datetime.now(ZoneInfo(SCHEDULE["tz"]))
    return (
        now.weekday() in SCHEDULE["workdays"]
        and time(SCHEDULE["start"]) <= now.time() <= time(SCHEDULE["end"])
    )
```

The routing logic itself is minimal because Lupin's existing offline handling does the heavy lifting. When `response_default` is set and the user is offline, Lupin returns the default immediately. The SmartRouter's job is to ensure that off-hours decisions flow to the proxy via the existing WebSocket listener, and that the proxy's decisions are logged for morning ratification:

```python
# In the orchestrator's main loop:
async def route_blocking_decision(question, options, role, category, session_id):
    """Route through Lupin — proxy auto-handles if human unavailable."""

    # Lupin's offline detection handles the routing:
    # - Human online → SSE blocks until response
    # - Human offline + default set → immediate default return
    # - Human offline + no default → 503 → proxy's WebSocket listener picks it up

    response = await team_io.ask_confirmation(
        question   = question,
        role       = role,
        default    = "defer",  # safe default if completely unreachable
        timeout    = 300,
        abstract   = f"**Category**: {category}\n**Options**: {', '.join(options)}",
        session_id = session_id,
    )
    return response
```

### 5.5 Morning Ratification Endpoint

Add a REST endpoint for reviewing provisional proxy decisions:

```python
# src/cosa/rest/routers/proxy_decisions.py
from fastapi import APIRouter, Depends
from cosa.rest.middleware.api_key_auth import require_api_key_or_jwt

router = APIRouter(prefix="/api/proxy", tags=["proxy-decisions"])


@router.get("/pending/{user_email}")
async def get_pending_decisions(user_email: str, auth=Depends(require_api_key_or_jwt)):
    """Morning review: all provisional decisions awaiting ratification."""
    decisions = await decision_store.get_pending(user_email)
    return {
        "count":     len(decisions),
        "decisions": [
            {
                "id":              d["id"],
                "category":        d["category"],
                "question":        d["question"],
                "proxy_choice":    d["proxy_decision"],
                "confidence":      d["confidence"],
                "reasoning":       d["reasoning"],
                "agent_role":      d["agent_role"],
                "created_at":      d["created_at"],
                "similar_history": d.get("similar_count", 0),
            }
            for d in decisions
        ],
    }


@router.post("/ratify/{decision_id}")
async def ratify_decision(
    decision_id: str,
    approved: bool,
    override: str = None,
    auth=Depends(require_api_key_or_jwt),
):
    """Ratify or override a proxy decision. Feeds trust tracker."""
    record = await decision_store.ratify(decision_id, approved, override)
    trust_tracker.learn(record)  # updates per-category accuracy
    return {"status": "ratified", "final_decision": record["human_decision"]}
```

---

## 6. Graduated Trust: From Shadow to Autonomous

### 6.1 Five Trust Levels

| Level | Authority | Trigger to Advance |
|---|---|---|
| **L1: Observe** | Shadow mode — proxy predicts but doesn't act, logs shadow decisions | Deployment (initial state) |
| **L2: Suggest** | Proxy decides provisionally, human ratifies in morning | 50+ shadow predictions at ≥80% agreement |
| **L3: Act + Notify** | Proxy commits decision, human audits asynchronously | 200+ ratified decisions at ≥90% acceptance |
| **L4: Autonomous + Sample Audit** | Proxy operates independently, random 10% audited | 500+ decisions at ≥95% agreement, zero critical failures in 30 days |
| **L5: Full Autonomy** | No routine auditing (emergency demotion only) | 1000+ decisions at ≥98% agreement, explicit human sign-off |

**Trust is tracked per decision domain**, not globally. The proxy might reach L4 for "approve test reruns" while remaining at L1 for "merge to main."

### 6.2 Trust Tracker

```python
# src/cosa/agents/notification_proxy/trust_tracker.py
from collections import deque
from datetime import datetime

# Graduation and rollback thresholds per level
THRESHOLDS = {
    1: {"graduate_score": 0.80, "graduate_count": 50,  "rollback_score": 0.0},
    2: {"graduate_score": 0.90, "graduate_count": 200, "rollback_score": 0.70},
    3: {"graduate_score": 0.95, "graduate_count": 500, "rollback_score": 0.85},
    4: {"graduate_score": 0.98, "graduate_count": 1000, "rollback_score": 0.90},
}


class CategoryTrust:
    def __init__(self, category: str, window: int = 100, decay: float = 0.95):
        self.category  = category
        self.level     = 1  # start in shadow mode
        self.decisions = deque(maxlen=window)
        self.decay     = decay
        self.total     = 0

    def record(self, correct: bool, severity: float = 1.0):
        self.decisions.append({
            "ts":       datetime.utcnow(),
            "correct":  correct,
            "severity": severity,
        })
        self.total += 1
        self._evaluate()

    def score(self) -> float:
        if len(self.decisions) < 10:
            return 0.0
        now = datetime.utcnow()
        w_correct = w_total = 0.0
        for d in self.decisions:
            age = max((now - d["ts"]).days, 0)
            weight = (self.decay ** age) * d["severity"]
            w_total += weight
            if d["correct"]:
                w_correct += weight
        return w_correct / w_total if w_total > 0 else 0.0

    def _evaluate(self):
        s = self.score()
        t = THRESHOLDS.get(self.level)
        if t and s >= t["graduate_score"] and self.total >= t["graduate_count"]:
            self.level = min(self.level + 1, 5)
        elif self.level > 1:
            rollback = THRESHOLDS.get(self.level - 1, {}).get("rollback_score", 0)
            if s < rollback:
                self.level = max(self.level - 1, 1)


class TrustTracker:
    def __init__(self):
        self.categories: dict[str, CategoryTrust] = {}

    def level_for(self, category: str) -> int:
        return self.categories.get(category, CategoryTrust(category)).level

    def learn(self, ratification_record: dict):
        category = ratification_record["category"]
        if category not in self.categories:
            self.categories[category] = CategoryTrust(category)
        ct = self.categories[category]
        correct = ratification_record["approved"]
        severity = 2.0 if category in ("destructive", "deployment") else 1.0
        ct.record(correct, severity)
```

### 6.3 Circuit Breaker

Automatic demotion when anomalies are detected:

```python
# src/cosa/agents/notification_proxy/circuit_breaker.py
class CircuitBreaker:
    def __init__(self, trust_tracker: TrustTracker, alert_fn=None):
        self.trust = trust_tracker
        self.alert = alert_fn  # async fn to notify human via Lupin

    async def check(self, category: str, metrics: dict):
        reasons = []
        ct = self.trust.categories.get(category)
        if not ct:
            return

        if metrics.get("error_rate", 0) > 0.03:
            reasons.append(f"Error rate spike: {metrics['error_rate']:.1%}")
        if metrics.get("avg_confidence", 1.0) < 0.6:
            reasons.append(f"Confidence collapse: {metrics['avg_confidence']:.2f}")
        if metrics.get("is_novel", False):
            reasons.append("Out-of-distribution context detected")

        if reasons:
            old_level = ct.level
            ct.level = max(ct.level - 1, 1)
            if self.alert:
                await self.alert(
                    f"⚠️ Trust downgraded for '{category}': L{old_level} → L{ct.level}\n"
                    f"Reasons: {'; '.join(reasons)}"
                )
```

### 6.4 Anti-Patterns to Avoid

| Anti-Pattern | Description | Mitigation |
|---|---|---|
| **Premature escalation** | Granting autonomy before sufficient track record | Hard minimum counts per level (50 → 200 → 500 → 1000) |
| **Autonomy creep** | Gradual unintentional authority expansion | Per-category tracking; explicit graduation only |
| **Automation bias** | Human disengages once proxy seems reliable | Random audit sampling even at L4; periodic manual override exercises |
| **No rollback** | No mechanism to demote trust on regression | Circuit breaker with automatic demotion on anomaly |
| **Global trust** | Single trust score across all categories | Per-domain tracking; "approve test reruns" ≠ "merge to main" |
| **Irreversible high-stakes** | Destructive operations at any trust level | `destructive` and `deployment` categories capped at L3 regardless of score |

---

## 7. Multi-Agent Failure Modes and Defenses

The MAST taxonomy (UC Berkeley, NeurIPS 2025) analyzed 1,600+ traces across 7 frameworks. Roughly 79% of failures originate from specification and coordination issues, not implementation bugs. Failure rates range from 41% to 86.7%.

### 7.1 The Three Deadliest Categories

**Specification failures (~17% of all failures)**: Under-specified task objectives leave agents to interpret ambiguously. Fix: every delegation from lead to subagent must be a structured JSON task with objective, output format, tool guidance, and scope boundaries. Anthropic learned this internally: short instructions cause duplication and gaps.

**Inter-agent misalignment**: Role drift (agents straying from assigned responsibilities), information withholding, duplicate work. Fix: capability-based routing via restricted `allowed_tools` per `AgentDefinition`, agent ID tagging on all Lupin notifications, structured handoff through the orchestrator.

**Termination and verification failures**: Premature termination, infinite loops, incorrect self-assessment. Fix: **default-to-terminate** design — agent loops stop by default, requiring explicit continuation. Layer on maximum iteration limits (5-10 steps per task initially), token budget caps, wall-clock timeouts, and LLM-as-judge verification.

### 7.2 Defensive Architecture Checklist

```python
# Embed these constraints in the orchestrator's agent loop
SAFETY_LIMITS = {
    "max_iterations_per_task":   10,      # hard stop per subagent task
    "max_tokens_per_session":    500_000, # budget cap (≈$2.50 on Sonnet)
    "wall_clock_timeout_secs":   1800,    # 30 min max per task
    "max_consecutive_failures":  3,       # escalate to human after 3 fails
    "max_file_changes_per_task": 20,      # prevent runaway edits
    "require_test_pass":         True,    # block merge if tests fail
}
```

### 7.3 Context Window Management

Anthropic's guidance: treat context as a finite resource with diminishing returns. Use **just-in-time context retrieval** — maintain lightweight identifiers (file paths, function names, test IDs) and load data dynamically via tools at runtime. Combine with:

- SDK automatic compaction (summarization approaching limits)
- 1M token beta context windows (`betas=["context-1m-2025-08-07"]`)
- File-based memory via `CLAUDE.md` (loaded automatically by the SDK)
- `feature_list.json` + `claude-progress.txt` for cross-session state

### 7.4 Error Cascading Prevention

One agent's mistake propagates and compounds downstream. Defenses:

- **Contract validation**: Structured JSON schemas for inter-agent handoffs, validated before the next agent consumes them
- **Sandboxed execution**: Each subagent runs in its own context (the SDK already isolates subagent contexts)
- **Circuit breakers per integration point**: If a subagent fails 3 consecutive tasks, the orchestrator stops delegating to it and notifies the human via Lupin (`priority="urgent"`)
- **Git-based revert**: Every subagent commits with descriptive messages; the orchestrator can `git revert` on verification failure

---

## 8. Putting It Together: The Orchestrator

### 8.1 Minimal Orchestrator

```python
# src/cosa/agents/agent_team/orchestrator.py
"""
Minimal agent team orchestrator.
Decomposes tasks, delegates to subagents, routes decisions through Lupin.
"""
import asyncio
import json
from claude_agent_sdk import query, ClaudeAgentOptions, AgentDefinition
import cosa.agents.agent_team.cosa_interface as team_io

SESSION_ID = "team-" + uuid4().hex[:8]

AGENTS = {
    "coder": AgentDefinition(
        description="Implements features incrementally. One feature per task.",
        allowed_tools=["Read", "Edit", "Bash"],
        system_prompt="""You are a senior backend engineer. Rules:
- Implement ONE feature per task
- Write clean, typed Python with docstrings
- Commit after each feature with a descriptive message
- Update claude-progress.txt after each commit
- If tests fail, fix them before moving on
- NEVER modify files outside your assigned scope"""
    ),
    "tester": AgentDefinition(
        description="Writes and runs smoke, unit, and integration tests.",
        allowed_tools=["Read", "Edit", "Bash"],
        system_prompt="""You are a QA engineer. Rules:
- Write smoke tests first (does it start? does the endpoint respond?)
- Then unit tests (each function in isolation)
- Then integration tests (end-to-end flows)
- Use pytest with markers: @pytest.mark.smoke, @pytest.mark.unit, @pytest.mark.integration
- Run tests after writing them — fix failures before reporting success
- Target >80% coverage on new code"""
    ),
    "reviewer": AgentDefinition(
        description="Reviews code for quality, security, and correctness.",
        allowed_tools=["Read", "Grep", "Glob"],
        system_prompt="""You are a senior code reviewer. Rules:
- Check for: security issues, error handling, type safety, SOLID violations
- Verify test coverage is adequate
- Flag any hardcoded credentials or secrets
- Output a structured review: {passed: bool, issues: [...], suggestions: [...]}
- Be specific — cite file:line for every issue"""
    ),
}


async def run_task(task_description: str):
    """Execute a full development task with the agent team."""
    await team_io.notify_progress(
        message    = f"Starting task: {task_description[:100]}",
        role       = "lead",
        priority   = "medium",
        session_id = SESSION_ID,
        abstract   = task_description,
    )

    # Phase 1: Implementation
    async for msg in query(
        prompt=f"""Implement the following task, then write comprehensive tests.

TASK: {task_description}

WORKFLOW:
1. Read existing code to understand the codebase
2. Delegate implementation to the 'coder' agent with detailed instructions
3. Delegate test writing to the 'tester' agent
4. Delegate code review to the 'reviewer' agent
5. If reviewer finds issues, iterate with coder
6. Report final status

RULES:
- Each delegation MUST include: objective, expected output, scope boundaries
- After each phase, update claude-progress.txt
- If any phase fails 3 times, stop and report the failure""",
        options=ClaudeAgentOptions(
            allowed_tools=["Read", "Edit", "Bash", "Glob", "Task"],
            agents=AGENTS,
            hooks={
                "Notification": lambda e: team_io.notify_progress(
                    message=e.message, role=e.agent_name or "lead",
                    priority="low", session_id=SESSION_ID
                ),
            },
        ),
    ):
        pass  # stream processing; all status flows through hooks

    await team_io.notify_progress(
        message    = f"Task complete: {task_description[:80]}",
        role       = "lead",
        priority   = "high",
        session_id = SESSION_ID,
    )
```

### 8.2 Startup Sequence

```python
# src/cosa/agents/agent_team/__main__.py
import asyncio
import sys
from cosa.agents.agent_team.orchestrator import run_task

async def main():
    task = " ".join(sys.argv[1:]) or "Implement a health check endpoint at /healthz"
    await run_task(task)

if __name__ == "__main__":
    asyncio.run(main())
```

Usage:

```bash
python -m cosa.agents.agent_team "Implement OAuth2 login flow with JWT refresh tokens"
```

---

## 9. Where to Start (Incremental Build Order)

Do not build all six agents at once. Start with the minimum viable loop and add complexity only when you have measurable evidence the simpler system fails.

**Phase 1 — Single agent + Lupin integration** (1-2 days)
- Wire one `claude-agent-sdk` session into Lupin via the `cosa_interface` pattern
- Register `agent.lead` as a new sender type
- Verify fire-and-forget and blocking notifications flow correctly
- Confirm the existing Notification Proxy receives and can respond to agent team notifications

**Phase 2 — Lead + Coder** (2-3 days)
- Add the `coder` subagent definition
- Implement the basic delegation loop: lead decomposes → coder implements → lead verifies
- Add `PreToolUse` hook for dangerous command gating
- Test with a simple task end-to-end

**Phase 3 — Add Tester** (1-2 days)
- Add the `tester` subagent
- Implement the coder → tester → review loop
- Define `SAFETY_LIMITS` and verify iteration caps work

**Phase 4 — Trust-aware proxy** (3-5 days)
- Add `EngineeringDecisionStrategy` to the proxy's strategy chain
- Implement `TrustTracker` with PostgreSQL backing
- Build the morning ratification endpoint
- Start the proxy in L1 (shadow mode) — let it predict while you make real decisions
- After 50+ predictions, evaluate agreement rate before promoting to L2

**Phase 5 — Reviewer + Debugger + Circuit Breaker** (2-3 days)
- Add remaining agent roles
- Implement the circuit breaker with automatic trust demotion
- Add the full defensive architecture checklist

---

## 10. Key References

| Resource | URL | Relevance |
|---|---|---|
| Claude Agent SDK (Python) | `github.com/anthropics/claude-agent-sdk-python` | Core SDK, subagent API |
| Agent SDK Demos | `github.com/anthropics/claude-agent-sdk-demos` | Multi-agent research system example |
| Subagents in the SDK | `docs.anthropic.com/en/docs/claude-code/sdk/subagents` | Subagent definition patterns |
| Agent Teams (experimental) | `code.claude.com/docs/en/agent-teams` | Inter-agent messaging |
| Building Effective Agents | `anthropic.com/research/building-effective-agents` | Orchestrator-worker, start simple |
| Effective Harnesses for Long-Running Agents | `anthropic.com/engineering/effective-harnesses-for-long-running-agents` | Context compaction, state management |
| Context Engineering for Agents | `anthropic.com/engineering/effective-context-engineering-for-ai-agents` | Just-in-time context, context rot |
| Multi-Agent Research System | `anthropic.com/engineering/multi-agent-research-system` | Anthropic's own multi-agent architecture |
| MAST Taxonomy (NeurIPS 2025) | `arxiv.org/pdf/2503.13657` | 14 failure modes, 1600+ traces |
| Why Multi-Agent Systems Fail | `augmentcode.com/guides/why-multi-agent-llm-systems-fail-and-how-to-fix-them` | Practical failure analysis |
| Guided Autonomy: Progressive Trust | `llmwatch.com/p/guided-autonomy-progressive-trust` | Trust escalation patterns |

---

## Appendix A: New Lupin Sender ID Regex Compatibility

All proposed `agent.*` sender IDs are valid under the existing regex:

```
^[a-z]+(\.[a-z]+)+@[a-z]+\.deepily\.ai(#([a-f0-9]{8}|[a-z]+(-[a-z]+)*|[a-z]+-[a-f0-9]{8}))?$
```

Verification:
- `agent.lead@lupin.deepily.ai` ✓ (2-segment agent type, no suffix)
- `agent.lead@lupin.deepily.ai#a1b2c3d4` ✓ (hex session suffix)
- `agent.coder@lupin.deepily.ai#team-a1b2c3d4` ✓ (hyphenated topic suffix)
- `agent.proxy@lupin.deepily.ai` ✓ (no session needed for singleton proxy)

No regex changes required.

## Appendix B: Token Cost Estimates

| Agent | Model | Avg Tokens/Task | Cost/Task (est.) |
|---|---|---|---|
| Lead (Opus 4.6) | claude-opus-4-6 | ~50K input + 10K output | ~$1.50 |
| Coder (Sonnet 4.5) | claude-sonnet-4-5-20250929 | ~100K input + 30K output | ~$0.60 |
| Tester (Sonnet 4.5) | claude-sonnet-4-5-20250929 | ~80K input + 20K output | ~$0.40 |
| Reviewer (Sonnet 4.5) | claude-sonnet-4-5-20250929 | ~60K input + 5K output | ~$0.22 |
| **Full task cycle** | | | **~$2.70** |

Multi-agent systems consume roughly **15× more tokens** than single-agent chat. Treat every additional agent as a liability that must justify its token cost.
