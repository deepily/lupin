"""
The recorded search: a fixed-string search of the tree that backs a ruling of distinct.

It asks no model. The terms come from the text of a reuse receipt, or of an indexed entry.
Each term is searched with `git grep`. Every hit is mapped to the indexed definition that holds its line.
The five nearest definitions are written once as a search record that the exit gate can check.
"""
import re
import subprocess

from cosa.repo.symindex import build as sx_build
from cosa.repo.symindex.candidates.identifier_split import split_identifier
from cosa.repo.symindex.paths import index_readable
from cosa.repo.symindex.spec import spec_for
from lupin_mcp import reuse_tools as rt

MIN_TERMS  = 3                                                  # a search needs at least this many terms in all
MAX_TERMS  = 6                                                  # and at most this many
MIN_WORD   = 4                                                  # a derived term is at least this many characters
TOP        = 5                                                  # candidates kept
BATCH      = 500                                                # paths per `git grep` call
SEARCH_DIR = "search-records"
SEARCH_ID  = re.compile( r"^rs-[0-9a-f]{10}$" )
BACKS      = ( "check_exists", "fetch_similar" )                # the receipts a search can back
SCOPE      = [ "public", "private" ]                            # tests are searched only when item 1.6 lands
STOP_WORDS = frozenset( { "about", "after", "also", "been", "does", "each", "from", "have", "into", "just", "like", "make", "more", "most", "only",
                          "over", "return", "returns", "self", "some", "such", "than", "that", "their", "them", "then", "there", "they", "this",
                          "true", "false", "none", "used", "uses", "using", "very", "were", "what", "when", "which", "will", "with", "would" } )
HIT_LINE   = re.compile( r"(\d+)[:\0-]" )


class SearchError( Exception ):
    """
    A named failure of a recorded search.

    Requires:
        - name is one of the error names of the search tool
    """

    def __init__( self, name, detail="" ):
        super().__init__( f"{name}: {detail}" )
        self.name, self.detail = name, detail


def derive_terms( text, room=MAX_TERMS, skip=() ):
    """
    Derive the search terms of a text.

    Requires:
        - text is a string; room is the most terms to return; skip holds lowercase words to leave out

    Ensures:
        - splits with split_identifier, the one splitter of the candidate stage, and writes no rule of its own
        - keeps words of at least MIN_WORD characters that are not in STOP_WORDS or skip, each once
        - returns at most room of them, the longest first and ties in alphabetical order, so the same text gives the same terms
    """
    words = []
    for w in split_identifier( text ):
        if len( w ) >= MIN_WORD and w not in STOP_WORDS and w not in skip and w not in words: words.append( w )
    return sorted( words, key=lambda w: ( -len( w ), w ) )[ :room ]


def search_terms( text, extra_terms ):
    """
    Join the terms derived from a text with the terms the agent added.

    Requires:
        - extra_terms is a list of strings

    Ensures:
        - returns the derived terms followed by the added ones, each added term stripped and kept once
        - the derived terms are cut so the total never passes MAX_TERMS
    Raises:
        - SearchError TOO_MANY_TERMS when the added terms alone pass MAX_TERMS
        - SearchError NO_TERMS when fewer than MIN_TERMS terms result
    """
    extra = []
    for t in extra_terms:
        t = t.strip()
        if t and t.lower() not in [ e.lower() for e in extra ]: extra.append( t )
    if len( extra ) > MAX_TERMS: raise SearchError( "TOO_MANY_TERMS", f"{len( extra )} added terms, at most {MAX_TERMS}" )
    terms = derive_terms( text, MAX_TERMS - len( extra ), { e.lower() for e in extra } ) + extra
    if len( terms ) < MIN_TERMS: raise SearchError( "NO_TERMS", f"{len( terms )} terms, at least {MIN_TERMS} are needed: add some in extra_terms" )
    return terms


def git_grep( root, term, paths ):
    """
    Search the working tree for one fixed string.

    Requires:
        - root is a git working tree and paths are relative paths under it

    Ensures:
        - returns ( path, line number ) for every hit, case-insensitive, in tracked files with their uncommitted edits and in untracked files
        - passes the arguments as a list, never through a shell, and asks about 500 paths at a time
        - reads every path literally, so a path with a glob character in it names that path and no other
        - returns [] without starting git when paths is empty, since an empty pathspec would search the whole tree
    Raises:
        - SearchError GREP_FAILED when git exits with a code other than 0 or 1
    """
    hits = []
    for i in range( 0, len( paths ), BATCH ):
        res = subprocess.run( [ "git", "--literal-pathspecs", "grep", "--untracked", "--null", "-n", "-F", "-i", "-e", term, "--", *paths[ i:i + BATCH ] ],
                              cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace" )
        if res.returncode not in ( 0, 1 ): raise SearchError( "GREP_FAILED", f"git exited {res.returncode}: {res.stderr.strip()[ :200 ]}" )
        for line in res.stdout.splitlines():
            name, sep, rest = line.partition( "\0" )
            found = HIT_LINE.match( rest ) if sep else None
            if found: hits.append( ( name, int( found.group( 1 ) ) ) )
    return hits


def run_search( ctx, terms, paths, grep=git_grep, fresh=sx_build.is_fresh ):
    """
    Search every term, then check that the tree did not move while the search ran.

    Requires:
        - grep takes ( root, term, paths ) and returns ( path, line ) pairs; fresh takes ( spec, out_dir )

    Ensures:
        - returns ( path, line, term ) for every hit of every term
        - nothing is searched when paths is empty
    Raises:
        - SearchError INDEX_STALE when the index is no longer fresh after the last grep, so the spans may not match the hits
    """
    hits = [ ( path, line, term ) for term in terms for path, line in grep( ctx.root, term, paths ) ] if paths else []
    if not fresh( spec_for( ctx.root ), ctx.out_dir ): raise SearchError( "INDEX_STALE", "a file changed while the search ran" )
    return hits


def map_hits( hits, records ):
    """
    Give every hit to the definition whose lines hold it.

    Requires:
        - records are index records with file and line, and end_line when the extractor knows it

    Ensures:
        - returns ( found, dropped ): found maps a definition id to { rec, terms, lines }, dropped counts the hit lines in no definition
        - a hit goes to the innermost definition whose line to end_line span holds it
        - a hit outside every span, or in a file whose records have no end_line, is dropped and counted, never given to a neighbour
    """
    spans = {}
    for r in records:
        if "end_line" in r: spans.setdefault( r[ "file" ], [] ).append( r )
    found, lost = {}, set()
    for path, line, term in hits:
        inside = [ r for r in spans[ path ] if r[ "line" ] <= line <= r[ "end_line" ] ] if path in spans else []
        if not inside:
            lost.add( ( path, line ) ); continue
        best = max( inside, key=lambda r: ( r[ "line" ], -r[ "end_line" ] ) )
        row  = found.setdefault( best[ "id" ], { "rec": best, "terms": set(), "lines": set() } )
        row[ "terms" ].add( term ); row[ "lines" ].add( line )
    return found, len( lost )


def rank_candidates( found, exclude_id ):
    """
    Rank the definitions the hits landed in.

    Ensures:
        - orders by the number of distinct terms matched, then the number of hit lines, then the symbol id
        - leaves out exclude_id, the definition under review
        - returns at most five candidates, each { id, file, line, sig, terms_matched }
    """
    rows = sorted( ( f for f in found.values() if f[ "rec" ][ "id" ] != exclude_id ), key=lambda f: ( -len( f[ "terms" ] ), -len( f[ "lines" ] ), f[ "rec" ][ "id" ] ) )
    return [ { "id": f[ "rec" ][ "id" ], "file": f[ "rec" ][ "file" ], "line": f[ "rec" ][ "line" ], "sig": f[ "rec" ][ "sig" ], "terms_matched": sorted( f[ "terms" ] ) }
             for f in rows[ :TOP ] ]


def receipt_source( ctx, receipt_id ):
    """
    Read what a search is about from the reuse receipt it backs.

    Ensures:
        - returns ( text, language, exclude_id, index_sha ) taken from the receipt and its own snapshot, never from the live index
        - a fetch_similar receipt gives its stored need_text, else the entry text its snapshot holds, so a rebuild since then cannot break the search
        - a receipt with no language searches every language, as it did
    Raises:
        - ReuseError RECEIPT_MISSING, RECEIPT_CORRUPT or RECEIPT_ID_MISMATCH from load_receipt
        - SearchError BAD_SEARCH_KEY for a receipt of another tool
        - SearchError UNKNOWN_ENTRY when the snapshot no longer holds the entry
    """
    r = rt.load_receipt( ctx, receipt_id )
    if r[ "tool" ] not in BACKS: raise SearchError( "BAD_SEARCH_KEY", f"a search backs a {' or '.join( BACKS )} receipt, not one of {r[ 'tool' ]}" )
    language = r[ "language" ] if "language" in r else "all"
    if r[ "tool" ] == "check_exists": return r[ "query" ], language, r[ "exclude_id" ] if "exclude_id" in r else None, r[ "index_sha" ]
    entry = r[ "query" ]
    if "need_text" in r: return r[ "need_text" ], language, entry, r[ "index_sha" ]
    entries, _ = rt.load_snapshot( ctx, r[ "index_sha" ] )
    hit = next( ( e for e in entries if e[ "id" ] == entry ), None )
    if hit is None: raise SearchError( "UNKNOWN_ENTRY", entry )
    return rt.entry_text( hit ), language, entry, r[ "index_sha" ]


def entry_source( gen, entry ):
    """
    Read what a search is about from an indexed entry that the tools refused to send.

    Ensures:
        - returns ( text, index_sha ): the entry's id, signature and first docstring line, and the generation's search hash
    Raises:
        - SearchError UNKNOWN_ENTRY when the generation holds no public or private definition of that id
    """
    hit = next( ( r for r in sx_build.read_searchable( gen ) if r[ "id" ] == entry ), None )
    if hit is None: raise SearchError( "UNKNOWN_ENTRY", entry )
    return rt.entry_text( hit ), sx_build.read_header( gen )[ "search_sha" ]


def search_record_id( record ):
    """Ensures: returns `rs-` plus ten hex characters of the hash of the record."""
    return "rs-" + rt.sha( rt.canonical( record ), 10 )


def record_search_impl( receipt_id, entry, extra_terms, language, ctx ):
    """
    Search the tree for the nearest existing code and record the search.

    Requires:
        - exactly one of receipt_id and entry is given
        - receipt_id is the reuse receipt of the check_exists or fetch_similar call the search backs; it brings its own language
        - entry is a symbol id, for a definition that has no receipt; it needs a language, py, ts, dart or all
        - extra_terms is None or a list of strings the agent adds to the derived terms; three to six terms are searched in all

    Ensures:
        - returns { status, search_id, receipt_id, candidates, terms, dropped_hits }, the candidates at most five
        - the search record is written once under search-records, named by its id, so the same search on the same tree is a no-op
        - the index is brought up to date first, so the spans describe the working tree as it is now
        - a named error comes back as { status: error, error, detail } and never as an empty candidate list
    """
    try:
        return _search( receipt_id, entry, extra_terms, language, ctx )
    except ( SearchError, rt.ReuseError ) as e:
        return { "status": "error", "error": e.name, "detail": e.detail }


def _search( receipt_id, entry, extra_terms, language, ctx ):
    """Ensures: does the work of record_search_impl and raises its named errors."""
    if ( receipt_id is None ) == ( entry is None ): raise SearchError( "BAD_SEARCH_KEY", "give exactly one of receipt_id and entry" )
    if receipt_id is not None and language is not None: raise SearchError( "BAD_SEARCH_KEY", "a receipt_id search takes the language of its receipt" )
    extra = [] if extra_terms is None else extra_terms
    if not isinstance( extra, list ) or not all( isinstance( t, str ) for t in extra ): raise SearchError( "BAD_SEARCH_KEY", "extra_terms is a list of strings" )
    if any( "\n" in t or "\0" in t for t in extra ): raise SearchError( "BAD_SEARCH_KEY", "an added term is one line of text, with no newline or NUL" )
    if entry is not None:
        bad = rt.language_error( language )
        if bad is not None: return bad
    if not index_readable( ctx.root ): raise SearchError( "NOT_LUPIN_TREE", str( ctx.root ) )
    if receipt_id is not None: text, language, exclude_id, index_sha = receipt_source( ctx, receipt_id )
    try:
        gen = sx_build.ensure( ctx.root, ctx.out_dir )
    except Exception as e:                                                   # a build that cannot finish leaves the index stale
        raise SearchError( "INDEX_STALE", f"{type( e ).__name__}: {e}" ) from e
    if entry is not None:
        text, index_sha = entry_source( gen, entry )
        exclude_id      = entry
    terms   = search_terms( text, extra )
    records = rt.in_language( sx_build.read_searchable( gen ), language )
    hits    = run_search( ctx, terms, sorted( { r[ "file" ] for r in records } ) )
    found, dropped = map_hits( hits, records )
    candidates     = rank_candidates( found, exclude_id )
    record = { "receipt_id": receipt_id, "entry": entry, "terms": terms, "language": language, "scope": SCOPE, "index_sha": index_sha, "generation": gen.name,
               "candidates": candidates, "dropped_hits": dropped }
    sid = search_record_id( record )
    rt.write_once( ctx.data / SEARCH_DIR / f"{sid}.json", ( rt.canonical( { "id": sid, **record } ) + "\n" ).encode( "utf-8" ) )
    return { "status": "ok", "search_id": sid, "receipt_id": receipt_id, "candidates": candidates, "terms": terms, "dropped_hits": dropped }
