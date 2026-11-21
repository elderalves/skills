# Report input

`report.json` describes one run. Its parent directory is the run directory. Store referenced screenshots and clips under its `assets/` directory. The renderer writes `report.html` beside the input and embeds all referenced media. Python 3.10 or later is sufficient.

Write `"format_version": 2` in new `walkthrough.json` and `report.json` files, including runs with zero findings. Reports without `format_version` use the original format and display one priority-ordered list of findings.

```json
{
  "format_version": 2,
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
        "markers": [{
          "x": 78, "y": 22,
          "label": "The closed Filters button gives no date range.",
          "bounds": {"x": 73, "y": 20, "width": 10, "height": 4},
          "finding": 1
        }]
      }
    }
  ],
  "findings": [
    {
      "title": "The active date range is hard to confirm",
      "category": "improvement",
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

- **Outcome.** Use `completed` when the task goal was reached, `blocked` when an observed product issue stopped the task, or `not-tested` when a prerequisite or access gap prevented a meaningful attempt. Explain the outcome in `observation`. Include an observed strength there when it helps explain the outcome. An empty walkthrough requires `not-tested` and a coverage gap.
- **Steps.** Order steps by capture. Evidence references are one-based positions in this list. `viewport`, `image`, and `clip` are optional. Images accept PNG, JPEG, and WebP. An image can include [screenshot markers](#screenshot-markers). A `clip` has `file` and `caption` fields and accepts MP4 or WebM.
- **Findings.** Provide a title, `category`, `what`, `why`, `confidence`, and at least one cited step. Use `why` to explain the impact on the intended user. Use `observed` for directly demonstrated claims and `hypothesis` for inferred effects, including the anticipated benefit of an idea. Use `review_note` for a material disagreement if relevant. Keep `what` at the level of the product experience.
- **Takeaways.** When separate UX and UI takeaways help the reader, add an optional `takeaways` object with `ux` and `ui` strings. Ground both in the run's findings. Otherwise the task outcome supplies the summary.
- **Coverage.** Use `capture` to name the browser tool and explain any fallback. List parts of the task or evidence you could not cover in `gaps`. Each reviewer role has status `completed`, `blocked`, or `unavailable`. Include a `note` when the reviewer did not complete. Before dispatch, `walkthrough.json` uses `unavailable` and a note of `Review pending` for each role. Replace those states when writing `report.json`.

## Screenshot markers

- Record each marker's `label` and point `x` and `y` as percentages of the final saved screenshot, measured from its top-left corner.
- Add `bounds` when the UI area is visible and measurable in that image. Use `x`, `y`, `width`, and `height` as percentages of the full screenshot, with positive dimensions and the rectangle within the image. Clip partially visible targets to the captured area. For point-only evidence, omit `bounds`.
- Leave `finding` absent in `walkthrough.json` while the findings are being reconciled. In `report.json`, set it to the finding's one-based position in the final `findings` array when the marker directly supports that finding and the finding cites the step. For step context or an ambiguous association, set `finding` to `null`. Several markers can reference the same finding. Review the associations again if findings move or are merged.
- Older reports may omit both optional fields. The offline HTML displays the original numbered point and label for each marker. The Figma report uses the association and bounds to pair evidence cards with highlights.

## Finding categories

| `category` | Report group | When to use it | `what` label |
| --- | --- | --- | --- |
| `fix` | Needs to be Fixed | The current experience prevents reliable completion or creates a consequential error. An export silently omits rows. | What to change |
| `improvement` | Needs Improvement | The task remains reliably achievable with avoidable friction. The export button is hard to find, and the file it produces is correct. | What to change |
| `idea` | Ideas | The walkthrough suggests a distinct opportunity to try. A hard-to-reverse action suggests an opportunity to explore undo. | What to try |
| `good` | Good! | An observed behavior helps the intended user. A clear confirmation shows that a save succeeded. | What works |

Display the nonempty groups in table order. Within each problem group, sort by P0–P3 and keep source order for ties. Ideas and strengths keep source order. Every finding displays **Why it matters**, confidence, and evidence links. The proposed changes and ideas supply the next steps when the run supports them.

## Priority by user impact

Include `priority` on `fix` and `improvement` findings. Omit it on `idea` and `good` findings. Use the observed impact on the scoped task to rank problems within their category.

| Priority | When to use it |
| --- | --- |
| `P0` | Stops the scoped task with no observed path to completion. |
| `P1` | Creates a serious obstacle or consequential error in the scoped task. |
| `P2` | Adds avoidable effort, delay, or confusion on the way to completion. |
| `P3` | Causes minor friction with limited effect on the task outcome. |
