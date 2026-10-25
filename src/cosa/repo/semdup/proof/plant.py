"""Planted rewrites: pick originals, name the banned words and check a rewrite."""
import ast
import pathlib
import random
import re
import textwrap

from cosa.repo.symindex import dups, need_input, py_index
from cosa.repo.symindex import spec as sp
from cosa.repo.symindex.candidates.identifier_split import split_identifier
from cosa.repo.symindex.need_writer import name_hits

SCRIPT_SHARE    = 0.6
MIN_NAME_LEN    = 3
MIN_WORD_LEN    = 4
SAME_SHAPE      = dups.DEFAULT_THRESH
TRIES           = 3
FAILURE_KINDS   = ( "banned_word", "unparsable", "same_shape" )
SYSTEM_PROMPT   = "You rewrite one function so it does the same job in a different way. Reply with the rewritten function source only, in the language it was given in."


def select_originals( pool, count, seed, min_nodes, script_share=SCRIPT_SHARE ):
    """
    Draw the definitions to rewrite, with a fixed share of script definitions.

    Requires:
        - pool is a list of definition records with id, lang ("py" or a script language) and nodes
        - count is a positive int; seed is an int; min_nodes is the frozen minimum

    Ensures:
        - returns count records sorted by id: round( count * script_share ) script ones and the rest Python, all with at least min_nodes nodes
        - the same seed gives the same draw whatever order the pool arrives in
        - the draw is made from the ids in sorted order, so a pool in another order cannot move it

    Raises:
        - ValueError if count is below 1 or a language has fewer eligible definitions than it needs
    """
    if count < 1: raise ValueError( f"count must be 1 or more, got {count}" )
    eligible = sorted( ( d for d in pool if d[ "nodes" ] >= min_nodes ), key=lambda d: d[ "id" ] )
    script   = [ d for d in eligible if d[ "lang" ] != "py" ]
    python   = [ d for d in eligible if d[ "lang" ] == "py" ]
    want     = round( count * script_share )
    if len( script ) < want or len( python ) < count - want:
        raise ValueError( f"need {want} script and {count - want} Python definitions, found {len( script )} and {len( python )} with {min_nodes} nodes or more" )
    rng    = random.Random( seed )
    chosen = rng.sample( script, want ) + rng.sample( python, count - want )
    return sorted( chosen, key=lambda d: d[ "id" ] )


def python_forbidden( rec, root ):
    """
    List the names need_input forbids for a Python definition.

    Requires:
        - rec is a Python definition record; root is the repository root, whose spec names the folder module ids resolve under

    Ensures:
        - returns need_input.build_input( module.name, the spec's module base ).forbidden, longest first
    """
    spec   = sp.spec_for( root )
    module = py_index.module_name( spec, pathlib.Path( root ) / rec[ "file" ] )
    return need_input.build_input( f"{module}.{rec[ 'name' ]}", str( spec.module_base ) ).forbidden


def banned_names( rec, forbidden=() ):
    """
    List the words a rewrite of a definition may not contain.

    Requires:
        - rec is a definition record with name, file and declared
        - forbidden is the names need_input forbids for a Python definition (python_forbidden), or empty for a script one

    Ensures:
        - returns names of 3 or more characters from forbidden, the declared locals, the definition's name, its class and its file stem,
          plus every word of 4 or more letters of those names, longest first and each once
        - self and cls are never banned, because a method cannot be written without them
        - a script definition's names come from declared, its name, class and file stem, because need_input resolves Python modules only
    """
    pieces = [ *forbidden, *rec[ "declared" ], *rec[ "name" ].split( "." ), rec[ "file" ].rsplit( "/", 1 )[ -1 ].split( "." )[ 0 ] ]
    names  = { p for p in pieces if len( p ) >= MIN_NAME_LEN and p not in need_input.KEEP_NAMES }
    names |= { w for p in list( names ) for w in split_identifier( p ) if len( w ) >= MIN_WORD_LEN }
    return sorted( names, key=lambda n: ( -len( n ), n ) )


def strip_names( text, declared, name=None ):
    """
    Replace the definition's name and declared names by placeholders, longest name first.

    Requires:
        - text is the definition's source; declared is its declared names; name is its own name or None

    Ensures:
        - returns ( stripped text, the names replaced )
        - name becomes `NAME` and each declared name `ARGn`, numbered in the order the names first appear in the text
        - a longer name is replaced before a shorter one it contains, so getUserId never becomes a half-replaced getARG1Id
        - a name matches only as a whole word
    """
    names = sorted( { n for n in declared if n }, key=lambda n: ( -len( n ), n ) )
    if name: names = [ name ] + [ n for n in names if n != name ]
    if not names: return text, []
    first   = { n: ( m.start() if ( m := re.search( r"(?<![A-Za-z0-9_])" + re.escape( n ) + r"(?![A-Za-z0-9_])", text ) ) else len( text ) ) for n in names }
    order   = sorted( ( n for n in names if n != name ), key=lambda n: ( first[ n ], n ) )
    holders = { n: f"ARG{i}" for i, n in enumerate( order, start=1 ) }
    if name: holders[ name ] = "NAME"
    pattern = re.compile( r"(?<![A-Za-z0-9_])(" + "|".join( re.escape( n ) for n in names ) + r")(?![A-Za-z0-9_])" )
    return pattern.sub( lambda m: holders[ m.group( 1 ) ], text ), names


def rewrite_prompt( original, banned, failures=None ):
    """
    Build the prompt that asks for a rewrite.

    Requires:
        - original is the definition's source; banned is its banned words
        - failures is None or the failure kinds of the last try, with banned_word naming the words found as { "banned_word": [ words ] }

    Ensures:
        - returns ( system prompt, user prompt )
        - the user prompt holds the source and every banned word, and says each failure of the last try without the original's shape
    """
    lines = [ "Rewrite this function so it does the same job without using any of these words anywhere, in names, strings or comments:",
              ", ".join( banned ), "", original ]
    for kind, detail in ( failures or {} ).items():
        if kind == "banned_word": lines += [ "", f"Your last try still used: {', '.join( detail )}." ]
        if kind == "unparsable": lines += [ "", "Your last try did not parse. Reply with valid source only." ]
        if kind == "same_shape": lines += [ "", "Your last try was built the same way as the original. Use a different way of doing the job." ]
    return SYSTEM_PROMPT, "\n".join( lines )


def python_shape( text ):
    """
    Return the shingle set of the first function in Python source, or None.

    Requires:
        - text is a string

    Ensures:
        - returns dups.shingles of the first function definition, indentation removed first
        - returns None when the text does not parse or holds no function
    """
    try:
        tree = ast.parse( textwrap.dedent( text ) )
    except SyntaxError:
        return None
    for node in ast.walk( tree ):
        if isinstance( node, ( ast.FunctionDef, ast.AsyncFunctionDef ) ): return dups.shingles( node )
    return None


def check_rewrite( original, rewrite, banned, shape_of=python_shape, threshold=SAME_SHAPE ):
    """
    Judge a rewrite against its original.

    Requires:
        - original and rewrite are definition sources; banned is the banned words
        - shape_of takes a source and returns its shingle set, or None when it does not parse; threshold is the near cut

    Ensures:
        - returns { failure kind: detail } for each kind of FAILURE_KINDS that applies; empty when the rewrite passes
        - banned_word: the banned words found as whole words, by need_writer.name_hits
        - unparsable: the rewrite does not parse
        - same_shape: the Jaccard of the two shingle sets is at or above threshold (the dups near cut)
    """
    failed = {}
    hits   = name_hits( banned, rewrite )
    if hits: failed[ "banned_word" ] = hits
    shape  = shape_of( rewrite )
    if shape is None:
        failed[ "unparsable" ] = True
    else:
        base = shape_of( original )
        if base is not None and dups.jaccard( base, shape ) >= threshold: failed[ "same_shape" ] = dups.jaccard( base, shape )
    return failed


def plant_rewrite( original, banned, ask, shape_of=python_shape, tries=TRIES ):
    """
    Ask for a rewrite until one passes or the tries run out.

    Requires:
        - ask takes ( system prompt, user prompt ) and returns the reply text
        - tries is 1 or more

    Ensures:
        - returns { "status": "planted", "rewrite", "tries" } for the first rewrite that passes check_rewrite
        - returns { "status": "failed", "tries", "failures": [ one failure dict per try ] } when none passes, so the next original is drawn
        - each retry names the last failure in its prompt
    """
    failures, last = [], None
    for attempt in range( 1, tries + 1 ):
        reply  = ask( *rewrite_prompt( original, banned, last ) )
        failed = check_rewrite( original, reply, banned, shape_of )
        if not failed: return { "status": "planted", "rewrite": reply, "tries": attempt }
        failures.append( failed )
        last = failed
    return { "status": "failed", "tries": tries, "failures": failures }
