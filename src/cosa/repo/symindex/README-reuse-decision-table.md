# check_exists decision table

Status: draft for review, written before any W-C code (spec critique B3, B1, B2). The rules are
implemented by `verdict.py` and tested row by row in `src/tests/unit/test_symindex_verdict.py`.

## Inputs

One sweep asks Jev one question per index entry. Each answered call gives probabilities
`p_reuse`, `p_extend`, `p_unrelated` (sum 1). Four numbers are derived per call:

| Name | Definition |
| --- | --- |
| `p_overlap` | `p_reuse + p_extend` |
| `confidence` | the largest of the three probabilities |
| `choice` | the answer with the largest probability: `reuse`, `extend` or `unrelated` |
| failed | the call did not return an answer after its retries |
| malformed | the answer is not exactly the three keys, each a finite number in [0, 1], summing to 1 within 0.02; or its id is not an index entry, or is answered twice |

Policy constants, all part of the receipt (see Receipt identity): `T = 0.5` relevance threshold,
`C = 0.9` confidence bar, `F = 0.3` uncertainty floor, `K = 10` shortlist size, `0.02` sum tolerance.

## Which calls count (B3)

A call is **relevant** when `p_overlap >= T`. It goes on the shortlist.

A call is **doubtful** when `p_overlap >= F` and `confidence < C`. An unrelated entry that Jev
answers "unrelated 0.85" has `p_overlap = 0.15`: it is neither relevant nor doubtful, so the
thousands of unrelated entries in a sweep cannot make every query uncertain. Only calls that
could matter count.

## Verdict

The causes are checked in the order below; the first one that holds decides, and every cause that
holds is also listed, in this order, in `causes`.

| # | Cause | Holds when | Verdict |
| --- | --- | --- | --- |
| 1 | `NOT_LUPIN_TREE` | the index root is not a lupin tree | UNCERTAIN_READ_SOURCE |
| 2 | `DEPENDENCY_MISSING` | the index header lists a missing tool, or a tool the call needs is absent | UNCERTAIN_READ_SOURCE |
| 3 | `INDEX_STALE` | the index does not match the tree and cannot be rebuilt | UNCERTAIN_READ_SOURCE |
| 4 | `KEY_UNREADABLE` | the Jev key file is missing or unreadable | UNCERTAIN_READ_SOURCE |
| 5 | `CALL_FAILED` | a call failed, or some index entry id is neither answered, failed nor malformed (coverage is checked as set equality, never as a count; an entry the call budget left unasked counts as unanswered, so a spent budget gives this cause and never `NEW`) | UNCERTAIN_READ_SOURCE |
| 6 | `MALFORMED_ANSWER` | at least one answer is malformed; every malformed answer is dropped and listed with its reason | UNCERTAIN_READ_SOURCE |
| 7 | `LOW_CONFIDENCE` | at least one call is doubtful | UNCERTAIN_READ_SOURCE |
| 8 | none of the above, and some shortlist entry has `choice = reuse` | | REUSE |
| 9 | none of the above, the shortlist is not empty, no entry has `choice = reuse` | | EXTEND |
| 10 | none of the above, the shortlist is empty | | NEW |

The order follows the pipeline: a tree that cannot be indexed comes before an incomplete index,
which comes before a stale one, a missing key, failed calls and finally an unsure model. A verdict
of NEW needs a complete sweep, no doubtful call and an empty shortlist, so a NEW never rests on a
failed or unsure call. NEW still does not rule DISTINCT: the reviewer reads the shortlist's source
first (plan 2, section 8).

The shortlist holds at most `K` relevant entries, best `p_overlap` first, ties broken by symbol id.
The receipt also stores `shortlist_total`, the number of relevant entries before the cut, and
`nearest`: the best `K` entries by `p_overlap` whatever their value. A NEW verdict therefore still
names what the reviewer must read before ruling DISTINCT.

A malformed answer never contributes to a verdict, and never becomes NEW or REUSE. `missing` lists the
expected ids that received no account at all.

## Worked rows

| Sweep | Result |
| --- | --- |
| 5,000 entries, all `unrelated >= 0.85`, none failed | NEW |
| the same, one entry `reuse 0.95` | REUSE, shortlist of 1 |
| the same, one entry `extend 0.92` | EXTEND |
| one entry `reuse 0.6, unrelated 0.4` (confidence 0.6) | UNCERTAIN, cause LOW_CONFIDENCE |
| one entry `unrelated 0.6, reuse 0.3, extend 0.1` (`p_overlap` 0.4, confidence 0.6) | UNCERTAIN, cause LOW_CONFIDENCE |
| one entry `unrelated 0.75, reuse 0.2, extend 0.05` (`p_overlap` 0.25, below `F`) | NEW |
| one failed call and one doubtful call | UNCERTAIN, cause CALL_FAILED, causes `[CALL_FAILED, LOW_CONFIDENCE]` |
| one answer `reuse 0.9, extend 0.9, unrelated 0.9` | UNCERTAIN, cause MALFORMED_ANSWER, reason `sum_not_one` |
| 4 expected ids, answers for 2 of them and 2 unknown ids | UNCERTAIN, causes `[CALL_FAILED, MALFORMED_ANSWER]`, `missing` the 2 unanswered ids |
| index stale and key missing | UNCERTAIN, cause INDEX_STALE, causes `[INDEX_STALE, KEY_UNREADABLE]` |

## Receipt identity (B1, B2)

The receipt id is the sha1 (first 16 hex) of a canonical JSON of:

`tool`, `tool_version`, `query`, `index_sha`, `model`, `policy` (the constants above),
`prompt_template_hash` (hash of the Jev instructions and criteria sent with every call), `causes`
(the uncertainty causes that held; empty for a complete answer).

The causes are part of the id so that an incomplete result, such as a missing key or a failed call,
never shadows the complete receipt of the same question, and a complete one never hides an incomplete
one. A later healthy call therefore gets its own receipt.

Changing the prompt, the tool version, a threshold or the model therefore yields a new id, and a
cached answer for the old prompt is never returned as current.

A receipt is immutable: it holds the inputs, the verdict, `cause`, `causes`, the shortlist and the
Jev cache keys. It never holds callers or times. Who asked, and when, lives only in the per-session
call log, one file per server, merged at read time. Two callers asking the same question share one
receipt file and each writes its own log line, so no process ever rewrites a receipt.

## Where each rule is implemented and tested

| Rule | Code | Test |
| --- | --- | --- |
| verdict, causes, precedence, coverage, malformed answers | `verdict.py` | `test_symindex_verdict.py` |
| sweep, cache by request hash, receipts, snapshots, replay | `src/lupin_mcp/reuse_tools.py` | `test_reuse_tools.py` |
| server-side call log | `src/lupin_mcp/reuse_call_log_middleware.py` | `test_reuse_mcp_mount.py` |
| replay gate (ii), (iii) by mutation | `mutate_reuse` run, see the W-C handoff | `test_gate_ii_...`, `test_gate_iii_...` |
