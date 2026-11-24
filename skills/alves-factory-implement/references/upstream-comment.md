# The concluding Upstream comment

The factory's only write to the Upstream ticket, posted once per implementation, after the draft PR exists and its CI is green or absent ([trackers.md](../../alves-factory-run/references/trackers.md) names the operation per tracker). Its readers are the project team, who know the ticket but not the factory.

```markdown
Draft PR: <PR url>

**What changed**
- <one line per user-visible or reviewer-relevant change, in the ticket's own terms>

**Verification**
- <each check run, with its result: tests, lint, typecheck, CI status>

**Worth a look in review**
- <assumptions or deviations a reviewer should confirm; omit this section when there are none>
```

- Keep it under twenty lines: the PR carries the detail.
- Use the ticket's vocabulary, not the factory's: no Plan, Council, Gate decision, scores, Risk flags or Linear links.
- A retried run that updates an existing PR edits its earlier comment when the tracker allows it (`addOrEditJiraIssueComment` with the `commentId`), and otherwise posts a new one saying what changed since.
- For a `pasted` ticket there is no Upstream ticket: put this text in the Factory ticket comment instead.
