"""
Merge-head guard — a `git commit` during a live merge CONCLUDES that merge.

THE MECHANISM. A merge is a two-step operation over tree-global state: `git
merge` stages the result and leaves MERGE_HEAD set, and a later `git commit`
writes the merge commit. Between those two steps the merge belongs to the tree,
not to the session that started it, so ANY seat committing in that tree in the
meantime concludes somebody else's merge under its own message.

WHAT IT COST, 2026-08-31 (row f3306404, reported by Maya and Rachel). A merge one
seat had staged was live when another committed in the same tree. The commit
consumed it. Parentage was lost, the lane landed with one parent, all ten shas
came out non-ancestors, and a known-defective assertion went live on the working
branch. Four seats spent about an hour finding and repairing it, ending at
`f3e9b41a`. Nobody could see it happening while it happened.

WHY NO EXISTING HABIT CATCHES IT, which is the finding that made this worth a
hook rather than a note:

    git status                 says plainly that a merge is in progress
    git status --porcelain     says NOTHING once conflicts are resolved and staged
    git status --porcelain=v2  says NOTHING either

Measured on 2026-08-31 in a scratch repo: with a live MERGE_HEAD and the conflict
resolved and staged, v1 printed `M  f.txt` and v2 printed one `1 M.` line, while
the long form printed "All conflicts fixed but you are still merging."

⇒ So every script, alias and glance built on a machine-readable status is blind to
precisely the dangerous state, and it is blind in the SAFE-LOOKING direction.

THE RELIABLE CHECK IS PLUMBING:  `git rev-parse -q --verify MERGE_HEAD`
Exit 0 with a sha = a merge is live. Non-zero = none. Worktree-aware by
construction, because git resolves the ref through the worktree's own git dir.

🔴 DO NOT USE THE PATH FORM. `test -f .git/MERGE_HEAD` is wrong, and wrong in the
safe-looking direction: in a LINKED WORKTREE `.git` is a FILE, not a directory, so
the path does not exist and the test reports NO MERGE while one is live. Measured
in a scratch linked worktree with a live merge: the path test said no-merge and
`rev-parse` returned the sha. `test_merge_head_guard.py` measures all of that
against real git rather than asserting it.

The path form is right in ONE location — the main checkout — and wrong in every
linked worktree, which is where this fleet's work happens. DO NOT QUOTE A COUNT;
it moves daily as seats come and go. Re-derive it:

    git worktree list --porcelain | awk '/^worktree /{print $2}' \\
      | while read -r w; do [ -f "$w/.git" ] && echo linked; done | wc -l

Snapshot for scale only, not to be quoted: 102 linked of 103 trees, 2026-08-31.
Row f3306404 recorded 92 nine hours earlier, which is why the command is here and
the number is not.

WHAT THIS GUARD DOES: on a Bash `git commit` with MERGE_HEAD live in the target
tree, DENY, name the merge sha, and say what committing would do. Rick ruled the
shape by voice on 2026-08-31 ~20:05 EDT — a hard deny over a warning, because a
warning in a busy log is not a control.

SCOPE, as ratified:
  · DENY, not advise.
  · GLOBAL, not conditional on the branch. A guard with fewer conditions has fewer
    ways to be wrong, and stash_guard set that precedent.
  · ESCAPE HATCH for the seat that STARTED the merge and must finish it.
  · FAIL OPEN when the check itself errors.

🔴 READ THIS BEFORE THE REST: WHY THERE ARE TWO PROBES AND NOT ONE. Asked by
mr radio 🦉 on review, 2026-08-31 — WOULD THIS GUARD HAVE STOPPED THE INCIDENT IT
WAS BUILT FOR? With MERGE_HEAD alone the answer was NO, and that is what got the
second probe ruled in rather than left as a footnote.

Two measurements and one deduction, kept separate so the join can be refused:
  1. MEASURED in a scratch repo — a `git commit` made while MERGE_HEAD is live
     ALWAYS records the merge parent, unconditionally. You cannot commit during a
     merge and come out with one parent.
  2. MEASURED on the real commit — `b26d31a1` has exactly ONE parent, and the lane
     tip `4fb745f8` is NOT an ancestor of it. It IS an ancestor of the repair
     `f3e9b41a`.
  ⇒ MERGE_HEAD was not live when b26d31a1 was written, so a MERGE_HEAD-only guard
     would have been silent through the whole event.

THAT LEFT TWO ROUTES TO THE SAME END STATE, and the artifact cannot say which:
  (a) the content was staged by a `git merge --squash`, which never sets MERGE_HEAD
  (b) a merge was live EARLIER and was cleared before the commit landed
Route (a) is now COVERED by the SQUASH_MSG probe (Rick ruled the widening by voice,
2026-08-31 ~21:05 EDT). Route (b) is not, and cannot be: once MERGE_HEAD is gone
there is nothing left in the tree to detect.

⇒ SO THE HONEST ANSWER IS STILL NOT A CLEAN YES. The guard now covers one of the
two routes that end in that shape, and no evidence exists to say which route was
taken. Anyone tempted to write "this would have prevented the incident" should stop
at "this covers the squash route to it."

⇒ AND IT IS WORTH ITS PLACE EITHER WAY: the hazard it closes — a staged merge
concluded by a passing commit — is real, reproducible on demand, and invisible to
BOTH machine-readable `git status` forms. A control that prevents a mechanism earns
its keep even where it would not have prevented one particular instance of the
damage. This paragraph exists so nobody has to guess which way the module leans.

⚠️ THREE LIVE RESIDUALS AND ONE CLOSED, NAMED RATHER THAN HIDDEN.

1. ✅ CLOSED — a squash merge was invisible to a MERGE_HEAD-only check, and is now
   caught by the SQUASH_MSG probe. Kept in this list rather than deleted, because
   the reasoning is what justifies the second probe's existence and a future reader
   deciding to "simplify" back to one check needs to meet it.

2. A PARTIAL COMMIT CANNOT CONSUME A MERGE — git refuses it first. Measured:
   `git commit -m x -- <paths>` during a live merge dies with "fatal: cannot do a
   partial commit during a merge", while a plain `git commit -m x` succeeds and
   produces a two-parent merge commit under the committer's own message. The
   guard still refuses the pathspec shape, deliberately: denying it costs a
   command git was going to reject anyway, and carving it out would add a
   condition whose only effect is another way to be wrong.

3. A `git commit` AT THE START OF A LINE INSIDE A HEREDOC IS REFUSED, and that
   is a CHOICE. ⚠️ THE FIRST CUT OF THIS NOTE SAID "quoted inside a heredoc",
   which is WIDER THAN WHAT IS TRUE, and the test written to pin it FAILED and
   corrected me. Measured: mid-line prose (`the rule is: git commit takes ...`)
   does NOT match, because `git` is not in command position there; a line that
   BEGINS `git commit` does, because a newline opens a command slot.
   `commit_scope_guard` strips heredoc bodies before matching, because text that
   is DATA read as COMMAND made it refuse the very commit carrying its own
   message. This guard deliberately does NOT strip, because the direction of harm
   differs: there a false deny blocks an honest commit at any time, whereas here
   it can only fire while a merge is ALREADY LIVE in the tree — a state in which
   being stopped and told so is nearly always the right outcome. Not stripping
   also means a heredoc that opens and never closes cannot hide a real commit
   behind it. The cost is one hatch prefix for a seat writing prose about
   `git commit` mid-merge, and a test pins the behaviour so it stays a decision
   rather than becoming a surprise.

4. `git merge --continue` ALSO CONCLUDES A MERGE, and this guard does not see it
   because it is not a `git commit`. Measured: with MERGE_HEAD live, it produces a
   two-parent merge commit and clears MERGE_HEAD, exactly as a plain commit does.
   Not covered because Rick ruled on the COMMIT, and because it differs in the one
   way that matters to the founding incident: it writes git's own default merge
   message rather than the running seat's, so a peer's merge does not land under
   somebody else's words. Ownership confusion still applies. Under an accident
   threat model this is thin — a seat types `git merge --continue` only when it
   believes it owns a merge, whereas `git commit` is what everyone types all day.

THREAT MODEL — ACCIDENT, NOT EVASION. The matcher is `commit_scope_guard`'s,
reused rather than re-spelled so there is one answer in the tree to "is this a
git commit". It recognises the natural spellings in command position and nothing
claims completeness; a seat determined to route around it can.

SAFETY — this runs inside the hot-path PreToolUse hook, so:
  • FAIL-OPEN: ANY error → allow (return None). The `git rev-parse` read is
    bounded by a timeout, and every failure mode of it — not a repo, git absent,
    a directory that does not exist, a slow disk — returns None and allows.
  • ESCAPE HATCH: `LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...`.

    🔴 HONOURED BY A PREFIX CARVE-OUT, NOT AN ENV READ, and that is not a
    shortcut — it is the only thing that can work. A PreToolUse hook is a SEPARATE
    PROCESS reading its OWN environment, and an inline `VAR=1 cmd` prefix belongs
    to a command that HAS NOT RUN YET. stash_guard learned this the expensive way:
    its documented hatch was broken for most of its life and appeared to work only
    because the env assignment pushed the program out of command position. The
    process environment is ALSO honoured, for a session deliberately exported into
    merge work, but the prefix is what makes the deny message's instruction true.

🔴 HOW THIS MODULE ITSELF WAS LANDED, and why that is not a shortcut. It reached the
working branch by FAST-FORWARD (`b7af819b`), not by a merge commit, and anyone who
sees only the linear history will read that as someone skipping the ceremony.

It was the opposite. A `--no-ff` merge happens IN THE SHARED CHECKOUT and leaves
MERGE_HEAD live there for as long as it takes to write the commit — which is exactly
the window this module exists to close, and there were peers working in that tree at
the time. Landing a MERGE_HEAD guard by opening a MERGE_HEAD window would have been
the shape the whole row is a warning about.

⇒ SO THE ORDER WAS: bring the working branch INTO the lane branch, in the author's
own worktree where a window harms nobody; verify green there; then fast-forward. The
shared tree never held a merge in flight for a second, and ancestry is fully
preserved — all seven commits are ancestors, which is the receipt that matters.

🔴 AND THAT REASONING WAS BROADER THAN THE MECHANISM SUPPORTS — NARROWED HERE, one
hour later, after Rachel 🕊️ landed a different lane with `--no-ff` and mr radio 🦉
noticed two opposite readings of one rule on one branch. MEASURED, and it settles it:

    CLEAN `--no-ff` merge        MERGE_HEAD after the command: NONE
    CONFLICTING merge            MERGE_HEAD after the command: LIVE

A clean merge AUTO-COMMITS inside the single `git merge` invocation, so there is no
interval in which a peer can commit into a staged merge. THE WINDOW IS NOT CREATED BY
`--no-ff`; it is created by a merge that does NOT auto-commit — a CONFLICT, or an
explicit `--no-commit`. My original phrasing implicated the merge STYLE, which is the
wrong variable.

⇒ SO BOTH LANDINGS WERE CORRECT AND THEY ARE NOT IN TENSION. A clean `--no-ff` is the
better default — it preserves lane ancestry in one commit and opens nothing. A
fast-forward is worth reaching for when a merge is EXPECTED TO CONFLICT in a shared
checkout, which is the only case where the style choice changes the exposure.

⇒ THE RULE, RESTATED AT THE ALTITUDE THE EVIDENCE ACTUALLY REACHES: prefer a landing
that cannot leave a merge STAGED-BUT-UNCOMMITTED in a tree other people are working
in. Merge style is a proxy for that and a poor one; auto-commit is the property.

⇒ AND THE GUARD IS INDIFFERENT TO ALL OF IT, which is the reassuring part: it fires
on a live MERGE_HEAD at commit time however that state arose. A conflicting `--no-ff`
leaves MERGE_HEAD live, the merger concludes with `git commit`, and the guard refuses
until they use the hatch — the designed friction, working. A clean `--no-ff` never
reaches the guard at all, because git commits internally rather than through a Bash
`git commit`, and there is nothing there to protect.

(This paragraph exists because the first version of it was written from reasoning and
the correction came from measurement. A retraction has to reach the artifact, not
just the conversation it happened in.)

⚠️ THE FRICTION THIS BUYS, stated so it can be re-measured rather than defended:
the seat that legitimately concludes its own merge must use the hatch every time.
That is the ratified trade — the alternative is guessing which seat owns a merge
from a tree that records no owner.
"""
import os
import re
import subprocess
from typing import Optional

from lupin_cli.claude_code.hooks.lib.commit_scope_guard import git_commit_match


BASH_TOOL_NAMES = ( "Bash", )

_ENV_FLAG    = "LUPIN_ALLOW_MERGE_COMMIT"
_TRUE_VALUES = ( "1", "true", "on", "yes" )

# How long the MERGE_HEAD read may take before the guard gives up and allows.
GIT_TIMEOUT_SECONDS = 5

# THE ONLY CHECK. Not a path test, not a status parse — see the module docstring
# for the measurement behind both refusals.
MERGE_HEAD_ARGV = ( "git", "rev-parse", "-q", "--verify", "MERGE_HEAD" )

# THE SECOND PROBE. `git merge --squash` stages the whole merge and sets NO
# MERGE_HEAD, so the first probe is blind to it — and the resulting commit has ONE
# parent and loses the lane's ancestry, which is the shape the founding incident
# ended in. Rick ruled the widening by voice, 2026-08-31 ~21:05 EDT, after being
# shown that the MERGE_HEAD-only guard would not have caught its own incident.
#
# `--git-path` resolves through the worktree's own git dir, so this is worktree-
# aware for the same reason `rev-parse --verify` is; never build the path by hand.
#
# ⚠️ MEASURED BEFORE SHIPPING, because a file that LINGERS would be a permanent
# false refusal for every seat that ever abandoned a squash:
#     after `git merge --squash`   PRESENT   <- the state to catch
#     after the commit             absent    <- git clears it
#     after `git reset --hard`     absent    <- the normal abandon path clears it
#     after an ordinary merge      absent    <- cannot be confused with MERGE_HEAD
# Both real ways out of a squash clear it, so it cannot strand a seat.
SQUASH_MSG_ARGV = ( "git", "rev-parse", "--git-path", "SQUASH_MSG" )

# Which in-flight state was found. They need different words: one names a sha the
# committer can look up, the other has none to name.
KIND_MERGE  = "merge"
KIND_SQUASH = "squash"

_INLINE_FLAG_RE = re.compile( rf"\b{_ENV_FLAG}=(?P<value>[^\s;&|]*)" )

# `git -C <path> commit` runs in ANOTHER tree, so that is the tree whose merge
# state decides the verdict. Case-sensitive: `-c key=val` is a config override,
# not a directory.
_DASH_C_RE = re.compile( r"-C\s+(?P<path>[^\s;&|]+)" )

# 🔴 `cd <tree> && git commit` IS THE SHAPE THIS FLEET ACTUALLY USES, and without
# this the guard checks the wrong tree. MEASURED 2026-08-31 against the real hook,
# with a live merge in a linked worktree and the hook standing in the main checkout:
#
#     git -C <merge tree> commit       DENY     <- -C was already handled
#     cd <merge tree> && git commit    ALLOWED  <- the miss
#
# The Bash tool resets its working directory to the session root on every call, so a
# seat working in a worktree types `cd <worktree> && git ...` all day and the hook's
# own cwd is never the tree being committed to. A guard that misses that shape misses
# nearly every commit in the fleet.
#
# `cd` in COMMAND POSITION only, so a `cd` inside an argument is not read as one.
_CD_RE = re.compile(
    r"(?:^|[;&|(){}\n]|\bthen\b|\bdo\b|\belse\b)\s*cd\s+(?P<path>[^\s;&|]+)"
)


def _guard_disabled( env=None ) -> bool:
    """
    True iff the escape-hatch flag is set truthy in the process environment.

    Requires:
        - env is None (real os.environ) or a mapping injected for testing

    Ensures:
        - True only for a recognised truthy spelling of the flag
        - never raises
    """
    env = env if env is not None else os.environ
    return str( env.get( _ENV_FLAG, "" ) ).strip().lower() in _TRUE_VALUES


def _hatch_in_prefix( prefix ) -> bool:
    """
    True iff THIS invocation's own env-assignment prefix carries the hatch, truthy.

    Requires:
        - prefix is the matched env-assignment / wrapper span, or None

    Ensures:
        - reads the flag from the COMMAND, never from os.environ — see the module
          docstring for why an env read alone cannot honour an inline prefix
        - scoped to this invocation's prefix, so an unrelated `echo FLAG=1`
          earlier in the line cannot unlock a later commit
        - never raises
    """
    if not prefix: return False

    found = _INLINE_FLAG_RE.search( prefix )
    if not found: return False

    return found.group( "value" ).strip().strip( "'\"" ).lower() in _TRUE_VALUES


def _target_directory( command, match, cwd=None ):
    """
    The directory whose merge state governs this commit.

    Two things move a commit into another tree, and BOTH are common here:
      · `cd <path> && git commit` — the Bash tool resets its working directory to
        the session root every call, so a seat working in a worktree types this all
        day and the hook's cwd is never the tree being committed to
      · `git -C <path> commit` — moves the whole invocation

    They compose in that order, each relative to the last, which is exactly
    os.path.join's rule: a later absolute path wins outright.

    Requires:
        - command is the raw Bash command
        - match is the git_commit_match result for it
        - cwd is the directory the hook is standing in, or None for the process cwd

    Ensures:
        - returns cwd when the command names neither a cd nor a -C
        - otherwise returns the composed target, resolved against cwd, with ~ expanded
        - FALLS BACK TO cwd when the composed path is not an existing directory, so a
          `cd` misread out of a quoted literal checks the session's own tree rather
          than checking nowhere — the fallback is what makes the loose scan safe
        - only a `cd` BEFORE the commit counts; one after it has not run yet
        - never raises

    ⚠️ It follows the LAST `cd` before the commit and does not model subshells or
    conditionals. Under an accident threat model that is the whole job; a misread
    lands on the existence check above and degrades to today's behaviour.
    """
    base  = cwd or os.getcwd()
    parts = []

    for found in _CD_RE.finditer( command[ :match.start() ] ):
        path = found.group( "path" )
        if path != "-":                       # `cd -` is the previous directory, unknowable here
            parts = [ os.path.expanduser( path ) ]

    parts.extend( _DASH_C_RE.findall( match.group( "pre" ) or "" ) )

    if not parts: return cwd

    target = os.path.join( base, *parts )
    return target if os.path.isdir( target ) else cwd


def _live_merge_head( cwd=None ) -> Optional[ str ]:
    """
    The MERGE_HEAD sha iff a merge is live in <cwd>, else None.

    Requires:
        - cwd is a directory path, or None for the process cwd

    Ensures:
        - returns the sha string when `git rev-parse -q --verify MERGE_HEAD`
          exits 0 with output
        - returns None when it exits non-zero, when git is absent, when the
          directory does not exist, or when the read times out — every one of
          which ALLOWS the commit
        - never raises
    """
    try:
        done = subprocess.run(
            list( MERGE_HEAD_ARGV ),
            cwd            = cwd,
            capture_output = True,
            text           = True,
            timeout        = GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return None

    if done.returncode != 0: return None

    return done.stdout.strip() or None


def _squash_in_flight( cwd=None ) -> bool:
    """
    True iff a `git merge --squash` is staged and unconcluded in <cwd>.

    Requires:
        - cwd is a directory path, or None for the process cwd

    Ensures:
        - asks git for the SQUASH_MSG path rather than building one, so it is
          worktree-aware exactly as the MERGE_HEAD probe is
        - returns False on any failure — git absent, not a repo, a timeout, a
          missing directory — every one of which ALLOWS the commit
        - never raises
    """
    try:
        done = subprocess.run(
            list( SQUASH_MSG_ARGV ),
            cwd            = cwd,
            capture_output = True,
            text           = True,
            timeout        = GIT_TIMEOUT_SECONDS,
        )
    except Exception:
        return False

    if done.returncode != 0: return False

    path = done.stdout.strip()
    if not path: return False

    # --git-path answers relative to the repo when cwd is inside it.
    if not os.path.isabs( path ):
        path = os.path.join( cwd or os.getcwd(), path )

    try:
        return os.path.isfile( path )
    except Exception:
        return False


def _deny_reason_for( kind: str, merge_sha=None ) -> str:
    """
    Compose the refusal: what is live, what committing would do, how to proceed.

    Requires:
        - kind is KIND_MERGE or KIND_SQUASH
        - merge_sha is the live MERGE_HEAD sha for KIND_MERGE, None for KIND_SQUASH

    Ensures:
        - names the sha, so the committer can identify the merge before acting
        - names the machine-readable blindness, because the seat's next instinct
          is to check `git status --porcelain` and be reassured by nothing
        - gives a remedy that MATCHES THE STATE. The hatch is right for a merge you
          mean to conclude and WRONG for a squash that is not yours — using it there
          lands the squash, which is the damage. A refusal whose instruction causes
          the harm is worse than none, because it carries authority (Rachel 🕊️, 2026-08-31)
        - NAMES ITS OWN RESIDUALS. A residual recorded only in a module docstring
          and a test is invisible to the person who actually meets the guard, who
          will reasonably assume it covers every way a merge gets concluded. The
          refusal is the only text a seat reads, so the scope belongs in it.
    """
    # 🔴 THE REMEDY DIFFERS BY STATE, AND OFFERING THE WRONG ONE CAUSES THE HARM.
    # Found by Rachel 🕊️ on review, 2026-08-31: the squash refusal pointed at the
    # hatch, and the hatch is exactly what a seat must NOT reach for when the staged
    # squash is not theirs — using it LANDS the squash under their message, which is
    # the damage this guard exists to prevent. A refusal whose instruction produces
    # the harm is worse than no refusal, because it carries authority.
    #
    # MEASURED — a plain `git reset` (not --hard) is the safe way out of a squash:
    #     SQUASH_MSG           PRESENT -> absent
    #     the seat's own untracked file      kept
    #     the seat's own tracked edit        kept
    #     the lane's files       left in the worktree, UNSTAGED
    # Nothing is lost, which is why it can be recommended without a warning attached.
    #
    # ⚠️ The unstaged leftovers matter and the message says so: a later `git add -A`
    # or `git commit -a` re-captures the lane's files and lands them without ancestry
    # anyway — the original harm reached by a second route.
    if kind == KIND_SQUASH:
        remedy = (
            "IF YOU MEAN TO LAND THIS SQUASH, re-run with:\n"
            "  LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...\n"
            "IF IT IS NOT YOURS, OR IS LEFT OVER — you are almost certainly here because you "
            "wanted to commit your OWN unrelated work — DO NOT use the hatch: it would land "
            "the squash under your message. Clear it instead:\n"
            "  git reset            # unstages the squash, keeps every file, drops SQUASH_MSG\n"
            "Your own changes survive that untouched, staged or not. ⚠️ It leaves the merged "
            "files in the worktree UNSTAGED, so commit your paths BY NAME afterwards — a later "
            "`git add -A` or `git commit -a` would sweep them back in and land them without "
            "ancestry, which is the same damage by another route.\n"
        )
        headline = (
            "`git commit` is denied: A SQUASH MERGE IS STAGED AND UNCONCLUDED IN THIS TREE "
            "(SQUASH_MSG is present, and there is no MERGE_HEAD to name).\n"
            "Committing now LANDS that merge under YOUR message, with ONE parent and none of "
            "the lane's ancestry — which is exactly the shape the 2026-08-31 incident ended in "
            "(row f3306404: `b26d31a1`, one parent, ten shas non-ancestors, repaired at "
            "`f3e9b41a`).\n"
        )
    else:
        remedy = (
            "IF THE MERGE IS YOURS and you mean to conclude it, re-run with:\n"
            "  LUPIN_ALLOW_MERGE_COMMIT=1 git commit ...\n"
            "IF IT IS NOT YOURS, it belongs to another seat mid-operation. Do NOT abort it and "
            "do NOT commit around it — ask the owner to finish, or wait. Unlike a staged squash "
            "this one is not yours to clear: `git merge --abort` would destroy their conflict "
            "resolution. Your own work is safe where it is; nothing here loses it.\n"
        )
        headline = (
            f"`git commit` is denied: A MERGE IS LIVE IN THIS TREE (MERGE_HEAD {merge_sha[ :12 ]}).\n"
            "Committing now CONCLUDES that merge under YOUR message.\n"
        )

    return (
        headline +
        "A merge is a two-step "
        "operation over tree-global state — staged by one command, written by the next — "
        "so between those steps it belongs to the tree, not to whoever started it. That "
        "happened on 2026-08-31 (row f3306404): parentage was lost, the lane landed with "
        "one parent, ten shas came out non-ancestors, and four seats spent an hour "
        "repairing it.\n"
        "DO NOT CHECK `git status --porcelain` — BOTH machine-readable forms show NOTHING "
        "once the conflicts are staged. Use the long `git status`, or "
        "`git rev-parse -q --verify MERGE_HEAD`, or look for SQUASH_MSG.\n"
        + remedy +
        "WHAT THIS GUARD DOES NOT COVER, so you do not read it as more than it is: "
        "`git merge --continue` also concludes a merge and is NOT checked. Seeing no "
        "refusal is not evidence that no merge is in flight."
    )


def merge_head_deny_reason(
    tool_name,
    tool_input,
    *,
    enabled       : Optional[ bool ] = None,
    env           = None,
    cwd           = None,
    merge_reader  = None,
    squash_reader = None,
) -> Optional[ str ]:
    """
    Return a deny-reason string iff a Bash `git commit` would conclude a live merge.

    Requires:
        - tool_name is the hook payload's tool_name (str)
        - tool_input is the hook payload's tool_input (dict) whose "command" key
          carries the shell command, when present
        - enabled is None (resolved from env) or injected for testing
        - merge_reader / squash_reader are None (real git) or injected for testing

    Ensures:
        - None unless ALL hold: the guard is enabled, tool_name is Bash, the
          command invokes `git commit` in command position, the hatch prefix is
          absent, and EITHER MERGE_HEAD resolves in the target tree OR a squash
          merge is staged there
        - MERGE_HEAD is checked first: when it resolves, the refusal can name a sha,
          which is more use to the committer than the squash wording
        - the target tree honours BOTH `cd <path> &&` and `git -C <path>`, composed
          in that order; an unresolvable target falls back to cwd
        - FAIL-OPEN: any unexpected error → None
    """
    try:
        if enabled is None:
            enabled = not _guard_disabled( env )
        if not enabled: return None
        if tool_name not in BASH_TOOL_NAMES: return None
        if not isinstance( tool_input, dict ): return None

        command = tool_input.get( "command", "" )
        if not isinstance( command, str ) or not command: return None

        match = git_commit_match( command )
        if match is None: return None

        if _hatch_in_prefix( match.group( "prefix" ) ): return None

        target    = _target_directory( command, match, cwd )
        merge_sha = ( merge_reader or _live_merge_head )( target )
        if merge_sha:
            return _deny_reason_for( KIND_MERGE, merge_sha )

        if ( squash_reader or _squash_in_flight )( target ):
            return _deny_reason_for( KIND_SQUASH )

        return None

    except Exception:
        # FAIL-OPEN BACKSTOP, and it is EXERCISED rather than asserted: a test
        # injects a merge_reader that raises and asserts the commit is allowed.
        # stash_guard's equivalent carries `pragma: no cover` because nothing can
        # reach it; here the reader is a seam, so the branch is real and a pragma
        # would be a claim in place of a measurement.
        return None


def build_merge_head_deny_response( reason: str ) -> dict:
    """
    Build the PreToolUse deny envelope (mirrors build_stash_deny_response).

    Ensures:
        - returns { hookSpecificOutput: { hookEventName: "PreToolUse",
          permissionDecision: "deny", permissionDecisionReason: <reason> } }
    """
    return {
        "hookSpecificOutput": {
            "hookEventName"            : "PreToolUse",
            "permissionDecision"       : "deny",
            "permissionDecisionReason" : reason,
        }
    }
