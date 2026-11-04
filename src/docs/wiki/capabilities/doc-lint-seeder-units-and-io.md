---
capability: doc-lint-seeder-units-and-io
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.repo.doc_lint.labelled_set_seeder.read_jsonl@e002204e38
  - cosa.repo.doc_lint.labelled_set_seeder.write_jsonl@5610f5accf
  - cosa.repo.doc_lint.labelled_set_seeder.write_json@b6397e77a3
  - cosa.repo.doc_lint.labelled_set_seeder.sha256_file@58299c4f8c
  - cosa.repo.doc_lint.labelled_set_seeder.load_stoplist@de499ed34f
  - cosa.repo.doc_lint.labelled_set_seeder.stratum_of@6e2d4d856b
  - cosa.repo.doc_lint.labelled_set_seeder.unit_of@9f734d2d36
  - cosa.repo.doc_lint.labelled_set_seeder.is_short@08c509dd3d
  - cosa.repo.doc_lint.quota_split.quotas@7199bfeea2
  - cosa.repo.doc_lint.labelled_set_seeder.short_quota@fc2fd97093
  - cosa.repo.doc_lint.labelled_set_seeder.strata_mix_of@f1d9ee8ecf
  - cosa.repo.doc_lint.labelled_set_seeder.split_units@530812ef62
  - cosa.repo.doc_lint.labelled_set_seeder.partition_units@b49db27cda
  - cosa.repo.doc_lint.labelled_set_seeder.disjoint@e1f9f522bb
  - cosa.repo.doc_lint.labelled_set_seeder.build_parser@d18e3bdca5
  - cosa.repo.doc_lint.labelled_set_seeder.main@e46dfd678d
---
# Doc-lint seeder units and I/O

The file helpers, strata and split partition of the labelled-set seeding script. A script, never a model, chooses what is removed or weakened in a real docstring. Each phase is its own command.

## Files
- `read_jsonl` returns the records of a JSON Lines file, skipping blank lines. `write_jsonl` and `write_json` sort keys, so the same rows give the same bytes. `sha256_file` hashes a file's bytes.
- `load_stoplist` reads one lowercased word per line and ignores `#` lines and blanks.

## Strata and quotas
- `stratum_of` returns `S` for 3 to 6 docstring lines, `M` for 7 to 12 and `L` for 13 or more, and `None` under 3. `is_short` is true for a span of 2 or 3 words.
- `strata_mix_of` returns the plan's mix, as shares that sum to 1 within 1e-9, from the default or a `--sizes-json` file.
- `quotas` splits a total by a mix with largest remainders, so the parts sum to the total. `short_quota` is `ceil( floor / 2 )` short spans per seeded kind.

## Splits
- `unit_of` returns a file's package directory, the unit never split across dev, gate and reserve. `split_units` shuffles units by seed, deterministically for a sorted input.
- `partition_units` gives each of `dev`, `gate` and `gate-reserve` a third of the shuffled units. `disjoint` says whether the splits share no file and no unit.

## Command line
- `build_parser` builds one subcommand per phase, and `main` runs one phase and returns its exit code.
