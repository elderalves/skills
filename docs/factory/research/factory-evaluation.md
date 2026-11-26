# Alves factory: evaluation and improvement plan

Evaluated 2026-11-26 against branch `alves-factory` at `d2db409`. Sources: the five `alves-factory-*` skills, `docs/factory/`, the 23 factory commits from `30efc8b` onward, the live config shape in `~/.factory/projects.json` (no secrets read), the local run work dirs in `~/.factory/runs/` and `~/.factory/triage/`, read-only queries of the Alves Linear team through `linear.py`, and `gh pr view` on the two factory PRs. Vendor capabilities are cited to official docs. Where a capability belongs to T3 Code, the only source is the T3 tool schemas available in this session (`schedule_task`, `watch_pull_request`), since I found no public T3 docs.

Paths are relative to `C:\Users\MichaelAlves\.agents` unless they start with `~/.factory`.

---

## 1. How the factory works today

### Stages

| Stage | Trigger | Skill | Ends in |
|---|---|---|---|
| Triage | Jira "Issue assigned" automation sends a web request to T3 Task C (`docs/factory/t3-wiring.md:57-97`) | `alves-factory-triage` | **work**: it calls `alves-factory-run` in the same thread. **unsure**: a Factory ticket is created in Backlog with a triage comment. **not work**: nothing is written (`skills/alves-factory-triage/SKILL.md:29-33`) |
| Planning run | Factory ticket enters **Ready** (Task A), or triage | `alves-factory-run` | Plan Approved, Needs Human or Blocked (`skills/alves-factory-run/SKILL.md:7,62`) |
| Plan | step 4 of the run | `alves-factory-plan` | `PLAN.md` + `ASSUMPTIONS.md`, or a blocked-form Plan containing Blockers (`skills/alves-factory-plan/SKILL.md:28,43`) |
| Council round | step 5 of the run | `alves-factory-review` | three lens reviews (requirements, architecture, testing-risk) on configured seats, run in parallel through T3 `delegate_task` (`skills/alves-factory-review/SKILL.md:29-41`) |
| Gate | end of each round | `gate.py` | implement / revise / escalate, decided only by the script (`skills/alves-factory-review/scripts/gate.py:193-292`). Implement needs an average of at least 90, a lowest score of at least 85, a spread of at most 10 and every reviewer voting approve. Escalate fires when the average is below 75, when any Blocker or escalate-tier Risk flag exists, or at the revision cap of 2 (`skills/alves-factory-review/assets/default-policy.json`) |
| Implementation run | ticket enters **Plan Approved** (Task B). The planning run sets this status itself, so an `implement` gate chains straight into implementation with no human step | `alves-factory-implement` | Team Review, In Review or Blocked (`skills/alves-factory-implement/SKILL.md:7`) |
| Ready check | end of the implementation run | `ready.py` | promote only when all seven conditions hold (`skills/alves-factory-implement/references/ready-check.md:5-13`) |
| Promotion | ticket moves In Review → Team Review (Task D) | `alves-factory-implement --promote` | PR marked ready, plus the Upstream comment (`skills/alves-factory-implement/SKILL.md:71-80`) |

### Statuses and records
- Linear statuses and who sets each one: `skills/alves-factory-run/references/linear-record.md:17-33`. The run claims a ticket by checking its status and then setting a new one (`skills/alves-factory-run/SKILL.md:34-41`, `skills/alves-factory-implement/SKILL.md:42`).
- The Factory ticket is the only durable record (ADR `docs/factory/adr/0001-factory-tracker-is-the-record.md:3`). It holds the Plan and Assumptions documents, one `gate:` label, and comments marked `[alves-factory]` (`linear-record.md:11-13,39`). Every comment without the marker counts as an owner answer (`linear-record.md:91`).
- The Upstream tracker is read at the start of planning. It gets one write: the concluding comment, posted only when the PR is promoted (`skills/alves-factory-run/references/trackers.md:3`, `skills/alves-factory-implement/references/upstream-comment.md:3`). Jira is reached through `acli` (`trackers.md:11,16`), GitHub Issues through `gh`, and Native tickets live in Linear itself.
- Local scratch lives in `~/.factory/runs/<ref>/` (`skills/alves-factory-run/SKILL.md:30`).

### Human touchpoints
1. Wiring each project once: a T3 task and a Linear webhook for each of A, B and D, a Jira automation rule for C, and the status ids (`t3-wiring.md:55,88-113`).
2. **Unsure** triage: the owner moves the ticket to Ready or Canceled (`linear-record.md:86`).
3. **Needs Human**: the owner answers in a comment, then moves the ticket to Ready to re-plan or to Plan Approved to implement as is (`linear-record.md:71-72`).
4. **In Review**: the PR stayed a draft, and the owner promotes it by moving the ticket to Team Review (`SKILL.md:65`).
5. **Blocked**, or a run that crashed: the owner moves the ticket back by hand (`linear-record.md:35`).
6. **Done**: set by the owner after the merge (`linear-record.md:31`).
7. Everything after the PR (review comments, CI on later pushes, the merge) is outside the factory.

### Track record so far (local work dirs + Linear + GitHub)
| Ticket | Rounds → decision (score) | Outcome |
|---|---|---|
| ALV-9 (Native) | revise 91.3 → revise 86.4 → implement 94.4 | Linear: In Review |
| PCS-6132 / ALV-13 | revise 88.7 → implement 93.1 | PR fullsteam-pcs/agilekit#59 **merged**, approved with no changes requested; Linear still **In Review** |
| PCS-6117 / ALV-14 | revise 93.4 → implement 96.1 | PR #60 **merged**, approved with no changes requested; ready check said draft (6 screenshots missing, red `build-storybook`); Linear still **In Review** |
| PCS-6113 / ALV-15 | in progress | Plan Review at the time of writing |
| PCS-6137 | triage wrote **work** (`~/.factory/triage/PCS-6137/triage.md`) | **no Factory ticket and no run dir exists**: the work was dropped silently |

Every planning run that finished took 2–3 rounds, and every one ended `implement`. Both PRs that reached the team merged on the first review. The core loop works. The weak points are the edges around it.

---

## 2. Evaluation

### Strengths
- **Decisions are deterministic where it matters.** `gate.py` and `ready.py` are pure functions with exit-code contracts (`gate.py:12-13`, `ready.py:13-14`), and they are tested: 22 + 40 + 14 = 76 unit tests, all passing (run during this evaluation with `python -m unittest`). LLM reviewers judge the Plan, and the script decides. ADR 0002 makes the same separation for promotion (`docs/factory/adr/0002-draft-until-proven-safe.md:9`).
- **Its defaults fail safe.** Unknown Risk flags escalate (`gate.py:96-99`). An invalid review escalates the whole round (`gate.py:248-249`). Off-seat reviews escalate (`gate.py:250-252`). A PR is a draft unless every condition holds. Upstream content is treated as untrusted in every brief.
- **The vocabulary and docs are good.** The glossary, the ADRs and the lens mandates carry an "_Avoid_" discipline, the commit history explains why each change was made, and the fixes after each dry run were encoded into the skills (e.g. `fbd4e35`, `4e67593`, `ef15fc8`, `da831aa`).
- **It handles multiple accounts carefully.** Each command uses an explicit `GH_TOKEN` and never calls `gh auth switch` (`skills/alves-factory-run/references/config.md:105-111`). The `acli` site is checked but never switched (`trackers.md:16`). The Council config is snapshotted per run (`config.md:91`).
- **The Council finds real defects.** Across the real rounds it raised 5 major requirements issues, 5 major testing issues and 4 major feasibility issues: for example, contradictory stale-revision tests in ALV-9 round 1, and in PCS-6132 round 0 a missing named export that would fail the whole suite (`~/.factory/runs/*/round-*/decision.json`).

### Weaknesses, gaps and risks

**W1. A duplicate trigger can wipe a live run's work dir.** Step 1 empties `~/.factory/runs/<ref>/` (`skills/alves-factory-run/SKILL.md:30`). Step 2, which checks whether another run owns the ticket, comes after it (`SKILL.md:37`). A second planning run for the same ref (the owner re-moving the ticket to Ready, or a Linear redelivery outside the 120 s coalesce window, `t3-wiring.md:31`) deletes the live run's `PLAN.md` and `round-*` files before it discovers it should exit. The implementation run writes into the same dir's `implementation/` (`skills/alves-factory-implement/SKILL.md:40`), so a re-plan also destroys the local implementation evidence. Triage has the same shape (`skills/alves-factory-triage/SKILL.md:25`).

**W2. A crashed or dropped run is never noticed.** A crash leaves the ticket in Planning, Plan Review or In Progress, and only the owner can recover it (`linear-record.md:35`). Nothing detects a stuck ticket. Triggers are lost in several ways. Linear retries a delivery only 3 times (after 1 min, 1 h and 6 h) and may then disable the webhook ([Linear webhooks](https://linear.app/developers/webhooks)). The Jira trigger is an unsigned web request whose retry behaviour I could not verify. The runner is the owner's workstation (`t3-wiring.md:21`). PCS-6137 is a real case: triage decided **work**, but no Factory ticket exists in Linear and no run dir exists.

**W3. Nothing closes the loop after the PR.** Nothing moves a merged PR's ticket to Done, captures the review outcome, handles review comments, or reacts to CI on a later push. Evidence: PRs #59 and #60 both merged, yet ALV-13 and ALV-14 are still In Review in Linear. The factory therefore cannot learn whether its Plans and PRs were good: the Plan score "is not the probability that it succeeds" (`docs/factory/GLOSSARY.md:58`), and nothing calibrates it against outcomes.

**W4. The diff is never reviewed independently.** The `software-factory` design calls for three brakes, including "a separate run that reads the diff cold" (`skills/software-factory/SKILL.md:56-60`). The Council reviews the Plan only. After implementation, the orchestrator checks the subagent's diff itself (`skills/alves-factory-implement/SKILL.md:52-55`). In PCS-6117 the subagent dispatch failed ("subagent dispatch unavailable (tool schema error); both tasks implemented directly in-session", `~/.factory/runs/PCS-6117/implementation/verification.json`), so one agent wrote and reviewed every line. That fallback was recorded as a Plan "deviation", and deviations never block the ready check (`ready-check.md:15`). This conflicts with ADR 0002's own rejection of an agent grading its own work (`adr/0002:9`).

**W5. Runs keep re-deriving deterministic glue.** Several helper scripts were written fresh inside work dirs: `~/.factory/runs/PCS-6132/prepare_ticket.py` (turning Atlassian Document Format into `ticket.md`), `PCS-6132/summarize_round.py` (rendering the round summary), `PCS-6117/implementation/extract.py` and `extract2.py` (pulling `decision.json` back out of a Linear comment with a regex, writing `{}` when the regex finds nothing), and `fixenc.py` (stripping a UTF-8 BOM that PowerShell's `>` added to `checks.json`). Each one is model time, a chance for variance, and code that was never tested. The BOM problem is real: `ready.py:34`, `gate.py:55,104,121` and `council.py:40` read JSON as `utf-8`, and Python's `json.loads` raises `Unexpected UTF-8 BOM` on such input (verified locally).

**W6. The red-baseline rules contradict each other, and a broken base costs every run.** `skills/alves-factory-implement/SKILL.md:52` says "a red baseline stops the run Blocked". `ready-check.md:13,24-25` and ADR 0002 (`adr/0002:3`) instead define a check that "already failed on the base branch". Both real AgileKit runs continued despite a red `build-storybook` baseline (`~/.factory/runs/PCS-6117/implementation/verification.json`, `PCS-6132/implementation/factory-comment.txt`). Because the base is broken, every Storybook PR in AgileKit stays a draft and loses its screenshots (PCS-6117: 6 screenshots missing). The planner is read-only and runs no build (`skills/alves-factory-plan/SKILL.md:12`), so the Council approved Evidence blocks that could not be captured.

**W7. The Team Review status does not exist yet, so the promotion path is untested and some failures are half-done.** `t3-wiring.md:108` says Team Review is "not created yet", and Task D cannot be wired without it. On a `pr_ready: auto` project (DXPX is configured that way in `~/.factory/projects.json`), the ready branch of step 8 runs `gh pr ready`, then posts the Upstream comment, and only then sets Team Review (`SKILL.md:64`). `linear.py` raises when a status is missing (`skills/alves-factory-run/scripts/linear.py:123-124`), so that failure comes after the two irreversible external writes. In practice the owner promoted #59 and #60 on GitHub by hand, outside the factory's path.

**W8. Re-planning after a PR exists can reuse stale commits.** Retries "continue from" an existing `factory/<ref>` branch and count a task as done when a commit with `task <N>` exists (`skills/alves-factory-implement/SKILL.md:36,50`). Nothing ties those commits to a Plan revision or base commit. Once the owner re-plans (Ready), task N of the new Plan may be skipped because task N of the old Plan has a commit.

**W9. Jira through `acli` is a machine-wide single point of failure.** It holds one site for the whole machine (`trackers.md:16`, `t3-wiring.md:120`), and the configured projects span two sites (fullsteam for PCS; gridxissues for DXPX, RTP and AI, in `~/.factory/projects.json`). Only one of those sites can run at a time. Editing a comment on retry assumes `acli` returns a comment id, but in PCS-6132 "acli returned no separate comment id" (`~/.factory/runs/PCS-6132/implementation/factory-comment.txt`). Locally, `acli jira workitem comment create --help` offers only `--edit-last` ("Edit the last comment from the same author"). The factory posts as the owner, so that flag could edit the owner's own hand-written comment.

**W10. The owner cannot see what is running, what it costs or how often it succeeds.** The only views are Linear comments, T3 threads and the local work dirs. No run ledger exists, and no durations, token or cost figures, success rates or ready-check failure reasons are aggregated. The Council can re-dispatch reviewers (`skills/alves-factory-review/SKILL.md:43`) and run up to 3 rounds × 3 seats, with no budget cap anywhere. The only cost control is a stderr warning when a seat would bill OpenCode credits (`skills/alves-factory-run/scripts/council.py:119-128`).

**W11. The scripts are tested; the orchestration is not.** Every fix after launch was in the prose and orchestration layer, and no unit test could have caught any of them:
- an owner answer arriving without its question, and Linear rendering raw `<details>` (`4e67593`);
- an optional harness feature treated as fatal (`ef15fc8`);
- commitlint rejecting the commit headers (`da831aa`);
- tickets filed outside the project (`25d6aad`).

The `--dry-run` modes exist (`skills/alves-factory-run/SKILL.md:13`, `skills/alves-factory-implement/SKILL.md:16`), but no replay suite or invariant checker uses them. `linear.py` makes one HTTP attempt with no retry (`linear.py:64-80`), while Linear rate-limits API keys to 2,500 requests per hour with `429` and `Retry-After` ([Linear rate limiting](https://linear.app/developers/rate-limiting)). Any transient error therefore ends a run Blocked.

**W12. Several limits are enforced only by prompt text.** "Pushes only to its own two branches, never force-pushes, never merges" (`skills/alves-factory-implement/SKILL.md:21`) and "reviewers are read-only" (`skills/alves-factory-review/SKILL.md:21`) are instructions, not controls. The runner holds the owner's gh accounts, the Linear personal key and the `acli` session, and reads text from tickets anyone in a client's Jira can write. Implementation runs execute the client repos' install and build scripts on the owner's workstation. Other risks:
- The Jira trigger token is generated with `Get-Random` (`t3-wiring.md:85`), which Microsoft says "doesn't ensure cryptographically secure randomness" ([Get-Random](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/get-random)).
- `~/.factory/` is shared with another tool's files (`auth.v2.keyring`, `logs/droid-log-single.log`, `sessions/`, `crons/`), so the factory's config and runs live in a directory it does not own.

**W13. Parallel runs would collide.** Evidence servers use fixed ports from the Plan (e.g. `--port 6007`, `skills/alves-factory-plan/references/plan-format.md:61`). Two implementation runs in the same repo would fight over the port, and both would use the same per-ref work-dir layout.

**W14. The docs have drifted from reality.** `t3-wiring.md:113` says AgileKit is "configured, not wired", yet PCS tickets have been triaged, planned and shipped.

---

## 3. Recommended improvements (ranked by value / effort)

| # | Proposal | Effort | Fixes |
|---|---|---|---|
| 1 | Claim before you clean; per-run work dirs | S | W1, W13 |
| 2 | Ship the glue as tested scripts | S–M | W5, W7 |
| 3 | Reconciler: a scheduled sweeper for stuck, dropped and merged work | M | W2, W3 |
| 4 | Independent diff review before promotion | M | W4 |
| 5 | Post-PR loop: merge → Done, review feedback → fix run | M–L | W3 |
| 6 | Run ledger, metrics and a status page | M | W10, W3 |
| 7 | Base-health probe during planning | M | W6 |
| 8 | Preflight the Linear workflow; reorder irreversible writes | S | W7 |
| 9 | Plan-revision-aware branches | S | W8 |
| 10 | Replace `acli` with a per-site Jira REST client | M | W9 |
| 11 | Enforce the guardrails in hooks and token scope | S–M | W12 |
| 12 | Replay/eval harness on the existing dry-run modes | M–L | W11 |
| 13 | Per-repo lessons store fed to planner and Council | M | W6, W3 |
| 14 | Retries and backoff in `linear.py` | S | W11 |
| 15 | Cost budgets per run | M (after #6) | W10 |

### 1. Claim before you clean; per-run work dirs (S)
- **Problem:** W1 and W13.
- **Build:**
  - In `skills/alves-factory-run/SKILL.md`, move "empty the work dir" after step 2's claim. Better still, give each run its own dir: `~/.factory/runs/<ref>/<run-id>/`, with a `latest` pointer the implementation run follows.
  - The implementation run writes to `<ref>/impl-<run-id>/`.
  - Do the same in triage (`skills/alves-factory-triage/SKILL.md:25`).
  - Have the evidence step choose a free port and pass it to the Start command, or fall back to the Plan's port when the command hard-codes one.
- **Payoff:** removes a data-loss race, keeps the history of earlier rounds for the ledger (#6), and makes parallel runs safe.

### 2. Ship the glue as tested scripts (S–M)
- **Problem:** W5. Every run spends model time rewriting the same four helpers, and the regex extraction of `decision.json` can silently produce `{}`.
- **Build:**
  - `skills/alves-factory-run/scripts/ticket.py`: Jira or GitHub JSON, or a Linear issue, rendered to `ticket.md` per `trackers.md:22-58`, with Atlassian Document Format rendering and owner-answer pairing (the `4e67593` rule) under test.
  - `skills/alves-factory-review/scripts/summary.py`: `decision.json` + reviews rendered to `summary.md`, so the owner-facing table is deterministic.
  - Publish `decision.json` as a third Linear document (`linear.py put-doc --title Decision`), and add `get-doc` for it in step 3 of `alves-factory-implement` instead of parsing comments.
  - Read every JSON input as `utf-8-sig` in `gate.py`, `ready.py`, `council.py` and `linear.py`.
- **Payoff:** cheaper, more repeatable runs, and every helper covered by the existing unittest pattern.

### 3. Reconciler: a scheduled sweeper for stuck, dropped and merged work (M)
- **Problem:** W2 and W3. PCS-6137 was lost silently. ALV-13 and ALV-14 stay In Review after their merges. Crash recovery is manual.
- **Build:** a new skill, `alves-factory-sweep`, plus a `sweep.py` with the deterministic parts, run by a T3 scheduled task on an interval. The T3 `schedule_task` schema accepts `{type:'interval', everyMs}` with a 60 s minimum, and `fixed_time` (T3 tool schema). On each pass:
  - Find Linear tickets in Planning, Plan Review or In Progress whose last factory comment is older than N hours. Mark them Blocked with "run appears to have died", or re-trigger them once.
  - Find Jira tickets assigned to the owner in configured projects (JQL) that have no Factory ticket and no `not work` record. Re-run triage on them. This requires triage to persist its `not-work` decisions, e.g. in a `~/.factory/triage/<ref>/triage.md` ledger, so the sweeper does not re-triage them forever.
  - Find tickets in Ready or Plan Approved whose status change has had no run for more than N minutes, and start one.
  - Find factory PRs (`gh pr list --search "head:factory/"` with each project's account). On merge, set Done and record the outcome. On close without merge, set Canceled and record it.
  - Also consider T3's `maxDeliveryAgeMinutes` webhook option, to skip stale deliveries a sleeping laptop replays (T3 tool schema).
- **Payoff:** stops silent drops, makes recovery automatic, and records the PR outcomes that #6 and #13 depend on. Repo webhooks cannot replace polling here: creating one needs owner or admin access to the repo ([GitHub: creating webhooks](https://docs.github.com/en/webhooks/using-webhooks/creating-webhooks)), and the factory works in repos it does not own (ADR 0001).

### 4. Independent diff review before promotion (M)
- **Problem:** W4. Nothing reviews the code cold, and a failed subagent dispatch silently becomes self-review.
- **Build:**
  - After step 6 of `alves-factory-implement`, run a one-round **diff Council**: reuse the seats and `delegate_task` dispatch from `alves-factory-review`, with a code-review brief (the repo already has the `code-review` and `ce-code-review` skills), the Plan, the ticket and `git diff base..branch`.
  - Write its verdict to `implementation/diff-review.json`, and add a ready-check condition: "independent diff review found no major issue" (`ready.py` + `ready-check.md`, with tests).
  - Record harness fallbacks, such as subagents being unavailable, as `process_deviations`, separate from Plan deviations, and make any of them keep the PR a draft.
  - Major findings get one fix pass, then Blocked, mirroring the CI-fix cap.
- **Payoff:** adds the missing second brake, catches what CI does not (scope creep, unrequested changes, quality), and makes `pr_ready: auto` trustworthy enough to turn on for more projects.

### 5. Post-PR loop: merge → Done, review feedback → fix run (M–L)
- **Problem:** W3. Once the PR is ready, the factory is blind to it.
- **Build:**
  - Have the sweeper (#3) detect new review comments or `CHANGES_REQUESTED` on factory PRs, using `GET /repos/{owner}/{repo}/pulls/{n}/comments` and replying with `POST .../comments/{id}/replies` ([GitHub REST: PR review comments](https://docs.github.com/en/rest/pulls/comments)). On a hit, set a new **Changes Requested** status, which starts a run of `ce-resolve-pr-feedback` (already in the repo) scoped to the factory branch.
  - Because these are client repos, default to drafting the fixes and replies and posting them for the owner's approval on the Factory ticket. A per-project `feedback: auto` switch can mirror `pr_ready`.
  - Alternative: T3's `watch_pull_request` wakes a thread "on failed checks, passed required checks, new comments or reviews, conflicts, and once on merge or close" (T3 tool schema). That avoids polling, but it keeps one thread alive per PR, which bends the "a run never waits" rule (`skills/software-factory/SKILL.md:19`).
  - Recommendation: polling in #3 as the source of truth, with `watch_pull_request` as an optional accelerator.
- **Payoff:** the factory follows a ticket to its merge instead of stopping at the PR, and review feedback becomes training data for #13.

### 6. Run ledger, metrics and a status page (M)
- **Problem:** W10.
- **Build:**
  - Append one JSON line per stage transition to `~/.factory/ledger.jsonl` from `linear.py` (wrap `set-state` and `comment`). Fields: ticket, ref, project, stage, status from and to, timestamp, revision, plan score, gate rule, ready reasons, CI fix count, PR number. Add final outcome and time-to-merge from #3.
  - Add `stats.py` to compute per project and per week: tickets triaged, by decision; rounds per Plan; the distribution of gate rules; escalation rate; ready-check pass rate and its top failing reasons; Blocked rate by step; merge rate; and median times.
  - Publish it as a dashboard artifact, or post a weekly summary comment on a pinned Linear issue.
  - **Cost:** if T3 exposes per-thread usage, record it. Claude Code headless runs return `total_cost_usd` with `--output-format json` ([Claude Code headless](https://code.claude.com/docs/en/headless)). That covers the eval harness (#12), not T3 threads (see Open questions).
- **Payoff:** the owner sees what is running, what fails and why, and can tune the gate's 90/85/10 thresholds from data rather than guesswork.

### 7. Base-health probe during planning (M)
- **Problem:** W6. A broken base is found only at implementation, after the Council approved screenshots that cannot be captured.
- **Build:**
  - Fix the contradiction first: change `skills/alves-factory-implement/SKILL.md:52` to say a baseline failure is recorded and allowed, matching `ready-check.md`, or make it Blocked and drop the `baseline: fail` path. Either way, pick one rule.
  - Then let the planning run (not the planner, which stays read-only) run the repo's check commands once in its T3 worktree. Write `base-health.json` into `ticket.md`'s context, so the planner and the Council know that `build-storybook` is red before they approve an Evidence block.
  - When the base is red, have the run file a Native Factory ticket, "Base broken: `<command>`", once per repo, deduplicated by command, so the recurring cost becomes one fix.
- **Payoff:** fewer guaranteed-draft PRs in AgileKit, honest Evidence blocks, and one cause fixed instead of being paid for on every run.

### 8. Preflight the Linear workflow; reorder irreversible writes (S)
- **Problem:** W7.
- **Build:**
  - Add `linear.py preflight --team Alves`, which checks that every status named in `linear-record.md:17-33` exists and prints their ids. Run it in step 1 of every run, so a missing status stops the run before any write.
  - In step 8 of `alves-factory-implement`, set Team Review first, then `gh pr ready`, then post the Upstream comment, so a failure leaves nothing visible to the team.
  - Create Team Review and wire Task D (`t3-wiring.md:108`).
- **Payoff:** `pr_ready: auto` on DXPX cannot half-promote a PR, and owner promotion goes through the factory again instead of through GitHub by hand.

### 9. Plan-revision-aware branches (S)
- **Problem:** W8.
- **Build:**
  - Add a `Factory-Plan: <revision>@<sha256 of PLAN.md>` trailer to every task commit (`skills/alves-factory-implement/SKILL.md:28-36`).
  - On retry, count a task as done only when its commit carries the current Plan's trailer.
  - When an existing branch belongs to a different Plan or base, Block with "re-planned since the branch was cut; delete or rename `factory/<ref>`". Never force-push.
- **Payoff:** a re-plan can no longer ship old commits under a new Plan.

### 10. Replace `acli` with a per-site Jira REST client (M)
- **Problem:** W9.
- **Build:**
  - Add `skills/alves-factory-run/scripts/jira.py`, in the same shape as `linear.py`: `view`, `comments`, `comment-create` (returns the id), `comment-update`, and `search` for #3.
  - Authenticate with an email and an API token per site, read from `~/.factory/.env` (for example `JIRA_<SITE>_TOKEN`), using basic auth ([Atlassian basic auth](https://developer.atlassian.com/cloud/jira/platform/basic-auth-for-rest-apis/)).
  - Inject the transport so it can be tested like `test_linear.py`.
- **Payoff:** both Jira sites can run at the same time, comment ids are reliable (no `--edit-last` risk), and the sweeper gets JQL.

### 11. Enforce the guardrails in hooks and token scope (S–M)
- **Problem:** W12.
- **Build:**
  - Add a Claude Code `PreToolUse` hook (the repo's `git-guardrails-claude-code` skill sets one up) that denies, with exit code 2 ([Claude Code hooks](https://code.claude.com/docs/en/hooks)):
    - `git push` to refs other than `factory/*`;
    - `--force`, `-f` and `+refspec`;
    - `gh pr merge`, `gh auth switch`, `acli jira auth switch` and `gh repo delete`.
  - Where an org allows it, give each project a fine-grained token limited to that repo with contents and pull-request permissions ([GitHub fine-grained PATs](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)). Note GitHub's limits: org owners may require approval for such tokens, and they cannot be used where the user is an outside collaborator.
  - Regenerate the Jira token with `Get-SecureRandom` or `python -c "import secrets; print(secrets.token_hex(20))"`.
  - Move factory state to `~/.alves-factory/`.
- **Caveat:** I could not verify that T3's `claudeAgent` connection loads `~/.claude/settings.json` hooks, or how it sandboxes Codex and OpenCode reviewers. Test it with one deliberately blocked command.
- **Payoff:** a prompt-injected ticket can no longer reach a force-push or a merge, whatever the model does.

### 12. Replay/eval harness on the existing dry-run modes (M–L)
- **Problem:** W11. Regressions in the orchestration layer reach live runs first.
- **Build:**
  - Freeze the real runs (ALV-9 and PCS-6117, -6132 and -6113) as fixtures: `ticket.md`, the repo at the base commit, and the expected invariants.
  - Add `evals/run.py`, which calls `claude -p "/alves-factory-run --dry-run --pasted <fixture>" --output-format json` for headless runs with cost per run ([Claude Code headless](https://code.claude.com/docs/en/headless)).
  - Assert invariants on `record/`:
    - one final status;
    - every round has a `decision.json`;
    - an escalation comment exists whenever the decision is escalate;
    - no write happens outside the work dir;
    - the Plan frontmatter parses;
    - every Requirements row quotes `ticket.md`.
  - Use an eval Council file with Claude-only seats whose ids match the subagent dispatch, since outside T3 the review uses the harness's subagents (`skills/alves-factory-review/SKILL.md:37`).
  - Run it before merging any skill change.
- **Payoff:** skill edits like `fbd4e35` can be checked before they reach a client's ticket, with a cost number for each change.

### 13. Per-repo lessons store fed to planner and Council (M)
- **Problem:** repo-specific facts keep resurfacing as Council Issues or failed runs, for example:
  - the red base and Storybook index (`PCS-6117/round-0`, `PCS-6132/round-0`);
  - builds writing into the tracked `packages/ui/public`;
  - `.eslintignore` patterns;
  - the commitlint convention (`da831aa`).
- **Build:**
  - Keep `~/.factory/knowledge/<repo-slug>.md`, appended by the run when a major Issue is fixed in revision, when a deviation is recorded, when a CI fix is needed, or when #5 sees review feedback.
  - Have the planner (`alves-factory-plan/SKILL.md` step 1) and the reviewer brief read it as **untrusted context**.
  - Prune it with a monthly sweep.
- **Payoff:** fewer revise rounds (every real run needed at least one), which means lower cost and latency.

### 14. Retries and backoff in `linear.py` (S)
- **Problem:** W11. One transient error marks a run Blocked.
- **Build:** retry reads on `URLError`, `5xx` and `429`, honouring `Retry-After` ([Linear rate limiting](https://linear.app/developers/rate-limiting)). For `commentCreate`, retry only when the read-back finds no comment with the same body. Add tests with the fake transport.
- **Payoff:** fewer Blocked runs that the owner has to restart by hand.

### 15. Cost budgets per run (M, after #6)
- **Problem:** W10. Nothing caps spend: up to 3 rounds × 3 seats plus re-dispatches, implementation, and CI-fix loops.
- **Build:** once #6 records cost, add `max_cost_usd` per stage to the policy file. The run checks it between rounds and tasks and escalates with "budget reached" instead of continuing. For the headless eval harness, `--max-budget-usd` exists ([Claude Code headless](https://code.claude.com/docs/en/headless)).
- **Payoff:** spend stays predictable as the throttle opens. This depends on T3 exposing usage (see Open questions).

Not recommended now:
- **More parallel throughput.** T3 already runs each trigger in its own worktree thread. The real limits are W1, W9 and W13, which #1 and #10 fix.
- **Auto-merge.** The factory works in repos it does not own (ADR 0001), and ADR 0002 deliberately keeps humans on the merge.

---

## 4. Quick wins (under an hour each)
1. Read JSON as `utf-8-sig` in `ready.py:34`, `gate.py:55,104,121`, `council.py:40` and `linear.py:297`, with one BOM test each. This removes the need for the `fixenc.py`-style workaround.
2. Swap the order in `skills/alves-factory-run/SKILL.md:30-41`: claim the ticket in step 2 before emptying the work dir. Do the same in triage.
3. Create the **Team Review** status, record its id in `t3-wiring.md:108`, and wire Task D for AgileKit.
4. Reorder step 8's ready branch in `skills/alves-factory-implement/SKILL.md:64`: set the status, then `gh pr ready`, then post the Upstream comment.
5. Resolve the red-baseline contradiction (`SKILL.md:52` vs `ready-check.md:13`) in one sentence.
6. Regenerate the Jira trigger token with `Get-SecureRandom`, and fix `t3-wiring.md:85`.
7. Move ALV-13 and ALV-14 to Done, and decide what happens to PCS-6137 (re-run triage).
8. Update `t3-wiring.md:113` to say what is actually wired.
9. Publish `decision.json` as a Linear document at each round, and read it back in implementation step 3 instead of regex-parsing comments.
10. Make the ready check fail on a recorded harness fallback. For now, a reason line when a `deviations` entry contains "subagent" is a crude stopgap until #4 adds `process_deviations`.

---

## 5. Open questions for the owner
1. **Cost visibility in T3.** Does T3 expose token or cost usage per thread and per `delegate_task` delegate? If not, cost budgets (#15) need a different source.
2. **Hooks under T3.** Does T3's `claudeAgent` connection load `~/.claude/settings.json` hooks and permissions? Are Codex and OpenCode delegates sandboxed read-only, or only told to be? This decides whether #11 is enforceable.
3. **PCS-6137.** Triage wrote **work**, but no Factory ticket or run exists. Did the chained planning run fail before claiming, or was the thread stopped? The T3 thread will show which.
4. **Promotion of #59 and #60.** Both were promoted outside the factory, presumably by hand on GitHub, since Team Review does not exist yet. Was the PCS-6117 Upstream comment ever posted?
5. **Red-baseline policy.** Should a check that already fails on the base branch block promotion forever (the current ADR 0002 wording), or count as non-blocking when it fails identically before and after?
6. **Autonomy on review feedback.** In client repos, may the factory push fixes and reply to team reviewers on its own, or must the owner approve each reply (#5)?
7. **`pr_ready` across Metronome.** DXPX is `auto`, while RTP and AI, apparently the same repo, are draft. Is that intended?
8. **`~/.factory`.** Is the directory deliberately shared with the other tool whose files live there (`auth.v2.keyring`, `droid-log-single.log`)?
9. **Runner uptime.** Does the T3 runner machine sleep? Is `maxDeliveryAgeMinutes` set on the tasks, and does Jira Automation retry a failed "Send web request"? I could not verify the last one.
10. **Success metric.** What should the factory optimise: merge rate, time to merge, owner minutes per ticket, or cost per merged PR? The answer decides what #6 measures first.
