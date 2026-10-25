---
capability: needset-drafting-flows
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.draft.draft_need@7a3e16acd7
  - lupin_mcp.reuse_needset.draft.draft_cell@fea09c6d5f
  - lupin_mcp.reuse_needset.draft.replacement_report@75e3a4fa43
  - lupin_mcp.reuse_needset.draft.draft_cells@cd40e8a89d
  - lupin_mcp.reuse_needset.draft.none_prompt@82c49d11e8
  - lupin_mcp.reuse_needset.draft.none_note@908dcd7239
  - lupin_mcp.reuse_needset.draft.draft_none@4ac24a49db
  - lupin_mcp.reuse_needset.draft.make_none_drafter@cb2ca926b8
---
# Need set: drafting flows

Drafts one sentence per seed, leak-checked, rewritten up to three times, else replaced by the next seed. The calls and checks are on [[needset-drafter-plumbing]].

## One seed
- `draft_need` drafts the sentence for one seed. At most three sentences are checked, and an unreadable reply is asked again once with the same prompt.
- A rewrite request names the failure kinds and the seed's own offending words, never a key symbol or its text. The history holds no key text.
- It returns not ok with `UNREADABLE_REPLY` when both replies were unreadable, and `NEED_LEAKS_KEY` after three failed checks.

## One cell
- `draft_cell` walks the seeds in draw order and replaces each failed seed with the next. It returns the original ids, the final ids, the failures and a count of replacements by reason.
- When the seeds run out before the wanted needs are accepted, it raises `QUOTA_UNFILLABLE`.
- `replacement_report` summarises the replacements per cell and per reason for the manifest, keeping the original seed list beside the final one.
- `draft_cells` drafts several cells, up to a parallel limit at once. Specs with the same cell run one after another. A failure in one cell stops the cells not yet started and is raised once those in flight finish.

## Nothing cell
- `none_prompt` builds the prompt that asks for a helper the listed symbols do not provide. The symbols sit between tags that end in a random suffix found in none of them.
- It asks for one sentence that begins "A function that " and says what the helper does, with no name. `none_note` is the rewrite request, naming failure kinds only.
- `draft_none` drafts that need from the symbol list of one file. The key is always empty, and the retry rules match `draft_need`.
- `make_none_drafter` builds the drafter for the nothing cell. A second model looks for a match, and a yes on either list rejects the need with `ABSENCE_REJECTED`. The same model for both raises `CHECKER_EQUALS_DRAFTER`.
- A need that survives is only proposed as nothing-exists. People settle every one.
