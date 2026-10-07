---
capability: generator-sdk-clients
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.podcast_generator.api_client.PodcastAPIClient@f5da521d02
  - cosa.agents.podcast_generator.api_client.PodcastAPIClient.call_for_script@5a2c246c32
  - cosa.agents.podcast_generator.api_client.PodcastAPIClient.call_with_json_output@46b576922b
  - cosa.agents.podcast_generator.api_client.CostEstimate@df68204a8c
  - cosa.agents.presentation_generator.api_client.PresentationAPIClient@9334a4bf82
  - cosa.agents.presentation_generator.api_client.PresentationAPIClient.call_with_json_output@3ce92a0be9
  - cosa.agents.presentation_generator.api_client.CostEstimate@e225be7ff1
  - cosa.agents.deep_research.api_client.ResearchAPIClient@ebdbfedc7e
  - cosa.agents.deep_research.api_client.ResearchAPIClient.call_subagent@0ae9dd8678
  - cosa.agents.deep_research.api_client.ResearchAPIClient.call_with_json_output@dc6725397a
  - cosa.agents.deep_research.api_client.extract_json_object@5ff3564b7e
---
# Generator SDK clients

The podcast, presentation and deep-research agents each have one client class that sends their prompts to Claude through the in-process Claude Agent SDK (`claude_agent_sdk.query`). They use the subscription login, so they need no API key; see [[bounded-claude-code-jobs]] for the cost model.

## What it does
- `PodcastAPIClient`: `call_for_analysis`, `call_for_script`, `call_for_revision`, `call_with_json_output`; model `PodcastConfig.script_model`.
- `PresentationAPIClient`: `call_for_analysis`, `call_for_outline`, `call_for_elaboration`, `call_for_mermaid`, `call_for_matplotlib`, `call_for_d2`, `call_with_json_output`; model `content_model`.
- `ResearchAPIClient`: `call_lead_agent` (no tools), `call_subagent` (`WebSearch` and `WebFetch` unless `use_web_search=False`) and `call_with_json_output`; only the lead call can use extended thinking.
- Each call returns an `APIResponse` (text, model, tokens, stop reason, `sdk_cost_usd`). Podcast and presentation total usage in a `CostEstimate`; research records it in `CostTracker`, which can raise `BudgetExceededError`.

## Invariants
- `max_tokens` is accepted and ignored. `temperature` is turned into a sentence appended to the system prompt (podcast and presentation: 0.75 and above creative, 0.55 and below precise; research: 0.9 and above, 0.5 and below). It does not change sampling.
- A call with no tools uses permission mode `"default"`. In `"plan"` mode the model writes a plan for the output and the JSON parser then fails (podcast job `pg-efc6b2c8`, presentation job `pr-62254a7f`, 2026-08-04). Only research calls that have tools use `"plan"`.
- `call_with_json_output` raises `ValueError` when no JSON object can be recovered, and never returns a default. Podcast and presentation use `recover_json_object` ([[xml-io-models]]); research has its own `extract_json_object`.
- Construction raises `ImportError` if `claude_agent_sdk` is missing. `close()` does nothing.
- `sdk_cost_usd` is the SDK's telemetry, covered by the plan; the token prices in `CostEstimate` are approximate.

## How to extend
- Add a `call_for_*` method that calls `_call_api` with a new `call_type`. Keep `tools=[]`; the nine `call_for_*` methods in podcast and presentation are one exact-clone group in the duplicate report, so a change to one usually belongs in the other.

## Don't
- Don't set permission mode `"plan"` on a call without tools.
- Don't read `ENV_VAR_NAME` in the research client as a live key setting: it is kept for export compatibility and unused.
