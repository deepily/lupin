"""
`deploy-cloud-test.sh` must refuse to run against a VM that does not host the
venue it is hardcoded to — row 5f1532d1.

THE DEFECT
----------
Every config value at the top of that script names the cloud-TEST venue:

    REST_CONTAINER  lupin-rest-cloud-test
    COMPOSE_FILE    docker-compose.cloud-test.yml
    ENV_FILE        cloud-test.env

The one and only VM runs the cloud-GPU venue. Measured on lupin-host-test
2026-08-24, `docker ps -a` shows `lupin-rest-cloud-gpu` and
`lupin-cloudsql-proxy`, and `lupin-rest-cloud-test` exists in NO state, not even
stopped. Every `docker restart` and `docker inspect` in the script addresses a
container that is not there.

A SECOND, QUIETER WRONGNESS
---------------------------
The script's header said the AXIS-A bind-mount path must abort because "the
./src mount was removed 2026-07-07". True of cloud-test. FALSE of cloud-gpu,
where the same measurement shows:

    /mnt/lupin-data/lupin/src -> /var/lupin/src

So the abort would refuse the fast code path on the one VM where the fast code
path works. The header is now scoped to the venue it actually describes.

WHY GUARD RATHER THAN DELETE
----------------------------
Ruled by Mr Radio, 2026-08-24: this script is the only written record of the
two-axis code-vs-deps routing, and `lupin-vm.sh deploy` implements only the code
half. Deleting it would lose the design. Nobody is broken today because the
working path IS `lupin-vm.sh deploy`; the hazard is a reader picking this file by
its name — it reads like THE deploy script — and concluding from its failures
that the container is missing or that code deploys are impossible on this VM.
The guard turns a confusing failure into a named one that points somewhere.

WHY THE DECISION IS A PURE FUNCTION
-----------------------------------
`dctl_venue_present` takes the `docker ps` output as an argument instead of
shelling out, so the verdict is testable here with no VM, no network and no
docker. The script keeps the ssh; the lib keeps the judgement.

Venue: :7999-eligible. No SSH, no gcloud, no Docker.
"""
import os
import re
import subprocess

import cosa.utils.util as cu

PROJECT_ROOT = cu.get_project_root()
LIB_PATH     = os.path.join( PROJECT_ROOT, "src/scripts/lib/deploy-cloud-test-lib.sh" )
SCRIPT_PATH  = os.path.join( PROJECT_ROOT, "src/scripts/deploy-cloud-test.sh" )

with open( SCRIPT_PATH, "r" ) as f:
    SCRIPT = f.read()
with open( LIB_PATH, "r" ) as f:
    LIB = f.read()

# Measured on lupin-host-test, 2026-08-24. Used as the realistic input rather
# than a made-up container list.
LIVE_PS_ALL = "lupin-rest-cloud-gpu\nlupin-cloudsql-proxy"


def _venue_present( want, names ):
    """
    Run dctl_venue_present against a name list; return its exit code.

    Requires:
        - want is a container name; names is a newline-separated list

    Ensures:
        - returns the function's exit code (0 present / 1 absent / 2 empty list)
        - the list is passed as a single argv element, exactly as the script
          passes captured ssh output
    """
    r = subprocess.run(
        [ "bash", "-c",
          f'source "{LIB_PATH}"; dctl_venue_present "$1" "$2"',
          "_", want, names ],
        capture_output=True, text=True
    )
    return r.returncode


# ══════════════════════════════════════════════════════════════════════════
# The verdict
# ══════════════════════════════════════════════════════════════════════════

def test_the_live_vm_does_not_host_this_scripts_venue():
    """
    The defect itself, replayed through the function with the values measured on
    the VM. A guard that has only ever seen synthetic input has not been shown to
    catch the thing it was built for.
    """
    assert _venue_present( "lupin-rest-cloud-test", LIVE_PS_ALL ) == 1


def test_the_venue_that_IS_there_reads_as_present():
    """
    The other half of the same measurement. Without this, a function that always
    returned 1 would pass the test above.
    """
    assert _venue_present( "lupin-rest-cloud-gpu", LIVE_PS_ALL ) == 0


def test_an_empty_container_list_is_its_own_answer_not_absent():
    """
    "docker reported no containers" and "docker reported containers, none of them
    mine" are different facts. An empty list usually means the probe FAILED — ssh
    died, the VM is down, sudo refused — and answering "absent" to a question that
    was never successfully asked turns a broken probe into a confident wrong
    verdict, which is the whole failure mode this lane keeps finding.
    """
    assert _venue_present( "lupin-rest-cloud-test", "" ) == 2


def test_whitespace_only_output_is_also_treated_as_no_answer():
    """
    A probe that returns a bare newline has told you nothing, the same as one that
    returned nothing at all.
    """
    assert _venue_present( "lupin-rest-cloud-test", "\n  \n" ) == 2


def test_a_name_that_is_a_PREFIX_of_a_running_one_is_not_present():
    """
    THE FALSE-GREEN THIS GUARD EXISTS TO STOP. `lupin-rest` is a prefix of
    `lupin-rest-cloud-gpu`, and `lupin-rest-cloud-test` shares a long prefix with
    it too. A substring test would report the cloud-test container present on a VM
    that runs only cloud-gpu — the guard would pass and the script would go on to
    address nothing.
    """
    assert _venue_present( "lupin-rest", "lupin-rest-cloud-gpu" ) == 1
    assert _venue_present( "lupin-rest-cloud", LIVE_PS_ALL ) == 1


def test_a_name_that_is_a_SUFFIX_of_a_running_one_is_not_present():
    """
    The mirror of the case above; a `grep -F` without `-x` would match either end.
    """
    assert _venue_present( "cloud-gpu", LIVE_PS_ALL ) == 1


def test_a_stopped_container_still_counts_as_present():
    """
    The script probes with `docker ps -a`, so a stopped container is in the list
    and IS this venue — the right remedy there is "start it", not "you are on the
    wrong VM". The guard must not send that reader to lupin-vm.sh.
    """
    assert _venue_present( "lupin-rest-cloud-test", "lupin-rest-cloud-test" ) == 0


# ══════════════════════════════════════════════════════════════════════════
# Wiring — the guard is reachable, runs first, and names the way out
# ══════════════════════════════════════════════════════════════════════════

def test_the_script_calls_the_guard():
    """
    A guard nothing calls is a unit test with no deploy behind it.
    """
    assert "assert_target_venue_exists" in SCRIPT
    assert "dctl_venue_present" in SCRIPT


def test_the_guard_probes_with_ps_dash_a_not_bare_ps():
    """
    `docker ps` alone lists only RUNNING containers, so a stopped cloud-test
    container would read as "wrong VM" and send the operator to a different script
    when all they needed was to start it.
    """
    body = _guard_body()
    assert "docker ps -a" in body


def test_the_guard_runs_before_any_deploy_work():
    """
    Ordering is the point. A guard that fires after the ref resolve, the axis
    detect, or the first `docker restart` has let the confusing output happen
    already. It must precede every other VM interaction, the .deployed-ref read
    included.
    """
    call  = SCRIPT.index( "\nassert_target_venue_exists\n" )
    prev  = SCRIPT.index( "PREV_SHA=" )
    axis  = SCRIPT.index( "AXIS=\"$( dctl_detect_axis" )
    assert call < prev < axis


def test_the_guard_covers_dry_run_too():
    """
    --dry-run exists to tell you what a real run would do. On a VM that does not
    host this venue, the honest answer is "nothing, and here is why" — not a
    confident plan for a container that is not there. Asserted by position: the
    guard runs before the DRY_RUN branch, so there is no path around it.
    """
    assert SCRIPT.index( "\nassert_target_venue_exists\n" ) < SCRIPT.index( 'if [ "$DRY_RUN" -eq 1 ]' )


def test_every_return_code_of_the_probe_has_an_arm():
    """
    Three outcomes, three arms. A missing one would fall through and let the
    script continue against a venue it never confirmed — the silent pass.
    """
    body = _guard_body()
    for arm in ( "0)", "2)", "*)" ):
        assert arm in body, f"guard has no arm for {arm}"


def test_the_failed_probe_does_NOT_claim_the_container_is_absent():
    """
    The rc=2 arm must say the question could not be asked. Telling an operator
    "the container is absent" when the truth is "ssh failed" sends them to
    rebuild infrastructure that was never broken.
    """
    body = _guard_body()
    arm  = body[ body.index( "2)" ) : body.index( "*)" ) ]
    assert "NOT a verdict" in arm


def test_the_wrong_venue_error_names_the_script_that_DOES_work():
    """
    An abort that only says "no" leaves the reader exactly as stuck as the silent
    failure did. This one must name the working path, which is the entire reason
    the row chose to guard the script rather than delete it.
    """
    body = _guard_body()
    assert "lupin-vm.sh deploy" in body


def test_the_wrong_venue_error_reports_what_IS_running():
    """
    Naming the containers actually present is what turns "this is broken" into
    "you are in the wrong place" without a second round of investigation.
    """
    body = _guard_body()
    assert "docker ps --format" in body
    assert "running" in body


def test_the_error_warns_against_repointing_the_config():
    """
    The obvious "fix" on reading this error is to edit the three config lines to
    say cloud-gpu. That would carry cloud-test's assumptions — chiefly the AXIS-A
    abort, whose premise is false on cloud-gpu — onto a venue they do not
    describe. The error has to close that door explicitly.
    """
    body = _guard_body()
    assert "Do NOT 'fix' this by repointing" in body


def _guard_body():
    """
    The text of assert_target_venue_exists, from its definition to its closing
    brace at column 0.

    Ensures:
        - fails rather than returning None if the function cannot be located,
          so every assertion above breaks loudly instead of passing vacuously
    """
    m = re.search( r"^assert_target_venue_exists\(\) \{.*?^\}", SCRIPT, re.M | re.S )
    assert m, "could not find assert_target_venue_exists — was it renamed?"
    return m.group( 0 )


# ══════════════════════════════════════════════════════════════════════════
# The header claim that was true of one venue and asserted of all of them
# ══════════════════════════════════════════════════════════════════════════

def test_the_axis_a_note_is_scoped_to_the_venue_it_describes():
    """
    The header used to read "It does NOT today" about the /var/lupin/src bind —
    an unscoped present-tense claim that invited the reader to carry it to
    whatever VM they were looking at. It is true of cloud-test and false of
    cloud-gpu, where the mount is present. The note must now say which venue it
    is about.
    """
    header = SCRIPT[ : SCRIPT.index( "AXIS B (deps)" ) ]
    assert "cloud-TEST container does NOT" in header
    # The old wording still appears ONCE, quoted, in the note that explains what
    # was corrected — keeping it is what lets the next reader see the change
    # rather than wonder whether anyone noticed. What must not survive is the
    # phrase standing on its own as a live unscoped claim, so it is required to
    # appear only inside that quotation.
    assert header.count( "It does NOT today" ) == 1
    assert 'used to read "It does NOT today"' in header


def test_the_header_records_the_measurement_that_contradicts_it():
    """
    A correction that only softens the wording leaves the next reader to
    re-derive why. The measured cloud-gpu mount is the evidence, so it is written
    down beside the claim it bounds.
    """
    header = SCRIPT[ : SCRIPT.index( "AXIS B (deps)" ) ]
    assert "/mnt/lupin-data/lupin/src -> /var/lupin/src" in header
    assert "lupin-vm.sh deploy" in header


def test_the_lib_declares_the_new_pure_function():
    assert "dctl_venue_present()" in LIB
