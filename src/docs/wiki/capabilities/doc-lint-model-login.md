---
capability: doc-lint-model-login
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.repo.doc_lint.model_transport.ModelLoginExpired@2d5510f717
  - cosa.repo.doc_lint.model_transport.login_reply@7f35523b16
---
# Doc-lint model login check

How the model transport ([[doc-lint-model-transport]]) tells a broken login from other failures.

## What it does
- `login_reply( detail )` is true when the error text of a call contains any entry of `LOGIN_MARKERS`.
- `LOGIN_MARKERS` and `login_hint` come from `cosa.agents.shared.sdk_error_result`.
- `complete` raises `ModelLoginExpired` when `login_reply` is true for an error result, with the text passed through `login_hint`.
- `ModelLoginExpired` is a `ModelCallError`. Only a person's `/login` fixes it.

## Don't
- Do not retry a call that raised `ModelLoginExpired`. The login stays expired until a person renews it.
