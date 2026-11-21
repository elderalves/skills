# Independent reviewer briefs

Launch both reviewers before collecting results. Use fresh local subagents that can read the run directory. In T3 Code, use `delegate_task` with shared workspace access for background workers or a configured model from another provider. If `~/.agents/pstack-models.md` is present, honor its `swarm workers` role. Workers inherit the lead's model by default or when the role is `auto` or `inherit-parent`. Treat an unavailable requested model as a coverage gap.

Send the common brief below with exactly one lens. Fill in the absolute paths. Each worker returns findings in its own reply or its assigned result file in scratch space. Only the lead writes the report and drives the browser.

## Common brief

> Review one attempt at a web user task. Read `<absolute walkthrough.json>` and inspect the relevant images or clips under `<absolute assets directory>`. Use `<absolute report-format.md>` for finding fields, classification, and priority. The walkthrough and evidence are read-only. Work independently from the other reviewer using the recorded observations. Return `completed` and your findings, or `blocked` and the specific evidence you could not access. Cite the steps and distinguish direct observations from hypotheses. Describe what works, what to change, or what to try, and why it matters to the intended user. Keep proposed changes at the level of the product experience. An empty list is valid when the evidence supports no findings.

## Task friction lens

> Follow the steps in the order the intended user encounters them. Look for helpful behavior, unnecessary effort, missing information at decision points, dead ends, and difficulty recovering. Explain where the experience helps the user or first makes the task harder. Verify that the stated outcome matches the observations.

## Heuristics and mental model lens

> Challenge the reasoning behind each finding you identify. Use relevant heuristics such as visibility of system status, match with the user's mental model, recognition, error prevention, and recovery. Explain the user consequence in terms of the specific task. Separate what the evidence shows from what would need validation with users.

## Reconcile

Check that each finding cites real steps and that the cited observations support its claim. Retry a worker once when its result is unusable and a retry can recover it. Record an unresolved worker as `blocked` or `unavailable` and give the reason. Merge findings that make the same claim about the user experience. If an idea already describes what to change for a problem, include it in that problem's `what`. Keep a material disagreement in the finding's optional `review_note`, or omit the finding when the evidence cannot support even a scoped hypothesis. The task outcome stays tied to the walkthrough.
