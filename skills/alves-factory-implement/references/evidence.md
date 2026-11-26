# Evidence screenshots

Before/after screenshots of what the change looks like, taken when the Plan has an **Evidence** block ([plan-format.md](../../alves-factory-plan/references/plan-format.md#sections)). A Plan without one gets none: its PR's Evidence is the test and command output.

## Capture

Run twice: **before** in step 5, right after the baseline checks, while the checkout is still at `base_branch`; **after** in step 6, once the full checks pass. Each time:

1. Start the app with the block's **Start** command as a background process and wait until its URL answers.
2. For each capture (for before, skip those marked **New**): emulate reduced motion (`agent-browser set media light reduced-motion`), so spinners and transitions hold still; open `<start-url><path>` at its viewport, perform its **Setup**, wait for the page's content, and save a PNG to `<work-dir>/implementation/evidence/<capture-slug>-before.png` or `-after.png`. Shoot the **Section** when the capture names one (from its first heading to the next one after it), the full page otherwise.
3. Stop the server, so the checkout is left as step 4 requires.
4. After the after captures, look at every after PNG next to its before. A render the change broke (raw markup, missing content, overlap, clipped text) is a failing check: fix it per step 6 and capture again.

**Tool.** `agent-browser`, per its skill. When it is not on `PATH`, Playwright: `npx playwright screenshot --viewport-size=<w>,<h> --full-page <url> <file>`, or a short Playwright script in `implementation/evidence/` for a capture with Setup (`npx playwright install chromium` when its browser is missing).

**Localhost only.** Open only URLs on the Start server. A capture path that leads anywhere else (a deployed, staging or signed-in site) is skipped and recorded: the PNGs land in the repo, so they may only show the repo's own fixtures.

Record every capture, taken or skipped with its reason, in `verification.md`.

## Evidence branch

The PNGs go to the **evidence branch**, named after the factory branch plus `-evidence` (`factory/PCS-6132-evidence`, same case): an orphan branch in the project repo holding only screenshots, so the PR diff never carries them. Build its commit with plumbing, which leaves the checkout's working tree, index and branch untouched:

```sh
cd <checkout>
tree=$(for f in <work-dir>/implementation/evidence/*.png; do
  printf '100644 blob %s\t%s\n' "$(git hash-object -w "$f")" "$(basename "$f")"
done | git mktree)
parent=$(GH_TOKEN=… git fetch origin <factory-branch>-evidence 2>/dev/null && echo "-p FETCH_HEAD")
commit=$(git commit-tree "$tree" $parent -m "<upstream-ref>: evidence screenshots")
GH_TOKEN=… git push origin "$commit:refs/heads/<factory-branch>-evidence"
```

- Push with the run's GitHub account, as every network command ([config.md](../../alves-factory-run/references/config.md#github-account)).
- A retried run adds a commit on top of the existing evidence branch (the `-p FETCH_HEAD` above) and never force-pushes; the PR body then points at the new commit.
- Link each image by that commit's SHA, never the branch name: `https://github.com/<owner>/<repo>/blob/<commit>/<file>?raw=true`. It renders for everyone who can see the repo, private ones included.
- The factory never deletes the evidence branch: the PR's images live on it. The owner may delete it after merge.
- In a dry run, the PNGs stay in `implementation/evidence/` and nothing is pushed.

## Failures

Screenshots are evidence, not the run's work: an app that will not start, a browser that crashes, or an evidence push that fails ends the capture, never the run. Stop any server you started, record the reason in `verification.md`, and go on. The PR body's Evidence then says `Screenshots unavailable: <reason>` above the test evidence, and the Factory ticket's comment says the same.
