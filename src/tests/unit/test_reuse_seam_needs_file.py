"""
Seam: the needs file one stage writes and the end-to-end driver and the need check read.

The writer is the real `need_writer.run_members` and `need_writer.needs_document`; only the model reply is a scripted
function, so nothing is sent. The two readers, `reuse_e2e.load_needs` and `reuse_need_check.load_needs`, are the real ones.
The hand copies of the document in test_reuse_e2e_inputs.py and test_reuse_need_check.py are what this replaces as evidence.
"""
import asyncio
import hashlib
import json
import pathlib
import re

from cosa.repo.symindex import need_writer as nw
from lupin_mcp import reuse_e2e as e2e
from lupin_mcp import reuse_need_check as nc

FIXTURE = pathlib.Path( __file__ ).resolve().parent.parent / "fixtures" / "reuse_e2e" / "sample-by-component-58-42-seed-20261007.json"
OPENER  = re.compile( r'begins "(A (?:function|method|class) that )"' )


def make_source_tree( base, members ):
    """
    Write one small source file per module, so each id resolves to a function or a method.

    Ensures:
        - an id whose second-last part is capitalised becomes a method of that class, and a class holds all of its methods in one block
        - any other id becomes a function
    """
    modules = {}
    for m in members:
        parts = m.split( "." )
        if parts[ -2 ][ 0 ].isupper(): modules.setdefault( tuple( parts[ :-2 ] ), {} ).setdefault( parts[ -2 ], [] ).append( parts[ -1 ] )
        else:                          modules.setdefault( tuple( parts[ :-1 ] ), {} ).setdefault( None, [] ).append( parts[ -1 ] )
    for module, groups in modules.items():
        body = ""
        for cls, names in groups.items():
            if cls is None: body += "".join( f"def {n}( payload ):\n    return payload\n\n" for n in names )
            else: body += f"class {cls}:\n" + "".join( f"    def {n}( self, payload ):\n        return payload\n" for n in names ) + "\n"
        path = pathlib.Path( base ).joinpath( *module ).with_suffix( ".py" )
        path.parent.mkdir( parents=True, exist_ok=True )
        path.write_text( body, encoding="utf-8" )


class Scripted:
    """A scripted reply that opens the way the prompt asks."""

    async def __call__( self, prompt, system_prompt ):
        opener = OPENER.search( prompt ).group( 1 )
        return nw.Reply( text=opener + "gathers whatever pieces it is handed and hands back a tidy summary for whoever asked.",
                         session_id="job-" + hashlib.sha1( prompt.encode() ).hexdigest()[ :8 ], cost_usd=0.0, input_tokens=1, output_tokens=1 )


def write_needs_file( tmp_path ):
    """Ensures: returns ( needs path, needs sha, sample sha, members ) from the real writer."""
    members    = e2e.load_sample( FIXTURE )
    src_root   = tmp_path / "src"
    make_source_tree( src_root, members )
    run_dir    = tmp_path / "run"
    asyncio.run( nw.run_members( members, str( src_root ), str( run_dir ), Scripted() ) )
    sample_sha = hashlib.sha256( FIXTURE.read_bytes() ).hexdigest()
    document   = nw.needs_document( str( run_dir ), members, sample_sha )
    path       = tmp_path / "needs.json"
    text       = json.dumps( document, indent=2 )
    path.write_text( text, encoding="utf-8" )
    return path, hashlib.sha256( text.encode( "utf-8" ) ).hexdigest(), sample_sha, members


def test_the_needs_file_the_real_writer_wrote_loads_through_the_drivers_loader( tmp_path ):
    path, sha, sample_sha, members = write_needs_file( tmp_path )
    got = e2e.load_needs( path, sha, members, sample_sha )
    assert [ g[ "member" ] for g in got ] == members and len( got ) == 100
    assert all( g[ "need" ].startswith( ( "A function that ", "A method that ", "A class that " ) ) for g in got )


def test_the_same_file_loads_through_the_need_checks_loader_with_the_same_members_and_sentences( tmp_path ):
    path, sha, sample_sha, members = write_needs_file( tmp_path )
    driver  = { g[ "member" ]: g[ "need" ] for g in e2e.load_needs( path, sha, members, sample_sha ) }
    checker = nc.load_needs( path, sample_sha )
    assert checker == driver and list( checker ) == members


def test_both_loaders_refuse_the_writers_file_against_another_sample_hash( tmp_path ):
    path, sha, sample_sha, members = write_needs_file( tmp_path )
    other = "0" * 64
    try: e2e.load_needs( path, sha, members, other )
    except e2e.FrozenInputRefused as e: assert "sample_sha256" in str( e )
    else: raise AssertionError( "the driver's loader accepted a needs file written for another sample" )
    try: nc.load_needs( path, other )
    except ValueError as e: assert "sample_sha256" in str( e )
    else: raise AssertionError( "the checker's loader accepted a needs file written for another sample" )
