"""
No committed git conflict markers anywhere under src/ — row ed0183f0.

THE DEFECT: María found `<<<<<<< HEAD / ======= / >>>>>>> cfe8a3482` committed in
`multiplexer.html` (lines 67-75) while reviewing a rebase on 2026-09-23. 149/149 scoped tests
and tsc stayed green, because markers inside HTML or a string are just text to every other
gate. Nothing looked for them.

WHAT COUNTS AS A MARKER. A line that STARTS with `<<<<<<<` or `>>>>>>>` (exactly seven,
then a space or end of line), plus the diff3 base marker `|||||||`. The bare `=======`
separator is deliberately NOT matched alone: it is a legitimate line in reStructuredText,
markdown and plain-text underlines, and every real conflict also carries an opening and a
closing marker, so matching the two ends loses nothing and avoids the noise.

POPULATION: `git ls-files -- src`, never a directory walk, so an untracked scratch file is not
blamed and a tracked one cannot hide. Binary files (a NUL byte in the first 8 KiB, the test
git itself uses) are skipped and the skip count is reported.

THIS FILE'S OWN FIXTURES build their markers at run time (`"<" * 7`), so the file does not
contain a line that would trip the guard it defines.

Venue: :7999-eligible. One `git ls-files` plus reads of ~5k files, about a second.
"""
import os
import re
import subprocess

import pytest

import cosa.utils.util as cu

ROOT = cu.get_project_root()

OPEN   = "<" * 7
CLOSE  = ">" * 7
BASE   = "|" * 7
SEP    = "=" * 7

# A marker line: start of line, exactly seven of the character, then a space or end of line.
MARKER_RE = re.compile( rb"^(?:<{7}|>{7}|\|{7})(?: |\r?$)", re.MULTILINE )


def tracked_files( root, pathspec="src" ):
    """
    Requires: root is a git checkout
    Ensures:  returns the repo-relative paths git tracks under pathspec, sorted
    """
    out = subprocess.run( [ "git", "ls-files", "-z", "--", pathspec ], cwd=root,
                          capture_output=True, check=True ).stdout
    return sorted( p.decode() for p in out.split( b"\0" ) if p )


def scan( root, paths ):
    """
    Requires: paths are repo-relative paths under root
    Ensures:
        - returns ( hits, scanned, skipped ) where hits = [ ( path, line_no, text ) ]
        - a path that is binary, a symlink, or no longer on disk counts as skipped
    """
    hits, scanned, skipped = [], 0, 0
    for rel in paths:
        full = os.path.join( root, rel )
        if os.path.islink( full ) or not os.path.isfile( full ):
            skipped += 1
            continue
        with open( full, "rb" ) as fh:
            data = fh.read()
        if b"\0" in data[ :8192 ]:
            skipped += 1
            continue
        scanned += 1
        for match in MARKER_RE.finditer( data ):
            line_no = data.count( b"\n", 0, match.start() ) + 1
            end     = data.find( b"\n", match.start() )
            line    = data[ match.start() : end if end != -1 else len( data ) ]
            hits.append( ( rel, line_no, line[ :60 ].decode( "utf-8", "replace" ) ) )
    return hits, scanned, skipped


def test_no_tracked_file_under_src_carries_a_conflict_marker():
    paths = tracked_files( ROOT )
    hits, scanned, skipped = scan( ROOT, paths )

    print( f"\n[conflict-marker scan] tracked under src={len( paths )} scanned={scanned} skipped(binary/link/absent)={skipped}" )

    assert paths,   "git ls-files returned nothing for src — the guard would pass forever watching nothing"
    assert scanned > 0.5 * len( paths ), (
        f"only {scanned} of {len( paths )} tracked files were readable as text — the scan is looking at too little to vouch for src/"
    )
    assert not hits, "committed git conflict markers:\n" + "\n".join( f"  {p}:{n}  {t}" for p, n, t in hits )


# ── the guard must be able to find something ────────────────────────────────

@pytest.fixture
def repo( tmp_path ):
    """A throwaway git repo with a src/ tree; nothing here touches the real checkout."""
    def git( *args ): subprocess.run( [ "git", "-C", str( tmp_path ), *args ], check=True, capture_output=True )
    git( "init", "-q" )
    git( "config", "user.email", "t@example.com" )
    git( "config", "user.name", "t" )
    ( tmp_path / "src" ).mkdir()
    return tmp_path, git


def _write( root, rel, text ):
    path = root / rel
    path.parent.mkdir( parents=True, exist_ok=True )
    path.write_bytes( text if isinstance( text, bytes ) else text.encode() )


def test_a_planted_marker_is_found_with_its_file_and_line( repo ):
    root, git = repo
    _write( root, "src/page.html", f"<div>\n{OPEN} HEAD\nmine\n{SEP}\ntheirs\n{CLOSE} cfe8a3482\n</div>\n" )
    _write( root, "src/clean.py", "x = 1\n" )
    git( "add", "-A" ); git( "commit", "-qm", "c" )
    hits, scanned, _skipped = scan( str( root ), tracked_files( str( root ) ) )
    assert scanned == 2
    assert [ ( p, n ) for p, n, _t in hits ] == [ ( "src/page.html", 2 ), ( "src/page.html", 6 ) ]


@pytest.mark.parametrize( "marker", [ OPEN, CLOSE, BASE ] )
def test_each_marker_kind_is_found_bare_or_with_a_label_and_with_crlf( repo, marker ):
    root, git = repo
    for name, text in { "a": f"{marker}\n", "b": f"{marker} label\n", "c": f"{marker}\r\n", "d": f"ok\n{marker} x" }.items():
        _write( root, f"src/{name}.txt", text )
    git( "add", "-A" ); git( "commit", "-qm", "c" )
    hits, _s, _k = scan( str( root ), tracked_files( str( root ) ) )
    assert sorted( p for p, _n, _t in hits ) == [ "src/a.txt", "src/b.txt", "src/c.txt", "src/d.txt" ]


def test_lookalikes_are_not_flagged( repo ):
    root, git = repo
    _write( root, "src/doc.md", f"Title\n{SEP}\n\n  {OPEN} indented\n{OPEN}{OPEN[ :1 ]} eight\n{OPEN[ :6 ]} six\nx {CLOSE} mid-line\n" )
    git( "add", "-A" ); git( "commit", "-qm", "c" )
    hits, scanned, _k = scan( str( root ), tracked_files( str( root ) ) )
    assert scanned == 1 and hits == []


def test_population_comes_from_git_not_the_directory( repo ):
    root, git = repo
    _write( root, "src/tracked.txt", "fine\n" )
    git( "add", "-A" ); git( "commit", "-qm", "c" )
    _write( root, "src/untracked-scratch.txt", f"{OPEN} HEAD\n" )          # on disk, not in git
    _write( root, "other/outside-src.txt", f"{OPEN} HEAD\n" )              # tracked, but outside src/
    git( "add", "other/outside-src.txt" ); git( "commit", "-qm", "o" )
    assert tracked_files( str( root ) ) == [ "src/tracked.txt" ]
    hits, _s, _k = scan( str( root ), tracked_files( str( root ) ) )
    assert hits == []


def test_binary_links_and_vanished_files_are_skipped_and_counted( repo ):
    root, git = repo
    _write( root, "src/blob.bin", b"\0\1\2" + f"\n{OPEN} x\n".encode() )
    _write( root, "src/text.txt", "hi\n" )
    _write( root, "src/gone.txt", "bye\n" )
    os.symlink( "text.txt", root / "src" / "link.txt" )
    git( "add", "-A" ); git( "commit", "-qm", "c" )
    os.remove( root / "src" / "gone.txt" )
    hits, scanned, skipped = scan( str( root ), tracked_files( str( root ) ) )
    assert ( hits, scanned, skipped ) == ( [], 1, 3 )


def test_a_marker_without_a_trailing_newline_at_eof_is_found( repo ):
    root, git = repo
    _write( root, "src/eof.txt", f"a\n{CLOSE}" )
    git( "add", "-A" ); git( "commit", "-qm", "c" )
    hits, _s, _k = scan( str( root ), tracked_files( str( root ) ) )
    assert [ ( p, n ) for p, n, _t in hits ] == [ ( "src/eof.txt", 2 ) ]
