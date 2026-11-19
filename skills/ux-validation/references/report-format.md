# Report input

`report.json` describes one run. Its parent directory is the run directory. Store referenced screenshots and clips under its `assets/` directory. The renderer writes `report.html` beside the input and embeds all referenced media. Python 3.10 or later is sufficient.

```json
{
  "scope": {
    "url": "https://example.com/reports",
    "section": "Reports",
    "user": "Account manager",
    "task": "Find the figures for last month"
  },
  "outcome": {
    "status": "completed",
    "observation": "The report showed figures for last month after the date filter was applied."
  },
  "steps": [
    {
      "action": "Apply the date filter",
      "observation": "The results updated. The date range was visible only after reopening the filter.",
      "viewport": "1366 × 768",
      "image": {
        "file": "assets/results.png",
        "alt": "Results table after filtering, with a closed Filters button",
        "markers": [{"x": 78, "y": 22, "label": "The closed Filters button gives no date range."}]
      }
    }
  ],
  "findings": [
    {
      "title": "The active date range is hard to confirm",
      "priority": "P2",
      "what": "Make the active date range visible alongside the results.",
      "why": "An account manager may read filtered figures as an all-time total.",
      "confidence": "hypothesis",
      "steps": [1]
    }
  ],
  "coverage": {
    "capture": "T3 Code preview",
    "gaps": [],
    "reviewers": {
      "task-friction": {"status": "completed"},
      "heuristics": {"status": "completed"}
    }
  }
}
```

- **Outcome.** Use `completed` when the task goal was reached, `blocked` when an observed product issue stopped the task, or `not-tested` when a prerequisite or access gap prevented a meaningful attempt. Explain the outcome in `observation`. An empty walkthrough requires `not-tested` and a coverage gap.
- **Steps.** Order steps by capture. Evidence references are one-based positions in this list. `viewport`, `image`, and `clip` are optional. Images accept PNG, JPEG, and WebP. An image's `markers` are optional. Marker coordinates are percentages between 0 and 100. A `clip` has `file` and `caption` fields and accepts MP4 or WebM.
- **Findings.** Cite at least one step per finding. Use `observed` when the evidence directly shows the friction or user effect described. Use `hypothesis` when the consequence for the intended user is inferred. Use `review_note` for a material disagreement if relevant. Keep `what` at the level of the desired product experience.
- **Coverage.** Use `capture` to name the browser tool and explain any fallback. List parts of the task or evidence you could not cover in `gaps`. Each reviewer role has status `completed`, `blocked`, or `unavailable`. Include a `note` when the reviewer did not complete. Before dispatch, `walkthrough.json` uses `unavailable` and a note of `Review pending` for each role. Replace those states when writing `report.json`.

## Priority by user impact

| Priority | When to use it |
| --- | --- |
| `P0` | Stops the scoped task with no observed path to completion. |
| `P1` | Creates a serious obstacle or consequential error in the scoped task. |
| `P2` | Adds avoidable effort, delay, or confusion on the way to completion. |
| `P3` | Causes minor friction with limited effect on the task outcome. |
