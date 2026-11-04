---
capability: stale-mcp-process-reading
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.stale_mcp_check.read_boot_time@b2187c846e
  - scripts.stale_mcp_check.read_stat@9394498ffc
  - scripts.stale_mcp_check.read_cmdline@e52d6414e2
  - scripts.stale_mcp_check.read_environ@65d3f22aaa
  - scripts.stale_mcp_check.read_cwd@bf3bfcdfdc
  - scripts.stale_mcp_check.ancestors@b21c3ff1cd
  - scripts.stale_mcp_check.list_tmux_panes@024bc961d3
---
# Stale MCP check: reading a process

Finds live cosa-voice MCP processes that run code older than the tree. It runs outside the MCP, because a stale process runs a stale guard and sees nothing. It is read-only: it reads `/proc`, stats files and asks tmux to list panes. It never signals, kills or restarts anything. The census is on [[stale-mcp-census]].

## Process facts
- `read_boot_time` derives the boot time as now minus the uptime file, to 10 ms. The `/proc/stat` boot time is truncated to whole seconds, which once made a process look started before an edit. It raises `OSError` or `ValueError` if the uptime cannot be read.
- `read_stat` parses the parent id and the start time in clock ticks. A command name holding spaces or parentheses does not shift the fields. It returns `None` when the process is gone.
- `read_cmdline` returns a process's argument list, empty for a kernel thread, or `None` if unreadable.
- `read_environ` returns the environment as a dict, empty when it cannot be read.
- `read_cwd` resolves the working directory, or `None`.
- `ancestors` lists a process's ancestor ids nearest first, excluding itself. It stops at init, at an unreadable parent or on a cycle.
- `list_tmux_panes` maps each pane's shell id to its session name and pane id. It returns an empty map when tmux is missing, has no server or times out.
