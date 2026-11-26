# The diff review

The Council approved the Plan, and the run checked each task against it, but nothing independent has read the code. The **diff review** is that second brake: before the PR opens, the Council's three seats read the branch's diff cold, and `scripts/diff_gate.py` decides from their findings. Only a **clean** result lets the ready check promote the PR; any other result keeps it a draft, with the findings in the factory comment for the owner. The review never stops the run Blocked: the owner can judge a draft.

## Seats

The run's Council is the planning run's snapshot, `<work-dir>/council.json`. When it is missing (the Plan was made on another runner), resolve it again with `python ../alves-factory-run/scripts/council.py` as the planning run does ([config.md](../../alves-factory-run/references/config.md#council-targets)). Dispatch the seats exactly as `alves-factory-review` step 2 does: validate them with `orchestrator_capabilities` in T3 Code, start each with `delegate_task` (the harness's subagent tools elsewhere), full model ID and options as configured, and write the seats with the options actually sent to `diff-review-<N>/council.json`.

A seat that cannot run (disabled, unauthenticated, an unsupported option) is not substituted: record the exact problem and dispatch the others. Its missing review makes the pass **incomplete**.

## A pass

Pass `N` (`0`, then `1` after a fix) lives in `<work-dir>/implementation/diff-review-<N>/`.

1. Write `branch.diff`: `git diff <base commit>..HEAD` on the factory branch, where the base commit is the Plan's `base_commit` (the latest `base_branch` the branch was cut from, when the branch was rebased since).
2. Dispatch the three reviewers in parallel. Each prompt is, in order: [diff-reviewer-brief.md](diff-reviewer-brief.md), the line `Your lens: <lens>`, then the absolute paths of the work dir, the repo, `branch.diff`, its output file `diff-review-<N>/reviews/<lens>.json`, and on pass 1 the previous pass's `diff-review.json`. Reviewers of one pass never see each other's reviews.
3. Check the files with `python <skill-dir>/scripts/diff_gate.py <pass-dir>/reviews --check`. Re-dispatch a reviewer once, with its problems quoted, when its file is missing or has problems. A reviewer that fails twice keeps no file.
4. Decide: `python <skill-dir>/scripts/diff_gate.py <pass-dir>/reviews --council <pass-dir>/council.json --pass <N>`. It writes `<pass-dir>/diff-review.json`; copy it to `implementation/diff-review.json`, the file the ready check reads. Exit code `2` means the Council file is unusable: record the error, which leaves no `diff-review.json`, so the ready check keeps the draft.

## Acting on the result

- **clean**: go on to open the PR. Minor findings are not applied; list them in `verification.md` for the owner.
- **fix** (major findings on pass 0): dispatch a fresh subagent with [implementer-brief.md](implementer-brief.md), giving it the major findings as its task in place of a Plan task, and the **Files** blocks of the tasks they concern as its scope. A finding whose fix would change what the Plan builds or touch a file no task names is not fixed: record it as skipped, with why, and it stays for pass 1 to judge. Check the subagent's work as step 5 checks a task, run the full checks of step 6 again and update `verification.md` and `verification.json`, commit each fix as `fix(<upstream-ref>): review: <what>` per **Commit messages**, then run pass 1.
- **unresolved** (major findings on pass 1) or **incomplete**: go on to open the PR. It stays a draft, and the factory comment lists each reason under `Diff review:`.

One fix pass is the cap, as two CI fixes are: a branch that needs more needs the owner.
