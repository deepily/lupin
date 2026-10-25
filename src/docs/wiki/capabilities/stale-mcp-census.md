---
capability: stale-mcp-census
pin_algorithm: py3.13.x6a05a1/ts5.9.3
pins:
  - scripts.stale_mcp_check.mcp_launch@5006b9d8a2
  - scripts.stale_mcp_check.resolve_modules@4569bc7a4f
  - scripts.stale_mcp_check.census@a86477aa71
  - scripts.stale_mcp_check.format_epoch@b1eaa330c1
  - scripts.stale_mcp_check.render_text@8b59428eb6
  - scripts.stale_mcp_check.exit_code@24325b391f
  - scripts.stale_mcp_check.main@64809cb237
---
# Stale MCP check: census and exit codes

A process is stale when it started before any watched module last changed. Modules are resolved the way that process would import them, and a module found nowhere is reported unresolved, never fresh. The process reading is on [[stale-mcp-process-reading]].

## Finding the launch
- `mcp_launch` decides whether an argument list launches the MCP. A python interpreter whose script is `cosa_voice_mcp.py`, or whose `-m` module is `lupin_mcp.cosa_voice_mcp`, counts.
- The name inside a longer argument, or as an argument to another program, does not count. Interpreter options are skipped, and `-W`, `-X` and `--check-hash-based-pycs` take a value.
- `resolve_modules` finds the file each watched module would load from. It searches that process's `PYTHONPATH`, then the script's own `src` tree, then its `LUPIN_ROOT`. The first existing file wins.

## Census
- `census` measures every live MCP process against the files it loaded. It excludes itself and its ancestors, and skips a process that exits mid-census.
- A record is stale only if a resolved module's mtime is later than the process start. The pair of process id and start ticks names one process across runs. The derived start time drifts, so it is never a key.
- A newer mtime does not prove the process imported the changed code. The check flags anyway, as the safe side.

## Output
- `format_epoch` renders an epoch as local wall-clock time.
- `render_text` prints the denominator first, then each stale process with its pane, session, working directory and newer modules. It prints the remedy only when something is stale.
- `exit_code` returns 1 for any stale record, else 2 for any unresolved module, else 0.
- `main` runs the census and prints text, or JSON with `--json`. It returns 2 if `/proc` cannot be read.
- The remedy is a seat restart. A clear does not reload the MCP.
