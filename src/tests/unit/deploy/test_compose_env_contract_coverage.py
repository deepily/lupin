"""
Compose-vs-contract coverage — row a5255712.

THE DEFECT THIS EXISTS TO CATCH
-------------------------------
`src/conf/env-contract.tsv` calls itself, in its own header, "the ONE in-repo
authority for Lupin's environment variables." Measured 2026-07-26 it held FOUR of
the FOURTEEN variables the compose files interpolate — a nine-var hole once `HOME`
is set aside as EXEMPT. All nine were added 2026-07-26 and this comparator now holds
the line at zero.

Of those nine, `cloud-gpu.env` on the VM supplies SEVEN: `CLOUD_SQL_CONNECTION_NAME`,
`DB_PASSWORD`, `DB_USER`, `DB_NAME`, `LUPIN_IMAGE`, `LUPIN_MODEL_SERVER_TAG`,
`LUPIN_MODEL_SERVER_URL`. It does NOT supply the other two: `CLAUDE_CODE_OAUTH_TOKEN`
is present but COMMENTED OUT at `cloud-gpu.env:31`, so it resolves to empty on the VM
today, and `GH_TOKEN` is interpolated only by the local `docker-compose.yml`.

REQUIRED vs OPTIONAL was not a judgement call in the end — compose declares it:
`${VAR:?msg}` aborts `up` when unset (REQUIRED, 3 vars), `${VAR:-default}` cannot
(OPTIONAL, 6). One var is venue-split: `LUPIN_MODEL_SERVER_URL` is `:?` on the VM but
`:-` locally, and the contract records the VM's regime with that stated in its note.

The preflight's layer-A1 iterates the CONTRACT, so a variable absent from the
contract is a variable the preflight structurally cannot assert. Its failure mode is
the one already recorded on b5b6d252: `docker rm -f` succeeds, then
`docker compose up -d` FAILS TO PARSE because a non-interactive shell never sourced
`~/.bashrc`. The container stays down and nothing warned, because nothing was
watching. That happened to :8000 on 2026-07-26.

WHY A COMPARATOR AND NOT A LONGER LIST
--------------------------------------
The contract was already a hand-maintained list, and a hand-maintained list is what
produced a four-of-fourteen hole in the first place. Adding the ten by hand fixes
today and rots tomorrow, because nothing would notice the fifteenth. The compose
files ALREADY name the authoritative set — every `${VAR}` in them is a variable
docker will demand at up-time — so deriving from them is what makes the check
un-forgettable.

Same shape as the sibling comparators in this directory (R1 service parity, R4
LUPIN_ENV agreement): one fact, two authorities, and something that compares them.

⚠️ This asserts COVERAGE, not correctness. That a var appears in the contract says
nothing about whether its declared shape or surface is right — only that the
preflight can see it at all. A green here is a floor.

Venue: :7999-eligible. Pure file reads; no docker, no VM, no network.
"""
import os
import re

import pytest

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()

COMPOSE_FILES = (
    "docker-compose.yml",
    "docker-compose.cloud-gpu.yml",
)

CONTRACT = os.path.join( PROJECT_ROOT, "src/conf/env-contract.tsv" )

# ── EXEMPT ────────────────────────────────────────────────────────────────
# Interpolated vars that are deliberately NOT the contract's business, each with a
# dated reason. Kept deliberately tiny: every entry here is a hole the comparator
# will not see, so the bar for adding one is that the contract could not sensibly
# assert it — not that setting it up is inconvenient.
EXEMPT = {
    "HOME": "2026-07-26 — shell-provided on every POSIX login; asserting it would "
            "test the operating system, not Lupin's configuration.",
}


def _interpolated_vars( filename ):
    """
    Every ${VAR} docker-compose will interpolate in one file.

    Requires:
        - filename is a compose file relative to the project root

    Ensures:
        - returns a set of variable names, matching both ${VAR} and ${VAR:-default}
        - returns an empty set when the file does not exist (a compose file that has
          been removed is not this test's business)
    """
    path = os.path.join( PROJECT_ROOT, filename )
    if not os.path.exists( path ): return set()
    with open( path, "r" ) as f:
        return set( re.findall( r"\$\{([A-Z_][A-Z0-9_]*)", f.read() ) )


def _contract_names():
    """
    Every variable name declared in env-contract.tsv.

    Ensures:
        - returns a set of the first tab-separated field of each non-comment,
          non-blank row
        - raises AssertionError if the contract is unreadable — an empty set would
          make every assertion below pass vacuously
    """
    assert os.path.exists( CONTRACT ), f"env contract not found at {CONTRACT}"
    names = set()
    with open( CONTRACT, "r" ) as f:
        for line in f:
            if not line.strip() or line.startswith( "#" ): continue
            names.add( line.split( "\t" )[ 0 ].strip() )
    assert names, "env-contract.tsv parsed to ZERO names — the comparator would pass vacuously"
    return names


# ── the coverage assertion ────────────────────────────────────────────────

# The xfail(strict) marker that used to sit here is GONE, and it came off the way it
# was designed to: the 9 missing vars were added to the contract, all four assertions
# XPASSed, and strict=True turned that into a FAILURE rather than letting a stale
# waiver outlive the gap it excused. The marker forced its own removal.
#
# ⚠️ WHAT A GREEN HERE STILL DOES NOT MEAN — measured 2026-07-26, filed as its own row:
# `pfv_parse_manifest "$CONTRACT"` appears exactly ONCE in preflight-vm.sh, at :191,
# inside layer A1 — and A1 `continue`s past every surface=CONTAINER row (:158-159) on
# the stated grounds that "CONTAINER-surface vars are asserted in layer C". Layer C
# never iterates the contract. It hand-codes checks for four of them. So the nine rows
# this test now certifies as COVERED are asserted by nothing at all.
#
# That is precisely the scope line this file's module docstring already draws — "this
# asserts COVERAGE, not correctness ... a green here is a floor" — and it is why the
# floor is worth having anyway: a var absent from the contract cannot be asserted by
# ANY layer, on any box, ever. Closing that reach gap is a prerequisite for the
# follow-on, not a substitute for it.


@pytest.mark.parametrize( "compose_file", COMPOSE_FILES )
def test_every_compose_interpolated_var_is_in_the_contract( compose_file ):
    """
    A var docker will demand at up-time must be one the preflight can assert.

    This is the whole row: a variable absent here is invisible to layer A1, so its
    absence on a box is discovered by a failed `docker compose up -d` rather than by
    a preflight that ran while the container was still healthy.

    ⚠️ SCOPE, measured 2026-07-26 and narrower than this row was first filed with:
    `lupin-vm.sh` invokes compose with `--env-file cloud-gpu.env` (:192, :519), and
    that file supplies 7 of the 9 missing vars on the VM. So on the VM their absence
    from `~/.bashrc` does NOT strand a recreate — the env file is always read. The
    local `docker-compose.yml` has no `--env-file` and resolves from the shell, which
    is why the 2026-07-26 `:8000` incident happened THERE and not on the VM.

    What survives is the reach argument, and it is enough: the preflight iterates the
    contract, so a var absent from the contract cannot be asserted anywhere, on any
    box, by any phase.
    """
    interpolated = _interpolated_vars( compose_file ) - set( EXEMPT )
    missing      = sorted( interpolated - _contract_names() )
    assert not missing, (
        f"{compose_file} interpolates {len( missing )} var(s) absent from "
        f"env-contract.tsv: {missing}. The preflight cannot assert these, so their "
        f"absence on a host surfaces as a compose parse failure AFTER `docker rm -f` "
        f"has already taken the container down."
    )


def test_the_contract_covers_every_compose_file_at_once():
    """The union, so a var moving between compose files cannot slip through the
    per-file parametrization."""
    every = set().union( *( _interpolated_vars( f ) for f in COMPOSE_FILES ) ) - set( EXEMPT )
    missing = sorted( every - _contract_names() )
    assert not missing, f"vars interpolated somewhere in compose but absent from the contract: {missing}"


# ── the exemption list must not rot ───────────────────────────────────────

def test_every_exemption_is_still_interpolated_somewhere():
    """
    An exemption that no longer names a real interpolation is a stale excuse, and a
    one-way allow-list rots into a permanent one. Checked in BOTH directions, the
    way the sibling service-parity comparator checks its divergence map.
    """
    every = set().union( *( _interpolated_vars( f ) for f in COMPOSE_FILES ) )
    dead  = sorted( set( EXEMPT ) - every )
    assert not dead, (
        f"EXEMPT names {dead}, which no compose file interpolates any more. "
        f"Remove the entry rather than leaving a waiver for a var that is gone."
    )


def test_every_exemption_carries_a_dated_reason():
    """A bare name in EXEMPT is a hole nobody has to justify."""
    for name, reason in EXEMPT.items():
        assert re.match( r"^\d{4}-\d{2}-\d{2} — .+", reason ), (
            f"EXEMPT[{name!r}] must start with an ISO date and a reason; got {reason!r}"
        )


# ── instrument controls — this comparator must be able to fail ────────────

def test_the_comparator_DOES_detect_a_missing_var():
    """
    NEGATIVE CONTROL. The assertions above are green only if the contract genuinely
    covers compose; this proves they would go red otherwise, rather than passing
    because the interpolation regex matched nothing.

    Without it, a regex that silently stopped matching would read as full coverage —
    which is the exact failure the sibling comparator hit on 2026-07-26, when a
    hand-picked pattern list certified itself complete at 6 while the truth was 16.
    """
    interpolated = { "LUPIN_BOGUS_VAR_THAT_IS_NOT_IN_THE_CONTRACT" }
    assert sorted( interpolated - _contract_names() ) == [ "LUPIN_BOGUS_VAR_THAT_IS_NOT_IN_THE_CONTRACT" ]


def test_the_interpolation_regex_actually_finds_something():
    """
    The other half of the control: a regex matching NOTHING would make every
    coverage assertion above pass with an empty set. Pins that each compose file
    really does interpolate at least one variable.
    """
    for compose_file in COMPOSE_FILES:
        assert _interpolated_vars( compose_file ), f"{compose_file} parsed to ZERO interpolations"


def test_the_regex_matches_both_plain_and_defaulted_forms( tmp_path ):
    """`${VAR}` and `${VAR:-fallback}` are both interpolations docker will resolve;
    missing the defaulted form would hide exactly the vars someone thought about."""
    probe = tmp_path / "docker-compose.probe.yml"
    probe.write_text( "a: ${PLAIN_ONE}\nb: ${DEFAULTED_ONE:-fallback}\nc: $NOT_BRACED\n" )
    found = set( re.findall( r"\$\{([A-Z_][A-Z0-9_]*)", probe.read_text() ) )
    assert found == { "PLAIN_ONE", "DEFAULTED_ONE" }
