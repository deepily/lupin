"""
Generate the agent-router completion prompt from the v2 registry (row 95924f2d;
design 2026.08.16-generate-router-prompt-and-corpus-from-registry.md §2.2).

The serving prompt `src/conf/prompts/agent-router-template-completion.txt` was
hand-edited and had no writer anywhere in the tree, so nothing PREVENTED it from
drifting away from the registry. This module is that writer: it emits the file's
fixed scaffolding plus one `<command>` line per `speakable` command in the
REGISTRY. The paired test (`test_v2_router_prompt_generator.py`) pins the on-disk
file to what this emits, converting the drift guard from a detector into a
preventer.

Two invariants, stated so a future editor does not quietly break them:

  1. This module is a PROVABLE NO-OP on the serving artifact (Rachel's ruling,
     2026-08-16, superseding design §2.2's "generator owns order"): the generated
     file equals the current served file byte-for-byte, so the one question this
     row answers — is the generator correct, or did serving quietly change? — stays
     answerable. Command MEMBERSHIP comes from `registry.speakable`; `_SERVED_ORDER`
     fixes only the sequence and is cross-checked against that set (fail-loud on
     drift), so it is a presentation order, not a second definition. A better
     emission order is a SEPARATE, MEASURED change with its own probe — never
     bundled here.

  2. The scaffolding (the instruction prose, the `{voice_command}` slot, the
     response-format block) is NOT registry-derived — no registry can author it.
     It is held here verbatim as `_HEADER` / `_FOOTER`; only the command list
     between the `<agent-routing-commands>` tags is generated.

Regenerate the checked-in file:
    PYTHONPATH=src python -m cosa.rest.v2.router_prompt_generator
"""

import cosa.utils.util as cu
from cosa.rest.v2.registry import REGISTRY


# Relative to cu.get_project_root(); the same path the router readers load
# (llm_client.py, llm_completion.py) and the drift guard reads.
TEMPLATE_REL_PATH = "/src/conf/prompts/agent-router-template-completion.txt"


# ── The served command ORDER — a PRESENTATION order, NOT a second definition ──
# Rachel's ruling (2026-08-16): this generator must be a PROVABLE NO-OP on the
# serving artifact — the generated file must equal the served file byte-for-byte,
# so the one question this row answers ("is the generator correct, or did serving
# quietly change?") stays answerable. A different emission order may well be better,
# but that is a SEPARATE, MEASURED change with its own before/after probe — never
# bundled, unmeasured, inside this refactor.
#
# So order is fixed here to the current served sequence. This is NOT a competing
# definition of WHAT commands exist — membership comes from `registry.speakable`
# alone. `speakable_commands()` CROSS-CHECKS this tuple against that set and RAISES
# on any disagreement, so a registry change that forgets this list fails LOUD (and
# the pin test goes red) rather than silently emitting a stale order. Reorder here
# only as the deliberate, probed change described above.
_SERVED_ORDER = (
    "agent router go to datetime",
    "agent router go to weather",
    "agent router go to calendar",
    "agent router go to receptionist",
    "agent router go to todo",
    "agent router go to math",
    "agent router go to deep research",
    "agent router go to podcast generator",
    "agent router go to research to podcast",
    "agent router go to calculator",
    "agent router go to claude code",
    "agent router go to swe team",
    "agent router go to presentation generator",
    "agent router go to research to presentation",
    "agent router go to test suite",
    "agent router go to test fix expediter resume",
    "agent router go to automatic",
    "none",
)


# ── Fixed scaffolding — verbatim, byte-exact (design §2.2) ────────────────────
# `_HEADER` ends AT the opening `<agent-routing-commands>` tag (no trailing
# newline); `_FOOTER` begins AT the closing tag. The command block is spliced
# between them by render_router_prompt(). `{voice_command}` inside `_FOOTER` is a
# literal — the router substitutes it at serve time via str.format(); this module
# never calls .format() on the generated text, so it survives untouched.
_HEADER = (
    "<s>[INST]### Instruction:\n"
    "\n"
    "Use the Task and Input given below to write a Response that can solve the following Task.\n"
    "\n"
    "### Task:\n"
    "\n"
    "Your job is to discern the intent of a human voice command transcription and translate it "
    "into a standardized agent routing command that another LLM would understand.\n"
    "\n"
    "You will be given a human voice command as INPUT as well as a list of possible standardized "
    "commands. You must choose the correct standardized command from the following list:\n"
    "<agent-routing-commands>"
)

_FOOTER = (
    "</agent-routing-commands>\n"
    "\n"
    "Requirement: You MUST NOT use python code to answer this question.\n"
    "Requirement: You MUST use your linguistic knowledge and intuition to answer this question.\n"
    "Requirement: The first word of your response MUST be `<response>`\n"
    "Hint: Anything that isn't a part of the command itself should be treated as arguments "
    "related to the command.\n"
    "\n"
    "### Input:\n"
    "\n"
    "Below is the raw human voice command transcription formatted using simple XML:\n"
    "\n"
    "<human>\n"
    "    <voice-command>{voice_command}</voice-command>\n"
    "</human>\n"
    "\n"
    "The standardized command that you translate MUST be returned wrapped in simple, well-formed XML:\n"
    "\n"
    "<response>\n"
    "    <command></command>\n"
    "    <args></args>\n"
    "</response>\n"
    "[/INST]\n"
    "### Response:\n"
)


def speakable_commands():
    """
    The routing commands the prompt lists, in the served presentation order.

    Membership is the registry's alone (`spec.speakable`); `_SERVED_ORDER` only
    fixes the sequence for a provable byte-for-byte no-op on the serving artifact.

    Requires:
        - REGISTRY is populated (import side effect)

    Ensures:
        - Returns the FULL routing strings for every spec whose `speakable` field
          is True, sequenced by _SERVED_ORDER
        - Raises ValueError if _SERVED_ORDER and the registry's speakable set
          disagree in either direction — a registry change that forgets this list
          fails LOUD instead of emitting a stale order
    """
    speakable = { command for command, spec in REGISTRY.items() if spec.speakable }
    ordered   = set( _SERVED_ORDER )
    if ordered != speakable:
        raise ValueError(
            "router prompt order drift — _SERVED_ORDER disagrees with "
            "registry.speakable: "
            f"only in order={sorted( ordered - speakable )}, "
            f"only in registry={sorted( speakable - ordered )}"
        )
    return [ command for command in _SERVED_ORDER if command in speakable ]


def render_router_prompt():
    """
    Render the full agent-router completion prompt from the registry.

    Requires:
        - _HEADER / _FOOTER hold the verbatim scaffolding

    Ensures:
        - Returns the complete template text: scaffolding with one indented
          `<command>` line per speakable command spliced between the
          `<agent-routing-commands>` tags
        - `{voice_command}` remains an unsubstituted literal for the serve-time
          str.format()
    """
    command_block = "\n" + "".join(
        f"    <command>{command}</command>\n" for command in speakable_commands()
    )
    return _HEADER + command_block + _FOOTER


def write_router_prompt( path=None ):
    """
    Regenerate the checked-in prompt file from the registry.

    Requires:
        - path, when given, is a writable file path; otherwise the canonical
          TEMPLATE_REL_PATH under the project root is used

    Ensures:
        - Writes render_router_prompt() to the resolved path (overwriting)
        - Returns the resolved path written
    """
    resolved = path or ( cu.get_project_root() + TEMPLATE_REL_PATH )
    with open( resolved, "w" ) as handle:
        handle.write( render_router_prompt() )
    return resolved


def main():
    """Regenerate the checked-in prompt file and report the path + command count."""
    path = write_router_prompt()
    print( f"Regenerated {path} with {len( speakable_commands() )} commands" )
    return path


if __name__ == "__main__":
    main()   # pragma: no cover — CLI entry; main() itself is covered by the unit test
