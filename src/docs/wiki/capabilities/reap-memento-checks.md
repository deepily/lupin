---
capability: reap-memento-checks
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.reap_memento.seat_memento_slot@d22d72d360
  - lupin_mcp.reap_memento.seat_memento_root_record@fa71113630
  - lupin_mcp.reap_memento.verify_seat_memento_at_any_readable_slot@64ea2f2109
  - lupin_mcp.reap_memento.seat_repo_root@8ab6d431cb
  - lupin_mcp.reap_memento.resolve_pointer_target@80fcf3e6e2
  - lupin_mcp.reap_memento.parse_memento_header@8e87e46575
  - lupin_mcp.reap_memento.memento_body_lines@3b8e58d00b
  - lupin_mcp.reap_memento.verify_seat_memento@3962ca80e5
  - lupin_mcp.reap_memento.classify_slot_presence@4646ca9fcf
  - lupin_mcp.reap_memento.slot_record_header@feb1e50111
  - lupin_mcp.reap_memento.classify_slot_owner@47890e3d90
  - lupin_mcp.reap_memento.memento_alarm@c651cd7eaa
  - lupin_mcp.reap_memento.recheck_losing_seats@799653d989
  - lupin_mcp.reap_memento.coordinate_mementos@157f618ff8
  - lupin_mcp.reap_memento.describe_slot@1ac9ed00f9
  - lupin_mcp.reap_memento.format_slot_report@c22bf57246
  - lupin_mcp.reap_memento.main@deb11d57f5
  - lupin_mcp.reap_memento.withhold_notice@34e553926d
---
# Reap memento checks

Before a manager's reap kills a seat, these functions ask the seat for a memento and prove it is usable ([[mcp-session-spawn-and-reap]]). Slot paths are in [[memento-slots-claims-and-audit]].

- `seat_repo_root( ident )` reads the repo a seat sits in from its bridge `cwd`. It returns None when `cwd` is absent, and never falls back to the host's repo.
- `seat_memento_slot` is the bare pointer path `io/mementos/<persona>.md`. `seat_memento_root_record` is the root-slot record for one session. The root pointer is never used, because it was once shared by every seat.
- `resolve_pointer_target( slot_path, text )` follows a pointer's `current:` line to the record beside it, by basename only. `slot_record_header` parses the header of the record a slot names.
- `parse_memento_header( text )` returns the `memento-record` key-value pairs from the leading comment block, or an empty dict. `memento_body_lines` counts lines that are not blank, headings or comments.
- `verify_seat_memento` is usable only if the file is readable, big enough, has a content line, and carries a header naming this seat's session. The header time must be recent and not in the future. File mtime is never consulted.
- It also refuses a memento that says work is unmerged while naming a commit already in HEAD, when given a repo root.
- `verify_seat_memento_at_any_readable_slot` tries the io slot, the root record, then any io record whose own header names this session. A fallback hit says so in its reason.
- `classify_slot_presence` answers `present`, `empty` or `absent` for the bare slot. `classify_slot_owner` returns the other seat's session id when the slot holds a prior holder's memento.
- `coordinate_mementos` runs before any kill. It asks each seat and polls the slot, and returns one status per seat. These are `not_requested` when no memento was asked for, then `verified`, `written`, `timeout_no_memento`, `prior_holder_present`, `unparseable_present`, `unproven_present`, `skipped` and `skipped_no_cwd`.
- `recheck_losing_seats` re-reads the disk once after the kill. A seat whose own memento is now proven is upgraded. The input is not changed.
- `memento_alarm( outcomes )` is one sentence for the top of the reap result naming every seat killed without a usable memento. `withhold_notice` names every seat not killed, and why.
- `describe_slot` answers whether the memento sits where the reaper reads, as `ready`, `prior_holder`, `absent` or `present_unproven`. `format_slot_report` renders it, and `main` exits 0 only on `ready`.
