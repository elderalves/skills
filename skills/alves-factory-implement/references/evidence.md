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

The PNGs go to the **evidence branch**, named after the factory branch plus `-evidence` (`factory/PCS-6132-evidence`, same case): an orphan branch in the project repo holding only screenshots, so the PR diff never carries them. Publish them with the script, never by hand:

```sh
python <skill-dir>/scripts/publish_evidence.py --checkout <checkout> --evidence-dir <work-dir>/implementation/evidence --branch <factory-branch> --message "<upstream-ref>: evidence screenshots" --repo <owner>/<repo> --account <account> --out <work-dir>/implementation/evidence.json
```

It builds the commit with git plumbing, which leaves the checkout's working tree, index and branch untouched; fetches the run's account's token itself ([config.md](../../alves-factory-run/references/config.md#github-account)); and pushes only a commit it built, so it can never delete the branch. After the push it reads the commit's tree back from GitHub and checks every file is there under its exact name and size. `evidence.json` then holds `{"commit", "branch", "images": {"<file>": "<url>"}}`.

- Exit 1 means the push or the read-back failed: a failure per **Failures** below, with the error it printed as the reason. Exit 2 means an input is unusable (no PNG, a file name that is not a slug), which also counts as a failure.
- A retried run stacks a commit on the existing evidence branch and never force-pushes; the PR body then points at the new commit.
- Each URL pins that commit's SHA, never the branch name, and renders for everyone who can see the repo, private ones included. The PR body copies them from `evidence.json` ([pr-body.md](pr-body.md)).
- The factory never deletes the evidence branch: the PR's images live on it. The owner may delete it after merge.
- In a dry run, the PNGs stay in `implementation/evidence/` and nothing is pushed.

## Failures

Screenshots are evidence, not the run's work: an app that will not start, a browser that crashes, or an evidence push that fails ends the capture, never the run. Stop any server you started, record the reason in `verification.md`, add it to `verification.json`'s `evidence.missing` (`"evidence push failed: <error>"` for a failed push), and go on. The PR body's Evidence then says `Screenshots unavailable: <reason>` above the test evidence, the Factory ticket's comment says the same, and the PR stays a draft ([ready-check.md](ready-check.md)).
