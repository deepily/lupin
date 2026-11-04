"""
The commit scope guard judges the `commit` subcommand and no other that starts with it.

`git commit-tree`, `git commit-graph` and `git commit-msg` write no index and name no paths, so
the guard's question does not apply to them. The matcher ended in `commit\\b`, and a hyphen
is a word boundary, so all three were judged as a commit.
"""

import pytest

from lupin_cli.claude_code.hooks.lib.commit_scope_guard import git_commit_match


@pytest.mark.parametrize( "command", [
    "git commit-tree abc123 -m x",
    "git commit-graph write",
    "git commit-msg .git/COMMIT_EDITMSG",
    "git -C /tmp/r commit-tree abc123",
    "FOO=1 git commit-tree abc123",
] )
def test_a_subcommand_that_only_starts_with_commit_is_not_judged( command ):
    assert git_commit_match( command ) is None


@pytest.mark.parametrize( "command", [
    "git commit -F f -- path",
    "git commit -am x",
    "git commit",
    "git -C /tmp/r commit -m x",
    "git commit;echo done",
    "git commit&&git status",
    "LUPIN_COMMIT_SCOPE_ACK=1 git commit -m x",
] )
def test_a_real_commit_is_still_judged( command ):
    assert git_commit_match( command ) is not None


def test_a_commit_tree_inside_a_chain_does_not_hide_a_real_commit_after_it():
    match = git_commit_match( "git commit-tree abc && git commit -m x" )
    assert match is not None
    assert "commit -m x" in "git commit-tree abc && git commit -m x"[ match.start(): ]
    assert "commit-tree" not in "git commit-tree abc && git commit -m x"[ match.start():match.end() ]
