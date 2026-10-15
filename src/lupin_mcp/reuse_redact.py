"""
The need redactor: blank what must not leave the machine in a need before Jev sees it.

Plan: src/rnd/v0.2.2/2026.09.30-wiki-and-jev-for-code-reuse-review/2026.10.14-reuse-lookup-candidate-stage-plan.md,
section 6 (the redaction rulings). Standard library only, because the cosa-voice process runs in a light venv.

The five kinds are an email, a URL, an IP address, an absolute path and a credential-shaped token. A path that
is a known lupin route is kept. A kept route is still screened: a segment that holds one of the other kinds
makes the whole path redactable.
"""
import bisect
import ipaddress
import re

PLACEHOLDERS = { "email": "[email]", "url": "[url]", "ip": "[ip]", "path": "[path]", "secret": "[secret]" }
ORDER        = ( "url", "path", "email", "secret", "ip" )                    # an earlier kind wins an overlap
TRAILING     = ".,;:!?)]}>'\"`"                                              # sentence punctuation that is not part of a token

WWW_RE      = re.compile( r"\bwww\.\S+" )
EMAIL_DOMAIN = re.compile( r"[\w-]+(?:\.[\w-]+)+" )                          # what follows the @; the local part is read leftwards from it
EMAIL_LOCAL  = "_.+-"                                                       # besides letters and digits, what a local part may hold
IPV4_RE     = re.compile( r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\w)(?!\.\d)" )
IPV6_RE     = re.compile( r"(?<![\w:.])[0-9A-Fa-f:]{2,}(?![\w:])" )
POSIX_RE    = re.compile( r"(?<![\w/.\-])/(?=[^\s/])[^\s/]+(?:/[^\s/]+)+" )
HOME_RE     = re.compile( r"(?<![\w/.\-])(?:~(?:[A-Za-z_][\w.-]*)?|\$\{?HOME\}?)/\S*" )   # ~/x and ~user/x, never ~5/10
WINDOWS_RE  = re.compile( r"(?<!\w)[A-Za-z]:[\\/]\S+|\\\\[\w.$-]+\\[\w.$-]+\S*" )
PREFIX_RE   = re.compile( r"\bsk-[A-Za-z0-9_-]{8,}|\bAKIA[0-9A-Z]{16}\b|\bgh[pousr]_[A-Za-z0-9]{20,}|\bxox[abprs]-[A-Za-z0-9-]{10,}|\beyJ[A-Za-z0-9_-]{10,}" )
GENERIC_RE  = re.compile( r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])" )
WORD_SEG_RE = re.compile( r"[a-z]*(?:[A-Z]+(?=[A-Z][a-z])|[A-Z][a-z]+)*\d*\Z" )   # lowercase run, then capitalised words or an acronym that a capitalised word follows, then digits: an acronym can end at one place only, so it is linear
ROUTE_LINE  = re.compile( r"^[A-Z]+\s+(/\S*)\s+->" )


def _trim( text, start, end ):
    """
    Cut sentence punctuation off the end of a span.

    Requires:
        - 0 <= start <= end <= len( text )

    Ensures:
        - returns the new end, never below start
    """
    while end > start and text[ end - 1 ] in TRAILING: end -= 1
    return end


def _urls( text ):
    """
    Find URLs by starting at each `://` and each `www.`, so the cost is linear in the text.

    Ensures:
        - a URL is a scheme (a letter, then letters, digits, `+`, `.` and `-`, starting at a word boundary), `://`, then one or more non-space characters
        - a `www.` that starts at a word boundary and is followed by one or more non-space characters is a URL
        - the scheme is read leftwards from `://`, so no start position is retried
        - returns ( start, end ) pairs in text order, none overlapping, trailing punctuation left out
    """
    found, at = [], text.find( "://" )
    while at != -1:
        lo = at
        while lo > 0 and ( ( text[ lo - 1 ].isascii() and text[ lo - 1 ].isalnum() ) or text[ lo - 1 ] in "+.-" ): lo -= 1
        start = next( ( i for i in range( lo, at ) if text[ i ].isascii() and text[ i ].isalpha() and ( i == 0 or not ( text[ i - 1 ].isalnum() or text[ i - 1 ] == "_" ) ) ), None )
        nxt = at + 3
        if start is not None:
            end = at + 3
            while end < len( text ) and not text[ end ].isspace(): end += 1
            if end > at + 3: found.append( ( start, end ) ); nxt = end              # the match holds every later `://` up to the space, so the scan resumes after it
        at = text.find( "://", nxt )
    for m in WWW_RE.finditer( text ): found.append( ( m.start(), m.end() ) )
    out, last = [], 0
    for s, e in sorted( found ):
        if s < last: continue
        out.append( ( s, _trim( text, s, e ) ) ); last = e
    return out


def _emails( text ):
    """
    Find email addresses by starting at each `@`, so the cost is linear in the text.

    Ensures:
        - an address is a run of one or more of letters, digits, `_`, `.`, `+` and `-`, then `@`, then dotted domain labels
        - the local part is read leftwards from the `@` and the domain rightwards, so no start position is retried
        - returns ( start, end ) pairs in text order, none overlapping
    """
    out, floor, at = [], 0, text.find( "@" )
    while at != -1:
        start = at
        while start > floor and ( text[ start - 1 ].isalnum() or text[ start - 1 ] in EMAIL_LOCAL ): start -= 1
        dom = EMAIL_DOMAIN.match( text, at + 1 )
        if start < at and dom is not None: out.append( ( start, dom.end() ) ); floor = dom.end()      # the next local part starts after this address, as a left-to-right scan would
        at = text.find( "@", at + 1 )
    return out


def _ips( text ):
    """
    Find IP addresses.

    Ensures:
        - an IPv4 candidate counts only when the standard library parses it
        - an IPv6 candidate counts only when it parses and holds `::` or exactly eight groups, so `10:30:45:20` and `a:b:c:d` are not addresses
        - returns ( start, end ) pairs
    """
    out = []
    for m in IPV4_RE.finditer( text ):
        try: ipaddress.IPv4Address( m.group( 0 ) )
        except ValueError: continue
        out.append( ( m.start(), m.end() ) )
    for m in IPV6_RE.finditer( text ):
        tok = m.group( 0 )
        if ":" not in tok or not re.search( r"[0-9A-Fa-f]", tok ) or not ( "::" in tok or tok.count( ":" ) == 7 ): continue
        try: ipaddress.IPv6Address( tok )
        except ValueError: continue
        out.append( ( m.start(), m.end() ) )
    return out


def _is_word_shaped( token ):
    """
    Is a run made only of words and digits, so it is an identifier and not a secret?

    Requires:
        - token is a string

    Ensures:
        - splits on `_` and `-`; each segment is a lowercase run, then capitalised words, then digits, or digits alone
        - an empty segment is not word-shaped
    """
    return all( s != "" and WORD_SEG_RE.match( s ) is not None for s in re.split( r"[_-]", token ) )


def _secrets( text ):
    """
    Find credential-shaped tokens.

    Ensures:
        - the known prefixes always match
        - the generic rule matches a run of 32 or more of letters, digits, `_` and `-` that holds a digit and a letter and is not word-shaped
        - returns ( start, end ) pairs
    """
    out = [ ( m.start(), m.end() ) for m in PREFIX_RE.finditer( text ) ]
    for m in GENERIC_RE.finditer( text ):
        tok = m.group( 0 )
        if re.search( r"\d", tok ) and re.search( r"[A-Za-z]", tok ) and not _is_word_shaped( tok ): out.append( ( m.start(), m.end() ) )
    return out


def _paths( text ):
    """
    Find absolute-path candidates: POSIX, home and Windows or UNC.

    Ensures:
        - a POSIX path starts with `/` that no word character, dot, slash or hyphen precedes, and holds at least two segments
        - trailing punctuation is left out, and a POSIX candidate that shrinks below two segments is dropped
        - no list of roots is consulted
        - returns ( start, end ) pairs
    """
    out = []
    for m in POSIX_RE.finditer( text ):
        end = _trim( text, m.start(), m.end() )
        if len( [ s for s in text[ m.start():end ].split( "/" ) if s ] ) >= 2: out.append( ( m.start(), end ) )
    for rx in ( HOME_RE, WINDOWS_RE ):
        out.extend( ( m.start(), _trim( text, m.start(), m.end() ) ) for m in rx.finditer( text ) )
    return out


def routes_from_text( text ):
    """
    Read the known route paths from the text of an index `routes.md`.

    Requires:
        - text is a string of lines shaped "METHOD /full/path -> symbol  (file)"

    Ensures:
        - returns a sorted tuple of the distinct paths
        - a line of any other shape is skipped
    """
    found = set()
    for line in text.splitlines():
        m = ROUTE_LINE.match( line )
        if m: found.add( m.group( 1 ) )
    return tuple( sorted( found ) )


def _is_known_route( token, routes ):
    """
    Is a POSIX path token a known lupin route, or a prefix of one ending at a segment?

    Requires:
        - token starts with `/`

    Ensures:
        - a token that holds an email, URL, IP address or credential is never a route, whatever route it matches
        - a `{parameter}` segment of a route matches exactly one segment of the token
        - a query string or fragment is cut off before the segments are compared; redact_need never calls this for a token that has one
    """
    if any( find( token ) for find in ( _urls, _emails, _ips, _secrets ) ): return False
    parts = [ s for s in re.split( r"[?#]", token )[ 0 ].split( "/" ) if s ]
    for route in routes:
        rsegs = [ s for s in route.split( "/" ) if s ]
        if len( parts ) <= len( rsegs ) and all( r == t or ( r.startswith( "{" ) and r.endswith( "}" ) ) for r, t in zip( rsegs, parts ) ): return True
    return False


def redact_need( text, known_routes=() ):
    """
    Blank every email, URL, IP address, absolute path and credential-shaped token in a need.

    Requires:
        - text is a string, possibly empty
        - known_routes is a collection of route paths, possibly empty; `{parameter}` segments are allowed

    Ensures:
        - returns ( redacted, ranking_text, hits )
        - redacted holds `[email]`, `[url]`, `[ip]`, `[path]` and `[secret]` in place of each matched span, and is otherwise the text, byte for byte
        - ranking_text is the text with each matched span replaced by one space, so no placeholder word reaches a ranker
        - hits is a list of { kind, count } sorted by kind, and is empty when nothing matched
        - a POSIX path that is a known route is kept, and no other absolute path is; a route that carries a query or fragment is not kept
        - the function is idempotent: redacting `redacted` again returns it unchanged
        - a span of an earlier kind in the finder order wins an overlap, so a path that holds an email is one `[path]`
        - never raises on any string
    """
    cand = []
    finders = { "url": _urls, "path": _paths, "email": _emails, "secret": _secrets, "ip": _ips }
    for rank, kind in enumerate( ORDER ):
        for s, e in finders[ kind ]( text ):
            if kind == "path" and text[ s ] == "/" and re.search( r"[?#]", text[ s:e ] ) is None and _is_known_route( text[ s:e ], known_routes ): continue     # a query or fragment is data, so the whole token goes
            cand.append( ( rank, s, e, kind ) )
    taken, starts = [], []                                                    # taken stays sorted by start and its spans never overlap, so only the two neighbours can
    for rank, s, e, kind in sorted( cand ):
        at = bisect.bisect_left( starts, s )
        if at > 0 and taken[ at - 1 ][ 1 ] > s: continue
        if at < len( taken ) and taken[ at ][ 0 ] < e: continue
        starts.insert( at, s ); taken.insert( at, ( s, e, kind ) )
    out, rank_out, at, counts = [], [], 0, {}
    for s, e, kind in taken:
        out.append( text[ at:s ] + PLACEHOLDERS[ kind ] )
        rank_out.append( text[ at:s ] + " " )
        counts[ kind ] = counts.get( kind, 0 ) + 1
        at = e
    out.append( text[ at: ] ); rank_out.append( text[ at: ] )
    return "".join( out ), "".join( rank_out ), [ { "kind": k, "count": counts[ k ] } for k in sorted( counts ) ]
