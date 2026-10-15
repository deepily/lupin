---
capability: deep-research-state
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.deep_research.state.Citation@d20f5457e4
  - cosa.agents.deep_research.state.ClarificationDecision@2eab2d38ba
  - cosa.agents.deep_research.state.JobSubState@0c23af028e
  - cosa.agents.deep_research.state.OrchestratorState@af863634bb
  - cosa.agents.deep_research.state.ResearchPlan@dbb562ee2a
  - cosa.agents.deep_research.state.ResearchState@307df92334
  - cosa.agents.deep_research.state.SourceReference@db279fc372
  - cosa.agents.deep_research.state.SubQuery@e6b0a61dd5
  - cosa.agents.deep_research.state.SubagentFinding@1830674580
  - cosa.agents.deep_research.state.create_initial_state@1efe0d63f9
---
# Deep research state types

`state.py` defines the data shapes passed between the steps of [[deep-research]]. It holds two enums, Pydantic models for structured model output, and one typed dict for the whole run.

## What it does
- `OrchestratorState` lists the run states: active ones such as `PLANNING`, waiting ones, terminal ones (`COMPLETED`, `FAILED`) and external ones (`PAUSED`, `STOPPED`).
- `JobSubState` gives finer states for a job inside the `RUNNING` queue, such as waiting for a human or for the model.
- `SubQuery` is one research task: topic, objective, output format, tools, a priority from 1 to 5 and optional dependencies.
- `ResearchPlan` holds a complexity of `simple`, `moderate` or `complex`, the subqueries, an estimated subagent count and a rationale.
- `SourceReference` carries url, title, a relevance score from 0 to 1 and a source quality. `SubagentFinding` holds one subquery's findings, sources, confidence and gaps.
- `ClarificationDecision` says whether a question is needed and what was understood. `Citation` ties one claim to a source and a place in the report.
- `ResearchState` is the whole-run typed dict. `create_initial_state` returns it with the query set, counters at zero and everything else `None` or empty.

## Invariants
- `ResearchOrchestratorAgent`, which uses these states, is not on the production path (see [[deep-research]]).
