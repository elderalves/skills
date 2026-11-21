---
name: ux-audit-report-figma
description: Turn a completed UX validation run directory into an editable Figma audit report using Headway’s Report Template. Use when asked to generate a Figma report from a `/ux-validation` run.
---

# UX audit report in Figma

`/ux-audit-report-figma <run-directory>` produces one editable report page and returns its Figma link. Headway’s Report Template is built in. A project can provide its own destination.

1. **Prepare the run.** Run `python3 -B <skill-dir>/scripts/prepare_report.py <run-directory>` with the paths resolved. Use its JSON for the report, destination, and evidence uploads. Report input errors before making Figma writes. Read [Project destination](references/template-mapping.md#project-destination) to resolve an explicit destination, a saved project destination, or the built-in report template in that order.
2. **Find or reserve the report page.** Load `figma:figma-use` and start a Figma session on the destination. In a live shell PTY, run `flock -w 20 -E 75 -- <resolved-run-directory> sh -c 'echo locked; exec cat'`. Wait for `locked` before writing to Figma and wait again on exit 75. Hold the PTY until Figma work ends and release it with Ctrl+C. Follow the [page and retry procedure](references/template-mapping.md#report-page-and-retries). If the page is complete, return its link without writing to Figma. If Figma confirms the destination is view-only, follow the [draft copy procedure](references/template-mapping.md#view-only-destinations) and continue there.
3. **Populate the report.** Resolve Headway's native `Comment`, `zone`, and `indicator` variants using the [component mapping](references/template-mapping.md#native-finding-components). Clone the template frames and follow the [field and evidence mapping](references/template-mapping.md#field-mapping). Reconcile the page against the run on each attempt. Pair the cards and screenshot highlights in the appendix, then link the grouped findings to their evidence frames.
4. **Verify and return.** Follow the [report checks](references/template-mapping.md#report-checks), including native variants, matching card and highlight numbers, and evidence link targets. Mark the page complete only after those checks, then release the lock and return its direct link. If interrupted or blocked, leave the page resumable, release the lock, and identify the missing step or access needed.
