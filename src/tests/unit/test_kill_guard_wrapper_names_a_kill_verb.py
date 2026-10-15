"""
The kill guard refuses a wrapper whose argument text names kill, pkill or killall.

No shell is parsed. A command-position wrapper (shell, eval, ssh, docker, python,
xargs and the like) whose literal arguments contain a kill verb as a word is denied.
A variable or alias as the verb and a quote-split name stay allowed and are pinned in
test_kill_guard.py.
"""

import pytest

from tests.unit.test_kill_guard import _deny, _no_claude


def _wrapped( command ):
    return _deny( command, comm_reader=_no_claude, pgrep_probe=lambda selector: [] )


@pytest.mark.parametrize( "command", [
    "ssh host pkill -f TOK",
    "eval pkill -f TOK",
    "systemd-run --user pkill -f TOK",
    "docker exec c pkill -f TOK",
    "watch pkill -f TOK",
    "find . -exec pkill -f TOK {} +",
    "parallel pkill -f TOK ::: a",
    "python3 -c \"import os; os.system('pkill -f TOK')\"",
    "bash -c \"bash -c 'kill 4242'\"",
    "bash -c $'kill 4242'",
    "sh -c 'cat pids.txt | xargs kill'",
    "echo 4242 | xargs kill",
    "xargs -a pids.txt kill",
    "xargs sh -c 'kill $0'",
    "echo start; ssh host /bin/kill 4242",
    "LUPIN_X=1 ssh host killall python",
    "echo -P $$ | xargs kill 12345",
    "echo pgrep -P $$ | xargs kill",
    "cat ps --ppid $$ | xargs kill",
    "pgrep -P $$ | echo 123 | xargs kill",
    "pgrep -P $$ | xargs kill 12345",
    "pgrep -P $$ | xargs kill $(cat f)",
    "pgrep -P $$ | xargs kill < f",
    "pgrep -P $$ | xargs -a f kill",
    "xargs -a f kill",
    "pgrep -P $$ | xargs -r kill 12345",
    "pgrep -P $$ || echo 123 | xargs kill",
    "pgrep -P $$ && echo 123 | xargs kill",
    "pgrep -P $$; echo 123 | xargs kill",
    "pgrep -P $$ & echo 123 | xargs kill",
    "echo 123 | xargs kill; pgrep -P $$ | xargs kill",
] )
def test_a_wrapper_naming_a_kill_verb_is_denied( command ):
    assert _wrapped( command ) is not None, command


@pytest.mark.parametrize( "command", [
    "ssh host ls -l",
    "docker exec c ls | grep kill",
    "echo ssh host pkill",
    "echo 'ssh host pkill -f TOK'",
    "git log --grep=skill",
    "python3 -c 'print( 1 )'",
    "xargs -r ls",
    "ssh host skillet",
    "ssh host kill-switch",
    "bash -c 'pkill -P $$ -f pytest'",
    "bash -c 'kill $!'",
    "pgrep -P $$ -f pytest | xargs -r kill",
    "FOO=1 pgrep -P $$ -f pytest | xargs -r kill",
    "ps --ppid $$ -o pid | xargs kill",
    "pgrep -P $$ | xargs kill -9",
    "pgrep -P $$ | xargs -r kill -TERM",
    'bash -c "echo kill 4242"',
    "LUPIN_ALLOW_UNSCOPED_KILL=1 ssh host pkill -f TOK",
    "bash -c 'LUPIN_ALLOW_UNSCOPED_KILL=1 kill 4242'",
] )
def test_a_wrapper_without_a_kill_word_or_a_mention_is_allowed( command ):
    assert _wrapped( command ) is None, command
