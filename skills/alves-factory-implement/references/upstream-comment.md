# The concluding Upstream comment

The factory's only write to the Upstream ticket, posted once per implementation, when the PR is promoted: by the ready check at the end of the implementation run, or by a promotion run after the owner moves the ticket to Team Review ([trackers.md](../../alves-factory-run/references/trackers.md) names the operation per tracker). A PR that stays a draft gets no Upstream comment until then, so the team only ever hears of ready PRs. Its readers are the project team, who know the ticket but not the factory.

```markdown
PR: <PR url>
Before/after screenshots are in the PR.

What changed:
- <one line per user-visible or reviewer-relevant change, in the ticket's own terms>

Verification:
- <each check run, with its result: tests, lint, typecheck, CI status>

Worth a look in review:
- <assumptions or deviations a reviewer should confirm; omit this section when there are none>
```

- Plain text with `-` lists, no other markup: Jira through `acli` shows it as written.
- Keep it under twenty lines: the PR carries the detail, screenshots included. Leave out the screenshots line when the PR has none.
- Use the ticket's vocabulary, not the factory's: no Plan, Council, Gate decision, scores, Risk flags or Linear links.
- A retried run that updates an existing PR edits its earlier comment when the tracker allows it (the comment id the Factory ticket's comment recorded), and otherwise posts a new one saying what changed since.
- For a Native ticket (`linear`) or a `pasted` ticket there is no separate Upstream ticket: put this text in the Factory ticket comment instead, as one factory comment with the PR link and verification, whether the PR was promoted or stayed a draft.
