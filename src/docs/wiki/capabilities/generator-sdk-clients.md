---
capability: generator-sdk-clients
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.podcast_generator.api_client.PodcastAPIClient@eeac52f356
  - cosa.agents.podcast_generator.api_client.PodcastAPIClient.call_for_script@92acc1bb1e
  - cosa.agents.podcast_generator.api_client.CostEstimate@7c2fff6a57
  - cosa.agents.presentation_generator.api_client.PresentationAPIClient@82a308bbe1
  - cosa.agents.presentation_generator.api_client.CostEstimate@4a01d11bac
  - cosa.agents.deep_research.api_client.ResearchAPIClient@46fa8d5e14
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
- A result message with `is_error` raises `RuntimeError` through `raise_error_result`, with the SDK's failure text and a renew-login sentence on a 401. The three clients do this alike.
- Each call returns an `APIResponse` (text, model, tokens, stop reason, `sdk_cost_usd`). Podcast and presentation total usage in a `CostEstimate`; research records it in `CostTracker`, which can raise `BudgetExceededError`.

## Invariants
- `max_tokens` is accepted and ignored. `temperature` is turned into a sentence appended to the system prompt. In podcast and presentation, 0.75 and above reads creative and 0.55 and below precise. In research, the cut-offs are 0.9 and above, and 0.5 and below. It does not change sampling.
- A call with no tools uses permission mode `"default"`. In `"plan"` mode the model writes a plan for the output and the JSON parser then fails. This happened on 4 Aug 2026 to a podcast job, `pg-efc6b2c8`, and to a presentation job. Only research calls that have tools use `"plan"`.
- `call_with_json_output` raises `ValueError` when no JSON object can be recovered. It never returns a default. Podcast and presentation share one in [[bounded-cc-client-base]], which calls at temperature 0.5 and recovers with `recover_json_object` ([[xml-io-models]]); research has its own `extract_json_object`.
- Construction raises `ImportError` if `claude_agent_sdk` is missing. `close()` does nothing.
- `sdk_cost_usd` is the SDK's telemetry, covered by the plan; the token prices in `CostEstimate` are approximate.

## How to extend
- Add a `call_for_*` method that calls `_call_typed` with a new `call_type`. Keep `tools=[]`. The nine `call_for_*` methods in podcast and presentation are thin wrappers over the shared `_call_typed` ([[bounded-cc-client-base]]). A change to one usually belongs in the other.

## Don't
- Don't set permission mode `"plan"` on a call without tools.
- Don't read `ENV_VAR_NAME` in the research client as a live key setting: it is kept for export compatibility and unused.
