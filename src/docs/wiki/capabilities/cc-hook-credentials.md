---
capability: cc-hook-credentials
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.hook_credentials.get_hook_credentials@a5bb126f2f
  - lupin_cli.claude_code.hooks.lib.hook_credentials.get_owner_credentials@b747d06683
---
# Hook credentials

Hooks that call the Lupin API need a login. This capability reads it from the unified config file `~/.lupin/config`, so no hook carries a password of its own.

## What it does
- `get_hook_credentials` returns `( email, password )` for the current project. The project name comes from the shared session-bridge resolver, so a non-lupin session reads its own section.
- An explicit `project` argument overrides that name.
- `get_owner_credentials` returns the human owner's `( email, password )` from the `[owner]` section.
- The notification listener uses the owner login to find the owner's user id and stamp it on the bridge file.

## Don't
- Don't use the owner login for a service call. It is the human's account, used only to resolve their user id.
- Don't catch the errors and carry on with a guessed login. A missing file or section should stop the hook.

## Invariants
- A missing `~/.lupin/config` raises `FileNotFoundError`.
- A missing section or key raises `ValueError`.
