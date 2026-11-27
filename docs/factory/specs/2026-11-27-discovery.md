# Discovery: the factory proposes its own work

Settled in a grilling session on 2026-11-27 (Q1–Q22), from a ChatGPT discussion of a "continuous improvement" loop. Terms are in [the glossary](../GLOSSARY.md) (Discovery, Discovered ticket, Lens, Value score, Effort, Quick win); the one hard-to-reverse decision is [ADR 0009](../adr/0009-approved-discovered-tickets-are-filed-upstream.md).

## The loop

1. **Discovery** runs daily per repo and files the best few improvements it finds as **Discovered tickets** in Backlog.
2. The owner **approves** one by moving it to Ready, **rejects** it by moving it to Canceled (an optional comment is the reason), or leaves it in Backlog (not now).
3. On Ready, the planning run claims it, **files its Upstream ticket** (projects with an Upstream tracker), and plans it like any other ticket. Native projects skip filing.
4. From then on nothing differs: same Council, gate, ready check, `pr_ready`, promotion and sweep.

## Discovery pass

- **Where:** T3 task F, "factory: discover", daily, one per repo (`projects.json` entry), on that repo's Trigger owner, in the repo's T3 project, new worktree from `base_branch`. New thread each run.
- **Opt-in:** a `discovery` object on the entry. An entry with an Upstream tracker (`jira`, `github`) and no `upstream.file` cannot run Discovery: config error. When several entries share a Linear project, exactly one of them may carry `discovery`.
- **No state:** following the rule that runners keep no state between runs (ADR 0006), the Lens is `lenses[date.toordinal() % len(lenses)]`; the change set is the base branch's commits of the last 24 hours. A missed day skips that Lens.
- **Lenses (default):** architecture, testing, performance, ux-accessibility, security, maintainability, developer-experience.
- **Room:** `room = max(0, min(max_new, max_open - discovered tickets in Backlog))`, defaults `max_new` 3, `max_open` 10. Room 0 ends the pass before any search. Filing nothing is success.
- **Candidates:** at most 5 (`max_candidates`), each with repo evidence (paths, lines, command output), problem, why it matters, acceptance criteria.
- **Not again:** each candidate is compared against **every** Factory ticket in the repo's Linear project, in every status, with the owner's comments. It names the closest one and why it differs, or is dropped. A Done match is dropped unless the candidate shows evidence of a regression. A Canceled match is dropped; the owner's comment there says what kind of work not to propose.
- **Not already tracked upstream:** a keyword search of the Upstream tracker's **open** tickets (Jira: `upstream.file.project_key`; GitHub: the repo's issues). A match drops the candidate and the reply names it.
- **Scoring:** one independent scorer per candidate, never the Discovery agent's model. Seat: `discovery.scorer`, else the entry's resolved Council `testing-risk` seat; the same model (by `model_identity`) as the Discovery agent is a config error. The scorer sees the candidate and its evidence, never the Discovery agent's opinion of its worth.
- **Rubric (policy file):** each criterion 0–10; weights impact 30, engineering 25, reach 15, evidence 15, urgency 15; Value score = Σ weight × score / 10, rounded. Bands: High ≥ 70, Medium 50–69, Low 30–49; below 30 is not filed. Effort is the scorer's: S under half a day, M up to two days, L more; it never lowers the Value score.
- **Filing:** the top `room` candidates by Value score, as Factory tickets in Backlog in the entry's Linear project, label `discovered` (plus `quick-win` for High + S), Linear priority from the band (High → High, Medium → Medium, Low → Low; never Urgent), title without a ref, write-up in the description.
- **Writes:** Linear only. Discovery may build, lint and test in its worktree, and never commits, pushes or writes upstream.

## Discovered ticket description

The public part comes first and ends at a `## Factory notes` heading; everything from that heading on stays in Linear.

- Public: `## Problem`, `## Why it matters`, `## Acceptance criteria`.
- Factory notes: Lens, Evidence, Value score with its breakdown, Effort, closest existing ticket and why this differs.

The owner may edit it before approving; the filed ticket carries the edited public part.

## Filing upstream (ADR 0009)

On a claimed Discovered ticket with no Upstream link:

1. If no `## Filing upstream` factory comment exists, post one naming the exact title and the time.
2. Search upstream for a ticket the owner reported with that comment's title, created at or after its time. If one exists, use it.
3. Otherwise create it **unassigned**: summary = the title, body = the public part plus `_Found by automated analysis._`, as plain text on Jira and as Markdown on GitHub. Jira: `upstream.file.project_key`, `issue_type` (default `Task`), `labels` (default none). GitHub: the entry's repo.
4. Rename the Factory ticket `<ref>: <title>`, then attach the Upstream link (later stages key on the link, so it goes on only after the rename).
5. Assign the Upstream ticket to the owner (Jira's "assigned" rule then runs triage, which finds the Factory ticket and exits).
6. Post a `## Filed upstream` factory comment on the Factory ticket naming the Upstream ticket.

No Factory URL, factory label or score goes upstream. A failure ends the run Blocked. If the owner later cancels the Factory ticket, the factory leaves the Upstream ticket alone.

## Deferred

Automatic weight tuning from approval rates, semantic search across a whole tracker, a Deferred-until-date status. Revisit after 30–50 decided Discovered tickets.
