"""
THE CONTROL FOR ROW dde8b87a: a newly created worktree must come up able to run a WHOLE
tier, not merely able to start an interpreter — and this file reddens if it stops.

THE DEFECT IT GUARDS. The spawn path provisioned a `.venv` and nothing else, so a
spawned seat passed `INTERPRETER OK` and still could not run a single `.test.ts`:
`node_modules` is gitignored, so `git worktree add` cannot produce one, and every
TypeScript run in a fresh tree died with `Cannot find package 'tsx'`. That failure names
a PACKAGE rather than a tree, which is why it reads as a broken test and why this member
went unfound while the two that fail loudly were already documented.

⚠️ IT DRIVES THE REAL THING AT THE LAYER THE INCIDENT ENTERED AT. Real `WorktreeContext`,
real `git worktree add` into a real temporary repo, real `link-worktree-artifacts.sh`.
A helper-level receipt — calling `provision_worktree_artifacts` with a path handed to it
— would establish that the helper works and say nothing about whether the creation path
ever REACHES it. The incident was a spawn, not a helper call.

⚠️ IT CARRIES ITS OWN NEGATIVE CONTROL, and that is the load-bearing part. A test that
only checks the success case cannot tell "provisioning works" from "the assertion cannot
fail". `test_the_control_can_actually_see_an_unprovisioned_tree` builds the same tree
with the provisioning script removed and asserts the artifacts are ABSENT. If that test
ever goes green alongside the others, the instrument is broken, not the code.
"""

import os
import shutil
import subprocess
import tempfile

import pytest

from cosa.agents.shared.worktree_context import WorktreeContext
from cosa.utils.worktree_artifacts import provision_worktree_artifacts


# The real scripts, taken from the tree this test file lives in — never from LUPIN_ROOT,
# which names whatever repo the runner's shell happened to be standing in.
_REPO_ROOT  = os.path.abspath( os.path.join( os.path.dirname( __file__ ), "..", "..", ".." ) )
_SCRIPT_DIR = os.path.join( _REPO_ROOT, "src", "scripts" )


def _sibling_repo_root( name ):
    """
    The sibling repo `name` beside the MAIN lupin checkout, or None when it is not there.

    Resolved through git's common dir, not `<this tree>/..`: a seat's tree lives under
    `.claude/worktrees/`, where `..` is not the projects directory. READ-ONLY by contract —
    this module only copies script files out of it.

    Requires:
        - _REPO_ROOT is inside a git work tree

    Ensures:
        - returns an absolute path to an existing directory, or None
        - never writes anywhere
    """
    result = subprocess.run( [ "git", "-C", _REPO_ROOT, "rev-parse", "--path-format=absolute", "--git-common-dir" ],
                             capture_output=True, text=True )
    if result.returncode != 0: return None
    main_root = os.path.dirname( result.stdout.strip() )
    sibling   = os.path.join( os.path.dirname( main_root ), name )
    return sibling if os.path.isdir( os.path.join( sibling, "src", "scripts" ) ) else None

# 🔴 THE EXPECTED SET IS A LITERAL, PINNED HERE, ON PURPOSE. Deriving it from the
# script's own BORROW list would make both sides of every comparison below move
# together, so the assertions could never disagree with the code — a tautology wearing
# an assertion's clothes. These names are hand-written; if the script drops one, this
# file reddens.
_MUST_BE_BORROWED = ( "node_modules", "src/scripts/cloud-run.env",
                      "src/terraform/envs/test/.terraform/providers" )

# The parent of the provider cache holds tfstate and modules that a worktree run WRITES. It is
# hand-pinned as never-borrowed in TestTheBorrowListNeverCarriesASecret and checked as a real
# directory in the worktree below.
_TF_PROVIDERS = "src/terraform/envs/test/.terraform/providers"
_TF_PARENT    = "src/terraform/envs/test/.terraform"

# Row 5aedbad2. lupin-mobile carries its OWN copies of the three seat-worktree scripts, adapted
# (a Flutter SDK instead of a venv, a Gradle wrapper instead of node_modules), and they had
# no guard at all. One table per repo: where its scripts live, what its borrow array is called,
# what it must borrow (hand-pinned, never read from the script), what it must never borrow,
# and the untracked stand-ins a main checkout needs for the real scripts to have something to lend.
#
# `lend` is a member the artifacts script borrows; `sdk` is the tier's toolchain, made by the
# venv script. "stand_ins" are paths created AFTER the commit, so they are untracked as in life.
_MOBILE_ROOT = _sibling_repo_root( "lupin-mobile" )

_REPOS = {
    "lupin"        : {
        "script_dir"      : _SCRIPT_DIR,
        "borrow_array"    : "BORROW",
        "must_be_borrowed": _MUST_BE_BORROWED,
        "lend"            : "node_modules",             # a member whose absence at source is "nothing to lend"
        "owned_file"      : "src/scripts/cloud-run.env", # a member a seat may own for itself
        "sdk"             : ".venv/bin/python",
        "never"           : (
            ( "src/conf/keys",          "under" ),
            ( ".env",                   "exact" ),
            ( "src/lupin_app/static/dist", "under" ),
            ( "src/terraform/envs/test/.terraform", "exact" ),   # holds tfstate + modules a worktree run writes
            ( "src/scripts/auth_migration/migration_results.json", "exact" ),
        ),
    },
    "lupin-mobile" : {
        "script_dir"      : None if _MOBILE_ROOT is None else os.path.join( _MOBILE_ROOT, "src", "scripts" ),
        "borrow_array"    : "LINK_LIST",
        "must_be_borrowed": ( "android/gradlew", "android/gradle/wrapper/gradle-wrapper.jar" ),
        "lend"            : "android/gradlew",
        "owned_file"      : "android/gradlew",
        "sdk"             : "flutter/bin/flutter",
        # Hand-written from the script's own deny rules: a secret, the WRITTEN `.dart_tool/`
        # (a symlink would let `flutter test` rewrite the shared checkout), a build output,
        # and the tracked lock a copy would overwrite with someone else's working copy.
        "never"           : (
            ( "android/app/google-services.json", "exact" ),
            ( "CLAUDE.local.md",                  "exact" ),
            ( ".dart_tool",                       "under" ),
            ( "build",                            "under" ),
            ( "pubspec.lock",                     "exact" ),
        ),
    },
}


@pytest.fixture( params=list( _REPOS ) )
def repo( request ):
    """
    One repo's spec. The mobile arm SKIPS, naming why, when the sibling repo is not on this
    box — a missing sibling is the box's business, and a skip that says so is not a pass.
    """
    spec = { **_REPOS[ request.param ], "name": request.param }
    if spec[ "script_dir" ] is None:
        pytest.skip( f"sibling repo {request.param} not found beside the main lupin checkout" )
    return spec


def _init_main_checkout( path, with_script=True, spec=None ):
    """
    Build a temp git repo that looks like a main checkout: one commit, a `.venv` with an
    executable stand-in, the borrowable artifacts, and (optionally) the real scripts.

    Requires:
        - path is an existing directory

    Ensures:
        - the repo has exactly one commit on branch main, with origin/main pointing at it
        - `<path>/.venv/bin/python` exists and is executable
        - every name in _MUST_BE_BORROWED exists under path
        - the provisioning scripts are present iff with_script
        - spec None means lupin; a lupin-mobile spec builds that repo's stand-ins instead
    """
    spec = { **_REPOS[ "lupin" ], "name": "lupin" } if spec is None else spec
    if spec[ "name" ] != "lupin":
        return _init_mobile_main_checkout( path, with_script, spec )
    env = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null" }

    def run( *args ):
        subprocess.run( args, cwd=path, env=env, check=True, capture_output=True )

    run( "git", "init", "-b", "main", "." )
    run( "git", "config", "user.email", "test@example.com" )
    run( "git", "config", "user.name", "Test" )

    script_dir = os.path.join( path, "src", "scripts" )
    os.makedirs( script_dir, exist_ok=True )
    if with_script:
        for name in ( "link-worktree-venv.sh", "link-worktree-artifacts.sh" ):
            dest = os.path.join( script_dir, name )
            shutil.copy2( os.path.join( _SCRIPT_DIR, name ), dest )
            os.chmod( dest, 0o755 )
        # The scripts source this library from the folder beside them.
        os.makedirs( os.path.join( script_dir, "lib" ), exist_ok=True )
        shutil.copy2( os.path.join( _SCRIPT_DIR, "lib", "worktree-link-lib.sh" ), os.path.join( script_dir, "lib", "worktree-link-lib.sh" ) )
    else:
        # `src/scripts` must still be a tracked directory, or the worktree would not have
        # it and the cloud-run.env case would be testing directory creation instead of
        # the absence of provisioning. One variable at a time.
        with open( os.path.join( script_dir, ".keep" ), "w" ) as f: f.write( "" )

    tf_dir = os.path.join( path, "src", "terraform", "envs", "test" )
    os.makedirs( tf_dir, exist_ok=True )
    with open( os.path.join( tf_dir, "main.tf" ), "w" ) as f: f.write( "# tracked\n" )
    with open( os.path.join( path, "README.md" ), "w" ) as f:
        f.write( "# test\n" )
    run( "git", "add", "-A" )
    run( "git", "commit", "-m", "initial" )
    run( "git", "update-ref", "refs/remotes/origin/main", "HEAD" )

    # The main checkout's venv — a tiny executable is enough; the venv script's contract
    # is that `.venv/bin/python` resolves and runs.
    bin_dir = os.path.join( path, ".venv", "bin" )
    os.makedirs( bin_dir, exist_ok=True )
    python  = os.path.join( bin_dir, "python" )
    with open( python, "w" ) as f:
        f.write( '#!/usr/bin/env bash\necho "Python 3.13.7 (stand-in)"\n' )
    os.chmod( python, 0o755 )

    # The borrowable artifacts, created AFTER the commit so they are untracked exactly as
    # they are in the real repo. A tracked stand-in would be present in every worktree by
    # construction and could not fail.
    pkg = os.path.join( path, "node_modules", "tsx" )
    os.makedirs( pkg, exist_ok=True )
    with open( os.path.join( pkg, "package.json" ), "w" ) as f:
        f.write( '{ "name": "tsx" }\n' )
    with open( os.path.join( path, "src", "scripts", "cloud-run.env" ), "w" ) as f:
        f.write( "LUPIN_GCP_PROJECT_ID=stand-in\n" )
    # The terraform provider cache, plus the sibling state file that must NEVER be shared.
    # `src/terraform/envs/test` is tracked (a .tf file), as in the real repo.
    tf_dir = os.path.join( path, "src", "terraform", "envs", "test" )
    plugin = os.path.join( path, _TF_PROVIDERS, "registry.terraform.io", "hashicorp", "random", "3.9.0", "linux_amd64" )
    os.makedirs( plugin, exist_ok=True )
    with open( os.path.join( plugin, "terraform-provider-random" ), "w" ) as f: f.write( "stand-in binary\n" )
    with open( os.path.join( path, _TF_PARENT, "terraform.tfstate" ), "w" ) as f: f.write( "{}\n" )
    return path


def _init_mobile_main_checkout( path, with_script, spec ):
    """
    The lupin-mobile twin of `_init_main_checkout`: the mobile repo's own scripts, a stand-in
    Flutter SDK, and the Gradle wrapper pair, the last two created after the commit so they are
    untracked. No terraform and no secrets: the repo has none of the first and the deny test
    covers the second.

    Requires:
        - path is an existing directory
        - spec["script_dir"] holds link-worktree-venv.sh and link-worktree-artifacts.sh, and lib/worktree-link-lib.sh when the repo has one

    Ensures:
        - one commit on main with origin/main pointing at it
        - every spec["must_be_borrowed"] and the SDK exist under path, untracked
        - the scripts are present iff with_script
    """
    env = { **os.environ, "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null" }

    def run( *args ):
        subprocess.run( args, cwd=path, env=env, check=True, capture_output=True )

    run( "git", "init", "-b", "main", "." )
    run( "git", "config", "user.email", "test@example.com" )
    run( "git", "config", "user.name", "Test" )
    script_dir = os.path.join( path, "src", "scripts" )
    os.makedirs( script_dir, exist_ok=True )
    if with_script:
        for name in ( "link-worktree-venv.sh", "link-worktree-artifacts.sh" ):
            dest = os.path.join( script_dir, name )
            shutil.copy2( os.path.join( spec[ "script_dir" ], name ), dest )
            os.chmod( dest, 0o755 )
        # Where lupin-mobile has the library its scripts source it from beside themselves (mobile row c41c090a),
        # so a copy of those scripts without it dies at the first `source` and links nothing.
        # An older lupin-mobile has neither the library nor the `source` line, and has nothing to copy.
        lib_source = os.path.join( spec[ "script_dir" ], "lib", "worktree-link-lib.sh" )
        if os.path.exists( lib_source ):
            os.makedirs( os.path.join( script_dir, "lib" ), exist_ok=True )
            shutil.copy2( lib_source, os.path.join( script_dir, "lib", "worktree-link-lib.sh" ) )
    else:
        with open( os.path.join( script_dir, ".keep" ), "w" ) as f: f.write( "" )
    with open( os.path.join( path, "README.md" ), "w" ) as f: f.write( "# test\n" )
    run( "git", "add", "-A" )
    run( "git", "commit", "-m", "initial" )
    run( "git", "update-ref", "refs/remotes/origin/main", "HEAD" )

    sdk = os.path.join( path, spec[ "sdk" ] )
    os.makedirs( os.path.dirname( sdk ), exist_ok=True )
    with open( sdk, "w" ) as f: f.write( '#!/usr/bin/env bash\necho "Flutter (stand-in)"\n' )
    os.chmod( sdk, 0o755 )
    for rel in spec[ "must_be_borrowed" ]:
        dest = os.path.join( path, rel )
        os.makedirs( os.path.dirname( dest ), exist_ok=True )
        with open( dest, "w" ) as f: f.write( "stand-in\n" )
        os.chmod( dest, 0o755 )
    return path


class _StubConfig:

    def __init__( self, values ): self._values = values

    def get( self, key, default=None, return_type="string" ): return self._values.get( key, default )


_CFG = _StubConfig( {
    "cosa worktree sandbox root"         : ".claude/worktrees",
    "cosa worktree base ref"             : "origin/main",
    "cosa worktree auto cleanup"         : False,   # keep the tree so we can inspect it
    "cosa worktree cleanup timeout secs" : 30,
} )


@pytest.fixture
def main_checkout( request, repo ):
    """A temp repo standing in for a main checkout, with or without the scripts, for each repo."""
    with_script = getattr( request, "param", True )
    with tempfile.TemporaryDirectory() as tmp:
        real = os.path.realpath( tmp )
        _init_main_checkout( real, with_script=with_script, spec=repo )
        from unittest.mock import patch
        with patch( "cosa.agents.shared.worktree_context.cu.get_project_root", return_value=real ):
            yield real
        subprocess.run( [ "git", "worktree", "prune" ], cwd=real, check=False, capture_output=True )


class TestANewWorktreeCanRunAWholeTier:

    @pytest.mark.asyncio
    async def test_a_worktree_created_by_WorktreeContext_has_the_borrowed_artifact( self, main_checkout, repo ):
        """
        The row's first requirement, for each repo (row 5aedbad2). Every member's assertion
        names the member, so a failure says which one did not land. The member list is a
        hand-pinned literal in _REPOS and is asserted non-empty, because a loop over nothing
        passes.
        """
        assert repo[ "must_be_borrowed" ], "no members to check — the loop below would pass by vacuum"
        async with WorktreeContext( job_id="tfe-artifacts-control", config_mgr=_CFG, enabled=True ) as wt:
            for rel in repo[ "must_be_borrowed" ]:
                landed = os.path.join( wt.path, rel )
                assert os.path.exists( landed ), f"new worktree has no {rel} at {landed}"
                assert os.path.islink( landed ), f"{rel} is present but is not a borrowed link"
                assert os.path.realpath( landed ) == os.path.realpath( os.path.join( main_checkout, rel ) )

    @pytest.mark.asyncio
    async def test_the_tier_toolchain_resolves_through_the_venv_script( self, main_checkout, repo ):
        """
        The other half of "tier-capable": the toolchain the venv script lends (lupin's
        `.venv`, mobile's Flutter SDK, whose script keeps the lupin name because the spawn
        path calls it by that name). It must RESOLVE and run, not merely exist.
        """
        async with WorktreeContext( job_id="tfe-artifacts-sdk", config_mgr=_CFG, enabled=True ) as wt:
            sdk = os.path.join( wt.path, repo[ "sdk" ] )
            assert os.path.exists( sdk ), f"new worktree has no {repo[ 'sdk' ]}"
            assert os.access( sdk, os.X_OK ), f"{repo[ 'sdk' ]} is present but not executable"
            assert subprocess.run( [ sdk ], capture_output=True ).returncode == 0

    @pytest.mark.asyncio
    async def test_the_borrowed_node_modules_actually_resolves_a_package( self, main_checkout, repo ):
        """
        A symlink that resolves to nothing looks identical to success from a stat, and
        the incident was not "no directory" — it was `Cannot find package 'tsx'`. So the
        assertion is that a PACKAGE resolves through the link, which is the thing the
        failing TypeScript run could not do.
        """
        if repo[ "name" ] != "lupin": pytest.skip( "lupin-only: lupin-mobile borrows no node_modules" )
        async with WorktreeContext( job_id="tfe-artifacts-resolve", config_mgr=_CFG, enabled=True ) as wt:
            assert os.path.isfile( os.path.join( wt.path, "node_modules", "tsx", "package.json" ) )

    @pytest.mark.asyncio
    async def test_only_the_providers_dir_is_linked_and_its_state_neighbour_is_not_shared( self, main_checkout, repo ):
        """
        Row 31344c5f follow-on. The provider cache resolves THROUGH the link, while its parent
        `.terraform` is a REAL directory of the worktree's own — so the `terraform.tfstate`
        beside it in the main checkout is neither visible nor writable from here.
        """
        if repo[ "name" ] != "lupin": pytest.skip( "lupin-only: lupin-mobile has no terraform tree" )
        async with WorktreeContext( job_id="tfe-artifacts-tf", config_mgr=_CFG, enabled=True ) as wt:
            parent = os.path.join( wt.path, _TF_PARENT )
            assert os.path.isdir( parent ) and not os.path.islink( parent ), ".terraform must be a real dir, not a link"
            assert os.path.islink( os.path.join( wt.path, _TF_PROVIDERS ) )
            assert os.path.isfile( os.path.join( wt.path, _TF_PROVIDERS, "registry.terraform.io", "hashicorp",
                                                 "random", "3.9.0", "linux_amd64", "terraform-provider-random" ) )
            assert not os.path.exists( os.path.join( parent, "terraform.tfstate" ) ), \
                "the main checkout's tfstate leaked into the worktree"

    @pytest.mark.asyncio
    @pytest.mark.parametrize( "main_checkout", [ False ], indirect=True )
    async def test_the_control_can_actually_see_an_unprovisioned_tree( self, main_checkout, repo ):
        """
        THE NEGATIVE CONTROL. Same repo, same context manager, provisioning scripts
        removed. The worktree must come up WITHOUT the artifacts — proving the
        assertions above are capable of failing. A green here alongside the others would
        mean this whole file is measuring nothing.
        """
        async with WorktreeContext( job_id="tfe-artifacts-negative", config_mgr=_CFG, enabled=True ) as wt:
            for rel in ( *repo[ "must_be_borrowed" ], repo[ "sdk" ] ):
                assert not os.path.exists( os.path.join( wt.path, rel ) ), \
                    f"a tree with no provisioning script somehow got {rel} — the control is broken"

    @pytest.mark.asyncio
    async def test_a_second_pass_is_idempotent_and_leaves_the_links_alone( self, main_checkout, repo ):
        """Provisioning runs on every worktree creation, so it must never churn."""
        async with WorktreeContext( job_id="tfe-artifacts-idem", config_mgr=_CFG, enabled=True ) as wt:
            before = { rel: os.readlink( os.path.join( wt.path, rel ) ) for rel in repo[ "must_be_borrowed" ] }
            result = provision_worktree_artifacts( wt.path )
            assert result[ "status" ] == "ok"
            assert set( result[ "artifacts" ].values() ) == { "ALREADY" }
            for rel, target in before.items():
                assert os.readlink( os.path.join( wt.path, rel ) ) == target

    @pytest.mark.asyncio
    async def test_a_real_file_the_seat_put_there_is_never_replaced( self, main_checkout, repo ):
        """
        A seat that wrote its own `cloud-run.env` owns it. Provisioning must leave it
        exactly as found — the same no-op contract the venv script has for a real
        `.venv` directory.
        """
        async with WorktreeContext( job_id="tfe-artifacts-mine", config_mgr=_CFG, enabled=True ) as wt:
            mine = os.path.join( wt.path, repo[ "owned_file" ] )
            os.remove( mine )
            with open( mine, "w" ) as f: f.write( "mine\n" )

            result = provision_worktree_artifacts( wt.path )
            assert result[ "status" ] == "ok"
            assert result[ "artifacts" ][ repo[ "owned_file" ] ] == "ALREADY"
            assert not os.path.islink( mine ), "a real file the seat wrote was replaced by a link"
            assert open( mine ).read().strip() == "mine"

    @pytest.mark.asyncio
    async def test_a_dangling_link_of_ours_is_replaced_rather_than_left_broken( self, main_checkout, repo ):
        """
        The one case worth clearing: a link that resolves to nothing is ours and is
        broken, and leaving it would make every later run report ALREADY over a tree
        that still cannot run.
        """
        async with WorktreeContext( job_id="tfe-artifacts-dangling", config_mgr=_CFG, enabled=True ) as wt:
            link = os.path.join( wt.path, repo[ "lend" ] )
            os.remove( link )
            os.symlink( os.path.join( main_checkout, "gone-forever" ), link )
            assert not os.path.exists( link )

            result = provision_worktree_artifacts( wt.path )
            assert result[ "artifacts" ][ repo[ "lend" ] ] == "LINKED"
            assert os.path.realpath( link ) == os.path.realpath( os.path.join( main_checkout, repo[ "lend" ] ) )

    @pytest.mark.asyncio
    async def test_a_main_checkout_with_nothing_to_lend_is_a_no_op_and_not_a_failure( self, main_checkout, repo ):
        """
        A box that never ran `npm install` has nothing to borrow. That is the operator's
        business, not a provisioning failure — alarming on it would fire on every spawn
        on a fresh box, and an alarm that always fires is one nobody reads.
        """
        source = os.path.join( main_checkout, repo[ "lend" ] )
        shutil.rmtree( source ) if os.path.isdir( source ) else os.remove( source )
        async with WorktreeContext( job_id="tfe-artifacts-nolend", config_mgr=_CFG, enabled=True ) as wt:
            result = provision_worktree_artifacts( wt.path )
            assert result[ "provisioned" ] is True
            assert result[ "status" ] == "ok"
            assert result[ "artifacts" ][ repo[ "lend" ] ] == "SOURCE_ABSENT"

    @pytest.mark.asyncio
    async def test_debug_narrates_the_artifact_outcomes( self, main_checkout, repo, capsys ):
        """
        The narration is how an operator tells "provisioned" from "could not" without
        reading the tree. It reports the OUTCOMES, not merely that the call was made —
        a clean exit is not evidence the work happened.
        """
        async with WorktreeContext( job_id="tfe-artifacts-debug", config_mgr=_CFG,
                                    enabled=True, debug=True ) as wt:
            out = capsys.readouterr().out
            assert "[WorktreeContext] artifacts: ok" in out
            assert repo[ "lend" ] in out


class TestTheBorrowListNeverCarriesASecret:
    """
    🔴 THE DENY SIDE IS A RULING, NOT A PREFERENCE (Mr. Radio, 2026-09-01), so it gets a
    test rather than a comment. The allow list is parsed out of the script; the deny list
    is hand-written here. Two provenances, so the comparison can actually disagree.
    """

    @staticmethod
    def _script_of( repo ):
        return os.path.join( repo[ "script_dir" ], "link-worktree-artifacts.sh" )

    # The deny list is hand-written per repo in _REPOS["..."]["never"], deliberately not derived
    # from anything the script can move. Each entry is (needle, mode): "exact" for a path that
    # is forbidden only as itself, "under" for a prefix nothing may live beneath.
    #
    # ⚠️ `.env` IS EXACT, AND THE FIRST CUT OF THIS TEST HAD IT AS A SUBSTRING — which
    # reddened on `src/scripts/cloud-run.env`, a file whose own header reads "No secrets
    # here". The repo-root `.env` is the secret (JWT_SECRET_KEY, POSTGRES_PASSWORD); a
    # name ending in `.env` is not. Left visible because the coarse form is the obvious
    # one to write and would have banned a legitimate member.

    def _borrow_list( self, repo ):
        """The borrow array (BORROW in lupin, LINK_LIST in lupin-mobile), read out of the shipped script."""
        lines, inside = [], False
        for line in open( self._script_of( repo ) ):
            stripped = line.strip()
            if stripped.startswith( repo[ "borrow_array" ] + "=(" ): inside = True;  continue
            if inside and stripped == ")":       inside = False; break
            if inside and stripped.startswith( '"' ):
                lines.append( stripped.strip( '"' ) )
        return lines

    def test_the_borrow_list_is_found_at_all( self, repo ):
        """
        The positive control for the parser below. An empty list would satisfy every
        deny assertion in this class by vacuum — a loop over nothing is green.
        """
        borrowed = self._borrow_list( repo )
        assert len( borrowed ) >= 2, f"parsed only {borrowed} out of {self._script_of( repo )}"
        assert repo[ "lend" ] in borrowed
        # The literal pins and the parsed array must overlap; a parser reading the wrong array would not.
        assert set( repo[ "must_be_borrowed" ] ) <= set( borrowed ), f"{repo[ 'name' ]}: pinned members missing from the script"

    def test_no_borrowed_path_is_a_secret_or_a_build_output( self, repo ):
        """
        A symlink puts a live credential inside a throwaway tree that gets rm -rf'd,
        copied and shared, and the `.venv` precedent makes it look sanctioned. A venv is
        a build artifact; a key is a secret. A build OUTPUT is excluded for a different
        reason: a build run in a throwaway tree would write into the shared checkout.
        """
        assert repo[ "never" ], "no deny entries — the loops below would pass by vacuum"
        borrowed = self._borrow_list( repo )
        assert borrowed, "empty borrow list — nothing below could fail"
        for forbidden, mode in repo[ "never" ]:
            for rel in borrowed:
                hit = ( rel == forbidden ) if mode == "exact" else rel.startswith( forbidden )
                assert not hit, f"{repo[ 'name' ]}: the borrow list carries a forbidden path: {rel} ({mode} {forbidden})"
