# Architecture Decisions — SWE Team Agent

Decisions traced to research in `agent-team-architecture-design.md`.

## ADR-001: Orchestrator-Worker Pattern (not Peer-to-Peer)

**Decision**: All agent communication flows through the Lead orchestrator, not directly between agents.

**Rationale** (Research Section 2):
- Traceability: every delegation is logged
- Prevents conflicts from concurrent file edits
- Enables clean human-in-the-loop via Lupin notification channels
- Matches existing Deep Research pattern

**Consequence**: Slightly higher token cost (lead sees all context), but far safer.

---

## ADR-002: Model Tiering — Opus for Planning, Sonnet for Execution

**Decision**: Lead + Architect use Opus 4.6; Coder, Reviewer, Tester, Debugger use Sonnet 4.5.

**Rationale** (Research Section 3.1):
- Opus excels at task decomposition and extended thinking
- Sonnet handles routine coding at ~1/5 the cost
- Full task cycle estimated at ~$2.70

**Consequence**: Budget-conscious execution without sacrificing planning quality.

---

## ADR-003: Per-Category Trust Tracking (not Global)

**Decision**: Trust proxy tracks trust level independently per decision domain (deployment, testing, dependencies, architecture, destructive, general).

**Rationale** (Research Section 6.3):
- "approve test reruns" != "merge to main"
- Destructive and deployment categories CAPPED at L3 regardless of score
- Prevents autonomy creep across unrelated domains

**Consequence**: Slower trust graduation but much safer. A mistake in "testing" doesn't affect "deployment" trust.

---

## ADR-004: Default-to-Terminate Design

**Decision**: Hard iteration limits (10 per task), token budgets (500K per session), wall-clock timeouts (30 min).

**Rationale** (Research Section 7.2, NeurIPS 2025 MAST taxonomy):
- Termination failures are one of the three deadliest multi-agent failure categories
- Better to stop early and report than loop indefinitely

**Consequence**: Some legitimate long-running tasks may hit limits. Configurable per-task override available.

---

## ADR-005: Sender ID Format for Agent Roles

**Decision**: `agent.{role}@lupin.deepily.ai#{session_id}` format.

**Rationale** (Research Section 5.2):
- Conforms to existing Lupin sender ID regex
- Role-aware routing enables per-role notification filtering
- Session ID suffix enables multi-session isolation

**Consequence**: Notification proxy can distinguish agent team senders from other system senders.

---

*Additional ADRs will be added as implementation decisions are made.*
