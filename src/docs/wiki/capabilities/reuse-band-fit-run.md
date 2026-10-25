---
capability: reuse-band-fit-run
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reuse_band_fit_run.estimate@8c54b964d9
  - lupin_mcp.reuse_band_fit_run.Sink@be35713e67
  - lupin_mcp.reuse_band_fit_run.capture_replays@7dd0f9e737
  - lupin_mcp.reuse_band_fit_run.overlaps@e34780f692
  - lupin_mcp.reuse_band_fit_run.packed_context@e1be1ff670
  - lupin_mcp.reuse_band_fit_run.check_manifest@ec3f1d9fd6
  - lupin_mcp.reuse_band_fit_run.make_asks@b20c079154
  - lupin_mcp.reuse_band_fit_run.quantile@da7d661ef4
  - lupin_mcp.reuse_band_fit_run.spreads@9adbb38cdd
  - lupin_mcp.reuse_band_fit_run.fit_band@49b6b05f61
  - lupin_mcp.reuse_band_fit_run.gather@b835b4b940
  - lupin_mcp.reuse_band_fit_run.receipt@6ed45b0260
  - lupin_mcp.reuse_band_fit_run.write_once@197e8d9bb6
  - lupin_mcp.reuse_band_fit_run.live_stage@e47579c16d
  - lupin_mcp.reuse_band_fit_run.one_prefix@f93eef0d69
  - lupin_mcp.reuse_band_fit_run.stage_record@1e2e1f17d4
  - lupin_mcp.reuse_band_fit_run.check_ceiling@5b78eb8e98
  - lupin_mcp.reuse_band_fit_run.derive_needs@12d94938e7
  - lupin_mcp.reuse_band_fit_run.main@557c4dca08
  - lupin_mcp.reuse_band_fit_run.cli@7e9a8d4cfe
---
# Reuse band-fit run
The band fit measures how far Jev's per-entry overlap moves between repeats, to set the uncertain band of the verdict. Each need gets one candidates-route lookup, then five live replays of its receipt. A canary of five needs is read first. See [[reuse-flip-rate-measure]].
- `derive_needs` picks the needs from the frozen end-to-end needs, ordered by the sha256 of a seed written down first. It leaves out members that are not sendable entries and records them under `skipped`.
- `estimate( needs )` is the token estimate: needs times one lookup plus the repeats, entries per ask and tokens per entry. `check_ceiling` refuses a ceiling above the estimate times the factor. `one_prefix` reads the one ledger prefix.
- `live_stage( top )` builds the production candidate stage with its refresher off, so a lookup cannot rebuild the vector set the run is pinned to. `check_manifest` refuses a stage whose vector set is not the pinned one. `stage_record` is the arm, K and set hash each result file carries.
- `packed_context( ctx, stage )` returns a copy of the run's context with the candidate stage and the packing the lookup ships with. Packs are cut from the whole shortlist sorted by id.
- `make_asks` builds the lookup and then one ask per repeat. `Sink` keeps each need's lookup receipt id. `capture_replays` records every sweep a replay makes, because a replay's public result holds the verdict only.
- `overlaps( sweeps )` reads each answered entry's overlap, reuse plus extend, and lists answers the verdict layer would call malformed.
- `gather` collects each entry's overlaps from the complete repeats of the result files, and names needs with repeats missing.
- `spreads` gives each entry's mean, largest deviation and span over its draws. `quantile( values, q )` is nearest-rank.
- `fit_band` takes entries whose mean overlap lies near a cut-off. The band is a high quantile of their deviations, rounded up to three places and never under the labelled set's minimum.
- `receipt` builds the finished run's record with the band, its sensitivity, token totals and raw draws. `write_once` writes a JSON file whole under a name that must not exist.
- `main` runs one step: `derive-needs`, `estimate`, `canary`, `approve`, `run` or `report`. `cli` turns a refusal into one line and exit code 2.
