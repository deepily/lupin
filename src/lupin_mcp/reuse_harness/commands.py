"""The command runner the harness ports share: one command, its exit code and its output."""
import subprocess

RUN_TIMEOUT = 300


def run_command( argv, env=None, cwd=None, timeout=RUN_TIMEOUT, stdout_only=False ):
    """
    Run one command and return its exit code and its output.

    Requires:
        - argv is a non-empty list of strings
        - stdout_only is True to read only standard output, as it was written

    Ensures:
        - returns ( exit code, standard output and error joined as text ), or with stdout_only ( exit code, standard output exactly as printed )
        - a command that cannot start, or runs past the timeout, is reported as exit code 127, never raised
        - a command that ran past the timeout keeps what it printed: the output is the error line, then the partial standard output and error
    """
    try:
        done = subprocess.run( argv, capture_output=True, text=True, env=env, cwd=cwd, timeout=timeout )
    except subprocess.TimeoutExpired as error:
        partial = b"".join( part if isinstance( part, bytes ) else part.encode( "utf-8" ) for part in ( ( error.stdout, ) if stdout_only else ( error.stdout, error.stderr ) ) if part )
        return 127, ( f"{type( error ).__name__}: {error}\n" + partial.decode( "utf-8", errors="replace" ) ).strip()
    except ( OSError, subprocess.SubprocessError ) as error:
        return 127, f"{type( error ).__name__}: {error}"
    if stdout_only: return done.returncode, done.stdout
    return done.returncode, ( done.stdout + done.stderr ).strip()
