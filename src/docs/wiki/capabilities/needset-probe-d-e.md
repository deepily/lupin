---
capability: needset-probe-d-e
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_needset.probe_d_e.drafted_rows@9d721caf69
  - lupin_mcp.reuse_needset.probe_d_e.passes_agree@0dcd7e4117
  - lupin_mcp.reuse_needset.probe_d_e.term@a930cbf2e9
  - lupin_mcp.reuse_needset.probe_d_e.arm_view@10515ab037
  - lupin_mcp.reuse_needset.probe_d_e.inside@4911688df9
  - lupin_mcp.reuse_needset.probe_d_e.presence@9f4575b7d3
  - lupin_mcp.reuse_needset.probe_d_e.mean_shares@3ccefb40b5
  - lupin_mcp.reuse_needset.probe_d_e.newly_inside@b753c9823f
  - lupin_mcp.reuse_needset.probe_d_e.probe_d@e8ba35c954
  - lupin_mcp.reuse_needset.probe_d_e.leak_split@04a7a6d310
  - lupin_mcp.reuse_needset.probe_d_e.probe_e@e18ef3fbf7
  - lupin_mcp.reuse_needset.probe_d_e.replay@d2de08d9d8
  - lupin_mcp.reuse_needset.probe_d_e.cell@0e61f643ae
  - lupin_mcp.reuse_needset.probe_d_e.render@ba0f13156e
  - lupin_mcp.reuse_needset.probe_d_e.main@41200cbe89
  - lupin_mcp.reuse_needset.control_report.fusion_terms@e64d880139
---
# Need set: control probes d and e

Replays two probes over a saved first-thousand control report, with no model call. Probe d asks where each plant stood in each source list and in the fused list, with its purpose line and without it. Probe e asks whether the need's wording overlaps the plant's purpose line more than the original's. The rows come from [[needset-control-scoring]].

## Probe d: ranks
- `drafted_rows` gives the drafted pair rows of the control stage. `passes_agree` is true when every pass of a multi-pass control repeats the report's rows.
- `fusion_terms` gives what each source list added to an entry's fused score in one search. `term` gives what a list adds at a place. `arm_view` reads one arm of a pair: the ranks saved for an entry and what each list added.
- `inside` says whether a place is within a cut-off. `presence` counts the entries inside the cut-offs 10, 32 and 128, per source list and in the fused list. `mean_shares` averages the share each list gave to the fused score.
- `newly_inside` lists the pairs whose plant is inside the fused cut-off with the line and not without it. `probe_d` runs all of it for the plant with its line, without it and for the original.

## Probe e: wording
- `leak_split` compares the need's overlap with the plant's line against the original's line. It counts pairs rating the plant higher, tied or lower, with the median and mean difference. A pair counts only when both overlaps are saved.
- `probe_e` runs it over all pairs, and over the same-job and not-same rows apart.

## Running
- `replay` runs both probes over one saved report. `cell` formats a rank or number, a dash for none. `render` writes the markdown tables, and `main` reads the report, writes the JSON and prints the tables.
