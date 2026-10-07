---
capability: small-agents-core
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - cosa.agents.agent_base.AgentBase@dcdd36082a
  - cosa.agents.agent_base.AgentBase.do_all@7cdb641a9f
  - cosa.agents.agent_base.AgentBase.run_code@5d9d45ccfb
  - cosa.agents.math_agent.MathAgent@4676111b43
  - cosa.agents.weather_agent.WeatherAgent@f952508e2a
  - cosa.agents.receptionist_agent.ReceptionistAgent@ae4a283815
  - cosa.agents.calculator.agent.CalculatorAgent@5d4c47e913
  - cosa.agents.calculator.agent.CalculatorAgent.run_code@0b641aec1b
  - cosa.rest.v2.flow.AskFlow.ask@73da1cd4d3
  - cosa.utils.util_code_runner.assemble_and_run_solution@88a30dccaf
---
# Small agents core

Seven small agents answer one voice or text request each. All extend `AgentBase` and run inline on the queue's consumer thread, not in the agentic pool.

## The run path
- `do_all` is `run_prompt`, then `run_code`, then `run_formatter`, and returns the conversational answer. `run_prompt` asks the LLM and parses its XML reply with no fallback. The calculator overrides `do_all`.
- `run_code` runs the generated code through `assemble_and_run_solution`. `run_formatter` makes a second LLM call to phrase the result.
- The constructor raises `ValueError` when both `question` and `last_question_asked` are empty. A subclass must supply its routing command, prompt and XML tag names.
- `AgentBase` caches nothing. The queue saves a solution snapshot after a clean run, except for the Receptionist, Weather and CRUD agents.

## The agents
- `MathAgent` has the LLM write code that runs. It skips the LLM formatter when `formatter prompt for math terse` is true. Only Development sets it, and both Testing sections inherit that; the code default is false.
- `CalendaringAgent`, `TodoListAgent` and `DateAndTimeAgent` follow the same path with a CSV or the app time zone in the prompt.
- `WeatherAgent.run_prompt` raises `NotImplementedError` and `do_all` skips it. Its `run_code` calls `LupinSearch`, then the formatter runs.
- `ReceptionistAgent` takes the `answer` tag as the reply and runs no code. It formats only when the category is not `benign`.
- `CalculatorAgent` asks the LLM for a `<calc_intent>` block, and plain Python then does the sum. It supports arithmetic, unit conversion, price comparison and mortgage.
- The calculator hands off to a `MathAgent` when the intent will not parse, the operation is unsupported, or a unit is missing or unknown. A bad operand raises `CodeGenerationFailedException`.

## Routing
- `AskFlow.ask` checks the question, asks the LLM router for a command, then looks it up. An unknown command goes to the receptionist. The old `TodoFifoQueue.push_job` has no caller.
- A registry lookup builds math, calculator, datetime, todo, calendar and weather. Calendar and todo become CRUD forks, as shipped. The receptionist comes from the flow's own factory.

## When code fails
- With `debug auto` true, as shipped, an iterative debugger tries twice over the models in `llm model keys for debugger`. Only the Development section sets that key; Production is not traced. If both fail the job goes to the dead queue. With it false, `run_code` returns nothing, the formatter still runs, and the job is dead-lettered with the default apology.
- The code runs as a plain `python3` child process with a 60 second timeout. There is no sandbox and no import limit.
