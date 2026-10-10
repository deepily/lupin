"""
Page pairs: whole-page before and after texts, cut into chunks the claim harness can read.

The claim harness was built on docstrings. A page is far longer than a docstring.
The old page is cut at its section headings into chunks of about a fixed word count.
Each chunk is paired with the whole new text.

Venue: :7999 (unit, no server, no model call).
"""

import json
import os
import subprocess

import pytest

from cosa.repo.doc_lint import page_pairs as pp


def _words( count, tag="w" ):
    return " ".join( f"{tag}{i}" for i in range( count ) )


def test_a_page_with_no_heading_is_one_section():
    assert pp.split_sections( "just text\nmore text\n" ) == [ "just text\nmore text\n" ]


def test_sections_start_at_second_and_third_level_headings_and_join_back_to_the_text():
    text = "intro\n\n## One\nbody one\n\n### Sub\nbody sub\n\n## Two\nbody two\n"
    sections = pp.split_sections( text )
    assert [ s.splitlines()[0] for s in sections ] == [ "intro", "## One", "### Sub", "## Two" ]
    assert "".join( sections ) == text


def test_a_heading_inside_a_fenced_block_is_not_a_section_start():
    text = "## Real\n```\n## not a heading\n```\n## Next\nx\n"
    sections = pp.split_sections( text )
    assert [ s.splitlines()[0] for s in sections ] == [ "## Real", "## Next" ]
    assert "".join( sections ) == text


def test_a_tilde_fence_also_hides_headings_and_a_longer_fence_closes_only_on_its_own_kind():
    text = "~~~\n## inside\n~~~\n## After\ny\n"
    assert [ s.splitlines()[0] for s in pp.split_sections( text ) ] == [ "~~~", "## After" ]


def test_first_level_headings_are_not_section_starts():
    text = "# Title\n\n## One\nx\n"
    assert [ s.splitlines()[0] for s in pp.split_sections( text ) ] == [ "# Title", "## One" ]


def test_chunks_group_whole_sections_up_to_the_target_and_join_back():
    text = f"## A\n{_words( 300, 'a' )}\n## B\n{_words( 300, 'b' )}\n## C\n{_words( 300, 'c' )}\n"
    chunks = pp.chunk_text( text, target_words=650 )
    assert len( chunks ) == 2
    assert chunks[ 0 ].startswith( "## A" ) and chunks[ 1 ].startswith( "## C" )
    assert "".join( chunks ) == text


def test_a_section_over_the_target_is_a_chunk_of_its_own_and_never_cut():
    text = f"## Big\n{_words( 900 )}\n## Small\n{_words( 20, 's' )}\n"
    chunks = pp.chunk_text( text, target_words=600 )
    assert len( chunks ) == 2
    assert chunks[ 0 ].startswith( "## Big" ) and chunks[ 1 ].startswith( "## Small" )


def test_a_blank_leading_section_is_folded_into_the_next_chunk():
    chunks = pp.chunk_text( "\n\n## A\nx y z\n", target_words=600 )
    assert len( chunks ) == 1 and chunks[ 0 ].endswith( "x y z\n" )


def test_empty_text_has_no_chunks():
    assert pp.chunk_text( "", target_words=600 ) == []
    assert pp.chunk_text( "  \n\n", target_words=600 ) == []


def test_pairs_carry_a_page_and_chunk_id_and_the_whole_new_text():
    old = f"## A\n{_words( 400, 'a' )}\n## B\n{_words( 400, 'b' )}\n"
    pairs = pp.page_pairs( "src/docs/x.md", old, "NEW TEXT", target_words=500 )
    assert [ p[ "id" ] for p in pairs ] == [ "src/docs/x.md#000", "src/docs/x.md#001" ]
    assert all( p[ "new" ] == "NEW TEXT" for p in pairs )
    assert "".join( p[ "old" ] for p in pairs ) == old


def test_a_new_page_made_of_parts_is_joined_with_a_file_header_per_part():
    joined = pp.join_new_text( [ ( "src/docs/x.md", "index text\n" ), ( "src/docs/x/01-a.md", "part text\n" ) ] )
    assert joined.index( "src/docs/x.md" ) < joined.index( "index text" ) < joined.index( "src/docs/x/01-a.md" ) < joined.index( "part text" )
    assert pp.join_new_text( [] ) == ""


def _git( root, *args ):
    return subprocess.run( [ "git", "-C", str( root ), *args ], capture_output=True, text=True, check=True ).stdout


@pytest.fixture
def repo( tmp_path ):
    _git( tmp_path, "init", "-q" )
    _git( tmp_path, "config", "user.email", "t@example.com" )
    _git( tmp_path, "config", "user.name", "t" )
    ( tmp_path / "page.md" ).write_text( "## A\none two three\n## B\nfour five six\n" )
    _git( tmp_path, "add", "page.md" )
    _git( tmp_path, "commit", "-q", "-m", "old" )
    old_sha = _git( tmp_path, "rev-parse", "HEAD" ).strip()
    ( tmp_path / "page.md" ).write_text( "index\n" )
    ( tmp_path / "part.md" ).write_text( "part\n" )
    _git( tmp_path, "add", "page.md", "part.md" )
    _git( tmp_path, "commit", "-q", "-m", "new" )
    return tmp_path, old_sha


def test_read_at_returns_the_text_at_a_revision_and_none_for_a_missing_path( repo ):
    root, old_sha = repo
    assert pp.read_at( str( root ), old_sha, "page.md" ).startswith( "## A" )
    assert pp.read_at( str( root ), "HEAD", "page.md" ) == "index\n"
    assert pp.read_at( str( root ), old_sha, "part.md" ) is None


def test_build_pairs_reads_old_at_its_revision_and_new_at_the_head_from_the_manifest( repo ):
    root, old_sha = repo
    manifest = [ { "page": "page.md", "old_ref": old_sha, "old_path": "page.md", "new_ref": "HEAD", "new_paths": [ "page.md", "part.md" ] } ]
    pairs = pp.build_pairs( str( root ), manifest, target_words=600 )
    assert len( pairs ) == 1 and pairs[ 0 ][ "id" ] == "page.md#000"
    assert pairs[ 0 ][ "old" ].startswith( "## A" )
    assert "index" in pairs[ 0 ][ "new" ] and "part" in pairs[ 0 ][ "new" ]


def test_a_page_with_no_old_text_is_refused_by_name( repo ):
    root, old_sha = repo
    manifest = [ { "page": "part.md", "old_ref": old_sha, "old_path": "part.md", "new_ref": "HEAD", "new_paths": [ "part.md" ] } ]
    with pytest.raises( ValueError, match="part.md" ):
        pp.build_pairs( str( root ), manifest, target_words=600 )


def test_a_page_whose_new_path_is_missing_is_refused_by_name( repo ):
    root, old_sha = repo
    manifest = [ { "page": "page.md", "old_ref": old_sha, "old_path": "page.md", "new_ref": "HEAD", "new_paths": [ "gone.md" ] } ]
    with pytest.raises( ValueError, match="gone.md" ):
        pp.build_pairs( str( root ), manifest, target_words=600 )


def test_main_writes_the_pairs_file_and_prints_the_counts( repo, tmp_path_factory, capsys ):
    root, old_sha = repo
    out_dir  = tmp_path_factory.mktemp( "out" )
    manifest = out_dir / "manifest.json"
    manifest.write_text( json.dumps( [ { "page": "page.md", "old_ref": old_sha, "old_path": "page.md", "new_ref": "HEAD", "new_paths": [ "page.md" ] } ] ) )
    out = out_dir / "pairs.json"
    rc = pp.main( [ "--root", str( root ), "--manifest", str( manifest ), "--out", str( out ), "--target-words", "600" ] )
    assert rc == 0
    assert json.loads( out.read_text() )[ 0 ][ "id" ] == "page.md#000"
    assert "1 pages, 1 pairs" in capsys.readouterr().out
