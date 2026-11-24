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
The project's own ticket tracker, which the factory does not control and touches only to read the work and to report its conclusion.
_Avoid_: real tracker, client tracker, ticket source, source tracker

**Upstream ticket**:
The ticket in an Upstream tracker that describes the work to be done. Each Upstream ticket has exactly one Factory ticket.
_Avoid_: original ticket, source ticket, Jira ticket

**Native ticket**:
A Factory ticket that is also the work's Upstream ticket, for a project with no Upstream tracker of its own: the owner files the work directly in the Factory tracker.
_Avoid_: internal ticket, Linear-only ticket, self-ticket

## Plans and review

**Plan**:
The factory's proposal for how to carry out one Upstream ticket, revised until a Gate decision lets it be implemented or escalated.
_Avoid_: spec, design, proposal

**Plan review**:
One reviewer's evaluation of one revision of a Plan, scoring each rubric criterion against evidence and naming its Blockers and Issues.
_Avoid_: council review, vote

**Council**:
The set of independent reviewers who each produce a Plan review of the same revision in one round.
_Avoid_: panel, review board

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
A declared property of a Plan, such as a data migration or an auth change, that makes the work unsafe to implement without the owner.
_Avoid_: high risk, danger

**Gate decision**:
The outcome of a Council round under the factory's policy: Implement, Revise or Escalate.
_Avoid_: verdict, approval, routing

**Escalation**:
A Gate decision that hands a Plan to the owner, with its Blockers, to answer on the Factory ticket.
_Avoid_: human review, handoff
