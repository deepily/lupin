"""
Interpreter-startup hook: make every `.pyc` written here checked-hash.

`site` imports `sitecustomize` automatically at startup, from anywhere on
`sys.path`. This repo puts `src/` on the path for every interpreter it runs
(CLAUDE.md § PATH MANAGEMENT), so landing the shim here reaches the test tier,
ad-hoc `python -c` probes, AND the MCP server process — the last of which is
where row f313fc2d's 77 timestamp pycs were found, and which no conftest or
pre-run hook can reach, because nothing in the test tier imports `src/lupin_mcp`.

Kept to a shim on purpose: the logic lives in `cosa.utils.checked_hash_pyc`,
where it can be imported and tested directly. A sitecustomize is invisible to a
test suite, so anything living only here is code nobody can cover.

⚠️ TWO INTERPRETER FLAGS BYPASS THIS ENTIRELY, and that is CPython's design, not a
gap to be closed here. Measured 2026-08-31, and they miss for DIFFERENT reasons:
`-S` skips `site` altogether, so this file is never imported and `is_installed()`
reports False; `-E` ignores `PYTHONPATH`, so on a repo that puts `src/` on the path
that way, the module is not importable at all. Either flag therefore writes
timestamp pycs. Nothing here can prevent that — which is exactly why row f313fc2d
pairs this preventer with the verifier as a DETECTOR: the verifier still reports
those pycs, whatever wrote them. Raised in review by Rachel 🕊️.

⚠️ FAILS OPEN, DELIBERATELY. A broken startup hook breaks every interpreter in
the repo at once, including the ones you would use to fix it. A hardening pass is
never worth that, so an unexpected failure here leaves the interpreter on
CPython's default behaviour rather than refusing to start. Row f313fc2d pairs
this preventer with the verifier as a DETECTOR precisely because a control that
can fail quietly needs something else that notices.
"""
try:
    from cosa.utils.checked_hash_pyc import install

    install()

except BaseException:
    # ⚠️ BaseException, NOT Exception, and the width is deliberate. Measured
    # 2026-08-31: a staged KeyboardInterrupt or SystemExit escaping this shim does
    # not merely skip the patch — CPython reports "Fatal Python error:
    # init_import_site" and the interpreter NEVER STARTS, which is precisely the
    # outcome the docstring above says is never worth a hardening pass. The cost is
    # that a Ctrl-C landing inside this handful of startup lines is swallowed; that
    # window is a few microseconds and the alternative is a dead interpreter.
    # Raised in review by Rachel 🕊️. Both branches are parametrized in the test.
    #
    # PROVEN, NOT ASSERTED: src/tests/unit/test_sitecustomize_fails_open.py stages
    # a `cosa.utils.checked_hash_pyc` that raises on import, starts a real
    # interpreter with this shim, and requires it to reach the caller's code and
    # exit 0 — with a positive control confirming the staged failure actually
    # fires, and a second control confirming a healthy shim really does import
    # and call install(). An earlier version of this file carried a no-cover
    # exclusion here, claiming the case was unreachable from the tier. It is
    # reachable; it just needs a subprocess rather than a monkeypatch. (Spelling
    # that directive out even inside prose would re-exclude this line, which is
    # how a comment silently becomes a coverage hole.)
    pass
