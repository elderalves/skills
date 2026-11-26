# The ready check

Every factory PR opens as a draft. The **ready check** decides, from facts a script reads, whether the run may **promote** it, that is mark it ready for the project team. A ready PR requests review from people who do not know the factory, so promotion needs every condition below; any one failing keeps the draft for the owner (ADR `docs/factory/adr/0002` in the skills repo).

## Conditions

1. The project's `pr_ready` is `auto` ([config.md](../../alves-factory-run/references/config.md)); `draft`, the default, never promotes.
2. The Council approved the Plan on its own: the last round's Gate decision is `implement`. A Plan the owner approved from an Escalation stays a draft.
3. The Plan carries no Risk flag of any tier, neither declared by the Plan nor added by a reviewer.
4. CI ran at least one check on the PR, and every check passed or was skipped. No CI means draft: nothing outside the factory verified the change.
5. CI was green on the first push: step 8 needed no fix commits.
6. With an Evidence block, every before and after screenshot was captured.
7. Every check the run executed passes on the branch, including one that already failed on the base branch.

Recorded deviations are allowed: each is a small correction the Plan clearly intended, and the PR body lists them for the reviewer.

## verification.json

Step 6 writes it beside `verification.md`, and step 8 sets `ci_fixes`:

```json
{
  "checks": [
    {"command": "yarn test", "result": "pass", "baseline": "pass"},
    {"command": "yarn build-storybook", "result": "fail", "baseline": "fail"}
  ],
  "deviations": ["scene AppProvider import corrected to ../../../AppProvider/AppProvider"],
  "ci_fixes": 0,
  "evidence": {"required": true, "missing": []}
}
```

- `checks`: every check step 6 ran, with `result` on the branch and `baseline` on the base branch (`pass`, `fail`, or `null` when it was not run there).
- `evidence.required` is true when the Plan has an Evidence block; `missing` names each capture not taken, with why.

## Running it

```sh
gh pr checks <pr> --json name,bucket > <work-dir>/implementation/checks.json
python <skill-dir>/scripts/ready.py --pr-ready <pr_ready> \
  --decision <work-dir>/implementation/decision.json \
  --verification <work-dir>/implementation/verification.json \
  --checks <work-dir>/implementation/checks.json \
  [--risk-flag <id> ...] --out <work-dir>/implementation/ready.json
```

Pass each Risk flag of the Plan's front matter as `--risk-flag`. A dry run leaves out `--checks`, and the result reports the local conditions. It prints `{"ready", "reasons"}`; the factory comment quotes the reasons. Exit 2 means an input is unusable: the PR stays a draft and the factory comment names the error.
