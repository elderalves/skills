# The ready check

Every factory PR opens as a draft. The **ready check** decides, from facts a script reads, whether the run may **promote** it, that is mark it ready for the project team. A ready PR requests review from people who do not know the factory, so promotion needs every condition below; any one failing keeps the draft for the owner (ADR `docs/factory/adr/0002` in the skills repo).

## Conditions

1. The project's `pr_ready` is `auto` ([config.md](../../alves-factory-run/references/config.md)); `draft`, the default, never promotes.
2. The Council approved the Plan on its own: the last round's Gate decision is `implement`. A Plan the owner approved from an Escalation stays a draft.
3. The Plan carries no Risk flag of any tier, neither declared by the Plan nor added by a reviewer.
4. CI ran at least one check on the PR, and every check passed or was skipped. No CI means draft: nothing outside the factory verified the change.
5. CI was green on the first push: step 9 needed no fix commits.
6. With an Evidence block, every before and after screenshot was captured and published. Every image the PR body shows is one `publish_evidence.py` verified on GitHub ([evidence.md](evidence.md#evidence-branch)), so a link that would render broken keeps the draft.
7. Every check the run executed passes on the branch, including one that already failed on the base branch.
8. The independent **diff review** ([diff-review.md](diff-review.md)) is **clean**: every seat reviewed the diff and no major finding remains. An unresolved finding, a missing or malformed review, or no diff review at all keeps the draft.
9. The run kept to its own process: `verification.json` records no **process deviation**, such as a task written in-session because its subagent could not start.

Recorded deviations are allowed: each is a small correction the Plan clearly intended, and the PR body lists them for the reviewer.

## verification.json

Step 6 writes it beside `verification.md`, the diff review's fix pass updates it, and step 9 sets `ci_fixes`:

```json
{
  "checks": [
    {"command": "yarn test", "result": "pass", "baseline": "pass"},
    {"command": "yarn build-storybook", "result": "fail", "baseline": "fail"}
  ],
  "deviations": ["scene AppProvider import corrected to ../../../AppProvider/AppProvider"],
  "process_deviations": [],
  "ci_fixes": 0,
  "evidence": {"required": true, "missing": []}
}
```

- `checks`: every check step 6 ran, with `result` on the branch and `baseline` on the base branch (`pass`, `fail`, or `null` when it was not run there).
- `process_deviations` (required): one sentence for each time the harness forced the run off its own process (step 5 of the skill), `[]` when there was none. A task written in-session because its subagent could not start belongs here, never in `deviations`, which are corrections to the Plan. The ready check refuses a file without this key.
- `evidence.required` is true when the Plan has an Evidence block; `missing` names each capture not taken, and a failed evidence push, with why.

## Running it

```sh
gh pr checks <pr> --json name,bucket > <work-dir>/implementation/checks.json
```

```sh
python <skill-dir>/scripts/ready.py --pr-ready <pr_ready> --decision <work-dir>/implementation/decision.json --verification <work-dir>/implementation/verification.json --diff-review <work-dir>/implementation/diff-review.json --checks <work-dir>/implementation/checks.json --pr-body <work-dir>/implementation/pr-body.md --evidence <work-dir>/implementation/evidence.json [--risk-flag <id> ...] --out <work-dir>/implementation/ready.json
```

Pass each Risk flag of the Plan's front matter as `--risk-flag`. Leave out `--diff-review` only when the review left no `diff-review.json`; the result then says no diff review ran. `--pr-body` is required with `--checks`. Leave out `--evidence` only when no screenshots were published; any image in the body then keeps the draft. A dry run leaves out `--checks`, `--pr-body` and `--evidence`, and the result reports the local conditions. It prints `{"ready", "reasons"}`; the factory comment quotes the reasons. Exit 2 means an input is unusable: the PR stays a draft and the factory comment names the error.
