---
capability: dm-experiment-schedule
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.dm-experiment.generate_schedule.randomize_with_max_run@9eced06842
  - scripts.dm-experiment.generate_schedule.mirror_arm@6bb50b9ce8
  - scripts.dm-experiment.generate_schedule.build_extension_slots@368e77c1cb
  - scripts.dm-experiment.generate_schedule.build_week2_slots@dd1370926c
  - scripts.dm-experiment.generate_schedule.build_schedule@7954ccbcc1
  - scripts.dm-experiment.generate_schedule.serialize@32af58c1f1
  - scripts.dm-experiment.generate_schedule.default_output_path@290f4dec33
  - scripts.dm-experiment.generate_schedule.write_schedule_file@4f9f2fac9b
  - scripts.dm-experiment.generate_schedule.main@72447a5011
---
# DM verbosity pilot: the arm schedule
`src/scripts/dm-experiment/generate_schedule.py` writes the fixed, git-tracked schedule that tells the server which arm runs in each hour. A recorded seed makes a re-run reproduce the file byte for byte. The analysis is on [[dm-experiment-arm-rows-and-pairs]].
- `randomize_with_max_run` permutes a list of arm labels so no run of one label is longer than the limit. It is deterministic for a seeded generator.
- `mirror_arm` returns the opposite arm, so Wednesday mirrors Tuesday. It raises `ValueError` for any other label.
- `build_extension_slots` builds 28 slots for Thursday, Friday and Saturday, 14 per arm, tagged with the extension block id.
- `build_week2_slots` builds 56 slots for week two, 28 per arm, tagged with the week-2 block id.
- `build_schedule` builds the whole schedule from the seed. The original Tuesday and Wednesday block stays byte-identical for a given seed.
- `serialize` gives canonical JSON: sorted keys, two-space indent and a trailing newline.
- `default_output_path` is `src/conf/dm-experiment-schedule.json` under the project root.
- `write_schedule_file` builds, verifies and writes the file. `main` writes it, or with `--check` exits 1 when the file on disk differs from a fresh build.
