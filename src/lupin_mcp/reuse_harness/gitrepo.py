"""
The git port of the run harness, over the repository the runs are cut from.

It answers three questions about a frozen commit: its full sha, whether main holds it, and what a file or folder held there.
Every answer is read from the commit, never from the working tree, so a later edit on main cannot change what a run is given.
"""
from cosa.repo.doc_lint import pool_builder


class GitRepo:
    """Read-only questions about one repository."""

    def __init__( self, root ):
        """
        Remember the repository the questions are asked of.

        Requires:
            - root is a directory inside a git working tree

        Ensures:
            - the repository is remembered; nothing is run yet
        """
        self.root = root

    def resolve( self, sha ):
        """
        Return the full sha of the commit sha names.

        Raises:
            - RuntimeError if sha names no commit
        """
        return pool_builder.resolve_commit( self.root, sha )

    def is_ancestor( self, sha, ref ):
        """
        Say whether the commit is reachable from ref.

        Requires:
            - sha is a full commit sha and ref names a commit

        Ensures:
            - true when the merge base of the two is the commit itself

        Raises:
            - RuntimeError if git cannot compute the merge base
        """
        base = pool_builder.run_git( self.root, [ "merge-base", sha, ref ] ).decode( "ascii" ).strip()
        return base == sha

    def list_at( self, sha, folder ):
        """
        Return the paths of the files directly in folder at the commit, sorted.

        Requires:
            - sha is a full commit sha and folder has no trailing slash

        Ensures:
            - a subfolder and what it holds are not listed
        """
        out   = pool_builder.run_git( self.root, [ "ls-tree", sha, folder + "/" ] ).decode( "utf-8" )
        rows  = [ line.split( "\t", 1 ) for line in out.splitlines() ]
        return sorted( path for meta, path in rows if meta.split( " " )[ 1 ] == "blob" )

    def file_at( self, sha, path ):
        """
        Return the text of one file at the commit.

        Raises:
            - RuntimeError if the commit holds no such file
        """
        return pool_builder.run_git( self.root, [ "show", f"{sha}:{path}" ] ).decode( "utf-8" )
