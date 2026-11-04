# Set B worked examples: same job or not

For Set B reviewers. Read it once before you start; it adds no rules to the instructions you already have. It shows how the rule table applies to the kinds of pair that split two reviewers on Set A. The Set A labels and the third rater's instructions are unchanged.

**Status: ruled by Rick on 31 October 2026.**

## The question

Would a caller who wanted what A gives be satisfied by B, perhaps after a small change such as an extra option or parameter? What counts is what the caller gets, not how alike the code looks.

## The rules these cases lean on

| Rule | Reads |
|---|---|
| Rule A | Same result on a different target, where the target could be a parameter: **Same job** |
| Rule B | Same result by different code: **Same job** |
| Rule C | Opposite things to the same thing: **Not the same job** |
| Rule D | Different data or a different result, even with the same plumbing: **Not the same job** |
| Rule E | Leaves state the caller depends on: **Not the same job** |

## The cases

Forty of the 47 Set A disputes were confident ones: neither reviewer marked unsure. Each reviewer simply read the pair differently. Twenty-five of the 47 were flags, so flags come first here.

| Case | Pair | Group | Reviewer A said | Reviewer B said | Ruled answer | Rule |
|---|---|---|---|---|---|---|
| 2 | pair-4875aab5d6 | flag | Not the same job | Same job | Not the same job | Rule D |
| 3 | pair-2592fb1df4 | flag | Same job | Not the same job | Not the same job | Rule D |
| 4 | pair-4f3668bf20 | monolith | Not the same job | Same job | Same job | Rule A |

### Case 2: error log and debug log (flag)

Both write a line to the console and to the panel. `error` always writes, as an error. `log` writes as information and does nothing when debugging is off. A caller who wants an error shown gets nothing from `log`. **Different result: Rule D.** Shared plumbing is not a shared job.

### Case 3: delegate a fix and execute an assigned job (flag)

Both call the agent SDK. `_delegate_to_coder` returns a pair: the coder's output and the files it changed. `execute_assigned_job` runs a whole job and returns a dict. The setup code is alike; what each hands back is not. **Rule D.**

### Case 4: stop one timer and stop another (monolith)

Each stops a repeating timer, clears its handle and does nothing if it is not running. Only the timer differs, and the timer could be a parameter. **Rule A: Same job**, even though the two stop different things. Cases 2 and 4 look alike and differ on the answer. In case 4 the caller gets the same result on another target. In case 2 the result itself differs.

## How to use the call sites

Each Set B item shows up to five places where the key symbol is called. Read one before you answer. If the next step at that call site still works with the other function, that is the swap test passed.
