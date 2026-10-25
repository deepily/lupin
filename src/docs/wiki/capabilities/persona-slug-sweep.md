---
capability: persona-slug-sweep
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.sweep_persona_slug_canonicalization.topic_stem@3f352e945b
  - scripts.sweep_persona_slug_canonicalization.persona_segment_of_session@588ee57134
  - scripts.sweep_persona_slug_canonicalization.scan_topic_mismatches@d2ce7f00c3
  - scripts.sweep_persona_slug_canonicalization.scan_tmux_mismatches@0616d1444a
  - scripts.sweep_persona_slug_canonicalization.apply_topic_renames@bef012bf07
  - scripts.sweep_persona_slug_canonicalization.discover_owners_from_bridges@229375e602
  - scripts.sweep_persona_slug_canonicalization.run_sweep@5f207e6bc3
  - scripts.sweep_persona_slug_canonicalization.main@edfc4ef044
---
# Persona slug sweep

Renames non-canonical DM-topic files to their canonical persona slug. It is a dry run by default, and `--apply` is required to change the filesystem. It is owner-driven: it enumerates known persona owners and looks for non-canonical spellings of each owner's topic. A blind check of every `dm-*` stem would falsely flag ad-hoc, session-id and spawned-session topics.

## Reading names
- `topic_stem` returns the persona stem of a `dm-<stem>.md` file name, or an empty string for any other name.
- `persona_segment_of_session` recovers the persona segment of a spawned tmux session name such as `cc-author-mr-radio-1`. A name that does not match the spawn pattern returns `None`.

## Scanning
- `scan_topic_mismatches` finds topic files whose separator-agnostic key matches an owner but whose name differs from the canonical one, in the live folder and the archive. A canonical-only owner contributes nothing.
- Each finding carries a `merge_required` flag, true when the canonical file already exists. The sweep never merges two real files. That is the job of the dedupe-aware case migration script.
- `scan_tmux_mismatches` reports live spawned sessions whose persona segment is a non-canonical spelling of an owner. It is report-only, because renaming a live session would orphan its bridge link. The remedy is reap and respawn.
- `discover_owners_from_bridges` reads live persona owners from the active voice-persona bridges.

## Applying
- `apply_topic_renames` renames each finding without a merge requirement and skips the others, logging `renamed` or `skipped_merge_required` for each.
- `run_sweep` runs the scan against explicit inputs and prints a human report. It returns the topic and tmux findings, what was applied and a no-op flag.
- `main` parses `--apply` and `--persona`, defaults to the dry run and always returns 0, since it is a report and not a gate.
