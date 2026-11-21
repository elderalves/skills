# Headway template mapping

## Project destination

Use the project's editable copy of [Headway’s Report Template](https://www.figma.com/design/kiyFIT7Jn7DD4I5QYHz9Y0/UX-Audit---Report-Template--Community-?node-id=17-1052). When a project is being set up, verify edit access through the Figma session and inspect the copy for the `Title Slide`, `General Slide`, and `Audit Slide` frames. Resolve the copy's layer IDs and typography from the file itself. The [worked report](https://www.figma.com/design/kiyFIT7Jn7DD4I5QYHz9Y0/UX-Audit---Report-Template--Community-?node-id=17-770) illustrates how the starter frames are used. If the user has only the Community original, ask for the link to an [editable duplicate](https://help.figma.com/hc/en-us/articles/360038510873-Duplicate-Community-files).

After verifying a newly supplied destination, save `{"fileUrl":"https://www.figma.com/design/<editable-file-key>/..."}` at `projectSetting` from the preparation output, when that path is present. Create the setting atomically if it is absent. If another invocation has saved a destination, read it back and use that file. Keep the Community files and the project's source frames as read-only inputs. Start from the supplied copy with its existing sharing settings.

## Report page and retries

- In the destination file, identify the report by the page's shared plugin data in namespace `uxauditreport`, key `runId`, using the exact value from preparation. Use key `state` with values `in-progress` and `complete`. A completed page with this identity supplies the result link even if someone has renamed or edited it.
- If no report exists, reserve a page named `UX audit — <runId>` using `$fig.page`. Set its identity and state, then read it back in a separate call before adding children. If a call's outcome is uncertain, look up the identity and exact reserved name before retrying. Finish marking a matching empty reserved page if creation stopped before its metadata was written. If multiple pages match or an unmarked match has content, report the conflict before writing.
- Load `figma:figma-generate-design` before visible mutations. Switch to the report page before creating children, clone the source frames into it with `$fig.clone`, and place the clones in reading order. Use stable item names or item metadata on the generated frames and upload targets, such as `Finding 1`, `Evidence · Step 6`, and `Step 6 screenshot`. Reuse those nodes on retry. Inspect existing fills before retrying an upload. Reconcile the generated frames with the current prepared run and preserve other content on the page.
- Use the destination file URL with `node-id` set to the report page ID for the result link. For findings, set editable text hyperlinks to their evidence frames by node ID. Verify the page and links after any call that returns an ambiguous result. Read the saved `complete` state back before reporting success.

## Field mapping

| Template frame | Content from the validation run |
|---|---|
| **Title Slide** | Use the section name and UX audit report title. Keep the template attribution and drop sample client branding unless the project supplies assets. |
| **General Slide** for summary | Show the task, intended user, scoped URL or section, and outcome status and observation. |
| **General Slide** for each finding | Keep the original order, title, P0–P3 priority, and observed or hypothesis label. Use `what` for the recommendation and `why` for the impact. Include `review_note` when present and add links for every distinct cited step. |
| **General Slide** for coverage | Include how the walkthrough was captured, coverage gaps, and reviewer statuses and notes. |
| **Audit Slide** for each cited step | Show its number, action, observation, and viewport when supplied. Place its screenshot and numbered callouts as described below. |

Keep the original frames' visual hierarchy and native styling. Use continuations when content exceeds the frame at a readable size. The finding recommendations supply the next steps. Omit placeholder sections for quotes, effort, owners, and dates when the run has no such data. For a valid run with zero findings, show the recorded outcome and coverage with a short “No findings recorded” note in the summary.

### Evidence appendix

Use one evidence frame per cited step. A step without a screenshot still gets a frame that the finding can link to. Use [the companion Audit Template example](https://www.figma.com/design/O1SbjGj1wzfCbR0mTx3HEt/UX-Audit---Template--Community-?node-id=17-772) for the screenshot, pin, and callout relationship. The original P0–P3 priorities and confidence labels carry the severity and certainty of the findings.

Upload each cited image using `upload_assets` on the report page, targeting its screenshot layer and using the prepared path and MIME type. If an image exceeds the connector's upload limit, optimize a temporary copy at the same aspect ratio. Fit each image inside the audit frame and use `alt` for its layer name or caption. Place each editable pin at the percentage `x` and `y` of the visible image bounds, accounting for any fit offset. Number the pins in source order and repeat each number next to its label. Check the smallest viewport on the canvas.

Show recorded clip captions with their step numbers. For a clip on a cited step, put the caption on that evidence frame. List any other clips together at the end. Refer readers to the corresponding step in the offline `report.html` for playback.
