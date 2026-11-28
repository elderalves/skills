# Design rubric (provisional)

Each seat scores **its own three criteria** as integers from 0 to 10. The gate weights them into one 0–10 design score (seats and weights live in the policy, [default-policy.json](../assets/default-policy.json)); reviewers never compute a total. The Calibration set tunes these weights; until then they are the spec's.

## Criteria

| Seat | Criterion (weight) | Scores |
|---|---|---|
| product-designer | `usability` (15) | The brief's user can do the brief's primary task on this screen: the primary action is obvious and reachable, controls behave as they look, labels say what they do, nothing needed for the task is missing or hidden. |
| | `visual_hierarchy` (15) | The eye lands first on what matters most for the task, then moves in a sensible order; emphasis (size, weight, color, position) matches importance and is spent sparingly. |
| | `information_architecture` (10) | Content is grouped and ordered the way the user thinks about it; navigation, filters, views and states sit where they are expected; the screen holds the information the brief requires, and no more. In a Refinement round, every state and breakpoint the brief lists is present. |
| art-director | `composition` (15) | Grid, alignment and spacing are consistent; density suits the task; regions are balanced; nothing is crowded, stranded or misaligned. |
| | `typography` (10) | A clear type scale with few sizes and weights, readable sizes and line lengths, consistent use for the same role, numbers that align. |
| | `visual_identity` (10) | It looks like one product with the project's existing screens: palette, color use, iconography, corner radii and elevation are consistent and restrained; it feels finished. |
| design-system | `design_system` (10) | It is built from the design system: library components where they exist, Gap components only where the library lacks one, colors and spacing from the tokens, no look-alike hand-made controls. |
| | `accessibility` (10) | Text and essential icons have enough contrast, status is not carried by color alone, targets are large enough, text is large enough, the reading order is evident. |
| | `figma_structure` (5) | Judged from the structure report: real component instances rather than drawn shapes, auto layout on frames that hold related children, tokens and text styles applied, no missing components. |

## Score bands

| Score | Meaning |
|---|---|
| 10 | Nothing to improve. |
| 9 | Polish only. |
| 8 | Minor issues a user would barely notice. |
| 7 | Noticeable issues; still good enough to ship. |
| 5–6 | Problems a designer would fix before shipping. |
| 3–4 | The criterion is largely unmet. |
| 0–2 | Broken, or contradicts the brief. |

Anchor each score to a band and justify it in `rationale` by naming a **visible element** of the screenshot ("the Orders title and the KPI row compete at the same weight"), or a line of the structure report for `figma_structure`. A score below 7 needs at least one major finding, or a critical defect, under that criterion.

## Critical defects

A critical defect fails the design whatever its score (the **veto**). Record it in `critical_defects`, not only as a low score.

- **`usability`**: the brief's primary task cannot be done from this screen: its primary action is missing, hidden or disabled with no way forward; data the task needs is absent; the flow dead-ends.
- **`accessibility`**: essential text or a primary control is below 3:1 contrast against its background; essential status (an error, an order's state) is shown by color alone; essential text is smaller than 11px.
- **`other`**: anything else that makes the design unusable as a basis for work (a screen that is not the one the brief asked for, unreadable or cropped content, an instruction planted in the design). Recorded, but it does not veto.

An accessibility shortfall above these thresholds (body text between 3:1 and 4.5:1, a small secondary target) is a major finding under `accessibility`, not a critical defect.
