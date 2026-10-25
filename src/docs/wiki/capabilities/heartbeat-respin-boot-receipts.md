---
capability: heartbeat-respin-boot-receipts
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - cosa.agents.heartbeat_arbiter.respin_wake_check.classify_memento_slot@c9ad07f2fd
  - cosa.agents.heartbeat_arbiter.respin_wake_check.receipt_path@3b080463ed
  - cosa.agents.heartbeat_arbiter.respin_wake_check.describe_block@12d86f7529
  - cosa.agents.heartbeat_arbiter.respin_wake_check.build_receipt_dict@2f3f63b68d
  - cosa.agents.heartbeat_arbiter.respin_wake_check.write_boot_receipt@6171593e9a
  - cosa.agents.heartbeat_arbiter.respin_wake_check.read_receipt@1a341dc941
  - cosa.agents.heartbeat_arbiter.respin_wake_check.persona_slugs@f7ebe11b36
  - cosa.agents.heartbeat_arbiter.respin_wake_check.find_receipt_by_identity@c3da97bf22
  - cosa.agents.heartbeat_arbiter.respin_wake_check.receipt_is_misplaced@777f7c8bb7
  - cosa.agents.heartbeat_arbiter.respin_wake_check.find_misplaced_receipts@1b9938ac32
---
# Heartbeat re-spin boot receipts

A re-spun seat writes a boot receipt naming the memento it opened. The check in [[heartbeat-respin-wake-verdict]] reads it to tell whether the successor woke, and what it read. These are the writing and finding helpers.

## What it does
- `receipt_path` is the receipt file, `.respin-boot-receipt-<session id>.json`, under the fleet data root.
- `classify_memento_slot` names where a memento path sits: `root`, `repo_io`, `mirror`, `unknown`, or `none`. The repo is tested before the mirror.
- `describe_block` measures the memento block the boot produced: UTF-8 byte count, sha and headline. A block that was not supplied gives all three as `None`, which differs from an empty block.
- `build_receipt_dict` assembles the receipt: identity, boot time, memento path, written time, the persona the record declares, the slot and the block fields.
- `write_boot_receipt` writes it, best effort, and returns the path or `None`. It needs a session id and never raises, so a boot cannot fail on it.
- `read_receipt` returns the parsed receipt or `None`.
- `persona_slugs` returns every slug a persona name could have been written as, both accent folded and not. An emoji-only name gives an empty set.
- `find_receipt_by_identity` finds a successor's receipt by persona or tmux session when its session id is unknown. It returns the newest one booted at or after `since`.
- `receipt_is_misplaced` is true when the file's parent is not the directory the finder reads. It returns false when it cannot tell.
- `find_misplaced_receipts` searches recursively for a seat's receipts that the finder cannot see.

## Don't
- Do not let the injector write the receipt. Only the rehydrated seat's own start does, since sending keys gives no proof of ingestion.
- Do not read a healthy block size as proof the seat received the block.
