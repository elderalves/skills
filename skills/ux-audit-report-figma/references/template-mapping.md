# Headway template mapping

## Project destination

Use the Figma destination explicitly supplied for the report, then the preparation output’s `destination` if set, then the **Templates** page of Headway’s UX Audit Report Template below. A missing `.ux/figma-report.json` uses the built-in default. The Audit Template supplies evidence layout examples.

Inspect the destination for `Title Slide`, `General Slide`, and `Audit Slide`. Resolve layer IDs and typography from that file, then check for the run’s report page. Figma adds “(Community)” to the names of duplicates too. Use Figma’s access status or the result of reserving the report page to determine write access. Keep the template pages and sharing settings intact.

### View-only destinations

When Figma confirms the destination is view-only, use a draft copy unless the user requires that specific destination. Follow the saving procedure below before duplicating the built-in Report Template into the signed-in user’s Drafts. Use Figma’s **Duplicate to drafts** action or its documented `/duplicate` URL with the query string removed. Read the new file URL from Figma, inspect its starter frames, and reserve or resume the report there. If a duplication result is unclear, check Drafts before retrying. If Figma prevents the required edit or duplication, report the access needed. [Figma’s duplication instructions](https://help.figma.com/hc/en-us/articles/360038511533-Duplicate-or-copy-files)

### Save the project destination

When `projectSetting` is present, save a verified project destination or a new draft copy there as `{"fileUrl":"https://www.figma.com/design/<file-key>/..."}`. Use the run lock procedure on the settings directory before creating a draft or saving a destination. Re-read the setting under that lock. If another invocation saved a destination, reuse it for the fallback. Save atomically when the setting is absent or still points to the destination Figma confirmed was view-only. A supplied override applies to the current run when the project already has a different working setting.

## Figma template links

| Template | Pages |
|---|---|
| UX Audit Template | [Introduction](https://www.figma.com/design/82aOK35i6UnifxgL5pFAtF/UX-Audit---Template--Community-?node-id=19-420&p=f&t=ravyLJU8mg8nTiGJ-0) · [Audit Example](https://www.figma.com/design/82aOK35i6UnifxgL5pFAtF/UX-Audit---Template--Community-?node-id=17-772) · [Components](https://www.figma.com/design/82aOK35i6UnifxgL5pFAtF/UX-Audit---Template--Community-?node-id=0-1&p=f&t=ravyLJU8mg8nTiGJ-0) |
| UX Audit Report Template | [Introduction](https://www.figma.com/design/0BZsJPlDkRJDvrLPLXDO1k/UX-Audit---Report-Template--Community-?node-id=19-420&p=f&t=WZQLrGTQByRw2ryp-0) · [Components](https://www.figma.com/design/0BZsJPlDkRJDvrLPLXDO1k/UX-Audit---Report-Template--Community-?node-id=0-1&p=f&t=WZQLrGTQByRw2ryp-0) · [Report Example](https://www.figma.com/design/0BZsJPlDkRJDvrLPLXDO1k/UX-Audit---Report-Template--Community-?node-id=17-770&p=f&t=WZQLrGTQByRw2ryp-0) · [Templates](https://www.figma.com/design/0BZsJPlDkRJDvrLPLXDO1k/UX-Audit---Report-Template--Community-?node-id=17-1052&p=f&t=WZQLrGTQByRw2ryp-0) |

## Report page and retries

- In the destination file, identify the report by the page's shared plugin data in namespace `uxauditreport`, key `runId`, using the exact value from preparation. Use key `state` with values `in-progress` and `complete`. A completed page with this identity supplies the result link even if someone has renamed or edited it.
- If no report exists, reserve a page named `UX audit — <runId>` using `$fig.page`. Set its identity and state, then read it back in a separate call before adding children. If a call's outcome is uncertain, look up the identity and exact reserved name before retrying. Finish marking a matching empty reserved page if creation stopped before its metadata was written. If multiple pages match or an unmarked match has content, report the conflict before writing.
- Load `figma:figma-generate-design` before visible mutations. Switch to the report page before creating children, clone the source frames into it with `$fig.clone`, and place the clones in reading order. Use stable item names or item metadata on the generated frames and upload targets, such as `Finding 1`, `Evidence · Step 6`, and `Step 6 screenshot`. Reuse those nodes on retry. Inspect existing fills before retrying an upload. Reconcile the generated frames with the current prepared run and preserve other content on the page.
- Use the destination file URL with `node-id` set to the report page ID for the result link. For findings, set editable text hyperlinks to their evidence frames by node ID. Verify the page and links after any call that returns an ambiguous result. Read the saved `complete` state back before reporting success.

## Field mapping

| Template frame | Content from the validation run |
|---|---|
| **Title Slide** | Use the section name and UX audit report title. Keep the template attribution and drop sample client branding unless the project supplies assets. |
| **General Slide** for summary | Show the task, intended user, scoped URL or section, and outcome status and observation. Include the prepared `takeaways` when present, using their supplied headings. |
| **General Slide** for each finding | Walk `findingGroups` in order. Keep each group together and use its `heading` as a section title on its first slide. A null heading uses **Findings**. Show each finding's title, priority when present, and **Observed** or **Hypothesis** label. Use the group's `whatLabel` for `what` and **Why it matters** for `why`. Include `review_note` when present and link every distinct cited step. |
| **General Slide** for coverage | Include how the walkthrough was captured, coverage gaps, and reviewer statuses and notes. |
| **Audit Slide** for each cited step | Show its number, action, observation, and viewport when supplied. Place its screenshot and numbered callouts as described below. |

Keep the original frames' visual hierarchy and native styling. Use continuations when content exceeds the frame at a readable size. Name each finding frame `Finding <number>` using the prepared finding's source `number`, even when display order differs. The problem and idea cards supply next steps when supported by the run. Omit placeholder sections for quotes, effort, owners, and dates when the run has no such data. When `findingGroups` is empty, show the recorded outcome and coverage with a short “No findings recorded” note in the summary.

### Evidence appendix

Use one evidence frame per cited step. A step without a screenshot still gets a frame that the finding can link to. Use the [Audit Example](#figma-template-links) for the screenshot, pin, and callout relationship. P0–P3 priorities carry problem severity, and confidence labels show whether a claim is observed or inferred.

Upload each cited image using `upload_assets` on the report page, targeting its screenshot layer and using the prepared path and MIME type. If an image exceeds the connector's upload limit, optimize a temporary copy at the same aspect ratio. Fit each image inside the audit frame and use `alt` for its layer name or caption. Place each editable pin at the percentage `x` and `y` of the visible image bounds, accounting for any fit offset. Number the pins in source order and repeat each number next to its label. Check the smallest viewport on the canvas.

Show recorded clip captions with their step numbers. For a clip on a cited step, put the caption on that evidence frame. List any other clips together at the end. Refer readers to the corresponding step in the offline `report.html` for playback.
