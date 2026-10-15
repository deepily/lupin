---
capability: rest-services-task-write-validators
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - cosa.rest.task_store_rules.UnscopedQueryError@4279050ae9
  - cosa.rest.task_store_rules.validate_create@e18f4bbff8
  - cosa.rest.task_store_rules.validate_patch@ed3993792e
  - cosa.rest.task_store_rules.normalize_patch_fields@7a7678ba1b
  - cosa.rest.task_store_rules.soft_guard_title@d4684b0ae8
  - cosa.rest.task_store_rules.validate_edit_title_length@5519b19ff5
  - cosa.rest.task_store_rules.validate_terminal_edit_fields@56ffc3ff2c
  - cosa.rest.task_store_rules.validate_terminal_title_prefix@f09571b53c
  - cosa.rest.task_store_rules.validate_no_envelope_tail@4f6427cf15
  - cosa.rest.task_store_rules.envelope_tail_tag@14b242fd0f
---
# Task store write validators

Pure checks on what a create, an edit or a closed-row correction may carry. The `validate_*` functions return a list of error strings, empty when clean; the router turns a non-empty list into a 422. Overview: [[task-store]].

## What it does
- `validate_create( item_class, gate_class, priority, authority, urgency )` checks that each of the five values is in its enum and returns one error per bad field.
- `validate_patch( fields )` needs at least one editable field and checks title, priority, gate class and urgency. `normalize_patch_fields` canonicalizes `owner_persona` and `accountable_manager` and keeps an explicit `None`.
- `soft_guard_title( title, body, cap )` trims a title over 120 characters on create and moves the overflow into the body, so nothing is discarded. `validate_edit_title_length` rejects an over-cap title on edit instead.
- `validate_terminal_title_prefix( old, new )` accepts a closed row's new title only as `"<MARKER> — <old title>"` with a marker of `WITHDRAWN`, `SUPERSEDED` or `CORRECTED`.
- `validate_terminal_edit_fields( fields, current_title, status )` refuses everything on a terminal row except that title prefix, and refuses it if any other field rides along.
- `envelope_tail_tag( text )` names a tool-call closing tag a text ends with, or `None`. `validate_no_envelope_tail( fields )` returns one error per free-text field that ends in one; it never edits the value.
- `UnscopedQueryError` is raised by the repository when an unscoped query matches more than 50 non-terminal rows and `unscoped_audit` is not set. The router answers 400.

## Don't
- Don't expect a title edit to be trimmed. Create trims; edit rejects.
- Don't send a priority change with a correction prefix on a closed row. The whole patch is refused.

## Invariants
- `validate_create` returns one error per bad field.
