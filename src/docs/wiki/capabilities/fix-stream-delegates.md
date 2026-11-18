---
capability: fix-stream-delegates
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - cosa.agents.shared.coder_stream.delegate_to_coder@d58b921873
  - cosa.agents.shared.tester_stream.verify_with_tester@434e97c869
---
# Fix expediters: Coder and Tester streams

The two stream wrappers both expediters share ([[fix-run-outputs-and-guards]] covers `read_coder_stream`, which `delegate_to_coder` calls).

## What it does
- `delegate_to_coder` runs one Coder delegation. Any failure except the safety stop becomes `( "", [] )` and logs `Coder delegation failed`. The caller passes the safety-limit class as `reraise`, because the safety primitives are an optional import.
- `verify_with_tester` reads a Tester's message stream and returns `( passed, tester_output )`. The Tester passes when its text says "pass" and not "fail", or says "all tests pass". The first test file it wrote is run, and a failure there turns the result to failed.
- A failure other than `reraise` returns `( False, "Verification error: ..." )`. With `error_label` set an error result message fails the check; unset, it is ignored.
- Both expediters' `_delegate_to_coder` and `_verify_fix` call these.
