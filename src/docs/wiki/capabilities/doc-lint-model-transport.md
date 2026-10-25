---
capability: doc-lint-model-transport
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.model_transport.record_calls@adaa91ee5d
  - cosa.repo.doc_lint.model_transport.ModelCallError@0f1f3577ec
  - cosa.repo.doc_lint.model_transport.ModelUnavailableError@1d6e243d03
  - cosa.repo.doc_lint.model_transport.ModelWaitCutShort@7161eda0f1
  - cosa.repo.doc_lint.model_transport.CallBudgetExceeded@6b52d392dc
  - cosa.repo.doc_lint.model_transport.set_budget@55de940d26
  - cosa.repo.doc_lint.model_transport.calls_used@ce25b51c2f
  - cosa.repo.doc_lint.model_transport.budget_summary@c8c307fe14
  - cosa.repo.doc_lint.model_transport.configure@f26fb8ef9e
  - cosa.repo.doc_lint.model_transport.configure_agy@557254d3e3
  - cosa.repo.doc_lint.model_transport.configure_claude@f3391f6174
  - cosa.repo.doc_lint.model_transport.agy_usage_summary@bafbf1693f
  - cosa.repo.doc_lint.model_transport.cli_version@cb9666da1d
  - cosa.repo.doc_lint.model_transport.prompt_version@882beeb7a9
  - cosa.repo.doc_lint.model_transport.new_suffix@fac8d819cc
  - cosa.repo.doc_lint.model_transport.wrap@57a3b9746a
  - cosa.repo.doc_lint.model_transport.complete@e24081bec2
---
# Doc-lint model transport

The one door the judge harness uses to reach a Claude model, through bounded Claude Code or through agy. It sits under [[doc-lint-claim-judge]] and the other judges.

## Calling
- `complete` sends one prompt and returns the stripped text, never empty. Tools are disabled, so the model can only write text. An empty model id raises `ValueError`.
- `record_calls` collects the stage and seconds of each finished call in its block, and blocks nest. A failed call is not recorded.
- `new_suffix` returns a random tag suffix that occurs in none of the given texts, and `wrap` puts a body between tags named with it. `prompt_version` derives a name and ten hex digits from the prompt's text and code.

## Choosing the path
- `configure` picks the Claude Code binary and working directory for later calls. `cli_version` returns the first line of that binary's `--version`, or `None` for the SDK's own.
- `configure_agy` sends later calls through agy, pinned to the binary on disk, and returns the ledger binding. `configure_claude` returns to Claude Code and forgets the pin.
- `agy_usage_summary` returns a copy of the tokens agy reported, per model.

## Budget
- `set_budget` caps calls per model id, counted from a ledger file that outlives the process. `calls_used` counts the ledger lines for a model, and `budget_summary` returns used and cap per capped model.
- A call over the cap raises `CallBudgetExceeded` before any model is contacted. It is not a `ModelCallError`, so a caller that retries must not retry past it.
- `ModelCallError` is a call that returned nothing usable. `ModelUnavailableError` is a service that stayed unavailable. `ModelWaitCutShort` is a wait ended by a stop.
