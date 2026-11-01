"""
The source tree of one commit, kept as plain files for a run to read.

A live run takes hours, and the main tree moves under it as peers merge.
A member found by line number in one version of a file cannot be stripped from another.
So the index, the bodies and every strip read this copy and nothing else.
"""
import os
import pathlib
import shutil
import subprocess
import tarfile

from lupin_mcp.reuse_needset import errors as er

MARKER = ".needset-source-commit"
TOP    = "src"


def full_sha( repo_root, commit ):
    """
    Resolve a commit name to its full sha.

    Requires:
        - repo_root is a git working tree

    Ensures:
        - returns the 40-character sha of the commit

    Raises:
        - NeedsetError SOURCE_EXPORT_FAILED when git does not know the commit
    """
    got = subprocess.run( [ "git", "-C", str( repo_root ), "rev-parse", "--verify", "--quiet", f"{commit}^{{commit}}" ], capture_output=True, text=True )
    if got.returncode != 0: raise er.NeedsetError( er.SOURCE_EXPORT_FAILED, f"{repo_root}: no commit {commit!r}" )
    return got.stdout.strip()


def tracked_at( repo_root, commit ):
    """
    List the files the commit tracks under src.

    Requires:
        - repo_root is a git working tree that holds the commit

    Ensures:
        - returns a set of repository-relative paths, from the commit and not from the working tree or the index

    Raises:
        - NeedsetError SOURCE_EXPORT_FAILED when git cannot list the commit
    """
    got = subprocess.run( [ "git", "-C", str( repo_root ), "ls-tree", "-r", "-z", "--name-only", full_sha( repo_root, commit ), "--", TOP ], capture_output=True, text=True )
    if got.returncode != 0: raise er.NeedsetError( er.SOURCE_EXPORT_FAILED, f"{repo_root}: {got.stderr.strip()}" )  # pragma: no cover  reason: full_sha has just proven the commit exists, so ls-tree on it fails only in a corrupt repository
    return { f for f in got.stdout.split( "\0" ) if f }


def export( repo_root, commit, dest ):
    """
    Write the commit's src folder into dest, once.

    Requires:
        - repo_root is a git working tree that holds the commit
        - dest is a path whose parent exists

    Ensures:
        - returns dest as a Path; dest holds src/ exactly as the commit has it, and a marker file naming the full sha
        - a dest already exported from the same commit is reused as it is
        - the files are built beside dest and renamed into place, so a stopped export leaves no dest for the next call to trust

    Raises:
        - NeedsetError SOURCE_EXPORT_MISMATCH when dest exists and is not an export of this commit
        - NeedsetError SOURCE_EXPORT_FAILED when git cannot produce the archive
    """
    sha, dest = full_sha( repo_root, commit ), pathlib.Path( dest )
    if dest.exists():
        marker = dest / MARKER
        if marker.is_file() and marker.read_text( encoding="utf-8" ).strip() == sha: return dest
        raise er.NeedsetError( er.SOURCE_EXPORT_MISMATCH, f"{dest} is not an export of {sha}; move it away to export again" )
    part = dest.with_name( dest.name + ".part" )
    if part.exists(): shutil.rmtree( part )
    part.mkdir()
    proc = subprocess.Popen( [ "git", "-C", str( repo_root ), "archive", "--format=tar", sha, "--", TOP ], stdout=subprocess.PIPE, stderr=subprocess.PIPE )
    try:
        with tarfile.open( fileobj=proc.stdout, mode="r|" ) as tar: tar.extractall( part, filter="data" )
    except ( tarfile.TarError, OSError ) as e:
        proc.kill()
        proc.wait()
        raise er.NeedsetError( er.SOURCE_EXPORT_FAILED, f"{repo_root}: {e}" ) from e
    err = proc.stderr.read().decode( "utf-8", "replace" ).strip()
    if proc.wait() != 0: raise er.NeedsetError( er.SOURCE_EXPORT_FAILED, f"{repo_root}: git archive {sha}: {err}" )
    ( part / MARKER ).write_text( sha + "\n", encoding="utf-8" )
    os.rename( part, dest )
    return dest
