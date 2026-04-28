# WG-5 — Add `lxml` to deps + audit other unguarded optional imports (1 FAIL)

## Root cause

`test_simple_agents_instantiation_smoke.py:43` instantiates `CalendaringAgent`, which fails with `lxml not found, please install or use the etree parser.` This is a runtime dep gap inside CalendaringAgent's parser selection.

## Approach

Add `lxml` to `pyproject.toml` (small, stable, well-known). It will be installed automatically by `uv sync` when WG-1 rebuilds the image. CalendaringAgent already wants it.

If the user prefers not to add the dep, alternative is to change CalendaringAgent's parser selection to fall back to `etree` (stdlib). Recommendation: add the dep — simpler.

## Audit step

Before `pyproject.toml` edit, sweep `src/cosa/agents/` for other unguarded optional imports that could surface next month:

```
grep -rEn '^from (peft|lxml|onnx|tensorrt|bitsandbytes|flash_attn|deepspeed|vllm) import' src/cosa/
```

Anything outside `peft_trainer.py` and `cosa/agents/<x>/__init__.py` boundaries that lacks try/except gets added to a follow-up backlog item.

## Acceptance

- `pyproject.toml` includes `lxml`.
- After image rebuild (WG-1), `test_simple_agents_instantiation_smoke` passes.
- Audit output captured in 90-execution-log.md; any extra unguarded imports filed as backlog.

## Files

- `pyproject.toml` (1 line) — adds `lxml`
- (Image rebuild piggybacks on WG-1.)

## Status

- [ ] Audit grep
- [ ] Add `lxml` to pyproject.toml
- [ ] (Image rebuild gated by WG-1)
