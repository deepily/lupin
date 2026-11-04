---
capability: symindex-tests-scope
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.symindex.spec.tests_spec@737879df38
  - cosa.repo.symindex.spec.skip_rule@03f8eb9a6e
---
# Symbol index: the tests scope
Test files are indexed apart from the main index, as their own generation ([[symbol-index]]). The `include_tests` option of the reuse tools reads it ([[reuse-search-tools]]).
- `tests_spec` builds the index spec of a repository's test files. A lupin tree reads Python and script files under `src/tests` and `src/cosa/tests`, whichever exist.
- Any other tree reads a `tests` or `src/tests` directory when it has one, and nothing otherwise.
- The spec skips every part of the main set except `tests`, so a test file is indexed in this scope and nowhere else.
- `skip_rule` names the rule that excludes a relative path. That is the first directory in the skip parts, else the file name suffix, else None. The file name itself is never matched against the parts.
- It publishes `test` as its searchable scope.
