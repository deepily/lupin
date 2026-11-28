---
capability: prediction-zero-model-proof
pin_algorithm: py3.13.xaad549/ts5.9.3
pins:
  - scripts.zero_model_proof.install_guards@38024a4c0a
  - scripts.zero_model_proof.pick_slice@f11d36f5f9
  - scripts.zero_model_proof.main@2d6a311e0b
---
# Proof that a replay makes no model call

`src/scripts/zero_model_proof.py` shows that a replay slice calls no model. [[prediction-rerun-phases-script]] uses its guards.

## What it does
- `install_guards( calls )` replaces the model-client, embedding and Anthropic and OpenAI client entry points with functions that count the attempt and raise `AssertionError`. A socket connect to a non-loopback address does the same. A client library that is not installed is reported and skipped.
- `pick_slice( asks, per_type )` takes the first `per_type` eligible asks of each response type, in cohort order.
- `main` needs `--vectors`, a question-vector side file. It reads the cohort from the database and replays the slice for yes/no and multiple choice, with the always-yes and three-way arms.
- It then calls one patched entry point as a control, so a count of 0 is shown able to rise.
- It returns 0 when the replay attempted no call and that control fired, else 1.

## Don't
- Don't call `install_guards` in a process that must reach a model later. It restores nothing.
