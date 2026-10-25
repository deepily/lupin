---
capability: deep-research-cost-and-rate-limits
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.deep_research.api_client.APIResponse@bbb8ee2be9
  - cosa.agents.deep_research.cost_tracker.ModelTier@b06f0e8725
  - cosa.agents.deep_research.cost_tracker.SessionSummary@545d23e059
  - cosa.agents.deep_research.cost_tracker.UsageRecord@f7608839c4
  - cosa.agents.deep_research.rate_limiter.TokenRecord@15a50a36f6
  - cosa.agents.deep_research.rate_limiter.WebSearchRateLimiter@cfcbd4ca03
---
# Deep research usage records and rate limiting

Plain records and a limiter used around the model calls of [[deep-research]]. The tracker that sums them, `CostTracker`, is described in that page.

## What it does
- `APIResponse` is one bounded Claude Code reply: content, model, token counts, stop reason and `sdk_cost_usd`. `tool_use` and `search_results` stay empty on this path.
- `ModelTier` names three price tiers (Opus, Sonnet, Haiku). Both the 4.5 and 4.6 model names map to them.
- `UsageRecord` is one call: model, tokens, cost, call type, subquery index and cache token counts.
- `SessionSummary` totals tokens, cost and calls, with the split by call type and by model, the duration and the budget left.
- `TokenRecord` is one timestamped token count in the limiter's window.
- `WebSearchRateLimiter` keeps a sliding window of recent token counts. `wait_if_needed` sleeps until the window is under `tokens_per_minute`, and tells the user through the callback when the wait passes the threshold.
- `record_usage` adds a call, `get_tokens_in_window` and `get_status` report the window, and `estimate_total_time` forecasts the wait for a number of calls.

## Don't
- Don't expect the limiter to gate calls under bounded Claude Code. It is kept for time estimates in the CLI.
- Don't read `sdk_cost_usd` as billed money. It is notional telemetry.
