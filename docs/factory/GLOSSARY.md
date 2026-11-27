# Software Factory

A personal factory of agents that plans, reviews and implements work assigned to its owner in any project, keeping its own record apart from that project's tracking. It extends the vocabulary of the `software-factory` skill (Task, Trigger, Run, Runner, Orchestrator) and uses those terms with the same meaning.

## Trackers and tickets

**Factory tracker**:
The ticket tracker the factory's owner controls, where the factory keeps its record of every piece of work and where the owner talks to its agents. It is always the same tracker, whichever project the work comes from.
_Avoid_: my tracker, internal tracker, ticket source

**Factory ticket**:
The ticket in the Factory tracker that holds the factory's record of one piece of work: its plan, reviews, decisions and outcome.
_Avoid_: mirror ticket, shadow ticket, internal ticket

**Upstream tracker**:
The project's own ticket tracker, which the factory does not control and touches only to read the work, to file a Discovered ticket the owner approved, and to report its conclusion.
_Avoid_: real tracker, client tracker, ticket source, source tracker

**Upstream ticket**:
The ticket in an Upstream tracker that describes the work to be done. Each Upstream ticket has exactly one Factory ticket.
_Avoid_: original ticket, source ticket, Jira ticket

**Native ticket**:
A Factory ticket that is also the work's Upstream ticket, for a project with no Upstream tracker of its own: the owner, or Discovery, files the work directly in the Factory tracker.
_Avoid_: internal ticket, Linear-only ticket, self-ticket

## Discovery

**Discovery**:
A scheduled pass over one repo, through one Lens, that looks for improvements worth doing and files each as a Discovered ticket for the owner to approve or reject. A pass that files nothing has succeeded.
_Avoid_: improvement engine, scan, audit

**Discovered ticket**:
A Factory ticket that Discovery filed in Backlog, before any Upstream ticket exists. Once the owner moves it to Ready it is an ordinary Factory ticket, and the factory files its Upstream ticket when the project has an Upstream tracker; once the owner cancels it, it stays as the record that Discovery must not propose it again.
_Avoid_: proposal, suggestion, finding, improvement ticket

**Lens**:
The one engineering angle a Discovery pass looks through, such as testing or accessibility, taken in turn from the repo's list.
_Avoid_: category, focus, perspective

**Value score**:
How worth doing a Discovered ticket is, from 0 to 100, shown as High, Medium or Low. It measures the improvement, never the Plan, and leaves Effort out.
_Avoid_: priority, confidence, impact score, IVS

**Effort**:
The size of a Discovered ticket's work (S, M or L), shown beside its Value score so the owner can pick by both.
_Avoid_: cost, estimate, complexity

**Quick win**:
A Discovered ticket of High Value score and S Effort.
_Avoid_: low-hanging fruit, easy win

## Plans and review

**Triage**:
The factory's first look at an Upstream ticket assigned to the owner: deciding, before any planning, whether it holds implementation work for a configured repo and, when the ticket's Upstream tracker feeds several repos, which one, from evidence in each repo. Once Triage has chosen, the Factory ticket's project carries that choice for every later stage.
_Avoid_: screening, intake, routing (alone)

**Triage decision**:
The outcome of Triage: Work (planning starts), Unsure (the Factory ticket waits in Backlog for the owner) or Not work (nothing is recorded).
_Avoid_: verdict, classification

**Plan**:
The factory's proposal for how to carry out one Upstream ticket, revised until a Gate decision lets it be implemented or escalated.
_Avoid_: spec, design, proposal

**Plan review**:
One reviewer's evaluation of one revision of a Plan, scoring each rubric criterion against evidence and naming its Blockers and Issues.
_Avoid_: council review, vote

**Council**:
The set of independent reviewers who each produce a Plan review of the same revision in one round.
_Avoid_: panel, review board

**Council seat**:
The T3 connection and exact model configured to review one lens of a Council. Every review must come from its lens's seat; one model may hold several seats.
_Avoid_: reviewer target, provider slot

**Model floor**:
The minimum number of distinct models a Council round must include (`min_models`), counting one model reached through two connections once. Off by default, so the configured seats decide diversity.
_Avoid_: provider diversity, single-provider policy

**Plan score**:
The weighted rubric result computed from a round's Plan reviews. It measures how well grounded and complete a Plan is, not the probability that it succeeds.
_Avoid_: confidence, confidence score

**Blocker**:
A material product or business question in a Plan that only the factory's owner can answer.
_Avoid_: open question, unknown

**Issue**:
A defect in a Plan that the planner can fix without the owner's input.
_Avoid_: finding, comment, nit

**Risk flag**:
A declared property of a Plan, such as a data migration or an auth change, that raises the bar the Plan must clear. An **escalate** flag sends the Plan to the owner before any code; a **strict** flag lets it pass on its own only when every reviewer approves and every risk score reaches the strict bar.
_Avoid_: high risk, danger

**Gate decision**:
The outcome of a Council round under the factory's policy: Implement, Revise or Escalate.
_Avoid_: verdict, approval, routing

**Escalation**:
A Gate decision that hands a Plan to the owner, with its Blockers, to answer on the Factory ticket.
_Avoid_: human review, handoff

## Implementation

**Evidence block**:
The section of a Plan that names how to serve the app locally and which pages to screenshot before and after the change. Only a Plan that changes what a user sees has one.
_Avoid_: screenshot plan, visual spec

**Evidence branch**:
The orphan branch, beside the factory branch in the project repo, that holds an implementation run's before/after screenshots so the PR body can show them.
_Avoid_: assets branch, screenshot branch

**Ready check**:
The scripted test, at the end of an implementation run, of whether the factory may promote its draft PR on its own: every condition must hold, and any failure keeps the draft for the owner.
_Avoid_: safety check, auto-approve

**Diff review**:
The Council's independent reading of a finished branch's diff, before its PR opens, by the same three seats that reviewed the Plan. Only a clean diff review lets the ready check promote a PR; major findings get one fix pass and otherwise keep it a draft.
_Avoid_: code review (the project team's), self-review, second Council round

**Process deviation**:
A time the harness forced an implementation run off its own process, such as a task written in-session because its subagent could not start. Unlike a deviation from the Plan, any process deviation keeps the PR a draft.
_Avoid_: fallback, deviation (alone)

**Promotion**:
Marking the factory's draft PR ready for review by the project team, either by the ready check on a project that allows it or by the owner moving the Factory ticket to Team Review.
_Avoid_: publishing, undrafting, approval

## Operations

**Sweep**:
A scheduled pass over the factory's record that catches what the event triggers missed: it restarts a run that died, starts a run whose trigger never fired, closes the Factory ticket of a merged PR, and repairs each repo's Account pin. It acts only on statuses, times and PR states, and starts at most one run per pass.
_Avoid_: cron, reconciler, janitor

**Account pin**:
A repo's own git config naming the GitHub account every plain `git` command in it uses, written by `github_account.py --pin` and kept by the sweep. It lets T3 prepare a worktree before any skill runs, when gh's active account cannot reach the repo.
_Avoid_: credential override, account switch

**Stale limit**:
How long a ticket may sit in a running status (Planning, Plan Review, In Progress) with no factory comment before the sweep judges its run dead and restarts it, once.
_Avoid_: timeout, TTL

**Trigger owner**:
The one Runner whose scheduled tasks receive a project's triggers: its webhooks point there and its sweep runs there. Any Runner may be able to run a project, but each project has exactly one Trigger owner at a time, so no ticket is acted on twice.
_Avoid_: main machine, factory machine, the runner (alone)
