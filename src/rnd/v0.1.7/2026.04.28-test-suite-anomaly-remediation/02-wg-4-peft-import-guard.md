# WG-4 — Optional `peft` import guard (3 FAILs)

## Root cause

`src/cosa/training/peft_trainer.py:12` performs unguarded:
```python
from peft import LoraConfig, prepare_model_for_kbit_training, PeftModel
```

`peft` is absent from the test image. Any test that imports the module — three `test_lora_env_update_smoke` tests — raises `ModuleNotFoundError` at **collection time**, before any test logic runs.

## Approach

Adopt the existing optional-dep idiom used by `src/cosa/orchestration/claude_code/dispatcher.py:50-65` (claude-agent-sdk).

```python
try:
    from peft import LoraConfig, prepare_model_for_kbit_training, PeftModel
    PEFT_AVAILABLE = True
except ImportError:
    PEFT_AVAILABLE = False
    LoraConfig = None
    prepare_model_for_kbit_training = None
    PeftModel = None
```

Functions that use these symbols raise `ImportError("peft not installed; pip install peft")` at call time. The 3 smoke tests only need module-import to succeed; they don't hit the trainer's training path.

## Acceptance

- `python -c "from cosa.training.peft_trainer import *"` succeeds without peft installed.
- 3 `test_lora_env_update_smoke` tests collect successfully and pass.
- Calling any function that needs peft (when it's not installed) raises a descriptive `ImportError`.

## Files

- `src/cosa/training/peft_trainer.py` (~10 lines)

## Status

- [ ] Edit `peft_trainer.py`
- [ ] py_compile
- [ ] Run `pytest src/tests/smoke/test_lora_env_update_smoke.py`
