---
name: ux-validation
description: Validate the UX of one task in a running web app. Use for scoped usability reviews that need a live walkthrough, independent review, and an offline HTML report of evidence-backed strengths, problems, and ideas.
---

# UX validation

1. **Scope one task.** Resolve the app URL, section, intended user, and task from the request and project context. Ask for missing details only when they would change the walkthrough. Use the target project's root for output, or the current project for a URL-only review. Create a unique run directory under `.ux/validation/` and an `assets/` directory inside it. Read the [report format](references/report-format.md) before capturing evidence.
2. **Walk the task once.** Follow the [browser walkthrough](references/browser-walkthrough.md). Own the browser session and record the actions, observed states, and task outcome. Attempt ordinary in-scope interactions with approved data and leave application files untouched. Save the evidence and an initial report input, with an empty findings list, as `walkthrough.json`. Record limitations as coverage gaps.
3. **Dispatch both reviewers in parallel.** Read the [reviewer briefs](references/reviewer-briefs.md). Give each reviewer the same walkthrough and assets by absolute path. Give each a separate result, and wait for both terminal responses. Record completion, blocked access, or unavailable dispatch for each reviewer. If a reviewer is unavailable, use that lens yourself where the evidence allows and disclose the gap in independent coverage. If there are no steps to review, record that in both reviewer notes and proceed to rendering.
4. **Reconcile and render.** Check each finding against the walkthrough. Merge duplicates, keep material disagreements visible, and assign each finding a category using the report format. Rank problems by user impact and distinguish direct observations from hypotheses. Save the categorized result as `report.json` in the run directory and render it with this command.

   ```sh
   python3 <skill-dir>/scripts/render_report.py <run-dir>/report.json
   ```

   Resolve both placeholders to actual paths. Fix any input error the renderer reports. Confirm `report.html` exists, the finding groups and card labels match the report format, and each finding links to its evidence. If you captured media, check that it displays and the clips play. Link the report and summarize the task outcome, key findings, and coverage gaps. When the user asks to see the report in T3, use `html_preview` and `html_render`.
