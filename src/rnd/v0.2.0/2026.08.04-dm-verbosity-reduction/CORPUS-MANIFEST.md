# Arm 4 corpus manifest

**The corpus itself is deliberately NOT in git.** It is 4.1 MB of real DM
bodies carrying a live email address, unreleased defect discussion, and named
colleagues. Committing it to make the numbers auditable would trade a
reproducibility problem for a disclosure one.

What is committed instead is everything needed to **verify you have the same
file** and to **re-derive the same sample** from it. That is the auditable part;
the bodies are not.

> Found because the gitignore trap had a third instance. Two outputs were caught
> first — a scratchpad, then `io/**` — and the INPUT was still sitting in
> `src/tmp/`, ignored at `.gitignore:5`. Every number in every arm-4 document
> pinned to a file nobody else could obtain. (María, 2026-08-07.)

## The pin

| | |
|---|---|
| Path (on the dev box) | `src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl` |
| Source | `src/tmp/dm_traffic.jsonl` — the live two-arm pilot capture, still growing |
| Pinned | 2026-08-07 by Mr. Radio 🦉 |
| Records | **2,951** |
| Bytes | 4,100,108 |
| **sha256** | `94b1c192bf777e03ac84e4599d30a34204289aa1d44e1548b1dc93db3d185d1d` |
| sha256[0:16] | `94b1c192bf777e03` |

Verify with:

```bash
sha256sum src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl
wc -l      src/tmp/arm4/dm_traffic_snapshot_2026.08.07.jsonl
```

A different digest means a different corpus, and every ratio in the arm-4
documents should be re-derived rather than compared across it.

## Band pools

Bands are by WORD COUNT of the body. Every arm-4 target is scaled by band, so a
run that does not reproduce these pool sizes is not sampling the same thing.

| band | pool | target compression |
|---|---|---|
| <80 | 791 | 15% |
| 80-150 | 1,379 | 30% |
| 150-250 | 670 | 45% |
| 250+ | 111 | 60% |
| **total with a body** | **2,951** | |

## The sample rule

**Deterministic stride within each band — no RNG.** Given the same file, the same
per-band count reproduces the same messages exactly:

```python
by_band[ band ] = [ every body whose word count falls in that band, in file order ]
stride          = max( 1, len( pool ) // PER_BAND )
sample          = pool[ ::stride ][ :PER_BAND ]
```

Implemented in `live_corpus_run.py`. That is why no seed is recorded: there is
nothing to seed.

## Why not just commit a redacted corpus

Redaction would have to survive the freeze protocol's own extractor, which is
tuned for RECALL — it deliberately over-freezes. A redactor with the same recall
would strip most of what makes the corpus a realistic test, and one with less
recall would leak. The manifest avoids the choice.
