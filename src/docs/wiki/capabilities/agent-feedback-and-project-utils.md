---
capability: agent-feedback-and-project-utils
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.agents.utils.feedback_analysis.is_approval@078cb0e352
  - cosa.agents.utils.feedback_analysis.is_rejection@6273d54251
  - cosa.agents.utils.feedback_analysis.extract_feedback_intent@637cdc8c04
  - cosa.agents.utils.sender_id.canonicalize_project_name@d19a7cf040
  - cosa.agents.utils.sender_id.detect_project@78436544c3
  - cosa.agents.utils.sender_id.detect_project_for_path@edd65d6a4d
  - cosa.agents.utils.sender_id.resolve_project_for_path@e843f0a26d
  - cosa.agents.claude_code.cosa_interface.notify_progress@ba2c8f21cd
  - cosa.agents.claude_code.cosa_interface.ask_confirmation@1a1a618d8f
---
# Agent feedback and project utilities

Three small helpers serve agentic jobs. One reads a spoken reply as approval or rejection. One names the project a path belongs to. One sends a progress note or a yes or no question from a Claude Code job.

## What it does
- `is_approval` is true when the feedback contains an approval signal or exactly matches a short word such as "yep". Empty or `None` input gives false.
- `is_rejection` is true when the feedback contains a change signal such as "instead" or "wait". Empty or `None` input gives false.
- `extract_feedback_intent` returns the two flags, the raw text and a `feedback_type` of `approval`, `change_request` or `additional_context`. Approval wins when both flags are set.
- `canonicalize_project_name` maps an already-resolved name through the alias table, so `planning-is-prompting` becomes `plan`. `None` stays `None`.
- `resolve_project_for_path` walks up to the first `.git` and returns the repository name, or `None` when there is none. A worktree resolves to its main repository.
- `detect_project_for_path` is the same walk. With no repository found it guesses the last path segment.
- That guess is printed to standard error.
- `detect_project` is `detect_project_for_path` applied to the current directory.
- `notify_progress` sends a fire-and-forget progress notification for a job. `ask_confirmation` asks a yes or no question and returns a bool.

## Don't
- Don't use the detect functions for a path you did not choose. They cannot tell a detection from a guess. Use `resolve_project_for_path`.
