---
capability: needset-stage-c-drafting
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.stage_c.draft_job@5b9025eb24
  - lupin_mcp.reuse_needset.stage_c.request_for@0227b7492b
  - lupin_mcp.reuse_needset.stage_c.ask_pair@421c145945
  - lupin_mcp.reuse_needset.stage_c.cache_only@2b1979b52c
  - lupin_mcp.reuse_needset.stage_c.draft_all@d0d264e41b
  - lupin_mcp.reuse_needset.stage_c.tries_of@72af39ebcf
  - lupin_mcp.reuse_needset.stage_c.save_rejects@9c56f47d10
  - lupin_mcp.reuse_needset.stage_c.share_bodies@5ae4de9a5e
  - lupin_mcp.reuse_needset.stage_c.group_rows@5059f7da52
  - lupin_mcp.reuse_needset.stage_c.fan_out@c87349f920
  - lupin_mcp.reuse_needset.stage_c.judge_all@640ae4b34a
  - lupin_mcp.reuse_needset.stage_c.twin_pairs@75e489d398
---
# Need set: the judge-only run, drafting and judging

Drafts one need per readable pair, then posts each pair three times, each with its own run-index token. The inputs are on [[needset-stage-c-inputs]] and the command on [[needset-stage-c-command]]. The judge calls are those of [[needset-judge-probe-arms]].

## Drafting
- `draft_job` builds the drafter's job for one pair. Its copy and leak checks run against side b too.
- `draft_all` drafts one need per pair. It returns the needs, the undrafted pairs and every sentence a check refused, marked `accepted_later` or `undrafted`.
- `cache_only` stands in for the drafter when a saved ledger must answer everything. An unanswered prompt raises `BAD_NEED`.
- `tries_of` gives `--max-tries` or the drafter's own limit. `save_rejects` writes each refused sentence beside the check that refused it.

## Judging
- `request_for` builds the request for one pair and repeat. `ask_pair` posts it and reads both sides' ratings; the cache is never consulted.
- `twin_pairs` finds pairs on one record pair in one order, before any draft exists. `share_bodies` finds pairs whose posted body would repeat an earlier pair's.
- `group_rows` keeps the first row of each key. `fan_out` gives a sharing pair the posted pair's results, marked `shared_with`.
- `judge_all` drafts under its own stage budget, checks that the bodies are distinct, then posts every pair and repeat.
