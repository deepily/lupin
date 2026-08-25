"""
Scan the repo — the working tree, any ref, or the whole pushed history — for
credential VALUES that were committed. Not paths, not field names, not
placeholders: actual values.

READ THIS BEFORE YOU TRUST A CLEAN RESULT. A scanner that reports "nothing
found" is indistinguishable from one that cannot see, and there is no way to
tell them apart from its output. This one was written after two earlier passes
missed a credential we already knew about. Its fixture suite
(src/tests/unit/test_secret_scan.py) plants known positives and fails loudly if
any of them stops being found — that suite is not optional decoration, it is
the only reason a number from here means anything. Re-run it after ANY change:
the original miss was introduced by an ordinary-looking refactor of the
matching loop and was invisible in the output.

WHAT AN EARLIER VERSION COULD NOT SEE, each now a fixture:
  · \\b does not fire between "_" and a letter, so \\b(password)\\b never matched
    DB_PASSWORD, db_pwd or api_secret — the commonest .env / ini key shape.
  · A JS/TS declaration (`const apiKey = "..."`) — the key pattern cannot span
    the space after `const`.
  · A value on the FOLLOWING lines: a YAML block scalar (`key: >`), a wrapped
    base64 blob, a PEM block.
  · A credential inside a URL query string, with no key beside it to match.

WHAT IT STILL CANNOT SEE, stated so a clean run is read correctly:
  · a bare token in prose with no credential-ish key beside it;
  · binaries, notebooks, non-UTF8 files, and anything outside the text
    extensions listed below;
  · values that only ever lived in gitignored or uncommitted files;
  · two deliberate precision trades — an all-lowercase value with two or more
    underscores/hyphens reads as an identifier name, and a value that repeats
    its own key reads as wiring. Both were the price of a readable list, and
    both are places a real secret could hide.

SCAN THE REF, NOT THE CHECKOUT. A working-tree copy can be redacted while the
value is still live on the pushed branch — that alone hid the credential this
scanner was built for. Use `ref origin/main` or `history`, not `worktree`, when
the question is what a reader of the public repo can see.

OUTPUT IS MASKED — key, length and a truncated sha256, never the value. A
report that quotes the secret has spread it further.

Usage:
    python3 src/scripts/secret_scan.py worktree
    python3 src/scripts/secret_scan.py ref origin/main
    python3 src/scripts/secret_scan.py history
"""

import hashlib
import re
import sys

# ── the VALUE test, taken from _scope_registry.py @ c32eac21 (unchanged from v1) ──
_PLACEHOLDER_VALUE = re.compile( r"^\s*(?:<[^>]*>|\$\{[^}]*\}|\{\{[^}]*\}\})\s*$" )
_PEM_PRIVATE_KEY   = re.compile(
    r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----" )

# ── D1: `_`/`-` count as separators, so DB_PASSWORD and db_pwd are visible ────────
_FIELD = re.compile(
    r"""(?ix)
    (?<![A-Za-z0-9])
    (
        password | passwd | pwd
      | secret | client_secret | webhook[_-]?secret
      | api[_-]?key | apikey
      | access[_-]?key | secret[_-]?key
      | service[_-]?account[_-]?key | signing[_-]?key
      | encryption[_-]?key | session[_-]?key
      | auth[_-]?token | access[_-]?token | refresh[_-]?token | bearer
      | private[_-]?key | private[_-]?key[_-]?id
      | credentials? | passphrase
    )
    (?![A-Za-z0-9]) """ )

# ── D2: strip a declaration keyword / type annotation before the key ──────────────
_DECL_PREFIX = re.compile(
    r"""(?ix) ^ (?: export \s+ )? (?: public | private | protected | static | final
                                    | const | let | var | val | readonly | my | our ) \s+ """ )
_TYPE_ANNOT  = re.compile( r"""(?ix) ^ (?P<key>[A-Za-z_][\w\-\.\[\]"']*) \s* : \s*
                                      (?: str | string | String | bytes ) \s* = \s* (?P<val> .+ ) $ """ )

_ASSIGN = re.compile(
    r"""(?ix)
    (?P<key>["']?[A-Za-z_][A-Za-z0-9_\-\.\[\]"']{0,60}?)
    \s* (?P<sep> [:=] ) \s*
    (?P<val> .+ ) $ """ )

# ── D4: a credential carried in a URL query string ────────────────────────────────
_URL_SECRET = re.compile(
    r"""(?ix) [?&]
    (?P<key> token | key | api[_-]?key | apikey | secret | password | passwd
           | access[_-]?token | auth | sig | signature | credential )
    = (?P<val> [^&\s"'<>)\]]+ ) """ )

# ── D3: a value that lives on the following lines ─────────────────────────────────
# a key naming something ABOUT a credential is not the credential
_DERIVED_KEY = re.compile(
    r"""(?ix) (?: _ | \b )
    (?: hash | hashed | digest | name | names | id | ids | type | field | column
      | expiry | expires | expiration | ttl | counter | count | len | length
      | prefix | suffix | pattern | regex | label | header | env | var | path | file )
    $ """ )
# cheap substring gate — must stay a SUPERSET of every term _FIELD, _URL_SECRET and the
# PEM matcher can hit, or the scan silently narrows. Widen this before widening those.
_CHEAP_HINTS = ( "pass", "pwd", "secret", "key", "token", "bearer", "cred", "auth", "sig",
                 "begin " )
_BLOCK_INDICATOR = re.compile( r"^[>|][-+]?$" )
_B64ISH          = re.compile( r"^[A-Za-z0-9+/=_\-]{24,}$" )


_LONG_B64_RUN = re.compile( r"[A-Za-z0-9+/=_\-]{24,}" )


def _carries_key_material( v ):
    """
    True when the VALUE is itself a credential payload rather than a container.

    The doc-viewer detector blocks these; this scanner used to drop them as "template"
    or "structure" because they contain braces or brackets (Rachel's F1, measured).

    Requires:
        - v is the stripped value text

    Ensures:
        - True for a JSON blob carrying a credential field, or a list/blob holding a long
          base64 run — a service-account key pasted as a string, key material as lines
        - False for an ordinary structure, template or short list
    """
    if not ( v.startswith( ( "{", "[", '"{', '"[' ) ) or v.startswith( ( "'{", "'[" ) ) ):
        return False
    if "-----BEGIN" in v:
        return True
    if _FIELD.search( v ) and _LONG_B64_RUN.search( v ):
        return True
    # key material split across list entries: ["MIIEvQIBADAN…", …]
    return bool( _LONG_B64_RUN.search( v ) ) and v.count( '"' ) >= 2


def _looks_like_a_reference( value ):
    """A pointer to a secret is not a secret. Paths, env lookups, code."""
    v = value.strip().strip( '",\'' ).strip()
    if not v:                                   return "empty"
    if _PLACEHOLDER_VALUE.match( v ):           return "placeholder"
    low = v.lower()
    if any( t in v for t in ( "os.environ", "os.getenv", "getenv(", "environ[",
                              "config.get", "cm.get", "self.", "process.env",
                              "request.", "response.", "resp.", "headers[", "params[" ) ):
        return "env-or-config lookup"
    if v.startswith( "$" ) or v.startswith( "%" ):          return "shell/ini var ref"
    if "/" in v or v.startswith( "~" ) or v.startswith( "." ):
        if not v.startswith( "//" ):            return "path"
    if low.endswith( ( ".json", ".key", ".pem", ".txt", ".ini", ".yml", ".yaml", ".md",
                       ".pub", ".crt" ) ):
        return "path"
    if low in ( "none", "null", "true", "false", "''", '""', "[]", "{}", "0", "1" ):
        return "literal non-secret"
    # F1 (Rachel, 2026-08-17) — a credential PAYLOAD is not a structure and not a template.
    # A whole service-account key carried as a JSON string, or key material as a list of
    # lines, was read as "template" / "structure" and dropped. Checked BEFORE those arms.
    if _carries_key_material( v ):              return None
    # F5 — a bare number is a size or a count, not a secret (CREDENTIAL_SNIFF_BYTES =
    # 8192 was being reported). UNQUOTED only: a quoted digit string is how an account id
    # or a numeric key is written, and that stays a candidate. The trade this accepts is
    # a bare numeric secret — a PIN, an unquoted numeric id.
    if '"' not in value and "'" not in value \
       and re.match( r"^[+-]?\d[\d_]*(?:\.\d+)?$", v ):      return "numeric literal"
    if v.startswith( ( "{", "[" ) ) and not v.startswith( '{"' ):  return "structure"
    if re.match( r"^[A-Za-z_][A-Za-z0-9_]*$", v ) and "_" in v and v.isupper():
        return "constant name"
    if re.match( r"^[A-Za-z_][A-Za-z0-9_]*\s*\(", v ):       return "function call"
    # ── shapes the first real triage pass proved dominate the candidate list ──
    if re.match( r"^[A-Za-z_][\w\.]*\s*\(", v ):             return "dotted call"      # cu.get_api_key(…)
    # var.x · this.token · data.google_secret_manager_secret_version.db_password[0].secret_data
    if re.match( r"^[A-Za-z_][\w\[\]]*(?:\.[\w\[\]]+)+$", v ):  return "attribute ref"
    if any( t in v for t in ( "?.", "??", "||", "&&", "=>", " if ", " else " ) ):
        return "code expression"
    ident = v.strip( "`" )
    if re.match( r"^[a-z][a-z_\-]*$", ident ) and len( re.findall( r"[_\-]", ident ) ) >= 2:
        return "identifier name"        # lupin_queue_session_id, lupin-notification-api-key
    # a subscript into something else is a lookup, not a value: creds[ "password" ]
    if re.match( r"^[A-Za-z_][\w\.]*\s*\[", v ):             return "subscript ref"
    # an UNQUOTED run of plain words is a docstring line describing the field, not setting
    # it — "password: User password". Quoted stays a candidate, so a two-word passphrase
    # in quotes survives; an unquoted one is the trade.
    if '"' not in value and "'" not in value \
       and re.match( r"^[A-Za-z][A-Za-z ]+$", v ) and len( v.split() ) >= 2:
        return "field description"
    if re.match( r"^f?['\"].*\{.*\}", v ):                   return "f-string template"
    if "{" in v and "}" in v:                                 return "template"
    if len( v.split() ) > 4:                                  return "prose"
    if v.endswith( ( ":", "—", "-" ) ):                       return "fragment"
    return None                                                # ⇒ candidate REAL value


def _echoes_its_key( key, value ):
    """`self.bearer = bearer` / `api_key: notificationState.apiKey` — a wiring line."""
    norm = lambda s: re.sub( r"[^a-z0-9]", "", s.lower() )
    k    = norm( key.split( "." )[ -1 ] )
    v    = norm( value.strip( "\"'`" ).split( "." )[ -1 ] )
    return bool( k ) and k == v


def _emit( out, origin, lineno, key, value, note="" ):
    clean = value.strip( '"\'' )
    if len( clean ) < 4:
        return
    digest = hashlib.sha256( clean.encode( "utf-8", "replace" ) ).hexdigest()[ :12 ]
    out.append( ( origin, lineno, key.strip() + note, f"len={len(clean)}", f"sha256:{digest}" ) )


def _gather_block( lines, i ):
    """D3 — a block scalar / wrapped value: join the following more-indented lines."""
    base   = len( lines[ i ] ) - len( lines[ i ].lstrip() )
    joined = []
    j      = i + 1
    while j < len( lines ):
        nxt = lines[ j ]
        if not nxt.strip():
            break
        if len( nxt ) - len( nxt.lstrip() ) <= base:
            break
        joined.append( nxt.strip() )
        j += 1
    return "".join( joined ), " ".join( joined ), j


def scan_text( text, origin ):
    """Yield masked findings for one blob of text."""
    out   = []
    lines = text.splitlines()
    i     = 0
    while i < len( lines ):
        line = lines[ i ]
        if len( line ) > 4000:
            i += 1
            continue

        if _PEM_PRIVATE_KEY.search( line ):
            out.append( ( origin, i + 1, "PEM-PRIVATE-KEY-BLOCK", "n/a", "PEM header present" ) )
            i += 1
            continue

        # cheap gate before the expensive patterns — every credential shape this scanner
        # knows carries one of these substrings, and skipping the rest is what keeps a
        # whole-ref scan inside the unit tier's budget. Verified result-identical.
        low = line.lower()
        if not any( t in low for t in _CHEAP_HINTS ):
            i += 1
            continue

        # D4 — a credential in a URL query string, wherever it appears on the line
        for m in ( _URL_SECRET.finditer( line ) if ( "?" in line or "&" in line ) else () ):
            if _looks_like_a_reference( m.group( "val" ) ) is None:
                _emit( out, origin, i + 1, m.group( "key" ), m.group( "val" ), " (in-url)" )

        stripped = line.strip().lstrip( "#-*>" ).strip()
        stripped = _DECL_PREFIX.sub( "", stripped )              # D2
        if not _FIELD.search( stripped ):
            i += 1
            continue

        m = _TYPE_ANNOT.match( stripped ) or _ASSIGN.match( stripped )
        if not m:
            i += 1
            continue
        key, val = m.group( "key" ), m.group( "val" )
        if not _FIELD.search( key ):            # the FIELD must be the key, not the value
            i += 1
            continue
        if _DERIVED_KEY.search( key.strip().strip( '"\'' ) ):   # password_hash, token_type, …
            i += 1
            continue

        val = re.split( r"\s+#", val )[ 0 ].rstrip( ",;" ).strip()

        # D3 — value continues on the following lines
        if _BLOCK_INDICATOR.match( val ) or not val:
            joined, spaced, j = _gather_block( lines, i )
            # the block must still pass the VALUE test — a runbook paragraph is prose,
            # and joining its lines must not disguise that
            if joined and _looks_like_a_reference( spaced ) is None \
               and ( _B64ISH.match( joined ) or len( joined ) >= 24 ):
                _emit( out, origin, i + 1, key, joined, " (multi-line)" )
            i = max( j, i + 1 )
            continue

        if _looks_like_a_reference( val ) is not None or _echoes_its_key( key, val ):
            i += 1
            continue
        _emit( out, origin, i + 1, key, val )
        i += 1
    return out


_TEXT_EXT = ( ".md", ".ini", ".env", ".cfg", ".conf", ".yaml", ".yml", ".json",
              ".py", ".tf", ".sh", ".ts", ".js", ".toml", ".properties", ".xml" )


# This scanner's OWN fixtures plant fake credentials on purpose. They are excluded by
# name — and nothing else is. An earlier version skipped the whole test tree, which meant
# a real credential in a test fixture was invisible to both the gate and the scan
# (Rachel's F3, measured). Tiffany found a live sandbox project id in test fixtures on
# this very afternoon, so "it is only a test file" is not a reason to stop looking.
_SELF_PLANTED = ( "src/tests/unit/test_secret_scan.py",
                  "src/tests/unit/test_secret_scan_payload_shapes.py",
                  "src/tests/unit/fixtures/secret_scan_last_full_scan.json" )


def _is_text_path( p ):
    low = p.lower()
    if any( low.endswith( s ) for s in _SELF_PLANTED ):
        return False
    return low.endswith( _TEXT_EXT ) or low.rsplit( "/", 1 )[ -1 ] in ( ".env", "Dockerfile" )


def _batch_read( specs, cwd=None ):
    """
    Read many blobs in ONE `git cat-file --batch`.

    Requires:
        - specs is a list of rev-parseable object specs, e.g. "origin/main:conf/app.ini"

    Ensures:
        - yields ( spec, text ) in input order, skipping anything git could not resolve
        - one subprocess for the whole list; per-blob subprocesses cost ~9s where this
          costs ~1s on this repo, which is the difference between a check that runs in
          the unit tier and one nobody runs
    """
    import subprocess
    if not specs:
        return
    proc   = subprocess.Popen( [ "git", "cat-file", "--batch" ], cwd=cwd,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE )
    out, _ = proc.communicate( ( "\n".join( specs ) + "\n" ).encode() )
    pos, i = 0, 0
    while pos < len( out ) and i < len( specs ):
        nl = out.find( b"\n", pos )
        if nl < 0:
            break
        header = out[ pos : nl ].decode( "utf-8", "replace" ).split()
        pos    = nl + 1
        if len( header ) != 3:          # "<spec> missing" — git could not resolve it
            i += 1
            continue
        size = int( header[ 2 ] )
        yield specs[ i ], out[ pos : pos + size ].decode( "utf-8", "replace" )
        pos += size + 1
        i   += 1


def scan_ref( ref, cwd=None ):
    """
    Scan every text path in a REF — the published surface, not the checkout.

    Ensures:
        - returns the masked findings list for that ref
        - a redacted working copy cannot hide what the ref still carries
    """
    import subprocess
    names = subprocess.run( [ "git", "ls-tree", "-r", "--name-only", ref ], cwd=cwd,
                            capture_output=True, text=True ).stdout.splitlines()
    paths = [ f for f in names if _is_text_path( f ) ]
    out   = []
    for spec, text in _batch_read( [ f"{ref}:{p}" for p in paths ], cwd=cwd ):
        out += scan_text( text, spec )
    return out


if __name__ == "__main__":
    import os
    import subprocess
    mode     = sys.argv[ 1 ] if len( sys.argv ) > 1 else "worktree"
    findings = []

    if mode == "ref":
        findings = scan_ref( sys.argv[ 2 ] )

    elif mode == "history":
        # every blob reachable from every remote ref
        objs = subprocess.run( [ "git", "rev-list", "--objects", "--remotes" ],
                               capture_output=True, text=True ).stdout.splitlines()
        wanted = {}
        for row in objs:
            parts = row.split( " ", 1 )
            if len( parts ) != 2:
                continue
            sha, path = parts
            if sha in wanted or not _is_text_path( path ):
                continue
            wanted[ sha ] = path
        # one `git cat-file --batch` for all of them; per-blob subprocesses are far slower
        proc = subprocess.Popen( [ "git", "cat-file", "--batch" ],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE )
        out, _ = proc.communicate( ( "\n".join( wanted ) + "\n" ).encode() )
        pos = 0
        while pos < len( out ):
            nl = out.find( b"\n", pos )
            if nl < 0:
                break
            header = out[ pos : nl ].decode( "utf-8", "replace" ).split()
            pos    = nl + 1
            if len( header ) != 3:
                continue
            sha, _kind, size = header[ 0 ], header[ 1 ], int( header[ 2 ] )
            body = out[ pos : pos + size ].decode( "utf-8", "replace" )
            pos += size + 1
            findings += scan_text( body, f"blob {sha[:10]} {wanted.get( sha, '?' )}" )
        print( f"--- {len( wanted )} unique text blobs scanned ---", file=sys.stderr )

    elif mode == "worktree":
        # 🔴 ANCHOR TO THE REPO ROOT (row 0adf242e, 2026-08-25). `git ls-files` is
        # CWD-SCOPED BY DEFAULT — no config required. Measured on this repo:
        #     from repo root : 4826 files
        #     from src/      : 4638 files   -> 188 files never scanned
        # Run from anywhere but the root, this scanner silently covered less than the
        # repository and still reported clean. A secret scanner that fails open is
        # worse than no scanner, because the clean result is believed.
        #
        # `git rev-parse --show-toplevel` is the anchor, and the `open()` below must
        # resolve against it too — ls-files emits repo-root-relative paths, so opening
        # them from another CWD would raise OSError and get swallowed by the except.
        # That would have turned a coverage hole into a SILENT one.
        root = subprocess.run(
            [ "git", "rev-parse", "--show-toplevel" ], capture_output=True, text=True
        ).stdout.strip()
        if not root:
            print( "secret_scan: not inside a git repository — refusing to report clean", file=sys.stderr )
            sys.exit( 2 )
        files = subprocess.run(
            [ "git", "-C", root, "ls-files" ], capture_output=True, text=True
        ).stdout.split()
        skip  = ( ".venv/", "node_modules/", "__pycache__/", ".claude/worktrees/" )
        for f in files:
            if any( s in f for s in skip ):
                continue
            try:
                with open( os.path.join( root, f ), "r", encoding="utf-8", errors="replace" ) as fh:
                    findings += scan_text( fh.read(), f )
            except ( OSError, IsADirectoryError ):
                continue
    for origin, lineno, key, length, digest in findings:
        print( f"{origin}:{lineno}\t{key}\t{length}\t{digest}" )
    print( f"\n--- {len( findings )} candidate value(s) ---", file=sys.stderr )
