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
CLAIMS_A_ROW = re.compile( r"parity\s+(" + ROW_KEY + r")", re.IGNORECASE )

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
    found = []

    for path in sorted( project_root.glob( "src/tests/**/*.test.ts" ) ):
        header = "\n".join( path.read_text( encoding="utf-8" ).splitlines()[ :HEADER_LINES ] )
        match  = CLAIMS_A_ROW.search( header )
        if match: found.append( ( str( path.relative_to( project_root ) ), match.group( 1 ), header ) )

    return found


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
