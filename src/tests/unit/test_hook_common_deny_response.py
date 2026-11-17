"""build_deny_response: the one PreToolUse deny envelope every guard answers with."""

from lupin_cli.claude_code.hooks.lib.hook_common import build_deny_response


def test_build_deny_response_is_a_pretooluse_deny():
    assert build_deny_response( "because" ) == {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : "because",
        }
    }


def test_no_guard_module_keeps_its_own_copy_of_the_envelope():
    import pathlib
    import lupin_cli.claude_code.hooks.lib as lib
    root   = pathlib.Path( lib.__file__ ).parent
    owners = sorted( p.name for p in root.glob( "*.py" ) if "\"permissionDecision\"" in p.read_text() )
    assert owners == [ "hook_common.py" ]
