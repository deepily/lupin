"""
One-line summary of a Coder tool call, for progress notifications.

The test fix and bug fix expediters both announce each Coder tool call. A bare
`Coder: Bash` line gave long runs of identical entries with no context. So the
summary names the tool and its key argument, cut to 100 characters.
"""


def summarize_tool_use( block ) -> str:
    """
    Compact single-line summary of a ToolUseBlock for progress notifications.

    Requires:
        - block has a `name` string and an `input` dict or None

    Ensures:
        - Bash gives the first line of the command, cut to 100 characters
        - Read, Edit and Write give the last 100 characters of the file path
        - Grep and Glob give the pattern, cut to 100 characters
        - any tool with no such argument, and every other tool, gives its bare name
    """
    name = block.name
    inp  = block.input or {}
    if name == "Bash":
        cmd = inp.get( "command", "" ) or ""
        first_line = cmd.splitlines()[ 0 ] if cmd else ""
        return f"Bash: {first_line[ :100 ]}" if first_line else "Bash"
    if name in ( "Read", "Edit", "Write" ):
        fp = inp.get( "file_path", "" ) or ""
        return f"{name}: {fp[ -100: ]}" if fp else name
    if name in ( "Grep", "Glob" ):
        pat = inp.get( "pattern", "" ) or ""
        return f"{name}: {pat[ :100 ]}" if pat else name
    return name
