# Headway template mapping

## Project destination

Use the Figma destination explicitly supplied for the report, then the preparation output’s `destination` if set, then the **Templates** page of Headway’s UX Audit Report Template below. A missing `.ux/figma-report.json` uses the built-in default.

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

## Native finding components

Use Headway's [Presentation Mobile example](https://www.figma.com/design/0BZsJPlDkRJDvrLPLXDO1k/UX-Audit---Report-Template--Community-?node-id=17-866) for the screenshot and comment layout. Its `Comment` instances supply the tinted card background and category styling. Each matching `zone` overlays an area of the screenshot and carries the same number. Use the standalone `indicator` component for point highlights.

Resolve the three component sets on the destination's **Components** page or from its linked library. Inspect the actual component names and variant properties and use the resolved IDs or keys. For Headway's built-in template, set `state` as follows.

| Prepared `category` | Report label | `Comment` state | `zone` and `indicator` state |
| --- | --- | --- | --- |
| `fix` | Needs to be Fixed | `fixed` | `fix` |
| `improvement` | Needs Improvement | `improvement` | `improvement` |
| `idea` | Idea | `idea` | `idea` |
| `good` | Good! | `good` | `good` |

Instantiate the matching variant with `$fig.instance` or reuse the matching instance from a cloned template frame. Preserve the instance, its nested indicator, and its template fills, strokes, and text styles. Inspect the variant's title, body, and number text layers and use text overrides. Load the fonts on any text ranges you edit through the Plugin API. Priority drives the P0–P3 badge and order within a problem group. Category drives the state of the card and highlight. For older findings without a recorded category, use the neutral finding layout and retain the recorded priority. If a required template variant is unavailable, identify the missing component and leave the report resumable.

## Field mapping

| Template frame | Content from the validation run |
|---|---|
| **Title Slide** | Use the section name and UX audit report title. Keep the template attribution and drop sample client branding unless the project supplies assets. |
| **General Slide** for summary | Show the task, intended user, scoped URL or section, and outcome status and observation. Include the prepared `takeaways` when present, using their supplied headings. |
| **General Slide** for each finding | Walk `findingGroups` in order. Keep each group together and use its `heading` as a section title on its first slide. A null heading uses **Findings**. Use the native category `Comment` for the finding title and a short description, and set its indicator to the source finding number. Show priority when present and **Observed** or **Hypothesis**. Use the group's `whatLabel` for `what` and **Why it matters** for `why`. Keep the full `what` and `why` available on the slide, showing `what` once if it already fits as the card description. Include `review_note` when present and link every distinct cited step. |
| **General Slide** for coverage | Include how the walkthrough was captured, coverage gaps, and reviewer statuses and notes. |
| **Audit Slide** for each cited step | Show its number, action, observation, and viewport when supplied. Put evidence cards beside the screenshot and numbered highlights over it as described below. |

Keep the original frames' visual hierarchy and native styling. Use continuations when content exceeds the frame at a readable size. Name each finding frame `Finding <number>` using the prepared finding's source `number`, even when display order differs. The problem and idea cards supply next steps when supported by the run. Omit placeholder sections for quotes, effort, owners, and dates when the run has no such data. When `findingGroups` is empty, show the recorded outcome and coverage with a short “No findings recorded” note in the summary.

### Evidence appendix

1. Use one evidence frame per cited step, with continuations for overflow. Keep the step frame for text-only evidence too. Upload each cited image using `upload_assets` on the report page, targeting its screenshot layer and using the prepared path and MIME type. If an image exceeds the connector's upload limit, optimize a temporary copy at the same aspect ratio. Fit the full image and use `alt` for its layer name or caption.
2. Resolve marker associations within the step's prepared `findingNumbers`, which reference the source `number` in `findingGroups`. An integer `marker.finding` is the recorded association. `null` records step context. If the field is absent, compare the marker label and screenshot against the citing findings and pair it only when the label uniquely identifies the UI and observation described by one finding. A citation or matching category by itself is insufficient. Keep markers without a unique categorized finding as neutral numbered callouts with their original labels and positions.
3. Replace the cloned Audit Slide's sample comments. Place one editable `Comment` beside the screenshot for each associated finding, with its title and the associated marker labels. Assign numbers in first marker order, sharing a number between all highlights for that finding on the step. Give each neutral callout its own number. Key the cards by step and finding number, and key the overlays by step and marker position in the source list, so retries can reuse the intended layers. Replace obsolete generated cards or markers on in-progress pages when their mapped component changes.
4. Map percentages to the visible image rectangle after fitting. For each paired marker with `bounds`, place the matching `zone` at `imageLeft + bounds.x / 100 * imageWidth` and `imageTop + bounds.y / 100 * imageHeight`, using the same scale for the rectangle's width and height. Resize the zone to those dimensions while preserving its indicator styling. For a paired point-only marker, center the matching `indicator` at the recorded `x` and `y` using the same transform. Override the indicator text to match the evidence card number.
5. Keep a card and its highlights together on any continuation. Repeat the screenshot where a continuation needs its own overlays. Link the grouped finding to the frame containing its paired evidence when available, otherwise to the step's primary evidence frame. Link continuations from the primary frame.

Show recorded clip captions with their step numbers. For a clip on a cited step, put the caption on that evidence frame. List any other clips together at the end. Refer readers to the corresponding step in the offline `report.html` for playback.

## Report checks

- Read back the page. Check group order, card labels, priority badges, and that each finding and cited step is present. Check the component ancestry and `state` of each categorized `Comment`, `zone`, and `indicator` against the mapping. Inspect the visible nested `_comment` fill for each category used.
- For every marker, check its source association, geometry, and displayed number against the card or neutral callout beside the screenshot. Check that paired cards and highlights share their number and match the finding category. Verify each finding link resolves to the intended evidence frame or continuation, including steps without screenshots.
- Inspect screenshots of the cover, the longest finding slide, and an annotated evidence frame when present. Check that the images are visible, overlays are aligned and readable at the smallest recorded viewport, and no sample cards or template copy remain in the report.
