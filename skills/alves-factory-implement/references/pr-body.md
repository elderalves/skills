# The PR body

Write it with the `pr` skill: load it and follow its template and section guidance, with the factory overrides below. Its readers are the project team, who know the ticket but not the factory. Save it to `<work-dir>/implementation/pr-body.md` and pass it with `--body-file`.

## Overrides to `pr`

- **First line**, above `## Summary`: `Upstream: <Upstream ticket link>`. A Native or `pasted` ticket has no Upstream link: leave the line out.
- **Glossary**: the `pr` skill's `GLOSSARY.md` is the project repo's, when it has one; the factory's glossary never reaches the body.
- **Summary**: the smallest visual that shows the change, drawn from the Plan's Goal, Architecture and File Structure.
- **Evidence**: screenshots first, then execution evidence.
  - For each capture of the Plan's Evidence block ([evidence.md](evidence.md)), its name and viewport, then a two-column table:

    ```markdown
    **Outline appearances** (1280×800)

    | Before | After |
    |---|---|
    | _new page_ | ![Outline appearances, after](<images["outline-appearances-after.png"] from evidence.json>) |
    ```

    Copy each image URL exactly from `evidence.json`'s `images` ([evidence.md](evidence.md#evidence-branch)); never write one by hand, since the ready check keeps the PR a draft for any image it does not find there. A **New** capture's Before cell is `_new page_`; a capture skipped on either side says why in its cell.
  - When capture failed: `Screenshots unavailable: <reason>` in place of the tables.
  - Then the execution evidence from `verification.md`: the test that pins the main behaviour, failing on `base_branch` and passing on the branch, and the full checks with their counts.
- **Merge Danger**:
  - **Door** comes from the Plan's **Risks and rollback** and `risk_flags`: one-way when a revert does not undo the change (a data migration, a removed public contract, a destructive operation), two-way otherwise.
  - **Blast Radius** names the surface the diff touches (`Storybook docs`, `checkout API`).
  - Its description carries what a reviewer should confirm: the Assumptions and Review Focus items worth their attention, and every recorded deviation.

## Leave out

The task list (the commits carry it), Linear links, Council scores, Gate decisions, Risk-flag ids (say what the risk is in plain words) and work-dir paths.
