"""The command runner the harness ports share: one command, its exit code and its output."""
import subprocess

RUN_TIMEOUT = 300


def run_command( argv, env=None, cwd=None, timeout=RUN_TIMEOUT ):
    """
    Run one command and return its exit code and its output.

    Requires:
        - argv is a non-empty list of strings

    Ensures:
        - returns ( exit code, standard output and error joined as text )
        - a command that cannot start, or runs past the timeout, is reported as exit code 127, never raised
    """
    try:
        done = subprocess.run( argv, capture_output=True, text=True, env=env, cwd=cwd, timeout=timeout )
    except ( OSError, subprocess.SubprocessError ) as error:
        return 127, f"{type( error ).__name__}: {error}"
    return done.returncode, ( done.stdout + done.stderr ).strip()
