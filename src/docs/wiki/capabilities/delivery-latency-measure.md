---
capability: delivery-latency-measure
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.delivery_latency.parse_boot_intervals@cc06a15837
  - scripts.delivery_latency.up_hours@8c951de3b6
  - scripts.delivery_latency.largest_silent_stretch@7a7dfd94d8
  - scripts.delivery_latency.read_deliveries@065a26020c
  - scripts.delivery_latency.main@7291a9b168
---
# Delivery latency measure

Measures how long each commit waits before it lands on a target branch. It is the instrument behind the delivery-route research figures. It is kept as a script, because a number whose only artifact lives in a temporary folder cannot be re-derived. The metric was rebuilt four times, so read the script's header before trusting a figure.

## Why per commit
- The final version measures each commit against the landing that carried it. Earlier versions used a committer date, an author date of the tip, the oldest commit or the newest commit. Each was either rewritten by a cherry-pick, confounded with stack size, or masked a stalled commit riding with fresh work.
- Splitting a wait at "the branch finished" is unfalsifiable, because any commit made while waiting resets it. The script computes it only as an unfalsifiable term and never as evidence. What survives is the largest silent stretch, a gap that has already happened.

## Functions
- `parse_boot_intervals` parses `journalctl --list-boots` output into sorted start and end pairs. It returns an empty list when nothing parses, so the caller can tell no boots from boots found.
- `up_hours` counts the hours of a span that fall inside any boot interval.
- `largest_silent_stretch` finds the longest commit-free stretch inside a delivery, counted in box-up hours. The gap ending at the landing is a candidate: branch finished, then sat.
- `read_deliveries` reads the deliveries to a branch from its reflog. It counts entries whose verb starts with merge, which includes fast-forward deliveries that a merge-commit scan misses.
- `main` refuses when it parses zero boot intervals or finds zero deliveries. It then prints the tail episodes and their box-up hours. Box up means an action window existed, never that a person failed to act.
