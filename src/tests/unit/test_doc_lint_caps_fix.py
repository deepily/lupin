"""
caps_fix: lowers the capitals the docstring linter flags, and nothing else.

The fixtures are a scratch git repo. The end-to-end test commits it, runs a real fix, and then asks
the linter and docs_only_diff, the two judges the fix has to satisfy.
"""

import io
import subprocess

import pytest

from cosa.repo.doc_lint import caps_fix as cf, docs_only_diff, word_list
from cosa.repo.doc_lint.docstring_lint import lint_source

WORDS = [ "not", "never", "the", "very", "must", "debug" ]

LOUD_PY = '''"""Module that is VERY loud."""

DEBUG = True


def f( x ):
    """
    This must NEVER fail, and "NEVER" in quotes and `MUST` in code stay.

    Requires:
        - the VERY first thing
    """
    return x


def g():
    """Set DEBUG for the NEVER case."""
'''

QUIET_PY = '''"""Plain."""
'''

ESCAPED_PY = '''"""Path `\\\\x` is NEVER shown."""
'''


def _git( root, *args ):
    res = subprocess.run( [ "git", "-C", str( root ), "-c", "user.email=t@t", "-c", "user.name=t", *args ], capture_output=True, text=True )
    assert res.returncode == 0, res.stderr
    return res.stdout.strip()


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    ( tmp_path / "src" / "conf" ).mkdir( parents=True )
    ( tmp_path / "src" / "conf" / "dm-tutor-lowercase-words.txt" ).write_text( "\n".join( WORDS ) + "\n", encoding="utf-8" )
    files = {
        "pkg/__init__.py" : "",
        "pkg/loud.py"     : LOUD_PY,
        "pkg/quiet.py"    : QUIET_PY,
        "pkg/escaped.py"  : ESCAPED_PY,
        "pkg/broken.py"   : "def (:\n",
        "loose/script.py" : QUIET_PY.replace( "Plain", "VERY plain" )
    }
    for rel, text in files.items():
        path = tmp_path / rel
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( text, encoding="utf-8" )
    ( tmp_path / "pkg" / "latin.py" ).write_bytes( b'"""caf\xe9 NEVER."""\n' )
    _git( tmp_path, "add", "." )
    _git( tmp_path, "commit", "-qm", "first" )
    yield tmp_path
    word_list._state[ "root" ]  = None
    word_list._state[ "words" ] = None


def _caps( repo, path ):
    source = ( repo / path ).read_text( encoding="utf-8" )
    return [ f for f in lint_source( path, source, repo ) if f.rule == "caps" ]


def test_code_identifiers_cover_every_kind_and_skip_strings():
    source = "import a.b as AB\nfrom c import D\nX = 1\nclass K:\n    def m( self, ARG, *, KW=1 ): return self.ATTR\nasync def af(): return f( KW=2 )\n'DOC'\n"
    names = cf.code_identifiers( source )
    assert { "AB", "D", "X", "K", "m", "ARG", "KW", "ATTR", "af", "f", "self" } <= names
    assert "DOC" not in names and "c" not in names


def test_lower_line_lowers_flagged_words_and_leaves_quotes_code_and_identifiers( repo ):
    word_list.configure_root( repo )
    new, lowered, left = cf.lower_line( 'This must NEVER fail, "NEVER" and `MUST` and NEVER and DEBUG', { "DEBUG" } )
    assert new == 'This must never fail, "NEVER" and `MUST` and never and DEBUG'
    assert ( lowered, left ) == ( 2, [ "DEBUG" ] )
    assert cf.lower_line( "nothing here", set() ) == ( "nothing here", 0, [] )


def test_fix_source_edits_only_docstring_text( repo ):
    word_list.configure_root( repo )
    result = cf.fix_source( "pkg/loud.py", LOUD_PY, repo )
    assert result[ "lowered" ] == 4 and result[ "unlocated" ] == 0
    assert result[ "left_alone" ] == [ ( 17, "DEBUG" ) ]
    new = result[ "new_source" ]
    assert "DEBUG = True" in new and '"NEVER" in quotes and `MUST` in code' in new
    assert "Module that is very loud." in new and "Set DEBUG for the never case." in new
    assert new.count( "\n" ) == LOUD_PY.count( "\n" ) and len( new ) == len( LOUD_PY )


def test_fix_source_unchanged_when_nothing_flagged_or_unparseable_or_escaped( repo ):
    word_list.configure_root( repo )
    for path, source in ( ( "q.py", QUIET_PY ), ( "b.py", "def (:\n" ) ):
        assert cf.fix_source( path, source, repo ) == { "new_source": source, "lowered": 0, "left_alone": [], "unlocated": 0 }
    escaped = cf.fix_source( "pkg/escaped.py", ESCAPED_PY, repo )
    assert escaped[ "new_source" ] == ESCAPED_PY and escaped[ "unlocated" ] == 1 and escaped[ "lowered" ] == 0


def test_dry_run_reports_and_changes_nothing( repo ):
    before = _git( repo, "status", "--porcelain" )
    report = cf.fix_files( repo, [ "pkg/loud.py", "pkg/quiet.py" ], dry_run=True )
    assert [ r[ "path" ] for r in report ] == [ "pkg/loud.py" ] and report[ 0 ][ "lowered" ] == 4
    assert _git( repo, "status", "--porcelain" ) == before == ""


def test_real_run_leaves_zero_caps_findings_and_passes_docs_only_diff( repo ):
    paths  = [ "pkg/loud.py", "loose/script.py", "pkg/quiet.py" ]
    report = cf.fix_files( repo, paths, dry_run=False )
    touched = [ r[ "path" ] for r in report if r[ "lowered" ] ]
    assert touched == [ "pkg/loud.py", "loose/script.py" ]
    assert _caps( repo, "loose/script.py" ) == []
    assert [ f.message for f in _caps( repo, "pkg/loud.py" ) ] == [ "ALL-CAPS word DEBUG" ]
    results = docs_only_diff.check_diff( repo, "HEAD" )
    assert [ p for p, _ in results ] == sorted( touched ) and all( failure is None for _, failure in results )


def test_refuses_a_file_that_docs_only_diff_rejects( repo, monkeypatch ):
    monkeypatch.setattr( cf, "python_difference", lambda old, new: "code changed" )
    report = cf.fix_files( repo, [ "pkg/loud.py" ], dry_run=False )
    assert report[ 0 ][ "refused" ] == "code changed" and report[ 0 ][ "lowered" ] == 0
    assert _git( repo, "status", "--porcelain" ) == ""
    assert "refused: code changed" in cf.format_report( report, False )


def test_unreadable_file_is_reported_not_skipped( repo ):
    report = cf.fix_files( repo, [ "pkg/latin.py" ], dry_run=False )
    assert report[ 0 ][ "refused" ].startswith( "could not read" ) and report[ 0 ][ "lowered" ] == 0


def test_crlf_line_endings_survive( repo ):
    ( repo / "pkg" / "crlf.py" ).write_bytes( b'"""A VERY loud line."""\r\nX = 1\r\n' )
    cf.fix_files( repo, [ "pkg/crlf.py" ], dry_run=False )
    assert ( repo / "pkg" / "crlf.py" ).read_bytes() == b'"""A very loud line."""\r\nX = 1\r\n'


def test_only_left_alone_words_write_nothing( repo ):
    ( repo / "pkg" / "only.py" ).write_text( '"""Set DEBUG."""\nDEBUG = 1\n', encoding="utf-8" )
    report = cf.fix_files( repo, [ "pkg/only.py" ], dry_run=False )
    assert report[ 0 ][ "lowered" ] == 0 and report[ 0 ][ "left_alone" ] == [ ( 1, "DEBUG" ) ] and report[ 0 ][ "refused" ] is None
    assert ( repo / "pkg" / "only.py" ).read_text( encoding="utf-8" ) == '"""Set DEBUG."""\nDEBUG = 1\n'


def test_format_report_totals_say_whether_anything_was_written( repo ):
    report = cf.fix_files( repo, [ "pkg/loud.py", "pkg/escaped.py" ], dry_run=True )
    text   = cf.format_report( report, True )
    assert "pkg/loud.py: 4 lowered, 1 left alone, 0 unlocated" in text and "  left alone DEBUG at line 17" in text
    assert "pkg/escaped.py: 0 lowered, 0 left alone, 1 unlocated" in text
    assert text.endswith( "4 words in 1 files would be lowered, nothing written\n" )
    assert cf.format_report( report, False ).endswith( "4 words in 1 files lowered and written\n" )


def test_main_dry_run_packages_only_and_explicit_paths( repo, monkeypatch, capsys ):
    out = io.StringIO()
    assert cf.main( [ "--repo-root", str( repo ), "--dry-run", "--packages-only" ], out ) == 0
    text = out.getvalue()
    assert "pkg/loud.py" in text and "loose/script.py" not in text and "nothing written" in text
    out = io.StringIO()
    cf.main( [ "--repo-root", str( repo ), "--dry-run", "loose/script.py" ], out )
    assert "loose/script.py: 1 lowered" in out.getvalue()
    monkeypatch.setattr( "sys.argv", [ "x", "--repo-root", str( repo ), "--dry-run" ] )
    assert cf.main() == 0
    assert "would be lowered" in capsys.readouterr().out
