"""
The arm switch: which of the four reuse surfaces a run's session can reach.

The two arms differ in the four surfaces and in nothing else. The session configuration is built from one base,
so the only keys that move between arms are the ones this module names. The switch is proven by asking a session
port to call each surface under the configuration, never by reading the configuration back.
"""
import copy

from cosa.repo.semdup import frozen
from lupin_mcp.reuse_harness import errors as err

ARM_WITH    = "with"
ARM_WITHOUT = "without"
ARMS        = ( ARM_WITH, ARM_WITHOUT )

# The labels the run directories and logs carry. They are the two strings of the frozen configuration's scrub list, so the
# blindness census covers what this harness writes. Ordinary words would fail it on thousands of definitions.
ARM_LABELS  = { ARM_WITH : frozen.ARM_LABELS[ 0 ], ARM_WITHOUT : frozen.ARM_LABELS[ 1 ] }

# The four surfaces of plan 3, section 7.1: three tools and one skill.
SURFACE_CHECK_EXISTS    = "check_exists"
SURFACE_FETCH_SIMILAR   = "fetch_similar"
SURFACE_READ_CAPABILITY = "read_capability"
SURFACE_REVIEWER        = "reuse-reviewer"
SURFACES                = ( SURFACE_CHECK_EXISTS, SURFACE_FETCH_SIMILAR, SURFACE_READ_CAPABILITY, SURFACE_REVIEWER )

# What denies each surface: a tool-permission rule the session starts with.
DENY_RULES  = {
    SURFACE_CHECK_EXISTS    : "mcp__cosa-voice__check_exists",
    SURFACE_FETCH_SIMILAR   : "mcp__cosa-voice__fetch_similar",
    SURFACE_READ_CAPABILITY : "mcp__cosa-voice__read_capability",
    SURFACE_REVIEWER        : "Skill(reuse-reviewer)",
}
# record_search is not one of the four, so neither arm denies it. Changing what an arm can call is Rick's decision (plan 3, section 7.1).
# The skill folder is removed from the worktree of the arm without it, so its description is not in the skill menu either.
SKILL_PATH  = ".claude/skills/reuse-reviewer"

BASE_CONFIG = {
    "setting_sources" : [ "project", "local" ],
    "claude_md"       : True,                      # CLAUDE.md and the docs are in both arms (section 7.1)
    "grep"            : True,
}


def build_session_config( arm, model_id ):
    """
    Build the configuration a run's session starts with.

    Requires:
        - arm is the with arm or the without arm
        - model_id is a non-empty string: the pinned implementer model

    Ensures:
        - the result holds model, arm_label, deny_rules and remove_paths besides every key of BASE_CONFIG
        - for the with arm, deny_rules and remove_paths are empty
        - for the without arm, deny_rules holds the rule of each of the four surfaces and no other, and remove_paths holds SKILL_PATH
        - every other key is equal between the arms for one model_id
        - the result shares nothing with BASE_CONFIG

    Raises:
        - HarnessError BAD_ARM if arm names neither arm
        - HarnessError BAD_SPEC if model_id is empty
    """
    if arm not in ARMS: raise err.HarnessError( err.BAD_ARM, f"{arm!r} is not one of {list( ARMS )}" )
    if not model_id: raise err.HarnessError( err.BAD_SPEC, "model_id is empty" )
    config = copy.deepcopy( BASE_CONFIG )
    config.update( { "model" : model_id, "arm_label" : ARM_LABELS[ arm ], "deny_rules" : [], "remove_paths" : [] } )
    if arm == ARM_WITHOUT:
        config[ "deny_rules" ]   = [ DENY_RULES[ surface ] for surface in SURFACES ]
        config[ "remove_paths" ] = [ SKILL_PATH ]
    return config


def verify_arm( arm, config, session ):
    """
    Prove the arm switch by calling each surface through the session port.

    Requires:
        - arm is the with arm or the without arm and config is the result of build_session_config for it
        - session.probe( config, surface ) returns True when the surface answered and False when the session refused the call

    Ensures:
        - every surface is probed, in the order of the surface list
        - returns { surface: bool } as the session answered
        - for the with arm, every surface answered; for the without arm, none did

    Raises:
        - HarnessError BAD_ARM if arm names neither arm
        - HarnessError SURFACE_REACHABLE naming the surfaces that answered in the arm without them
        - HarnessError SURFACE_MISSING naming the surfaces that did not answer in the arm with them
    """
    if arm not in ARMS: raise err.HarnessError( err.BAD_ARM, f"{arm!r} is not one of {list( ARMS )}" )
    answers = { surface : bool( session.probe( config, surface ) ) for surface in SURFACES }
    reached = [ surface for surface in SURFACES if answers[ surface ] ]
    absent  = [ surface for surface in SURFACES if not answers[ surface ] ]
    if arm == ARM_WITHOUT and reached: raise err.HarnessError( err.SURFACE_REACHABLE, f"the arm without the tools reached {reached}" )
    if arm == ARM_WITH and absent:     raise err.HarnessError( err.SURFACE_MISSING, f"the arm with the tools could not reach {absent}" )
    return answers
