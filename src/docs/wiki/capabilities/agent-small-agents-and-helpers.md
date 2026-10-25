---
capability: agent-small-agents-and-helpers
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.agent_base.CodeGenerationFailedException@7b3dea2f9c
  - cosa.agents.runnable_code.RunnableCode@a166b37df7
  - cosa.agents.calendaring_agent.CalendaringAgent@19a2dd1103
  - cosa.agents.date_and_time_agent.DateAndTimeAgent@c61bf1ab7b
  - cosa.agents.todo_list_agent.TodoListAgent@061888918c
  - cosa.agents.confirmation_dialog.ConfirmationDialogue@4ea86e3503
  - cosa.agents.receptionist_agent.fit_fragments_to_budget@d6aadcd96d
  - cosa.agents.two_word_id_generator.singleton@2da640dc1e
  - cosa.agents.two_word_id_generator.TwoWordIdGenerator@dab1864739
---
# Small agents and helpers

The code-generating agents share a base that runs generated code. These are the small agents built on it, plus the helpers beside them. The base itself is in [[small-agents-core]].

## What it does
- `RunnableCode` holds the generated code and its response. It can print the code, say whether any is runnable, run it and report whether it ran to completion.
- `CodeGenerationFailedException` means code was invalid and every debugging model also failed. The caller should treat it as a server error.
- `CalendaringAgent` answers event questions. Its prompt carries the events table's column names, event types and the first and last two rows.
- `DateAndTimeAgent` answers date and time questions by generating code. Its prompt names the configured app time zone, so the code reads the right clock.
- `TodoListAgent` answers todo questions. Its prompt carries the column names, list names and the first and last two rows as CSV.
- `ConfirmationDialogue` asks a model whether an utterance means yes or no. Ambiguous answers return the given default, or raise `ValueError` when none was given.
- `fit_fragments_to_budget` joins the newest fragments that fit a token budget and returns them oldest first. It uses a binary search over the count.
- `TwoWordIdGenerator` returns a random adjective and noun name that has not been issued before. When the pool is used up it appends letters to the noun.
- `singleton` is the decorator that makes `TwoWordIdGenerator` a single shared instance.

## Invariants
- `TodoListAgent`, `ReceptionistAgent` and `IterativeDebuggingAgent` restore through `AgentBase._restore_from_data`. It rebuilds the agent from its saved constructor arguments, then copies every other saved field onto it.
- `DateAndTimeAgent` does not support restoring serialized state. It raises `NotImplementedError`.
- Generated ids are two lowercase words, so they pass the session id check.
