---
capability: training-corpus-and-trainer-tools
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.training.corpus_fingerprint.collect_corpus_entries@dc4a9c45b9
  - cosa.training.corpus_fingerprint.compute_fingerprint@dbf939a463
  - cosa.training.corpus_fingerprint.fingerprint_path@8692f942f9
  - cosa.training.corpus_fingerprint.write_stamp@db79c99a41
  - cosa.training.corpus_fingerprint.read_stamp@1c8cb9b81c
  - cosa.training.corpus_fingerprint.artifact_exists@0bf4c7e3c8
  - cosa.training.corpus_fingerprint.describe_mismatch@41f9399489
  - cosa.training.corpus_fingerprint.main@d7d146bed5
  - cosa.training.peft_trainer.parse_arguments@9e5fd181be
  - cosa.training.peft_trainer.check_env@3c592ada82
  - cosa.training.peft_trainer.is_root@bf7f8e207e
  - cosa.training.peft_trainer.invoked_with_sudo@dac86b7769
  - cosa.training.peft_trainer.check_privileges@38cdc89ecc
  - cosa.training.peft_trainer.print_gpu_memory@5e44df43c9
  - cosa.training.peft_trainer.release_gpus@59a3910b8f
---
# Training corpus and trainer tools

The corpus fingerprint that guards a training run, and the process helpers `peft_trainer` runs around it. [[model-training]] describes the run itself.

## Corpus fingerprint
- `collect_corpus_entries` lists every corpus file that feeds the artifact, in manifest order, as dicts with `manifest`, `command` and `path`.
- `compute_fingerprint` hashes what the loader sees in each file. It returns the version, algorithm, projection, `corpus_hash` and each file's line count and `sha256`.
- `fingerprint_path` names the sidecar stamp beside the three JSONL artifacts. `write_stamp` writes it and returns the stamp. `read_stamp` returns `None` when there is no sidecar. `artifact_exists` is true only when all three artifact files are present.
- `describe_mismatch` labels the stamped `ARTIFACT-SIDE` and the on-disk `CORPUS-SIDE`. It names both hashes, each differing file and each line-count move, and says what to do for either choice.
- `main` is the command line for the two training arms. `verify` prints the report and returns an exit code, and `stamp` writes the sidecar and returns 0.

## Trainer helpers
- `parse_arguments` parses the trainer's command line. `check_env` returns the `LUPIN_ROOT` path, and exits when a required variable is missing.
- `is_root` is true for user id 0. `invoked_with_sudo` is true when `SUDO_UID` is set. `check_privileges` exits unless `is_root` is true, and sudo only changes a debug message.
- `print_gpu_memory` prints total, allocated and reserved gigabytes and utilization for each GPU, or a message when there is none.
- `release_gpus` moves models to CPU, deletes them, collects garbage and clears the CUDA cache. `nuclear_kill_button=True` also kills GPU processes and resets the GPUs.

## Don't
- Don't call `is_root` on a system without Unix user ids, or `write_stamp` before the artifact directory exists and is writable.
- Don't pass `nuclear_kill_button=True` without the rights to kill GPU processes. A mismatch report labels both sides and decides neither.
