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

Policy constants are all part of the receipt (see Receipt identity).

- `T = 0.3` relevance threshold.
- `C = 0.9` confidence bar.
- `F = 0.3` uncertainty floor.
- `K = 10` shortlist size.
- `0.02` sum tolerance.
- `S = 0.9` strong-match bar (`STRONG_MATCH`).

`T` is the fitted cut; the receipt file and its hash are named in the comment above `POLICY` in `verdict.py`.

## Which calls count (B3)

A call is **relevant** when `p_overlap >= T`. It goes on the shortlist.

A call is **doubtful** when `p_overlap >= F` and `confidence < C`. An unrelated entry that Jev
answers "unrelated 0.85" has `p_overlap = 0.15`: it is neither relevant nor doubtful, so the
thousands of unrelated entries in a sweep cannot make every query uncertain. Only calls that
could matter count.

A call is **strong** when `p_overlap >= S` and `confidence >= S`. When any call is strong, doubtful calls
no longer cause `LOW_CONFIDENCE`; they are listed in `doubtful` beside the verdict instead (Rick's ruling).
Every other cause still holds. The reuse-or-extend choice is then decided from the strong calls only; the shortlist is unchanged. A receipt stored before this rule has no `strong` in its policy and replays as it was.

## Which entries are asked (candidate stage)

A `check_exists` question on a context that holds a candidate stage asks the shortlist's entries only.
The stage embeds the redacted need and ranks the index by its vectors and the wiki page list.
It returns at most K entry ids, sorted by id, and the whole shortlist is packed in id order.
The receipt records the `route`:

| `route` | What ran | When |
| --- | --- | --- |
| `full` | one sweep of every entry | no candidate stage, or the question is sweep-only, `fetch_similar` or the pair question |
| `candidates` | one sweep of the shortlist's entries | the candidate stage answered |
| `none` | no sweep | a hard flag, an empty index, or a failed candidate stage |

A failed candidate stage answers `UNCERTAIN_READ_SOURCE` with cause `CALL_FAILED` and never falls back to a silent sweep.
The receipt's `candidate_stage.error` names the failure.
The `candidate_stage` block holds the arm, manifest hash, embed models, list sizes and heads, K and the ids.
It also holds `entries_total`, `entries_asked` and `entries_not_asked`, which add up.
A receipt of the retired page routes (`pages`, `pages_then_full`) stays readable and replays to error `ROUTE_RETIRED`.

A first sweep that sits near a cut-off is widened. The widening runs only when the stage ran, the sweeper is packed,
and the causes are `NEAR_CUTOFF` with at most `LOW_CONFIDENCE`. It asks the stage again for 512 ids,
sweeps the ids outside the first set in packs of their own, and decides over both sweeps.
The receipt then holds `widened: true`, the wide `K`, `widened_ids` and a `widened` stage.
A failed wide call keeps the first sweep, adds `CALL_FAILED` and records `candidate_stage.widen_error`.
A replay sweeps the recorded `widened_ids` and never recomputes the widening.
The shipped policy has no band, so nothing widens. Rick ruled the band off, to be fixed later. The value 0.076 and its fit receipt stay in the policy header comment in `verdict.py`. Adding `"band": 0.076` back turns it on.
One call budget spans the sweep, so a spent budget leaves the later entries unasked and the verdict `UNCERTAIN_READ_SOURCE` with `CALL_FAILED`.
`stats.stages` lists the stages that ran, and `stats.attempts_total` is their HTTP attempts.
`stats.tokens_in` and `stats.tokens_out` sum the `usage` that Jev reported on each live answered call, across
every stage; each stage entry carries its own pair. A cache hit adds nothing, and a failed call has no response
to read. A live answer with no `usage`, or one that is not two whole numbers, adds nothing and is counted in
`stats.usage_missing`. A receipt stored before this tally has none of these keys and still replays.
`stats.transport` summarises what the transport saw on every live response, all stages together: the count of responses,
the resolved `model` ids, HTTP statuses and attempts per response as counts, how many calls saw a `retry-after` and the
largest in seconds, and the latency of each answered attempt as min, max, mean, p50 and p95 in milliseconds. A cache hit
adds nothing. A retry waits the longer of the `retry-after` (at most 60 seconds) and the doubling backoff scaled by a
random factor between 0.75 and 1.25. A receipt stored before this summary has no `transport` key and still replays.

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
| 7 | `LOW_CONFIDENCE` | at least one call is doubtful and no call is strong | UNCERTAIN_READ_SOURCE |
| 7a | `NEAR_CUTOFF` | the policy has a `band` and any answered entry is inside it of a cut-off: its `p_overlap` of the threshold or the strong cut-off, its confidence of the confidence bar (when its `p_overlap` reaches the floor) or of the strong cut-off (when its `p_overlap` reaches it), or its `p_overlap` of the floor (when its confidence is under the bar); the edge is outside; a policy with no `band` never has this cause | UNCERTAIN_READ_SOURCE |
| 8 | none of the above, and some shortlist entry has `choice = reuse` | | REUSE |
| 9 | none of the above, the shortlist is not empty, no entry has `choice = reuse` | | EXTEND |
| 10 | `NO_MATCH` | none of the above, the shortlist is empty. This replaces the verdict `NEW` for every policy that carries `no_new` (the shipped one); a policy stored before it still decides `NEW` | UNCERTAIN_READ_SOURCE |

The order follows the pipeline: a tree that cannot be indexed comes before an incomplete index,
which comes before a stale one, a missing key, failed calls and finally an unsure model. A verdict
of `NEW` (now the cause `NO_MATCH`) needs a complete sweep, no doubtful call and an empty shortlist, so a `NEW` never rests on a
failed or unsure call, which is why `NO_MATCH` is never listed beside another cause. It still does not rule `DISTINCT`: the reviewer reads the shortlist's source
first (plan 2, section 8).

The shortlist holds at most `K` relevant entries, best `p_overlap` first, ties broken by symbol id.
The receipt also stores `shortlist_total`, the number of relevant entries before the cut, and
`nearest`: the best `K` entries by `p_overlap` whatever their value. A `NO_MATCH` result therefore still
names what the reviewer must read before ruling `DISTINCT`.

A malformed answer never contributes to a verdict, and never becomes `NO_MATCH` or `REUSE`. `missing` lists the
expected ids that received no account at all.

## Worked rows

| Sweep | Result |
| --- | --- |
| 5,000 entries, all `unrelated >= 0.85`, none failed | UNCERTAIN_READ_SOURCE, cause `NO_MATCH` |
| the same, one entry `reuse 0.95` | REUSE, shortlist of 1 |
| the same, one entry `extend 0.92` | EXTEND |
| one entry `reuse 0.6, unrelated 0.4` (confidence 0.6) | UNCERTAIN, cause LOW_CONFIDENCE |
| one entry `unrelated 0.6, reuse 0.3, extend 0.1` (`p_overlap` 0.4, confidence 0.6) | UNCERTAIN, cause LOW_CONFIDENCE |
| one entry `unrelated 0.75, reuse 0.2, extend 0.05` (`p_overlap` 0.25, below `F`) | UNCERTAIN_READ_SOURCE, cause `NO_MATCH` |
| one entry `reuse 0.95` and one `reuse 0.7, extend 0.2` (confidence 0.7) | REUSE, shortlist of 2, `doubtful` lists the second |
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

A `fetch_similar` receipt for a nested definition (a helper inside a function) also carries `need_text`, the text asked about.
It is part of the id. The snapshot never holds nested definitions, so replay could not rebuild the question from it.
A receipt for a public or `_private` definition has no such field. The snapshot holds it, and the index sha comes from `search_sha`.
That hash covers private definitions too.

A receipt is immutable: it holds the inputs, the verdict, `cause`, `causes`, the shortlist and the
Jev cache keys. It never holds callers or times. Who asked, and when, lives only in the per-session
call log, one file per server, merged at read time. Two callers asking the same question share one
receipt file and each writes its own log line, so no process ever rewrites a receipt.

## Where each rule is implemented and tested

| Rule | Code | Test |
| --- | --- | --- |
| verdict, causes, precedence, coverage, malformed answers | `verdict.py` | `test_symindex_verdict.py` |
| sweep, cache by request hash, receipts, snapshots, replay | `src/lupin_mcp/reuse_tools.py` | `test_reuse_tools.py` |
| candidate routing: the shortlist sweep, the failed-stage verdict, the receipt block, frozen replay | `src/lupin_mcp/reuse_tools.py` | `test_reuse_candidate_route.py` |
| server-side call log | `src/lupin_mcp/reuse_call_log_middleware.py` | `test_reuse_mcp_mount.py` |
| replay gate (ii), (iii) by mutation | `reuse_tools.py` mutated one line per arm; record in `reuse-gates-mutation-evidence.md` | `test_gate_ii_the_id_recomputes_from_the_stored_inputs_and_an_edited_input_is_named`, `test_gate_iii_a_corrupt_or_missing_input_is_a_named_error_never_a_verdict`, and the other named killers in that file |
