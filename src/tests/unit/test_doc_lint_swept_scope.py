"""
The swept scope: the one rule that says which files are held to zero findings.

The commit gate and the merge gate both import it, so these tests pin the rule itself and the
population it yields from a real git index.
"""

import subprocess

import pytest

from cosa.repo.doc_lint import swept_scope


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _write( root, rel, text="x = 1\n" ):
    path = root / rel
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_text( text, encoding="utf-8" )


@pytest.mark.parametrize( "path, expected", [
    ( "src/cosa/rest/queue.py",                    True ),
    ( "docker/lupin/scripts/patch.py",             True ),
    ( "src/lupin_mcp_extra/tool.py",               True ),    # a sibling name is not the held directory
    ( "docker/src/lupin_mcp/tool.py",              True ),    # the held text deeper in a path is not a prefix
    ( "src/lupin_mcp/cosa_voice_mcp.py",           False ),   # held
    ( "src/lupin_mcp/sub/deeper.py",               False ),   # held, at any depth
    ( "src/tests/unit/test_queue.py",              False ),   # a tests directory
    ( "src/cosa/rest/test_queue.py",               False ),   # a test file by name
    ( "src/cosa/rest/conftest.py",                 False ),
    ( "src/rnd/probe.py",                          False ),
    ( "src/cosa/rest/queue.md",                    False ),   # not Python
    ( "src/cosa/rest/queue.pyc",                   False ),
] )
def test_is_swept_decides_each_kind_of_path( path, expected ):
    assert swept_scope.is_swept( path ) is expected


def test_the_held_list_is_exactly_the_tool_directory():
    assert swept_scope.HELD_PREFIXES == ( "src/lupin_mcp/", )


def test_swept_files_reads_the_git_index_and_keeps_only_swept_paths( tmp_path ):
    _git( tmp_path, "init", "-q" )
    for rel in ( "src/app/b.py", "src/app/a.py", "src/lupin_mcp/tool.py", "src/tests/test_a.py", "src/app/notes.md" ):
        _write( tmp_path, rel )
    _git( tmp_path, "add", "src" )
    _write( tmp_path, "src/app/untracked.py" )

    assert swept_scope.swept_files( tmp_path ) == [ "src/app/a.py", "src/app/b.py" ]


def test_swept_files_raises_when_the_root_is_not_a_git_tree( tmp_path ):
    with pytest.raises( RuntimeError, match="git ls-files failed" ):
        swept_scope.swept_files( tmp_path )
