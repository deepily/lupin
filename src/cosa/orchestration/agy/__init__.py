"""
Antigravity (agy) CLI integration subpackage.

Runs Google's `agy` command-line agent as a subprocess so Lupin code can send one prompt
to a Gemini model and read back its raw answer.

Functions:
    run_agy: Send one prompt, return an AgyResult
    binary_fingerprint: Identify the agy binary on disk without starting it
    agy_version: Ask agy for its version string

Example:
    from cosa.orchestration.agy import run_agy, binary_fingerprint

    pinned = binary_fingerprint()
    result = run_agy(
        "Reply with the word PONG.",
        model              = "gemini-3.6-flash-low",
        workspace_dir      = scratch_dir,
        pinned_fingerprint = pinned
    )
    print( result.response )
"""

from cosa.orchestration.agy.runtime import (
    AgyBinaryChanged,
    AgyCallError,
    AgyResult,
    agy_version,
    binary_fingerprint,
    build_argv,
    build_stdin,
    parse_result,
    run_agy
)

__all__ = [
    "AgyBinaryChanged",
    "AgyCallError",
    "AgyResult",
    "agy_version",
    "binary_fingerprint",
    "build_argv",
    "build_stdin",
    "parse_result",
    "run_agy"
]
