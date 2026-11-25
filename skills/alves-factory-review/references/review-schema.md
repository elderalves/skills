# Plan review schema

The exact shape of one reviewer's output file. `gate.py` rejects a round with a malformed review, so a review that breaks these rules escalates the whole Plan.

```json
{
  "reviewer": "architecture",
  "provider": "anthropic",
  "model": "claude-opus-5-5",
  "scores": {
    "requirements": 90,
    "architecture": 82,
    "grounding": 95,
    "feasibility": 88,
    "testing": 85,
    "risk": 90
  },
  "rationale": {
    "requirements": "All three acceptance criteria map to tasks 1-3.",
    "architecture": "Task 2 adds a second retry helper beside src/http/retry.ts instead of reusing it.",
    "grounding": "Checked every path and both interfaces in the Plan; all exist as described.",
    "feasibility": "Tasks are ordered and independently verifiable; task 4 is large but coherent.",
    "testing": "Each task names its test; no check covers the timeout acceptance criterion.",
    "risk": "Rollback is a revert; no flags apply."
  },
  "verdict": "revise",
  "blockers": [],
  "issues": [
    {
      "criterion": "architecture",
      "problem": "Task 2 duplicates the existing retry helper.",
      "evidence": "src/http/retry.ts exports withRetry(fn, opts), used by 6 callers.",
      "fix": "Reuse withRetry and add the new backoff option there.",
      "minor": false
    }
  ],
  "risk_flags": [],
  "previous_issues": []
}
```

## Fields

- `reviewer`: your lens: `requirements`, `architecture` or `testing-risk`.
- `provider`: the provider of the model that wrote this review, in lowercase (`anthropic`, `openai`, `google`). Record the real provider, even when it substitutes for the lens's preferred one: the gate counts distinct providers.
- `model`: the model id that wrote this review.
- `scores`: an integer from 0 to 100 for every criterion key in the [rubric](rubric.md), no more and no fewer.
- `rationale`: one to three sentences of checked evidence per criterion.
- `verdict`, which `gate.py` checks against the lists below:
  - `approve`: implementable as written; every Issue is minor and `blockers` is empty.
  - `revise`: the planner can fix every problem; at least one Issue is not minor.
  - `escalate`: at least one Blocker.
- `blockers`: each `{question, why_owner, evidence}`. `question` is answerable by the owner in one reply; `why_owner` says why investigation cannot settle it.
- `issues`: each `{criterion, problem, evidence, fix, minor}`. `criterion` is a rubric key; `evidence` quotes or cites a file and line, the ticket, or the Plan; for something the Plan leaves out, cite the Plan section where it belongs and the ticket text or code that calls for it. `minor` is `true` when the fix would not change what gets built or how it is verified, per the [reviewer brief](reviewer-brief.md#blockers-and-issues).
- `risk_flags`: flags from the policy's list that the work carries but `PLAN.md` does not declare.
- `previous_issues`: on a revision, one `{issue, resolved, note}` per Issue in the previous `decision.json`; otherwise empty.
