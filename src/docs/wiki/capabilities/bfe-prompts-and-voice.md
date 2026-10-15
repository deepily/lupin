---
capability: bfe-prompts-and-voice
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.bug_fix_expediter.prompts.diagnosis.build_diagnosis_prompt@5f0ee418ad
  - cosa.agents.bug_fix_expediter.prompts.proposal.build_proposal_prompt@848874336e
  - cosa.agents.bug_fix_expediter.prompts.fix.build_fix_prompt@51b3568dad
  - cosa.agents.bug_fix_expediter.prompts.fix.build_verification_prompt@244bb5057b
  - cosa.agents.bug_fix_expediter.prompts.fix.build_redelegation_prompt@6c7918e942
  - cosa.agents.bug_fix_expediter.cosa_interface.notify_progress@792a535c1d
  - cosa.agents.bug_fix_expediter.cosa_interface.ask_confirmation@0ecc4641d7
  - cosa.agents.bug_fix_expediter.cosa_interface.get_feedback@d9e1ff4c28
  - cosa.agents.bug_fix_expediter.cosa_interface.present_choices@aea479611d
  - cosa.agents.bug_fix_expediter.voice_io.reconfigure@8265f4719a
---
# Bug fix expediter prompts and voice

These build the text each agent role receives and carry the questions the expediter asks the user. The phases that call them are in [[fix-expediter-bfe]].

## What it does
- `build_diagnosis_prompt` builds the lead agent's prompt. The first iteration holds the dead job's error, stack trace, question, routing command and metadata.
- From the second iteration the diagnosis prompt carries the prior diagnosis and asks for a refinement. Queued user messages are appended.
- `build_proposal_prompt` builds the lead agent's proposal prompt from the diagnosis and the dead job. Feedback on a rejected proposal is added when given.
- `build_fix_prompt` tells the coder to apply only the selected fix's changes and then list the files it changed.
- `build_verification_prompt` tells the tester to write unit tests for the changed files, run them and report a pass or a fail verdict.
- `build_redelegation_prompt` returns the tester's failure text to the coder and says not to edit test files.
- `notify_progress` sends a progress message and does not wait. `ask_confirmation` returns a boolean, and `get_feedback` returns the user's spoken answer or `None`.
- `present_choices` sends multiple-choice questions and returns the answers keyed by header.
- All four voice functions set the module's sender id on a shared dispatcher before each call.
- `voice_io.reconfigure` binds the shared `voice_io` layer to this agent's `cosa_interface` again.

## Don't
- Don't skip `reconfigure` at the start of a run. Another agent's import may have bound the shared layer to its own sender.
