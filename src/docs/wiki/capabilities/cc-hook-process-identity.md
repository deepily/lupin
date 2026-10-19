---
capability: cc-hook-process-identity
pin_algorithm: py3.13.xebd695/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.lib.process_identity.process_runs@d968732f75
---
# Hook process identity

A bridge file records the pid of a listener or an idle waiter. The system reuses pid numbers, so a bare liveness check can lead to a signal for an unrelated process.

## What it does
- `process_runs( pid, module )` is true only if the process was started as the Python program `module`, bare or dotted.
- It reads the process's own command line from `/proc` and walks the arguments after the interpreter.
- A `-m` argument matches when the next argument is the module, whole or as its last dotted part. A script matches when its basename is `<module>.py`.
- A `-c` argument ends the walk with false, because the rest is code.
- It returns false when the process is gone, the command line is unreadable or empty, or the program is not a Python interpreter.
- It returns true when `/proc` does not exist, so the caller keeps its earlier behaviour.

## Don't
- Don't signal a pid on the strength of `os.kill( pid, 0 )` alone. That proves only that some process holds the number.

## Invariants
- It never matches a module name that appears only inside another argument's text.
