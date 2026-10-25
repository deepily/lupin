---
capability: iterative-debugging-agent
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent@cc6cc3c51e
  - cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent.run_prompts@af2bd69ea5
  - cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent.is_code_runnable@9bc0fdfb4e
  - cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent.was_successfully_debugged@3c9965d4d0
  - cosa.agents.iterative_debugging_agent.IterativeDebuggingAgent.restore_from_serialized_state@47a76f095b
  - cosa.agents.agent_base.AgentBase.run_code@5d9d45ccfb
  - cosa.agents.agent_base.AgentBase.run_prompt@090b82fe89
  - cosa.agents.io_models.xml_models.IterativeDebuggingMinimalistResponse@0c621af2fb
  - cosa.agents.io_models.xml_models.IterativeDebuggingFullResponse@15b81ce049
---
# Iterative debugging agent

An `AgentBase` subclass that asks an LLM to fix code that just failed, runs the fix, and reports whether it worked. `AgentBase.run_code` is its only caller. It is the fallback described under "When code fails" in [[small-agents-core]].

## What it does
- `AgentBase.run_code` calls it when auto-debug is on and generated code fails. It passes the error text and `/io/code.py`, then tries `minimalist=True` and, if that fails, `minimalist=False`.
- The minimalist prompt asks for one line: the XML tags are `thoughts`, `line-number`, `one-line-of-code` and `success`. The full prompt asks for `thoughts`, `code`, `example`, `returns` and `explanation`.
- On a minimalist success, `_patch_code_in_response_dict` reads the file again, swaps the one line, and keeps the result in memory only. The file on disk is not rewritten.
- `run_prompts` then runs the code. `was_successfully_debugged` is true only when the run completed; `code` and `code_response_dict` hold the fix.

## Invariants
- An exception in one mode is caught and logged by `run_code`, so the other mode still runs. When both fail, `run_code` raises `CodeGenerationFailedException`.
- `run_prompts` loops over the keys in `llm model keys for debugger`, which the constructor keeps as `llm_model_keys`. Each pass sets `self.model_name` to that key before `run_prompt`, so a second key asks a different model. The last key ends the loop.
- The code file must exist when the agent is built. The constructor reads it to number its lines, and raises `FileNotFoundError` if it is missing.
- A minimalist reply with `success` other than `True` empties `code`, so that pass runs nothing.
- `run_code` is the `AgentBase` method, so the debugged code runs as a child process with no sandbox.

## How to extend
- Use `serialize_to_json` and `restore_from_serialized_state` to save and replay an attempt. Restore rebuilds from `error_message` and `path_to_code`, so the file must still be there.
- `restore_from_serialized_state` calls `AgentBase._restore_from_data` with the error message and code path, then the debug flags.
- The smoke test at the foot of the module writes a broken file to `path to code execution file` and needs a reachable LLM.
