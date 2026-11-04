---
capability: reuse-search-terms-and-grep
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_search.SearchError@a48cf878c8
  - lupin_mcp.reuse_search.derive_terms@69c04083f6
  - lupin_mcp.reuse_search.git_grep@3e0b4afbda
  - lupin_mcp.reuse_search.run_search@cb9c58d459
  - lupin_mcp.reuse_search.receipt_source@5e24c02939
  - lupin_mcp.reuse_search.entry_source@412a5c0b1f
---
# Reuse search: terms, grep and sources

The parts of `reuse_search.py` that [[reuse-record-search]] does not pin: how terms are derived, how the tree is searched, and where the search text comes from.

## Terms
- `derive_terms` splits the text with the candidate stage's identifier splitter and writes no splitting rule of its own.
- It keeps words of at least four characters that are not stop words or skipped words, each once. It returns the longest first, ties alphabetical, so the same text gives the same terms.
- `SearchError` carries a name and detail, such as `TOO_MANY_TERMS`, `NO_TERMS`, `GREP_FAILED` or `INDEX_STALE`.

## Searching the tree
- `git_grep` searches for one fixed string, ignoring case, in tracked files with their uncommitted edits and in untracked files. It returns the path and line number of each hit.
- It passes arguments as a list and reads paths literally, so a glob character names that path only. It asks about 500 paths at a time and starts no git run for an empty list.
- Any git exit code other than 0 or 1 raises `GREP_FAILED`.
- `run_search` greps every term, then checks that the index is still fresh. A file that changed during the search raises `INDEX_STALE`, because the spans may no longer match the hits.

## Where the text comes from
- `receipt_source` reads the need, language, excluded id and index hash from a stored receipt and its own snapshot, never from the live index. A receipt with no language searches every language.
- A `fetch_similar` receipt gives its stored need text, else the entry text its snapshot holds. A receipt of any other tool raises `BAD_SEARCH_KEY`.
- `entry_source` reads the id, signature and first docstring line of an indexed entry, public or private, with the generation's search hash. An id the generation lacks raises `UNKNOWN_ENTRY`.
