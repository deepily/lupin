---
capability: merge-cc-hooks
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.lib.merge_cc_hooks.normalise_command@562261b2c3
  - scripts.lib.merge_cc_hooks.normalise_entry@08c141a42e
  - scripts.lib.merge_cc_hooks.entries_by_event@f9e8802a08
  - scripts.lib.merge_cc_hooks.commands_by_event@432a943ed8
  - scripts.lib.merge_cc_hooks.unknown_entries@04ad392033
  - scripts.lib.merge_cc_hooks.merge@76c7fc0d8d
  - scripts.lib.merge_cc_hooks.main@8578500b01
---
# Merge Claude Code hooks

Merges the repo's Claude Code hooks template into a settings file, or refuses and says why. The installer used to replace the whole `hooks` key. A settings file holding a hook the template did not know lost it, with only a backup copy to show for it.

## Comparing
- `normalise_command` drops a leading interpreter, such as `python`, `python3` or `python3.N`, bare or by path, quoted or not. Two spellings of one script then compare equal. A program that merely ends in python is kept, and nothing else changes.
- `normalise_entry` reduces one hook entry to a canonical JSON string with its matcher and every field of every hook. Two entries are equal only when the matcher, hook order and every other field agree.
- `entries_by_event` lists the entries of a `hooks` key per event, in file order. An event whose value is not a list is skipped.
- `commands_by_event` collects the raw command strings per event, ignoring entries that are not dicts or have no command.
- `unknown_entries` returns, per event, the settings entries the template does not carry exactly. An entry made only of allow-listed commands counts as known.

## Merging
- `merge` returns an exit code and a message. Missing settings are written fresh with exit 0. Unreadable settings, or a file that is not a JSON object, stay untouched with exit 2.
- Settings with an unknown entry stay byte-identical with exit 3, and the message lists each one under its event.
- With `--force`, or when nothing would be lost, `merge` makes a backup copy first and replaces only the `hooks` key. Every other key stays.
- `main` runs the merge from the command line, printing the message to stdout on success and stderr otherwise.
