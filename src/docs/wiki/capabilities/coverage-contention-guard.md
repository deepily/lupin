---
capability: coverage-contention-guard
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.utils.coverage_contention.comm_could_be_pytest@845e75b15c
  - cosa.utils.coverage_contention.escape_hatch_engaged@a5ec54bff0
  - cosa.utils.flag_text.is_flag_on@1a013d702a
  - cosa.utils.coverage_contention.find_foreign_pytest@2fc812eba7
  - cosa.utils.coverage_contention.looks_like_a_direct_test_file_run@5f96a93a63
  - cosa.utils.coverage_contention.looks_like_a_running_suite@09a5ba0bd4
  - cosa.utils.coverage_contention.looks_like_pytest@bb82f032ae
  - cosa.utils.coverage_contention.main@cbc5c071f8
  - cosa.utils.coverage_contention.render_refusal@365a4e89e7
---
# Coverage contention guard

`coverage_contention` finds other running suites before a coverage run, because a peer tier on the same box makes the number untrustworthy. The shell caller is `src/scripts/lib/guard-contended-coverage.sh`.

## What it does
- `find_foreign_pytest` returns `( pid, cmdline )` rows that are not this process or an ancestor.
- A row must have a command line that passes `looks_like_a_running_suite` and a `comm` that passes `comm_could_be_pytest`.
- `looks_like_pytest` and `looks_like_a_direct_test_file_run` are the command-line predicates behind that check.
- `escape_hatch_engaged` reads `LUPIN_ALLOW_CONTENDED_COVERAGE`.
- `is_flag_on` is the shared reading of an operator-typed switch. `true`, `1`, `yes` or `on` in any case is on; `None` and every other text is off. The librarian tick and the asynchronous promotion switch use it too.
- `render_refusal` prints the refusal text. `main` exits 0 clear, 1 contended and 2 unknown. The escape hatch exits 0.

## Don't
- Don't read exit 2 as clear. It means contention is unknown.

## Invariants
- Unknown is never clear: contention exit 2 is distinct from a pass.
