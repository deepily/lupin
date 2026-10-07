---
capability: cc-hooks-git-guards
pin_algorithm: py3.13.xf75af6/ts5.9.3
pins:
  - lupin_cli.claude_code.hooks.pre_tool_use.main@26d0cfd35f
  - lupin_cli.claude_code.hooks.lib.stash_guard.stash_deny_reason@13e37ff81e
  - lupin_cli.claude_code.hooks.lib.branch_lock_guard.branch_lock_deny_reason@10ab10ceda
  - lupin_cli.claude_code.hooks.lib.kill_guard.kill_deny_reason@0935def6dc
  - lupin_cli.claude_code.hooks.lib.merge_head_guard.merge_head_deny_reason@8c41a6dd55
  - lupin_cli.claude_code.hooks.lib.commit_scope_guard.evaluate_commit_scope@ea494f9221
  - lupin_cli.claude_code.hooks.lib.commit_scope_guard.git_commit_match@d36ffc37dd
---
# Git and process guards (PreToolUse)

Five text-matching guards run on every Bash tool call and refuse or flag a risky `git` or `kill` command before it runs. `pre_tool_use.main` dispatches them. Heartbeat hooks are in [[cc-hooks-heartbeat]]; the session bridge is in [[cc-session-bridge]].

## Dispatch
- `main` calls the guards in this order: stash, branch lock, kill, merge head, commit scope. The first deny is emitted and the hook exits; later guards do not run.
- A deny is a `permissionDecision: "deny"` response carrying the reason text. Only commit scope can also allow with a notice, sent as `additionalContext`.
- Every guard acts only on the `Bash` tool and returns "allow" on any internal error.
- All five are on by default. The threat model is accident, not evasion: variable indirection, `eval` and similar are not caught.

## Per guard
- **`stash_guard`** matches `git stash` in command position, through paths, wrappers written without options (`env`, `sudo`, `xargs`...), env-assignment prefixes and `sh -c` payloads. A wrapper given an option, such as `xargs -n1 git stash`, is not matched. Only `list` and `show` are allowed; a bare `git stash` or any other word is denied. The stash stack is shared by every worktree. Hold work in a WIP commit instead.
- **`branch_lock_guard`** denies four routes around the branch-creation lock: setting `BRANCH_GUARD_ALLOW`, setting `core.hooksPath`, writing into the git hooks directory, and unsetting or overriding `CLAUDECODE`. Reading hooks or config stays allowed. `env -i` is refused only when the command also runs git.
- **`kill_guard`** denies a `kill` with a literal PID whose `/proc/<pid>/comm` is `claude`, and a `pkill`/`killall` pattern that `pgrep` shows matching a live `claude` process. It also denies a fleet-wide listing (`ps -e`, `ps aux`, `pgrep`) piped or looped into a kill, and `kill $(pgrep ...)`. Listings with `-P`, `--parent` or `--ppid` (own children) and listings with no kill are allowed. Heredoc bodies are ignored.
- **`merge_head_guard`** denies `git commit` while `git rev-parse -q --verify MERGE_HEAD` resolves, or the `SQUASH_MSG` file exists, in the tree the commit targets. It follows `cd <path> &&` and `git -C <path>`. It does not see `git merge --continue`.
- **`commit_scope_guard`** reviews the paths a `git commit` would write: the index, the index plus modified files for `-a`, or the named paths, after `--` or bare. It denies when a path is not claimed by this session's section of `.claude-session.md` (the basenames `history.md`, `TODO.md`, `CLAUDE.md`, `CLAUDE.local.md`, `bug-fix-queue.md` and the manifest itself are always allowed), or when a file is 10 MB or larger. `git_commit_match` is the shared "is this a git commit" matcher; `merge_head_guard` reuses it.
- **Allow cases for commit scope:** no manifest or no section for this session allows unless a file is large. A pathspec it cannot parse (bad quoting, globs, an unrecognised long option, a heredoc attached to the commit line) allows with a "NOT REVIEWED" notice. Write the message to a file and use `git commit -F <file> -- <paths>`.

## Escape hatches
- `stash_guard`: `LUPIN_ALLOW_GIT_STASH=1`, as an inline prefix on the command or in the hook's environment.
- `kill_guard`: `LUPIN_ALLOW_UNSCOPED_KILL=1`, inline or in the hook's environment.
- `merge_head_guard`: `LUPIN_ALLOW_MERGE_COMMIT=1`, inline or in the hook's environment. Its deny text warns against using it on a squash that is not yours.
- `commit_scope_guard`: `LUPIN_COMMIT_SCOPE_ACK=1` as an inline prefix on the `git commit` only; there is no environment read.
- `branch_lock_guard`: one operator flag read only from the hook's environment. An inline form is ignored, and the deny text does not name the flag. A seat has no way past it.

## When not to use
- These are accident-preventers, not a security boundary. Do not rely on them against deliberate evasion.
- To land work, merge by the usual route; do not commit around a live merge. Worktree handling is in [[worktree-lifecycle]].
