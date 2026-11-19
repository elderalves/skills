# Independent reviewer briefs

Launch both reviewers before collecting results. Use fresh local subagents that can read the run directory. In T3 Code, use `delegate_task` with shared workspace access for background workers or a configured model from another provider. If `~/.agents/pstack-models.md` is present, honor its `swarm workers` role. Workers inherit the lead's model by default or when the role is `auto` or `inherit-parent`. Treat an unavailable requested model as a coverage gap.

Send the common brief below with exactly one lens. Fill in the absolute paths. Each worker returns findings in its own reply or its assigned result file in scratch space. Only the lead writes the report and drives the browser.

## Common brief

> Review one attempt at a web user task. Read `<absolute walkthrough.json>` and inspect the relevant images or clips under `<absolute assets directory>`. Use `<absolute report-format.md>` for the finding fields and the priority scale. The walkthrough and evidence are read-only. Work independently from the other reviewer and use only the recorded observations for this review. Return `completed` and your findings, or `blocked` and the specific evidence you could not access. If no finding meets the evidence bar, return an empty list. Cite the step numbers and identify any user impact that is a hypothesis. Describe what should improve and why. Keep implementation details out of the recommendations.

## Task friction lens

> Follow the steps in the order the intended user encounters them. Look for unnecessary effort, missing information at decision points, dead ends, and difficulty recovering. Explain where the experience first makes the task harder. Verify that the stated outcome matches the observations.

## Heuristics and mental model lens

> Challenge the reasoning behind each issue you identify. Use relevant heuristics such as visibility of system status, match with the user's mental model, recognition, error prevention, and recovery. Explain the user consequence in terms of the specific task. Separate what the evidence shows from what would need validation with users.

## Reconcile

Check that returned findings cite real steps and that the cited observations support the claim. Retry a worker once when its result is unusable and a retry can recover it. Record an unresolved worker as `blocked` or `unavailable` and give the reason. Merge overlapping findings by the user problem and evidence. Keep a material disagreement in the finding's optional `review_note`, or omit the finding when the evidence cannot support even a scoped hypothesis. The task outcome stays tied to the walkthrough.
