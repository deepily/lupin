---
capability: deep-research-prompts
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.deep_research.prompts.clarification.get_clarification_prompt@fb9304adce
  - cosa.agents.deep_research.prompts.clarification.parse_clarification_response@b7961e3f09
  - cosa.agents.deep_research.prompts.planning.get_planning_prompt@8989fd6680
  - cosa.agents.deep_research.prompts.planning.get_theme_clustering_prompt@c58a6d6e2c
  - cosa.agents.deep_research.prompts.planning.parse_planning_response@062cb2f487
  - cosa.agents.deep_research.prompts.subagent.get_subagent_prompt@582dab2237
  - cosa.agents.deep_research.prompts.subagent.get_system_prompt_with_params@b439fe2c32
  - cosa.agents.deep_research.prompts.subagent.parse_subagent_response@e17822e119
  - cosa.agents.deep_research.prompts.synthesis.get_revision_prompt@f2ab3fa40a
  - cosa.agents.deep_research.prompts.synthesis.get_revision_system_prompt@8da0f36014
  - cosa.agents.deep_research.prompts.synthesis.get_synthesis_prompt@0523712037
---
# Deep research prompts

The `prompts` package builds the user message and reads the JSON reply for each model step of [[deep-research]]: clarify, plan, research, synthesize and revise. Each module also holds the fixed system prompt for its step.

## What it does
- `get_clarification_prompt` wraps the query, plus optional context, and asks for the JSON format in the system prompt.
- `get_planning_prompt` uses the clarified query when there is one and keeps the original beside it. It adds audience guidelines and a cap on subagents.
- `get_theme_clustering_prompt` numbers the subqueries, with the objective cut to 60 characters, and asks for 3 or 4 themes.
- `get_subagent_prompt` states topic, objective, output format and source limits, then the audience research guidelines.
- `get_system_prompt_with_params` fills the minimum and maximum source counts into the subagent system prompt.
- `get_synthesis_prompt` lists each finding with confidence, gaps and at most five sources. `get_revision_prompt` pairs a draft with user feedback; `get_revision_system_prompt` returns the revision system prompt.
- The three `parse_*_response` functions call `parse_fenced_json` ([[json-fenced-response-helpers]]). It strips a markdown code fence and parses JSON. A text that is not valid JSON raises `ValueError`.

## Invariants
- An unknown `audience` falls back to the `academic` guidelines.
