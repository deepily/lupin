---
capability: bug-injector
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.bug_injector.BugInjector@670fd390e9
  - cosa.agents.bug_injector.BugInjector.run_prompt@6863e7a4d2
  - cosa.agents.bug_injector.BugInjector.restore_from_serialized_state@bf383c265e
  - cosa.utils.util_code_runner.assemble_and_run_solution@88a30dccaf
  - cosa.agents.io_models.xml_models.BugInjectionResponse@e92f686130
---
# Bug injector

A test aid. It asks an LLM to break working generated code with one runtime-fatal edit, so the auto-debug path has something to fix. It is off unless a flag turns it on.

## What it does
- `BugInjector` is an `AgentBase` subclass built with a list of code lines. Its routing command is `agent router go to bug injector`, which names the prompt and the model.
- The prompt numbers the lines and asks for one syntax error inside a function body that stops the program from running. The reply carries a `line-number` and the replacement `bug` line.
- `run_prompt` parses the reply through `XmlParserFactory` into `BugInjectionResponse`, then writes the bug over that line.
- `assemble_and_run_solution` is the only caller. When `inject_bugs` is true it injects before it writes the code file and runs it.
- The failed run then enters the retry path in [[iterative-debugging-agent]].

## Invariants
- A line number of -1, 0 or past the end prints a banner and leaves the code unchanged. The original code then runs, so no bug was injected.
- On success `run_prompt` prepends a blank line so the 1-based number lines up. The returned list is one line longer, and the caller runs that list.
- The caller's list is not edited in place: the prepend builds a new list.
- `restore_from_serialized_state` always raises `NotImplementedError`.
- `debug` and `verbose` both default to true in the constructor, so a bare call is noisy.

## How it is used
- The INI key `debug inject bugs` is false in `[[Lupin: Baseline]]`. `v2_ask` (for `AskFlow`) and `TodoFifoQueue` read it and pass `inject_bugs` into each agent they build.
- `AgentBase.run_code` hands the flag to `RunnableCode.run_code`, and takes it as an argument, so a test can turn it on for one call.
- `cosa.agents.__init__` does not export the class. Import it from `cosa.agents.bug_injector`.
- The prompt is `src/conf/prompts/agents/bug-injector.txt`. The model is the `llm spec key for agent router go to bug injector` setting.
