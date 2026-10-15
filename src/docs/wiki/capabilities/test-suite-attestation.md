---
capability: test-suite-attestation
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.test_suite.attestation.artifact_root@21b494997a
  - cosa.agents.test_suite.attestation.attestation_path@19f3ef9e80
  - cosa.agents.test_suite.attestation.sha256_file@cc2300efe3
  - cosa.agents.test_suite.attestation.canonical_payload@daaebfffbe
  - cosa.agents.test_suite.attestation.build_record@104c7f0067
  - cosa.agents.test_suite.attestation.read_records@b1738f5198
---
# Test suite attestation

A durable, hash-chained record that a test tier ran, kept under the `io/` mount. It is tamper-evident and not tamper-proof. Chain verification and appending are in the same module.

## What it does
- `artifact_root` and `attestation_path` return the artifact folder and the append-only ledger file under the project's `io/` mount. Neither creates anything.
- `sha256_file` returns the hash of a file read in chunks, or `None` when the file does not exist.
- `canonical_payload` returns the sorted-key, fixed-separator `json` text that a record's hash is taken over, without its own hash field.
- `build_record` builds one record from a tier result, a suite name, a job id, the previous hash, a sequence number and two times.
- `build_record` reads each count explicitly, so a missing count is an error and not a zero.
- `read_records` returns every record in file order, or an empty list for a missing file.

## Invariants
- Under pytest, both path functions raise `RuntimeError` when no `project_root` is given, so a test cannot reach the real ledger.
- A tier with no junit file can still be attested, because `sha256_file` does not raise.
- A malformed ledger line raises in `read_records`. A corrupted ledger must not verify clean.
- The first record links to a previous hash of 64 zeros.
