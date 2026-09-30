"""
env-contract.tsv note citations must point at a line that names the variable.

THE SHAPE (row a859646f)
------------------------
`env-contract.tsv` calls itself "the ONE in-repo authority" for Lupin's
environment variables, and its `note` column carries `<compose>.yml:<line>`
citations as evidence for each row's declared surface and requirement. Preflight
A1 and C6 both read this file, and C6 now DERIVES its assertion tier from the
compose file and COMPARES it against these rows — so a note that points at the
wrong line sends the next reader to the wrong evidence for a claim two checks
depend on.

Nothing checked them. Measured 2026-07-27, two of eleven citations were stale:

    GH_TOKEN                 "(:204, :312)"        -> :312 is a volume mount
    LUPIN_MODEL_SERVER_TAG   "cloud-test.yml:143"  -> :143 is a network alias

(That second example names docker-compose.cloud-test.yml, retired 2026-08-26 —
row 0d175dac. Kept verbatim because it is the measurement that motivated this
file; the alias for that basename is gone from the map below, so a citation of it
is now simply unrecognised rather than checked.)

Both are off by the drift of an edited compose file, and both had been sitting in
the authority reading as evidence.

WHAT THIS ASSERTS, EXACTLY
--------------------------
For every citation of an IN-REPO compose file, the cited line must mention the
row's own variable name.

⚠️ It asserts the citation LANDS, not that the note's prose is true. A line that
names the var but is quoted for the wrong reason still passes here.

⚠️ THE PREDICATE MUST BE ABOUT THE CITATION, NOT ABOUT ANY `:digits`. The notes
also contain `:7998`, `:0` and `:1` — ports and GPU indices. A naive colon-digits scan
swallows those and asserts a compose file has a line 7998. So bare `:N` is
accepted ONLY inside a note that has already named a compose file, and only when
N is within that file's length; everything else must carry its own filename.

`cloud-gpu.env:31` is deliberately NOT checked: that file lives on the VM (mode
600), not in the repo. Skipping it is recorded here rather than left silent —
this suite cannot speak to it, and a reader must not read a green as coverage of
that citation.

Venue: :7999-eligible. Pure file reads; no docker, no VM, no network.
"""
import os
import pathlib
import re

import pytest


LUPIN_ROOT = pathlib.Path( os.environ[ "LUPIN_ROOT" ] )
CONTRACT   = LUPIN_ROOT / "src/conf/env-contract.tsv"

# Basenames used in the notes → the repo file they name.
COMPOSE_ALIASES = {
    "cloud-gpu.yml"          : "docker-compose.cloud-gpu.yml",
    "docker-compose.yml"     : "docker-compose.yml",
}

_FILENAMES = "|".join( re.escape( k ) for k in sorted( COMPOSE_ALIASES, key=len, reverse=True ) )

# ONE left-to-right scan, so a bare `:204` can be attributed to whichever file the
# note named most recently — whether or not that mention carried its own line
# number. Two separate scans is what the first version of this file did, and it
# SILENTLY DROPPED both GH_TOKEN citations: the note names `docker-compose.yml`
# with no attached number, so the file-anchor never got set and `:204, :312` were
# never checked. The count assertion below still read 11 and looked healthy.
# ONE left-to-right scan, so an anchor attaches to whichever file the note named
# most recently — whether or not it sits immediately after the filename. Requiring
# adjacency is what the first cut of this rewrite did, and it SILENTLY DROPPED both
# GH_TOKEN citations: that note reads "in the LOCAL docker-compose.yml only «...»",
# and the word "only" was enough to break the attachment. The count assertion read
# 13 and looked healthy. That is the SAME defect the line-number parser had,
# re-derived in a new notation — which is why the instrument check below is an
# assertion against a different counting method, not a number someone eyeballs.
ANCHOR = re.compile(
    r"\b(?P<file>" + _FILENAMES + r")"
    r"|\u00ab(?P<anchor>[^\u00bb]+)\u00bb"
)


def _contract_rows():
    """
    Parse the contract into ( name, note ) pairs.

    Ensures:
        - '#' comments and blank lines are dropped
        - raises rather than returning empty: an empty parse would make every
          assertion below pass vacuously, which is this directory's recurring
          failure mode
    """
    rows = []
    for line in CONTRACT.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith( "#" ):
            continue
        fields = line.split( "\t" )
        if len( fields ) >= 6:
            rows.append( ( fields[ 0 ], fields[ 5 ] ) )
    assert rows, "parsed ZERO contract rows — every citation assertion would pass vacuously"
    return rows


def _citations( name, note ):
    """
    Extract ( var_name, compose_path, anchor_text ) for every in-repo citation.

    Ensures:
        - EVERY «...» group attaches to the LAST file named earlier in the note,
          so one row can cite two lines of the same file without repeating its
          name, and prose may sit between the filename and its anchor
        - off-repo citations (cloud-gpu.env) carry no guillemets and are not returned
    """
    out       = []
    last_file = None
    for m in ANCHOR.finditer( note ):
        if m.group( "file" ):
            last_file = LUPIN_ROOT / COMPOSE_ALIASES[ m.group( "file" ) ]
        elif last_file is not None:
            out.append( ( name, last_file, m.group( "anchor" ) ) )
    return out


ALL_CITATIONS = [ c for name, note in _contract_rows() for c in _citations( name, note ) ]


def test_the_scan_FOUND_citations_to_check():
    """
    The instrument before the reading. A regex that matched nothing would make
    every parametrised case below disappear and the file report green.
    """
    assert len( ALL_CITATIONS ) >= 14, f"only {len(ALL_CITATIONS)} citations found — the scan is not reaching the notes"


def test_a_PORT_is_not_mistaken_for_a_citation():
    """
    The control, and it is exercised: `LUPIN_MODEL_SERVER_URL`'s note carries a
    `:7998` port inside a URL. Under the old line-number format that token had to
    be range-guarded out by hand. An anchor citation is delimited, so a bare
    `:7998` cannot be claimed as one — this asserts that property rather than
    assuming the format bought it.

    Asserted against the note that actually contains it, not against the corpus
    at large — an absence proves nothing if the token was never in range.
    """
    note = next( n for name, n in _contract_rows() if name == "LUPIN_MODEL_SERVER_URL" )
    assert ":7998" in note, "the note this control depends on no longer contains a port — the control is now vacuous"
    assert all( ":7998" not in a for _, _, a in _citations( "LUPIN_MODEL_SERVER_URL", note ) )


@pytest.mark.parametrize(
    "var,path,anchor",
    ALL_CITATIONS,
    ids=[ f"{v}@{p.name}" for v, p, _ in ALL_CITATIONS ],
)
def test_every_citation_anchor_is_still_present_in_the_file( var, path, anchor ):
    """
    A citation is a claim, and the anchor is the claim's own words. It must still
    be a line of the file it names.

    WHY AN ANCHOR AND NOT A LINE NUMBER (measured 2026-09-01, row 21a084d1's
    successor). The notes used to cite `<file>:<line>`. Almost every change to those
    files moved one — measured as net line delta ABOVE the cited line, so a hunk
    entirely below counts as harmless. One commit moved ten citations by +254.

    🔴 SAY WHICH POPULATION, BECAUSE THERE ARE TWO AND THEY GIVE DIFFERENT NUMBERS:

        11 of 12 FILE-TOUCHES     ( file, commit ) pairs — two shas touch both files
         9 of 10 DISTINCT COMMITS by sha

    ⚠️ This paragraph first read "of the twelve commits ... TEN displaced", which was
    wrong twice over and is left named rather than quietly fixed. Twelve is the count
    of file-touches, not of commits. And the ten was computed over the twelve
    line-numbers a regex found, when the contract carried SIXTEEN — the four bare
    continuation citations (`:192`, `:458`, `:302`, `:502`) were outside the
    measurement, so the figure was a LOWER BOUND presented as a result. Re-measured
    over all sixteen it is eleven, which makes the case for anchors stronger, not
    weaker — the correction was worth making anyway, because a number nobody can
    reproduce is not evidence.

    An anchor cannot drift: it either matches or it is gone, and "gone" is exactly the
    thing worth being told.

    ⚠️ TWO ANCHORS MATCH TWICE, BY DESIGN, AND THAT IS NOT AN AMBIGUITY TO FIX.
    `JWT_SECRET_KEY` and `GH_TOKEN` are set identically in two services of
    docker-compose.yml, and the contract cites both occurrences. Under the old
    format that was two line numbers (`:257, :458` and `:302, :502`); under this
    one it is a single anchor that lands twice. So this asserts the anchor is
    PRESENT, never that it is unique — a uniqueness assertion would fail on a
    correct contract. Ten of the twelve remaining anchors do match exactly once.

    ⚠️ It asserts the citation LANDS, not that the note's prose is true. A line
    that carries the anchor but is quoted for the wrong reason still passes here.
    """
    assert var in anchor, (
        f"{var}'s anchor does not mention {var}, so it cannot be evidence for this row.\n"
        f"  anchor: {anchor!r}"
    )
    stripped = [ l.strip() for l in path.read_text().splitlines() ]
    assert anchor in stripped, (
        f"{var}'s note anchors on a line of {path.name} that is no longer there.\n"
        f"  anchor: {anchor!r}\n"
        f"  Re-read the file and update the anchor in src/conf/env-contract.tsv."
    )


def test_the_scan_CLAIMS_every_anchor_written_into_the_contract():
    """
    The instrument check, as an assertion rather than a number to eyeball.

    A «...» group in a note is somebody writing a citation. If the scanner claims
    fewer of them than the file contains, a citation is going unchecked and the
    suite still reports green — which is how the old line-number parser lost both
    GH_TOKEN citations, and how the first cut of THIS parser lost them again by
    requiring the anchor to sit next to the filename.

    Counting the raw groups is deliberately a DIFFERENT method from the one under
    test: a scan that agrees with itself proves nothing.
    """
    raw = sum( note.count( "«" ) for _, note in _contract_rows() )
    assert raw == len( ALL_CITATIONS ), (
        f"the contract carries {raw} anchors but the scan claimed {len(ALL_CITATIONS)}.\n"
        f"  An anchor the scan cannot see is a citation nothing checks."
    )
