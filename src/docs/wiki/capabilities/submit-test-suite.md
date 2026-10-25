---
capability: submit-test-suite
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.submit-test-suite.parse_args@3a1e01e012
  - scripts.submit-test-suite.parse_env@46b7c5749c
  - scripts.submit-test-suite.build_payload@2ced1bc22e
  - scripts.submit-test-suite.main@c723242be8
---
# Submit test suite

Submits one test-suite job to a Lupin server through `POST /api/v2/submit` with the command `agent router go to test suite`. The old test-suite submit endpoint is retired and answers 410. This is the sanctioned door for `:8000` runs, wrapped so a seat does not hand-roll a login and a request each time. It does not check that the venue is idle, so run the idle check and read its exit code first.

## Functions
- `parse_args` parses the command line. `--test-types` is required. Other options include `--pytest-args`, `--scheduled-at`, `--dry-run`, `--env` and `--auto-fix`.
- `parse_env` turns the repeatable `--env KEY=VALUE` values into a dict. Only the first equals sign splits, a later pair for the same name wins, and a value may be empty.
- It raises `ValueError` for a pair with no equals sign, an empty name, or a name the suite job's own filter would drop. The filter is asked, not restated. The server keeps only names with a test-scoped prefix, so the script refuses such a name before anything is sent.
- `build_payload` returns the JSON body, leaving out unset optional fields. It always sends `auto_fix_on_failure`, false unless `--auto-fix` is given.
- `main` logs in with the shared tester account from the environment, submits and prints the response.

## Exit codes and limits
- 0 means submitted. 1 means bad usage or missing credentials, 2 means login failed, and 3 means the submit was refused.
- Version 2 answers HTTP 200 with a failed status for a refused submit, so the exit code reads the reply, not the HTTP code.
- The test container refuses the unit suite through this door. That suite runs on the host.
