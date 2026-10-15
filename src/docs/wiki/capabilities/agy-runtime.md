---
capability: agy-runtime
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.orchestration.agy.runtime.run_agy@43d915113f
  - cosa.orchestration.agy.runtime.build_argv@0bff1254fe
  - cosa.orchestration.agy.runtime.build_stdin@b3f14c6fa5
  - cosa.orchestration.agy.runtime.parse_result@97061628e5
  - cosa.orchestration.agy.runtime.check_success_fields@117fc9e710
  - cosa.orchestration.agy.runtime.binary_fingerprint@5c1103f679
  - cosa.orchestration.agy.runtime.agy_version@e95ea20cd0
  - cosa.orchestration.agy.runtime.AgyResult@3d9baf386d
  - cosa.orchestration.agy.runtime.AgyCallError@61dd254280
  - cosa.orchestration.agy.runtime.AgyUnavailable@9449e90231
  - cosa.orchestration.agy.runtime.AgyBinaryChanged@a400e6d663
---
# Agy runtime

`run_agy` sends one prompt to a Gemini model through Google's `agy` command-line agent and returns the raw answer. The doc-lint harness uses it as a model transport, through `model_transport.configure_agy`.

## What it does
- `build_stdin` encodes the prompt as one stream-json line on standard input. The command line never carries it, so quotes, newlines and the kernel's argument cap do not matter.
- `build_argv` builds the print-mode command: an empty `-p=`, `--model`, a `--print-timeout` with a unit such as `300s`, `--new-project` and `--disable-slash-commands`. `--effort` and `--agent` appear only when given.
- `parse_result` returns the `result` of the last `result` event on standard output and skips lines that are not JSON objects. `check_success_fields` then checks the five fields `AgyResult` is built from.
- `run_agy` returns an `AgyResult` only for exit 0, a `SUCCESS` status and a non-blank answer. The answer comes back unparsed.
- `binary_fingerprint` reads the binary's real path, size and modification time without starting it. `agy_version` does start agy, and returns the first line of `--version`.
- The subprocess timeout is the call's limit plus 60 seconds, so agy reports its own timeout first.

## Don't
- Don't point `workspace_dir` at a repository. agy runs unsandboxed with that directory as its working directory. No flag that grants edits is passed, so print mode refuses tool actions that need approval.
- Don't expect the call to retry. The caller owns the retry policy.
- Don't take the fingerprint before `agy_version`. Starting agy can trigger its updater, so ask for the version first.
- Don't expect a model to always write text. With the default agent it may try a tool, and print mode refuses it, so the answer is blank. Name a custom agent whose front matter says `tools: []`.

## Invariants
- A timeout, a non-zero exit, a missing or failed result and a blank answer all raise `AgyCallError`.
- A non-zero exit whose last 2,000 error characters carry `(code 503)` raises `AgyUnavailable`, a subclass. The match is on that text, not on the exit code.
- With `pinned_fingerprint`, a changed binary raises `AgyBinaryChanged` before the call, and again after it when the binary changed while it ran.
- `denied_actions` is always a list, empty when print mode refused nothing.
- The fingerprint hashes no content, so a replacement with the same path, size and modification time goes unseen.
