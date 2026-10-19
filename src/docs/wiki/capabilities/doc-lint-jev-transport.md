---
capability: doc-lint-jev-transport
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.repo.doc_lint.jev_transport.JevConfigError@49756aa91e
  - cosa.repo.doc_lint.jev_transport.JevCallError@906f2317fd
  - cosa.repo.doc_lint.jev_transport.JevBudgetSpent@79cf17ee40
  - cosa.repo.doc_lint.jev_transport.CallBudget@fbed5fc7fa
  - cosa.repo.doc_lint.jev_transport.request_ids@b215935908
  - cosa.repo.doc_lint.jev_transport.failure_kind@31028becab
  - cosa.repo.doc_lint.jev_transport.retry_after_seconds@54bce10370
  - cosa.repo.doc_lint.jev_transport.build_body@e79fc48612
  - cosa.repo.doc_lint.jev_transport.parse_answer@1930963bd0
  - cosa.repo.doc_lint.jev_transport.has_key@5b2a281554
  - cosa.repo.doc_lint.jev_transport.send_with_meta@a908d7d8ba
  - cosa.repo.doc_lint.jev_transport.send@a32c309734
  - cosa.repo.doc_lint.jev_transport.ask_noul@3f4070c783
---
# Doc-lint Jev transport

The one door the judge harness uses to reach Jev, TypeSafe's yes/no model. [[doc-lint-judges]] calls it through `ask_noul`.

## Asking
- `ask_noul` asks one yes/no question about a state and returns the probability of yes and the model string. It raises `ValueError` for an empty model.
- `build_body` makes the request body, one question under one id. `parse_answer` reads the probability and the model out of a response. It raises `JevCallError` if the model differs from the requested one.
- `has_key` says whether the key variable is set, and never returns the value.

## Sending
- `send` is the only HTTP path and returns the text of a 200 response. `send_with_meta` also returns the status, attempts, latency and the request ids of each attempt.
- A 429 or 529 is retried up to the attempt limit. With `transient` a timeout, a reset and the transient statuses are retried too. The wait is never shorter than the server's retry-after.
- `retry_after_seconds` reads that header as a finite number of at least zero, else `None`. `request_ids` picks the request-id headers. `failure_kind` returns `timeout` or `connection`.

## Budget and errors
- `CallBudget` caps HTTP attempts across all threads of one sweep. `take` counts one attempt or raises `JevBudgetSpent` without counting, and `used` never exceeds the limit.
- `JevConfigError` means no key or a refused request. `JevCallError` means no usable answer after retries.
- Both extend a private `_JevError`, which holds the message, the HTTP status and the attempt log. They are siblings, so catching one never catches the other.
