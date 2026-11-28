# Design review schema

The exact shape of one reviewer's output file, `reviews/<design>/<seat>.json`. `design_gate.py --check` rejects a review that breaks these rules, and the gate marks a round with one `invalid`.

```json
{
  "seat": "product-designer",
  "design": "B",
  "provider_instance": "claudeAgent",
  "model": "claude-opus-5-5",
  "screens_viewed": ["screens/B/desktop.png"],
  "scores": {
    "usability": 8,
    "visual_hierarchy": 6,
    "information_architecture": 8
  },
  "rationale": {
    "usability": "The New order button sits top right in primary blue; filters and search are one click away above the table.",
    "visual_hierarchy": "The four KPI cards use the same weight as the page title, so the eye has no first stop.",
    "information_architecture": "Views sit as tabs above the filters, matching the brief's saved-views model."
  },
  "critical_defects": [],
  "findings": [
    {
      "criterion": "visual_hierarchy",
      "severity": "major",
      "element": "KPI cards row",
      "problem": "The KPI values (24px bold) outweigh the page title, pulling attention from the orders table.",
      "fix": "Drop the KPI values to 20px and keep the title the heaviest element."
    }
  ],
  "strengths": ["Status reads at a glance from the colored dot and label in each row."]
}
```

## Fields

- `seat`, `design`: your seat and the design's id, exactly as given. They must match the file's path.
- `provider_instance`, `model`: the connection and model your seat dispatched you through, exactly as supplied. The gate marks a review from any other seat `council-mismatch`.
- `screens_viewed`: the path of every screen you were given, as written in your prompt, once you have looked at it.
- `scores`: an integer from 0 to 10 for each of **your seat's** criteria in the [rubric](rubric.md), no more and no fewer.
- `rationale`: per criterion, one to three sentences naming the visible element the score rests on.
- `critical_defects`: each `{category, element, problem}`, with `category` one of `usability`, `accessibility` or `other`, per the [rubric](rubric.md#critical-defects). Optional `evidence` (a measured contrast, a pixel size).
- `findings`: each `{criterion, severity, element, problem, fix}`. `criterion` is any rubric key (usually one of yours); `severity` is `major` when the fix changes the design (layout, hierarchy, component choice, content, flow) and `minor` for polish. `fix` is one or two sentences.
- `strengths`: what works and should survive any revision, one sentence each (may be empty).
