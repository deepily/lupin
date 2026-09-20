"""
A parity test names the legacy `file:line` it mirrors — build plan §6 item 19,
weak form, ruled by Mr. Radio 🦉 2026-09-17.

WHY THIS FILE EXISTS: §6 item 19 was a convention, and a rule that depends on
remembering is not installed. Nine test files already claim a parity row key in
their header; two of them name the legacy coordinate they mirror. Nothing
noticed the other seven, because nothing was looking.

THE RECOGNISER IS THE CLAIM, NOT THE CITATION. The obvious predicate — "a
parity test is one that cites a legacy file:line" — is a tautology: the citation
IS the thing being checked, so a test that forgot its citation is invisible to a
guard that finds parity tests by their citations. Such a guard is green on an
empty set and can never report a violation. So the population here is DECLARED:
a test opts in by naming its build-item row key in its header comment
("Parity A-0", "parity A-2 #2b"), and the row key must be one the manifest
actually lists. The denominator is the manifest's 42 row keys, and this file
asserts that denominator before it asserts anything about the tests.

"HEADER COMMENT", NOT "DOCSTRING". Item 19's cell said docstring; these are
TypeScript files and have none. The header is the first HEADER_LINES lines.

WEAK FORM AND STRONG FORM — BOTH ARE HERE. Weak: the coordinate is PRESENT
and well-formed. Strong (Mr. Radio 🦉's ruling, 2026-09-18): the coordinate
RESOLVES at HEAD —
  - a notifications.js citation names a legacy METHOD on its header line, and
    its whole line range falls inside that method's body (the `name(…) {` line
    through its closing brace);
  - a notifications.html citation names an element ID, and its whole range
    falls between that element's open tag and its matching close tag, found by
    PARSING the markup, not by counting lines;
  - the named method or id must appear in a note the row derives from
    (`io/phase2/A<n>.md`, as the manifest row cites it); a row with no note,
    like A-0, is held to the name in its own header instead;
  - a citation that names no method or id is red: the header must name one.

WHY BY NAME AND NOT BY THE NOTE'S LINE NUMBERS. The io/phase2 notes were read
off an older notifications.js, and their coordinates had already drifted when
they were committed (A3 R3 cites `js:21636-21645`; at f63350e3 that is another
method). A range check against them would reject citations that are right
today. A method or id name survives the drift; a line number does not.

"ON ITS HEADER LINE" means the same line as the coordinate or the line just
above it, so a wrapped comment still counts. Every name on that line is a
candidate, and the citation resolves if ANY of them contains the whole range:
a prose word that happens to be a method name can widen the candidates, but it
cannot make a range resolve that is not inside that method.
"""

from html.parser import HTMLParser

import re

from pathlib import Path

import pytest

import cosa.utils.util as cu


MANIFEST_REL = "src/rnd/v0.2.1/2026.09.16-parity-build-row-manifest.md"

# The first N lines of a test file are its header comment. Generous enough to
# clear a licence block, tight enough that a citation buried beside an
# assertion 200 lines down does not count as naming the test's source.
HEADER_LINES = 12

# A row key as the manifest's summary table writes it: A-0, A-1c3, A-2 #2b, B-7,
# and also B-1b and B-5L.
#
# 🔴 THIS WAS AN ENUMERATION AND IT WAS WRONG. The first cut spelled the two
# halves differently — `A-\d+[a-z]?\d*` for the A rows and a bare `B-\d+` for
# the B rows — because every B key visible at a glance was a bare number. `B-1b`
# and `B-5L` are not, so the guard's denominator read 42 against a table of 44
# and said nothing: a floor of `>= 40` cannot see two keys it never parsed, and
# any test claiming one of them would have been reported as claiming a row the
# manifest does not list. Caught by Mr. Radio 🦉 on 2026-09-17 against a peer's
# count of 44.
#
# So this is one predicate for both halves, and the case class is [A-Za-z]
# rather than [a-z] because `B-5L` is capitalised. The shape is: a phase letter,
# a number, an optional letter-and-number suffix, and an optional ` #N` item
# with its own optional letter.
ROW_KEY = r"(?:[AB]-\d+[A-Za-z]?\d*(?:\s*#\d+[A-Za-z]?)?)"

# A test opts in by naming its row key after the word "parity", in any case.
# This is the OLD SHAPE. It is prose, and prose cannot tell a declaration from a
# mention — see TRANSITIONAL ARM below.
CLAIMS_A_ROW = re.compile( r"parity\s+(" + ROW_KEY + r")", re.IGNORECASE )

# ---------------------------------------------------------------------------
# S1 — THE STRUCTURED MARKER
# ---------------------------------------------------------------------------
#
# 🔴 THE RECOGNISER IS THE WHOLE PROBLEM, AND PROSE CANNOT SOLVE IT. A prose
# recogniser cannot distinguish a test DECLARING its row from a passage MENTIONING
# one. Two live files prove it, and neither is a claim:
#
#   notifications_js/both_clients_issue_the_same_request_for_every_control.test.ts:30
#       `//   mux   HoldingAreaStore   patchTask   PATCH /api/tasks/{id}  (parity A-2 #0)`
#       — a TABLE ROW. 0 legacy coordinates anywhere in that file.
#   this file, line 16
#       `("Parity A-0", "parity A-2 #2b"), and the row key must be one the manifest`
#       — THIS GUARD'S OWN DOCSTRING explaining its own format. A prose recogniser
#       wide enough to see them makes the guard police itself.
#
# Both sit outside the 12-line window TODAY, which is luck, not a control: they are
# at lines 30 and 16 of files whose headers happen to be long. Widen the window and
# they walk in. Measured by Maya 2026-09-19: every header-window variant admits both.
#
# THE MARKER IS DEFINED BY PLACEMENT, and that is what makes it immune. It is the
# FIRST content on its line after an optional comment leader. A table row has columns
# before it; a docstring example has quotes and prose before it. Neither can produce
# a marker no matter how wide the window gets.
PARITY_MARKER = re.compile(
    r"^[ \t]*(?://+|\#+|\*)?[ \t]*PARITY-(CLAIM|EXEMPT):[ \t]*(" + ROW_KEY + r")[ \t]*(.*)$"
)

# An exemption must say WHY, on the same line. Precedent: stylelint refuses a waiver
# without a same-line reason (`.stylelintrc.json:3`, `run-stylelint-gate.sh:85`).
# An em-dash or a double hyphen opens the reason.
EXEMPT_REASON = re.compile( r"^\s*(?:—|--|-)\s*(\S.*)$" )


# ---------------------------------------------------------------------------
# THE TRANSITIONAL ARM — how the old shape survives without a flag day
# ---------------------------------------------------------------------------
#
# Every one of the live `.test.ts` claims uses the old prose shape. A marker-ONLY
# recogniser would take the claiming census to ZERO, and a guard policing an empty
# set is green forever — the exact tautology this file's own header warns about.
# So the old shape keeps working, behind two filters that reject both known negatives.
#
# 🔴 THESE TWO FILTERS ARE A PROXY, NOT THE PREDICATE, AND THEY HAVE NO DENOMINATOR.
# They were FITTED to the two negatives we happened to find. Nothing here says a third
# prose shape does not exist. That is why the arm is SELF-RETIRING rather than
# permanent: `test_the_old_shape_count_only_shrinks` pins the count, it may only go
# down, and when it reaches zero these filters and this comment come out together.
# A prose caveat would protect only the reader who reads it; the count is mechanical.

def strip_comment_leader( line ):
    """The line's content, with `//`, `#` or a docstring `*` removed."""
    return re.sub( r"^\s*(?://+|\#+|\*)\s*", "", line )


def is_table_row( line ):
    """
    Two or more runs of 2+ spaces between non-space text = columns, not a sentence.

    Requires:
        - line is a single physical line

    Ensures:
        - returns True for an aligned table row, False for ordinary prose
    """
    return len( re.findall( r"\S {2,}(?=\S)", strip_comment_leader( line ).rstrip() ) ) >= 2


def is_inside_quotes( line, idx ):
    """
    Whether position `idx` falls inside a quoted span on `line`.

    Requires:
        - 0 <= idx < len( line )

    Ensures:
        - returns True when idx sits between a matched pair of single or double
          quotes, which is what a docstring's own format example looks like
    """
    for match in re.finditer( r"\"[^\"]*\"|'[^']*'", line ):
        if match.start() < idx < match.end(): return True
    return False


def old_shape_claim( header ):
    """
    The row key this header claims in the OLD prose shape, or None.

    Ensures:
        - returns the row key only when the claim is neither a table row nor
          inside quotes — the two shapes measured to be mentions, not declarations
        - returns None when the header carries no parity mention at all
    """
    for line in header.splitlines():
        match = CLAIMS_A_ROW.search( line )
        if match is None: continue
        if is_table_row( line ): continue
        if is_inside_quotes( line, match.start() ): continue
        return match.group( 1 )
    return None


def exemption_has_rotted( header ):
    """
    Whether this header declares PARITY-EXEMPT and then names a legacy coordinate.

    Requires:
        - header is the file's leading lines

    Ensures:
        - True only when BOTH an EXEMPT marker and a legacy coordinate are present
        - False for a non-exempt header, whatever it cites
    """
    marker = marker_claim( header )
    if marker is None or marker[ 0 ] != "EXEMPT": return False
    return LEGACY_COORD.search( header ) is not None


def marker_claim( header ):
    """
    ( kind, row_key, reason ) from this header's PARITY marker, or None.

    Ensures:
        - kind is "CLAIM" or "EXEMPT"
        - reason is the text after the row key for an EXEMPT, else ""
        - returns the FIRST marker; a second one is caught by its own test
    """
    for line in header.splitlines():
        match = PARITY_MARKER.match( line )
        if match is None: continue
        kind, key, rest = match.group( 1 ), match.group( 2 ), match.group( 3 )
        reason = EXEMPT_REASON.match( rest )
        return ( kind, key, reason.group( 1 ).strip() if reason else "" )
    return None

# The legacy client is two files, and a coordinate is a line or a line range.
LEGACY_COORD = re.compile( r"notifications\.(?:js|html):\d+(?:-\d+)?" )

# The same, capturing its parts, for the strong form.
LEGACY_CITE = re.compile( r"notifications\.(js|html):(\d+)(?:-(\d+))?" )

LEGACY_JS_REL   = "src/lupin_app/static/js/notifications.js"
LEGACY_HTML_REL = "src/lupin_app/static/html/notifications.html"
PHASE2_DIR_REL  = "io/phase2"

# A method or function DEFINITION whose `{` ends the line: a class method at
# four spaces, or a top-level function. Its body closes on the first later line
# that is exactly the same indent plus `}`. Measured 2026-09-18 at 2847ea74:
# 617 definitions, every one closing before the next begins.
JS_DEF = re.compile( r"^(    |)(?:async\s+)?(?:function\s+)?([A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{\s*$" )
JS_KEYWORDS = frozenset( { "if", "for", "while", "switch", "catch", "function" } )

# A name a header line might carry: a JS identifier, or an element id with or
# without its leading `#`.
NAME_TOKEN = re.compile( r"#?([A-Za-z_$][\w$-]*)" )

# The manifest's detail block names its notes as "Phase 2 A3 R3 / A4 item 6".
NOTE_REF = re.compile( r"\bA(\d{1,2})\b" )

# HTML elements that never have a close tag.
VOID_TAGS = frozenset( {
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
    "source", "track", "wbr",
} )

# The manifest's summary table: | Row key | Title | Pri | Depends-on |
MANIFEST_ROW = re.compile( r"^\|\s*(" + ROW_KEY + r")\s*\|" )

# ---------------------------------------------------------------------------
# THE TWO RATCHETS — both MEASURED at f53aa9d9 on 2026-09-19, not chosen
# ---------------------------------------------------------------------------
#
#     claims=27  exempt=0  old_shape=27
#
# DECLARED_POPULATION_FLOOR may only be RAISED. It is what stops a recogniser
# change from quietly shrinking the population every other rule here loops over.
# A floor of "at least one" cannot see 27 become 1.
DECLARED_POPULATION_FLOOR = 27

# OLD_SHAPE_CEILING may only be LOWERED. It is the transitional arm's blast radius,
# and the arm is deleted when this reaches 0. A new file uses `PARITY-CLAIM:`.
OLD_SHAPE_CEILING = 27

# Seven files claimed a row key before this guard existed and none of them names
# its legacy source. They are GRANDFATHERED so the guard can land green, and the
# list is a CEILING, not a floor: `test_the_grandfather_list_only_shrinks`
# fails when an entry stops violating, so the list cannot outlive the debt it
# records. Do not add to it — a new parity test names its source or goes red.
GRANDFATHERED = frozenset( {
    "src/tests/unit/multiplexer/action_required_persistence.test.ts",
    "src/tests/unit/multiplexer/boot_wires_action_required_to_reveal_through_the_toolbar.test.ts",
    "src/tests/unit/multiplexer/render/action_required_cancel.test.ts",
    "src/tests/unit/multiplexer/render/action_required_pause.test.ts",
    "src/tests/unit/multiplexer/render/action_required_progress.test.ts",
    "src/tests/unit/multiplexer/render/shared_row_controls_reach_every_pane.test.ts",
    "src/tests/unit/notifications_js/two_renderers_one_class_name.test.ts",
} )


def js_method_bodies( source ):
    """
    Every legacy method or function body, by name.

    Requires:
        - source is the text of notifications.js

    Ensures:
        - returns { name: [ ( def_line, close_line ), ... ] }, 1-based and
          inclusive; a name defined twice keeps both spans
        - a definition whose closing brace cannot be found is left out, so a
          citation of it goes red rather than resolving against a guess
    """
    lines  = source.splitlines()
    bodies = {}
    for i, line in enumerate( lines ):
        match = JS_DEF.match( line )
        if match is None or match.group( 2 ) in JS_KEYWORDS: continue
        close = match.group( 1 ) + "}"
        end   = next( ( j for j in range( i + 1, len( lines ) ) if lines[ j ].rstrip() == close ), None )
        if end is None: continue
        bodies.setdefault( match.group( 2 ), [] ).append( ( i + 1, end + 1 ) )
    return bodies


class _ElementSpans( HTMLParser ):
    """Records each id-bearing element's span from its open tag to its matching close tag."""

    def __init__( self ):
        super().__init__( convert_charrefs=True )
        self.stack = []
        self.spans = {}

    def handle_starttag( self, tag, attrs ):
        if tag in VOID_TAGS: return
        self.stack.append( ( tag, dict( attrs ).get( "id" ), self.getpos()[ 0 ] ) )

    def handle_endtag( self, tag ):
        # Pop to the matching open tag; anything above it was left unclosed.
        for depth in range( len( self.stack ) - 1, -1, -1 ):
            if self.stack[ depth ][ 0 ] != tag: continue
            _, element_id, start = self.stack[ depth ]
            if element_id: self.spans.setdefault( element_id, [] ).append( ( start, self.getpos()[ 0 ] ) )
            del self.stack[ depth: ]
            return


def html_element_spans( source ):
    """
    Every id-bearing element's span, by id.

    Requires:
        - source is the text of notifications.html

    Ensures:
        - returns { id: [ ( open_line, close_line ), ... ] }, 1-based and
          inclusive, from the line the open tag starts on to the line of its
          matching close tag — parsed, never counted
        - an element whose close tag never arrives is left out
    """
    parser = _ElementSpans()
    parser.feed( source )
    parser.close()
    return parser.spans


def row_notes( manifest_text, row_key, note_dir ):
    """
    The io/phase2 notes a manifest row derives from.

    Requires:
        - manifest_text is the manifest; note_dir is the io/phase2 directory

    Ensures:
        - returns the texts of every `A<n>.md` the row's detail block names
          (its bold `**<key> ·` line through the next blank line) that exists
        - a row that names no note returns an empty list
    """
    lines = manifest_text.splitlines()
    want  = _normalize( row_key )
    start = next(
        ( i for i, line in enumerate( lines )
          if line.startswith( "**" ) and _normalize( line[ 2: ].split( "·" )[ 0 ] ) == want ),
        None,
    )
    if start is None: return []
    block = []
    for line in lines[ start: ]:
        if not line.strip(): break
        block.append( line )
    names = sorted( set( NOTE_REF.findall( " ".join( block ) ) ), key=int )
    return [ ( note_dir / f"A{n}.md" ).read_text( encoding="utf-8" )
             for n in names if ( note_dir / f"A{n}.md" ).is_file() ]


# The one reason that is NOT a defect in the test. Named once, so the producer and
# the reporter cannot drift apart into two spellings of the same idea.
NOTE_REASON = "is not named in the row's note"


def report_by_class( offenders ):
    """
    The failure text, split by DEFECT CLASS, naming the artifact that holds each.

    Requires:
        - offenders is [ ( test_path, row_key, citation, reason ), ... ]

    Ensures:
        - returns a string with one section per class present, and no section for
          a class with no offenders
        - a CITATION section names the TEST as the thing to edit
        - a NOTE section names the io/phase2 note and says not to edit the test
        - every offender appears in exactly one section

    Why it is its own function rather than inline in the assertion: an assertion
    message only renders on failure, so logic living there is unguarded by
    construction — the suite is green whether it is right or wrong. Measured
    2026-09-19 (Maya 🌻): the first cut of this lived inline, added no test, and
    left the test count unchanged at 15.
    """
    note_defects = [ o for o in offenders if NOTE_REASON in o[ 3 ] ]
    cite_defects = [ o for o in offenders if NOTE_REASON not in o[ 3 ] ]

    report = []
    if cite_defects:
        report.append(
            f"{len( cite_defects )} CITATION defect(s) — FIX THE TEST'S HEADER. A "
            "notifications.js citation names its legacy method on the same header line "
            "and falls inside that method's body; a notifications.html citation names "
            "its element id and falls between that element's open and close tags:\n  "
            + "\n  ".join( f"{path} ({key}) {cite}: {reason}" for path, key, cite, reason in cite_defects )
        )
    if note_defects:
        report.append(
            f"{len( note_defects )} NOTE defect(s) — DO NOT EDIT THE TEST. Its citation "
            f"resolves; the row's note under {PHASE2_DIR_REL}/ does not name the method, "
            "so add the method to the note (or correct the note's row key):\n  "
            + "\n  ".join( f"{PHASE2_DIR_REL}/ note for row {key} is missing "
                            f"{reason.split( ' ' + NOTE_REASON )[ 0 ]}  (cited by {path} as {cite})"
                            for path, key, cite, reason in note_defects )
        )
    return "\n\n".join( report )


def unresolved_citations( header, bodies, spans, notes ):
    """
    Every legacy citation in a header that does NOT resolve, with the reason.

    Requires:
        - header is a test file's first HEADER_LINES lines
        - bodies / spans come from js_method_bodies / html_element_spans at HEAD
        - notes is row_notes() for the row the header claims

    Ensures:
        - returns [ ( citation, reason ), ... ], empty when every citation resolves
        - a citation resolves iff a name on its line (or the line above) is a
          legacy method (js) or element id (html) whose span contains the WHOLE
          cited range, and — when the row has notes — that name appears in one
    """
    lines    = header.splitlines()
    problems = []
    for index, line in enumerate( lines ):
        for cite in LEGACY_CITE.finditer( line ):
            kind   = cite.group( 1 )
            first  = int( cite.group( 2 ) )
            last   = int( cite.group( 3 ) or cite.group( 2 ) )
            table  = bodies if kind == "js" else spans
            what   = "method" if kind == "js" else "element id"
            nearby = line + " " + ( lines[ index - 1 ] if index > 0 else "" )
            named  = [ t for t in dict.fromkeys( NAME_TOKEN.findall( nearby ) ) if t in table ]
            if not named:
                problems.append( ( cite.group( 0 ), f"names no legacy {what} on its line" ) )
                continue
            if last < first:
                problems.append( ( cite.group( 0 ), "range runs backwards" ) )
                continue
            holders = [ n for n in named if any( a <= first and last <= b for a, b in table[ n ] ) ]
            if not holders:
                where = "; ".join( f"{n} is {a}-{b}" for n in named for a, b in table[ n ] )
                problems.append( ( cite.group( 0 ), f"not inside the {what} it names ({where})" ) )
                continue
            if notes and not any( re.search( r"(?<![\w$-])" + re.escape( n ) + r"(?![\w$-])", note )
                                  for n in holders for note in notes ):
                problems.append( ( cite.group( 0 ), f"{', '.join( holders )} {NOTE_REASON}" ) )
    return problems


def _normalize( row_key ):
    """
    Collapse a row key to a comparable form.

    Requires:
        - row_key is a string

    Ensures:
        - returns the key upper-cased with all internal whitespace removed,
          so "A-2 #2b", "A-2  #2B" and "A-2#2b" compare equal

    Raises:
        - AttributeError if row_key is not a string
    """
    return re.sub( r"\s+", "", row_key ).upper()


@pytest.fixture( scope="module" )
def project_root():
    return Path( cu.get_project_root() )


@pytest.fixture( scope="module" )
def summary_table( project_root ):
    """
    The manifest's summary table, parsed two independent ways.

    Returns ( keys, data_row_count ):
      - keys           every row key ROW_KEY could parse, normalized
      - data_row_count every data row in the table, counted WITHOUT ROW_KEY

    The two are separate on purpose. Counting rows by a pattern and then
    checking that count against the same pattern is a tautology; the row count
    here comes from the table's own shape — a pipe-delimited line that is not
    the header and not the `|---|` separator — so a key shape ROW_KEY cannot
    parse shows up as a DISAGREEMENT rather than as a silently short
    denominator. That is the defect this fixture exists to make impossible.

    Scoped to the `## Summary table` section alone. The `## Minting state`
    table above it repeats 15 of the same keys, so a whole-file parse conflates
    two populations and cannot say which one it is reporting.
    """
    text    = ( project_root / MANIFEST_REL ).read_text( encoding="utf-8" )
    lines   = text.splitlines()

    start = next( i for i, line in enumerate( lines ) if line.strip() == "## Summary table" )
    end   = next(
        ( i for i in range( start + 1, len( lines ) ) if lines[ i ].startswith( "## " ) ),
        len( lines ),
    )

    keys           = set()
    data_row_count = 0

    for line in lines[ start:end ]:
        if not line.startswith( "|" ): continue

        first_cell = line.split( "|" )[ 1 ].strip()
        if first_cell in ( "Row key", "" ) or set( first_cell ) <= set( "-: " ): continue

        data_row_count += 1

        match = MANIFEST_ROW.match( line )
        if match: keys.add( _normalize( match.group( 1 ) ) )

    return keys, data_row_count


@pytest.fixture( scope="module" )
def legacy_bodies( project_root ):
    return js_method_bodies( ( project_root / LEGACY_JS_REL ).read_text( encoding="utf-8" ) )


@pytest.fixture( scope="module" )
def legacy_spans( project_root ):
    return html_element_spans( ( project_root / LEGACY_HTML_REL ).read_text( encoding="utf-8" ) )


@pytest.fixture( scope="module" )
def manifest_text( project_root ):
    return ( project_root / MANIFEST_REL ).read_text( encoding="utf-8" )


@pytest.fixture( scope="module" )
def manifest_row_keys( summary_table ):
    """Every row key the manifest's summary table lists, normalized."""
    keys, _ = summary_table
    return keys


@pytest.fixture( scope="module" )
def claiming_tests( project_root ):
    """
    Every test file whose header claims a parity row key.

    Returns a list of ( repo_relative_path, row_key, header_text ) — the
    declared population this guard polices.
    """
    return parity_census( project_root )[ "claims" ]


def parity_census( project_root ):
    """
    The whole declared population, split by HOW it declares.

    Ensures:
        - "claims"    — [ ( path, row_key, header ) ] a file DECLARING a row, by
                        marker or by the transitional old shape. EXEMPT files are
                        NOT here: an exemption says this file mirrors no legacy
                        passage, so the weak form has nothing to ask of it
        - "exempt"    — [ ( path, row_key, reason, header ) ]
        - "old_shape" — the subset of paths in "claims" declaring via prose, the
                        number the transitional arm is retiring
    """
    claims, exempt, old_shape = [], [], []

    for path in sorted( project_root.glob( "src/tests/**/*.test.ts" ) ):
        rel    = str( path.relative_to( project_root ) )
        header = "\n".join( path.read_text( encoding="utf-8" ).splitlines()[ :HEADER_LINES ] )

        marker = marker_claim( header )
        if marker is not None:
            kind, key, reason = marker
            if kind == "EXEMPT": exempt.append( ( rel, key, reason, header ) )
            else:                claims.append( ( rel, key, header ) )
            continue

        key = old_shape_claim( header )
        if key is not None:
            claims.append( ( rel, key, header ) )
            old_shape.append( rel )

    return { "claims": claims, "exempt": exempt, "old_shape": old_shape }


@pytest.fixture( scope="module" )
def exempt_tests( project_root ):
    """Files declaring PARITY-EXEMPT — they mirror no legacy passage."""
    return parity_census( project_root )[ "exempt" ]


@pytest.fixture( scope="module" )
def old_shape_tests( project_root ):
    """Files still declaring via the transitional prose shape."""
    return parity_census( project_root )[ "old_shape" ]


# ---------------------------------------------------------------------------
# The denominator — asserted before anything is asserted about the tests.
# A loop over nothing passes every assertion inside it.
# ---------------------------------------------------------------------------

def test_the_manifest_is_readable_and_lists_its_rows( manifest_row_keys ):
    """Without the manifest there is no declared population, only a corpus."""
    assert len( manifest_row_keys ) >= 40, (
        f"the manifest's summary table parsed to {len( manifest_row_keys )} row keys; "
        f"44 were counted on 2026-09-17. A parse that collapses to a handful means the "
        f"table's shape changed and this guard is now policing a denominator it invented"
    )


def test_the_denominator_accounts_for_every_row_in_the_table( summary_table ):
    """
    ROW_KEY parses every data row the summary table has — no silent shortfall.

    This is the assertion whose absence let the denominator read 42 against a
    table of 44: `B-1b` and `B-5L` were unparseable, and a floor check cannot
    see a key it never parsed. The floor above answers "did the parse collapse";
    only this answers "did the parse account for everything".

    The two sides reach the same number by different routes — one by matching
    row keys, one by counting table rows — so they can actually disagree.
    """
    keys, data_row_count = summary_table

    assert len( keys ) == data_row_count, (
        f"the summary table has {data_row_count} data rows but ROW_KEY parsed only "
        f"{len( keys )} of them. A row key whose shape ROW_KEY cannot read is invisible "
        f"to this guard's denominator, and any test claiming it would be reported as "
        f"claiming a row the manifest does not list. Widen ROW_KEY to the shape actually "
        f"in the table — and widen it as a PREDICATE, not by adding another alternative"
    )


def test_at_least_one_test_claims_a_row( claiming_tests ):
    """
    The guard must be able to find a positive before a zero means anything.

    Nine files claimed a row on 2026-09-17. A drop to zero means the header
    convention changed and every assertion below is passing vacuously.
    """
    assert claiming_tests, (
        "no test file claims a parity row key in its header — either the convention "
        "changed or this guard's recogniser is broken. Either way it is now policing "
        "an empty set and cannot fail"
    )


# ---------------------------------------------------------------------------
# The rule itself
# ---------------------------------------------------------------------------

def test_every_claimed_row_key_is_one_the_manifest_lists( claiming_tests, manifest_row_keys ):
    """A test claiming a row that does not exist is pointing at nothing."""
    unknown = [
        ( path, key ) for path, key, _ in claiming_tests
        if _normalize( key ) not in manifest_row_keys
    ]

    assert not unknown, (
        "these tests claim a parity row key the manifest does not list — a typo, or a "
        "row key that was retired without sweeping the tests that vouch for it:\n  "
        + "\n  ".join( f"{path} claims {key!r}" for path, key in unknown )
    )


def test_a_parity_test_names_the_legacy_source_it_mirrors( claiming_tests ):
    """
    Build plan §6 item 19, weak form: if a test claims a build-item row, its
    header comment carries a well-formed legacy coordinate.

    Exemplar: `src/tests/unit/multiplexer/render/scroll_reveal.test.ts`, whose
    header names the row, the date, the author, and `notifications.js:25386-25408`.

    A PARITY-EXEMPT file is not in `claiming_tests` at all — an exemption is the
    statement that this file mirrors no legacy passage, so there is no coordinate
    for it to be missing. `test_an_exempt_file_carrying_a_legacy_coordinate_is_red`
    is what stops that from becoming a way to opt out of the rule.
    """
    offenders = [
        ( path, key ) for path, key, header in claiming_tests
        if not LEGACY_COORD.search( header ) and path not in GRANDFATHERED
    ]

    assert not offenders, (
        "these tests claim a parity row but do not name the legacy `file:line` they "
        f"mirror in their first {HEADER_LINES} lines (build plan §6 item 19). Add a "
        "`notifications.js:NNN` or `notifications.html:NNN-NNN` coordinate to the header, "
        "as `render/scroll_reveal.test.ts` does. The coordinate comes from the accordion "
        "the row derives from, in `io/phase2/`:\n  "
        + "\n  ".join( f"{path} claims {key!r}" for path, key in offenders )
    )


# ---------------------------------------------------------------------------
# S1 — the marker, the exemption, and the self-retiring transitional arm
# ---------------------------------------------------------------------------

def test_a_mention_is_not_a_claim( project_root ):
    """
    The two live shapes that MENTION a row without declaring one stay out.

    Both are pinned here as committed fixtures rather than described in prose:
    delete `is_table_row` or `is_inside_quotes` and THIS test names the shape that
    walked back in. They are the entire evidence base for the transitional arm, and
    an arm fitted to two examples has to keep those two examples where a deletion
    trips over them.

    Their real line numbers are given so a reader can go and look, but the assertion
    does NOT depend on them — a coordinate goes stale, and the shape is the point.
    """
    table_row = (
        "//     mux     HoldingAreaStore   patchTask           "
        "PATCH /api/tasks/{id}      (parity A-2 #0)"
    )   # notifications_js/both_clients_issue_the_same_request_for_every_control.test.ts
    docstring = (
        '("Parity A-0", "parity A-2 #2b"), and the row key must be one the manifest'
    )   # this file's own header, explaining its own format

    # Control FIRST: the recogniser DOES see a claim in both, so the rejection below
    # is the filters working and not the regex failing to match.
    assert CLAIMS_A_ROW.search( table_row ) is not None
    assert CLAIMS_A_ROW.search( docstring ) is not None

    assert old_shape_claim( table_row ) is None, (
        "a TABLE ROW mentioning a row key is being read as a claim — `is_table_row` "
        "is gone or broken. That file carries no legacy coordinate anywhere, so it "
        "would be reported as an offender for a row it never claimed"
    )
    assert old_shape_claim( docstring ) is None, (
        "a DOCSTRING EXAMPLE is being read as a claim — `is_inside_quotes` is gone or "
        "broken. The example above is this guard's own, so the guard would police itself"
    )

    # And ordinary prose still declares, or the transitional arm has eaten the corpus.
    assert old_shape_claim( " * Parity A-2 #2h — the card's keyboard." ) == "A-2 #2h"


def test_the_marker_is_recognised_and_survives_a_wide_window():
    """
    A marker is defined by PLACEMENT, which is what makes it window-proof.

    The two negatives above are admitted by every header-window variant Maya
    measured. Neither can be written as a marker, because a marker is the first
    content on its line.
    """
    assert marker_claim( "// PARITY-CLAIM: A-2 #10" )    == ( "CLAIM", "A-2 #10", "" )
    assert marker_claim( "# PARITY-CLAIM: A-2 #10" )     == ( "CLAIM", "A-2 #10", "" )
    assert marker_claim( " * PARITY-CLAIM: B-5L" )       == ( "CLAIM", "B-5L", "" )
    assert marker_claim( "PARITY-CLAIM: A-0" )           == ( "CLAIM", "A-0", "" )

    # The negatives cannot become markers: both have content before the claim.
    assert marker_claim( "//  mux  patchTask  (parity A-2 #0)" ) is None
    assert marker_claim( '("Parity A-0", "parity A-2 #2b"), and the row key' ) is None

    # A marker mentioned mid-sentence is prose about a marker, not a marker.
    assert marker_claim( "the file writes PARITY-CLAIM: A-2 #10 in its header" ) is None


def test_an_exemption_without_a_reason_is_refused():
    """
    Precedent: stylelint refuses a waiver with no same-line reason
    (`.stylelintrc.json:3`, `run-stylelint-gate.sh:85`).

    An exemption removes a file from the rule. The reason is the only thing that
    makes that auditable later, so it is not optional.
    """
    kind, key, reason = marker_claim( "# PARITY-EXEMPT: A-2 #2a — happy-dom has no cascade" )
    assert ( kind, key ) == ( "EXEMPT", "A-2 #2a" )
    assert reason == "happy-dom has no cascade"

    for reasonless in [ "# PARITY-EXEMPT: A-2 #2a",
                        "# PARITY-EXEMPT: A-2 #2a —",
                        "# PARITY-EXEMPT: A-2 #2a — " ]:
        assert marker_claim( reasonless )[ 2 ] == "", (
            f"{reasonless!r} produced a reason out of nothing"
        )


def test_every_declared_exemption_states_a_reason( exempt_tests ):
    """The live rule over the live corpus — the unit test above is its instrument."""
    reasonless = [ ( path, key ) for path, key, reason, _ in exempt_tests if not reason ]

    assert not reasonless, (
        "these files declare PARITY-EXEMPT with no reason on the marker line. An "
        "exemption that does not say why cannot be audited or retired — write "
        "`PARITY-EXEMPT: <row> — <why this file mirrors no legacy passage>`:\n  "
        + "\n  ".join( f"{path} exempts {key!r}" for path, key in reasonless )
    )


def test_rot_detection_fires_on_an_exemption_that_has_gone_stale():
    """
    🔴 THE INSTRUMENT FOR THE RULE BELOW, BECAUSE THE RULE BELOW CURRENTLY LOOPS
    OVER NOTHING.

    The only exempt file in the tree is `.py`, and this guard's glob is `.test.ts`
    until S4 widens it. So `exempt_tests` is EMPTY, and a corpus assertion over an
    empty list passes however broken the rule is. Found by mutation: breaking the
    exemption so a coordinate rides with it killed no test at all.

    This test owns the rule instead. It does not touch the corpus, so it keeps
    working before S4, after S4, and if every exempt file is one day deleted.
    """
    clean   = "# PARITY-EXEMPT: A-2 #2a — happy-dom has no cascade"
    rotted  = clean + "\nand it mirrors notifications.js:25892-25947"

    assert exemption_has_rotted( clean ) is False, "a clean exemption must not be flagged"
    assert exemption_has_rotted( rotted ) is True, (
        "an exempt file carrying a legacy coordinate is not being flagged. The "
        "exemption says the file mirrors no legacy passage; a coordinate says it does. "
        "Nothing else can catch this — an exemption removes the file from every other "
        "assertion in this guard"
    )

    # A NON-exempt header with a coordinate is ordinary and must never be flagged.
    assert exemption_has_rotted( "# PARITY-CLAIM: A-2 #10\nnotifications.js:5735" ) is False


def test_an_exempt_file_carrying_a_legacy_coordinate_is_red( exempt_tests ):
    """
    ROT DETECTION over the live corpus. An exemption is a claim about CONTENT,
    and content changes.

    ⚠️ This loop is EMPTY until S4 widens the glob to `.py` — the one exempt file in
    the tree is Python. `test_rot_detection_fires_on_an_exemption_that_has_gone_stale`
    is what actually holds the rule today; this one starts biting when S4 lands.
    """
    rotted = [
        ( path, key, LEGACY_COORD.search( header ).group( 0 ) )
        for path, key, _, header in exempt_tests
        if exemption_has_rotted( header )
    ]

    assert not rotted, (
        "these files declare PARITY-EXEMPT — 'mirrors no legacy passage' — and then "
        "name a legacy coordinate. The exemption is stale: either drop it and let the "
        "citation rules apply, or remove the coordinate:\n  "
        + "\n  ".join( f"{path} exempts {key!r} but cites {coord}" for path, key, coord in rotted )
    )


def test_the_guard_states_a_denominator_not_a_numerator( project_root, claiming_tests, exempt_tests ):
    """
    🔴 A CENSUS THAT MAY ONLY BE NON-EMPTY IS NOT A DENOMINATOR.

    `test_at_least_one_test_claims_a_row` passes on ONE file. A recogniser change
    that silently dropped 27 claims to 1 would clear it, and every rule in this file
    would then be policing a population of one while looking exactly as green as it
    does now. That is the failure S1 could most easily have introduced: switch to
    marker-only and the census goes to ZERO on a corpus that uses prose.

    So the floor RATCHETS. It may only be raised, and raising it is a deliberate edit
    someone reviews.
    """
    total = len( claiming_tests ) + len( exempt_tests )

    assert total >= DECLARED_POPULATION_FLOOR, (
        f"the declared population is {total} ({len( claiming_tests )} claiming, "
        f"{len( exempt_tests )} exempt) against a floor of {DECLARED_POPULATION_FLOOR}. "
        "Files did not stop claiming rows by themselves — the recogniser changed and "
        "this guard is now policing a smaller set than it was built for. If the drop "
        "is genuine (files deleted or merged), LOWER the floor in the same commit that "
        "removes them, so the shrink is reviewed rather than absorbed"
    )


def test_the_old_shape_count_only_shrinks( old_shape_tests ):
    """
    The transitional arm is SELF-RETIRING, on the `GRANDFATHERED` pattern.

    `is_table_row` and `is_inside_quotes` are a proxy fitted to two known negatives.
    A proxy with no denominator is tolerable only while its blast radius is a number
    someone is watching go to zero. This is that number.

    When it reaches zero, delete both filters, `old_shape_claim`, this test and the
    TRANSITIONAL ARM comment together.
    """
    assert len( old_shape_tests ) <= OLD_SHAPE_CEILING, (
        f"{len( old_shape_tests )} files declare a parity row in the old prose shape, "
        f"above the ceiling of {OLD_SHAPE_CEILING}. A NEW file must use "
        "`PARITY-CLAIM: <row>`. The prose shape is being retired, so this count may "
        "only go down:\n  " + "\n  ".join( sorted( old_shape_tests ) )
    )


# ---------------------------------------------------------------------------
# The grandfather list is a ceiling, not a floor
# ---------------------------------------------------------------------------

def test_the_grandfather_list_only_shrinks( claiming_tests ):
    """
    An entry that no longer violates must leave the list.

    Without this, the list is a place debt goes to be forgotten: a file could be
    fixed and still sit here, and the next reader would take the length of the
    list for the size of the debt. Here it can only shrink.
    """
    claimed_paths = { path for path, _, _ in claiming_tests }

    still_clean = sorted(
        path for path, _, header in claiming_tests
        if path in GRANDFATHERED and LEGACY_COORD.search( header )
    )
    assert not still_clean, (
        "these files now name their legacy source and must be removed from "
        "GRANDFATHERED — the list records debt that is already paid:\n  "
        + "\n  ".join( still_clean )
    )

    departed = sorted( GRANDFATHERED - claimed_paths )
    assert not departed, (
        "GRANDFATHERED names files that no longer claim a parity row — deleted, renamed, "
        "or their header changed. Remove them; a stale entry silently exempts a path that "
        "may come back:\n  " + "\n  ".join( departed )
    )


# ---------------------------------------------------------------------------
# The strong form — a citation RESOLVES at HEAD, inside what it names
# ---------------------------------------------------------------------------

def test_the_legacy_parsers_find_what_they_claim( legacy_bodies, legacy_spans ):
    """
    Positive controls for the two instruments, before either is trusted.

    A parser that finds nothing makes every citation "name no method" — red, but
    for the wrong reason. These pin one known method and one known element, and
    the order of their bounds, so a broken parse is reported as a broken parse.
    """
    assert len( legacy_bodies ) > 500, f"only {len( legacy_bodies )} legacy methods parsed"
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    assert start < end, "onTTSPlaybackComplete's body closes before it opens"

    assert "tts-queue-section" in legacy_spans, "the html parse found no #tts-queue-section"
    ( open_line, close_line ), = legacy_spans[ "tts-queue-section" ]
    assert open_line < close_line, "#tts-queue-section closes on the line it opens"
    assert all( open_line < a and b < close_line for a, b in legacy_spans[ "tts-pause-btn" ] ), (
        "#tts-pause-btn is not nested inside #tts-queue-section — the close-tag match is wrong"
    )


def test_a_parity_citation_resolves_inside_what_it_names(
    claiming_tests, legacy_bodies, legacy_spans, manifest_text, project_root
):
    """
    Build plan §6 item 19, STRONG form. See the module docstring for the rule.
    """
    note_dir = project_root / PHASE2_DIR_REL
    cited    = [ t for t in claiming_tests if LEGACY_COORD.search( t[ 2 ] ) ]
    assert cited, "no parity test cites a legacy coordinate — this assertion would loop over nothing"

    offenders = [
        ( path, key, cite, reason )
        for path, key, header in cited
        for cite, reason in unresolved_citations(
            header, legacy_bodies, legacy_spans, row_notes( manifest_text, key, note_dir ) )
    ]

    # 🔴 REPORT THE DEFECT'S CLASS, AND POINT AT THE ARTIFACT THAT HOLDS IT.
    # unresolved_citations already computes WHICH kind of failure each one is; this
    # used to flatten all of them under one "your citations do not resolve" banner
    # with the TEST path leading every line. Measured 2026-09-19 (Maya 🌻): of six
    # offenders, five were not test-side fixable at all — the citation was right and
    # the row's io/phase2 note simply did not name the method. An author sent to edit
    # the test finds nothing wrong with it, and then discounts the next red too.
    # A failure message that names the wrong artifact is a wrong MECHANISM, not a
    # wrong number: a wrong number gets re-derived, a wrong mechanism sends someone
    # into innocent code.
    assert not offenders, report_by_class( offenders )


# The checker must be able to say no. These feed it citations built to fail
# against the REAL files at HEAD, one per reason and one per file type.

# The REPORTER must be able to tell the two classes apart, and must send the reader
# to the artifact that actually holds each defect. Maya 🌻 found this code unguarded
# on 2026-09-19: it lived inside an assertion message, which only renders on failure,
# so the suite was green whether the routing was right or wrong.

CITE_OFFENDER = ( "src/tests/e2e_ui/test_a.py", "A-2 #9", "notifications.js:5-6",
                  "names no legacy method on its line" )
NOTE_OFFENDER = ( "src/tests/e2e_ui/test_b.py", "A-2 #10", "notifications.js:100-200",
                  f"loadJobHistory {NOTE_REASON}" )


def test_the_report_sends_a_citation_defect_to_the_test():
    report = report_by_class( [ CITE_OFFENDER ] )

    assert "CITATION defect" in report
    assert "FIX THE TEST'S HEADER" in report
    assert CITE_OFFENDER[ 0 ] in report
    assert "NOTE defect" not in report, "a citation defect must not be reported as a note defect"


def test_the_report_sends_a_note_defect_to_the_note_and_not_the_test():
    report = report_by_class( [ NOTE_OFFENDER ] )

    assert "NOTE defect" in report
    assert "DO NOT EDIT THE TEST" in report
    assert PHASE2_DIR_REL in report, "a note defect must name the directory that holds the note"
    assert "loadJobHistory" in report, "it must name the method the note is missing"
    assert "CITATION defect" not in report, "a note defect must not be reported as a citation defect"


def test_the_report_separates_the_two_classes_and_drops_neither():
    report = report_by_class( [ CITE_OFFENDER, NOTE_OFFENDER ] )

    assert "1 CITATION defect(s)" in report, "the counts must stay separable"
    assert "1 NOTE defect(s)" in report
    # Every offender appears, so a mixed batch cannot silently lose one class.
    assert CITE_OFFENDER[ 0 ] in report and NOTE_OFFENDER[ 0 ] in report


def test_the_report_omits_a_class_that_has_no_offenders():
    # The control for the two tests above: they would also pass if the reporter
    # always emitted both headings. It does not.
    assert "NOTE defect" not in report_by_class( [ CITE_OFFENDER ] )
    assert "CITATION defect" not in report_by_class( [ NOTE_OFFENDER ] )


def test_an_out_of_range_js_citation_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    header = f"// `onTTSPlaybackComplete` (notifications.js:{end}-{end + 5})"
    problems = unresolved_citations( header, legacy_bodies, legacy_spans, [] )
    assert [ reason.split( " (" )[ 0 ] for _, reason in problems ] == [ "not inside the method it names" ]


def test_an_out_of_range_html_citation_is_red( legacy_bodies, legacy_spans ):
    ( open_line, close_line ), = legacy_spans[ "tts-pause-btn" ]
    header = f"// `#tts-pause-btn` (notifications.html:{open_line}-{close_line + 1})"
    problems = unresolved_citations( header, legacy_bodies, legacy_spans, [] )
    assert [ reason.split( " (" )[ 0 ] for _, reason in problems ] == [ "not inside the element id it names" ]


def test_a_citation_past_the_end_of_the_file_is_red( legacy_bodies, legacy_spans ):
    header = "// `onTTSPlaybackComplete` (notifications.js:999999-1000001)"
    assert unresolved_citations( header, legacy_bodies, legacy_spans, [] ), "a line past EOF resolved"


def test_a_citation_that_names_nothing_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    problems = unresolved_citations(
        f"// the playback-complete path (notifications.js:{start}-{end})\n"
        "// the header of the queue (notifications.html:434)",
        legacy_bodies, legacy_spans, [] )
    assert [ reason for _, reason in problems ] == [
        "names no legacy method on its line", "names no legacy element id on its line" ]


def test_a_backwards_range_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    header = f"// `onTTSPlaybackComplete` (notifications.js:{end}-{start})"
    assert [ r for _, r in unresolved_citations( header, legacy_bodies, legacy_spans, [] ) ] == [ "range runs backwards" ]


def test_a_name_missing_from_the_rows_note_is_red( legacy_bodies, legacy_spans ):
    ( start, end ), = legacy_bodies[ "onTTSPlaybackComplete" ]
    header = f"// `onTTSPlaybackComplete` (notifications.js:{start}-{end})"
    assert not unresolved_citations( header, legacy_bodies, legacy_spans, [ "names onTTSPlaybackComplete" ] )
    assert [ r for _, r in unresolved_citations( header, legacy_bodies, legacy_spans, [ "names nothing useful" ] ) ] == [
        "onTTSPlaybackComplete is not named in the row's note" ]


def test_the_manifest_row_notes_are_found( manifest_text, project_root ):
    """A-2 #2d names two notes, A-0 names none, and a key the manifest lacks names none."""
    note_dir = project_root / PHASE2_DIR_REL
    assert len( row_notes( manifest_text, "A-2 #2d", note_dir ) ) == 2
    assert row_notes( manifest_text, "A-0", note_dir ) == []
    assert row_notes( manifest_text, "Z-9", note_dir ) == []
