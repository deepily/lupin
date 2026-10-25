---
capability: reuse-fresh-needs-sample
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_phase5_run.pick_sample@33cacf08ad
  - lupin_mcp.reuse_phase5_run.write_sample@d722fdcf1f
  - lupin_mcp.reuse_phase5_run.load_record@3ace1cb734
  - lupin_mcp.reuse_phase5_run.sample_sha@eb49f3de95
  - lupin_mcp.reuse_phase5_run.read_sample@00f2f96821
  - lupin_mcp.reuse_phase5_run.check_stamps@407812086d
  - lupin_mcp.reuse_phase5_run.result_path@39065aad45
  - lupin_mcp.reuse_phase5_run.canary_approved@63a1ec0023
---
# Reuse fresh-needs sample and stamps

The sample of fresh needs that gets a full sweep, and the hash stamp that ties every result to it. The driver that uses them is on [[reuse-fresh-needs-driver]].

## The sample
- `pick_sample` ranks each need by the sha256 of the seed, a colon and its member id, and takes the first ten. No random state is involved, so the same seed and file give the same needs, returned in the file's order.
- The seed must be a non-empty string written down before the run. An empty seed, or a size outside 1 to the number of needs, raises `DriverRefused`.
- `write_sample` records the seed, members, needs hash, arm and index hash once, by exclusive create. A later call with the same values returns the same record. A different seed, arm or index is refused.
- `load_record` reads that file. Anything that is not a JSON object is a refusal, not a traceback.
- `read_sample` is the first step of every spending or reporting step. It refuses when no sample is recorded, or it was recorded for another needs file.

## The stamp
- `sample_sha` is the sha256 of the sample file's bytes. Each result carries it, so a run that stops partway still leaves a stamped file.
- `result_path` gives the result file of a run under the data directory.
- `check_stamps` looks at the canary, run and sweep results. A result with another hash is refused. One with none is refused when strict, else its name is returned so the report can skip it.
- `canary_approved` is true only when the canary report for the prefix exists and holds an approval.
