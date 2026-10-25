---
capability: worktree-straggler-tickets
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.shared.worktree_straggler_tickets.RepositoryStragglerStore@a073439dbc
  - cosa.agents.shared.worktree_straggler_tickets.compose_archive_row@cf144d864e
  - cosa.agents.shared.worktree_straggler_tickets.compose_row@def6ab1c29
  - cosa.agents.shared.worktree_straggler_tickets.load_state@53db943f3b
  - cosa.agents.shared.worktree_straggler_tickets.open_archive_tickets@c63bfabe98
  - cosa.agents.shared.worktree_straggler_tickets.owner_for_branch@db8655adbc
  - cosa.agents.shared.worktree_straggler_tickets.owner_for_tree@7c67973f9f
  - cosa.agents.shared.worktree_straggler_tickets.project_for_tree@e87311afa3
  - cosa.agents.shared.worktree_straggler_tickets.straggler_key@20185c3e08
  - cosa.agents.shared.worktree_straggler_tickets.write_state@18d5c9e395
---
# Worktree straggler tickets

A tree refused for more than a day, or an archived branch whose work never landed, becomes a task-store row with an owner. See [[worktree-refusal-ledger]].

## What it does
- `straggler_key` returns `worktree:` plus the normalized tree path, one key per tree.
- `owner_for_tree` reads a seat tree name `seat-cc-<role>-<manager>-<n>` and names that manager as owner. Any other name goes to `maria`.
- `owner_for_branch` reads the last path segment of a branch, minus a rescue time stamp, as a tree name.
- `project_for_tree` returns the basename of the repository that holds the tree, or `lupin` outside any sandbox.
- `compose_row` builds the title, body, owner, project and key for one straggler. The body marks an estimated first-refused time.
- `compose_archive_row` builds the row for an archived branch, keyed `archive:` plus the archive ref, with the restore command.
- `open_archive_tickets` opens one row per archived branch whose commits did not land. An open row with the key is adopted.
- `load_state` and `write_state` read and atomically replace the sidecar holding `first_refused_at`, `estimated` and `ticket_id` per tree.
- `RepositoryStragglerStore` is the real store. It has `find_open`, `create` and `drop`.

## Invariants
- The store writes to the task repository directly, and not through `/api/tasks`, so the arbiter can close its own rows.
- Rows close as `dropped`, because a system actor has no honest receipt for `done`.
- `load_state` returns an empty dictionary for an absent or corrupt file. It reads the `trees` section through `load_json_section` ([[utils-atomic-json]]). `write_state` raises `OSError`, which the caller logs.
