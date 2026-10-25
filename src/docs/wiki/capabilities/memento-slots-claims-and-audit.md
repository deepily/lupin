---
capability: memento-slots-claims-and-audit
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - lupin_mcp.memento_repo_root.repo_root_owning@e8e4cdb494
  - lupin_mcp.memento_repo_root.slot_base_root@224b4ae134
  - lupin_mcp.memento_merge_claim.default_ancestry_probe@4933ba4c44
  - lupin_mcp.memento_merge_claim.find_merge_claims@de3eca6c25
  - lupin_mcp.memento_merge_claim.refuted_merge_claim@8ecce5c911
  - lupin_mcp.memento_slot_audit.verdict_for@59df0b75b2
  - lupin_mcp.memento_slot_audit.audit_one@4653558fca
  - lupin_mcp.memento_slot_audit.render_report@3d167b6785
  - lupin_mcp.memento_slot.acceptable_slot_targets@74e0265f9e
  - lupin_mcp.memento_slot.mirror_home_clause@4b744fdc30
  - lupin_mcp.memento_slot.resolve_repo_root@adb0604dce
  - lupin_mcp.memento_slot.short_sid@c860e3950b
  - lupin_mcp.memento_slot.slot_pointer_path@46a0a01eb7
  - lupin_mcp.memento_slot.slot_record_path@cc38b1a36d
  - lupin_mcp.memento_slot.stray_record_clause@deee28ad14
  - lupin_mcp.memento_slot.verify_memento_at_any_readable_slot@232c373b46
---
# Memento slots, claims and audit

Where a seat's memento must live, how a path is checked against that, and how a stale merge claim is refuted. The reap and re-spin tools use these ([[mcp-session-spawn-and-reap]]).

- A memento has two slots. Each has a per-persona pointer and a per-session record. The `io` slot holds `io/mementos/<persona>.md` and `<persona>-<sid8>.md`. The `root` slot holds `.claude-memento-<persona>.md` and `.claude-memento-<persona>-<sid8>.md`.
- `slot_pointer_path` and `slot_record_path` build those two paths from the repo root, persona and slot. `short_sid` is the one place a session id is cut to 8 lowercase characters. `acceptable_slot_targets` returns the pointer and record path a seat may legitimately use.
- `repo_root_owning( start )` returns the repo root whose `io/mementos/` is the canonical slot. A linked worktree resolves to the main checkout. Every degraded fallback prints a warning.
- `slot_base_root( start, slot )` is the single answer for either slot. `resolve_repo_root` returns the root that owns this seat's memento for a slot.
- `verify_memento_at_any_readable_slot` proves the memento at the primary slot, then at the `io` slot. A complete, fresh file at the fallback slot passes.
- `stray_record_clause` names up to three records this persona has under another session id. `mirror_home_clause` adds a sentence when the path is under the out-of-repo mirror home.
- `find_merge_claims( text )` lists each negative merge claim, such as "not merged", that names a commit in the same clause, as (line, sha, line text). A line showing a live query is skipped.
- `refuted_merge_claim( text, repo_root )` returns the first claim git proves false, because the commit is already an ancestor of HEAD. It returns None when no claim can be refuted.
- `default_ancestry_probe( sha, repo_root )` is True for an ancestor of HEAD and False for a commit that is not. It is None when git cannot answer, which allows the memento.
- `audit_one` classifies one memento file by comparing the `slot=` its header declares with where it sits. `verdict_for( declared, actual )` names the relationship and the remedy.
- `render_report( findings )` lists every actionable file by name, with the corpus size. It reports no single defect count, because the causes differ.
