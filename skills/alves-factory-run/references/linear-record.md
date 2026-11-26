# The factory's record on Linear

The Factory ticket on Linear is the factory's only durable record (ADR `docs/factory/adr/0001` in the skills repo): every run rebuilds its state from it. All reads and writes go through [`scripts/linear.py`](../scripts/linear.py); shared by `alves-factory-run`, `alves-factory-implement` and `alves-factory-triage`.

## The Factory ticket

- **Title:** `<upstream-ref>: <upstream title>`.
- **Native tickets** are filed by the owner, so the factory leaves their title and description alone and adds no Upstream link; the rest of this record applies to them unchanged.
- **Upstream link:** one attachment whose URL is the Upstream ticket's URL and whose title is the **upstream ref** (`PROJ-123`, `github:acme/widgets#12`, or `pasted:<slug>`). The URL is the deduplication key.
- **Reading the upstream ref back.** The owner may file a Factory ticket by hand and attach the Upstream URL, and Linear then titles the attachment itself, so derive the ref from each attachment's **URL**: `https://<site>/browse/<KEY>` gives `<KEY>`, `https://github.com/<owner>/<repo>/issues/<n>` gives `github:<owner>/<repo>#<n>`, `https://factory.invalid/pasted/<stem>` gives `pasted:<stem>`. The Upstream link is the attachment whose derived ref a `projects.json` entry matches; other attachments (designs, docs) are context.
- **Description:** the Upstream link and the project name, nothing else. The record lives in documents and comments.
- **Documents:** `Plan` (the current `PLAN.md`) and `Assumptions` (the current `ASSUMPTIONS.md`), updated in place on every revision.
- **Label:** one `gate:` label, the latest Gate decision: `gate:implement`, `gate:revise` or `gate:escalate`.

## Statuses

The team's statuses, by exact name, and who sets each:

| Status | Set by | Meaning |
|---|---|---|
| Backlog | owner, or triage | not ready for the factory; triage parks an **unsure** ticket here |
| **Ready** | owner | trigger: start (or restart) a planning run |
| Planning | planning run | the planner owns the ticket |
| Plan Review | planning run | a Council round is running |
| Needs Human | planning run | Escalation: the owner's answer is needed |
| **Plan Approved** | planning run, or owner | trigger: start an implementation run |
| In Progress | implementation run | the implementer owns the ticket |
| In Review | implementation run, or promotion run | the draft PR is open, waiting on the owner; the last factory comment says why it stayed a draft |
| **Team Review** | implementation run, or owner | the PR is ready for the project team; entered from In Review (the owner's move), it triggers a promotion run |
| Blocked | either run, or the sweep | the run failed; the last factory comment says where and why |
| Done | the sweep, or owner | the factory PR merged |
| Canceled | owner | dropped |
| Duplicate | either run | a second Factory ticket for the same Upstream ticket |

**Ownership:** a run that finds its ticket in Planning, Plan Review or In Progress exits without acting: another run owns it. A run that crashed leaves its status behind. The **sweep** (`alves-factory-sweep`) finds it once no factory comment has come for the stale limit, and moves it back to Ready (or Plan Approved) to start a new run; a ticket that stalls again right after that restart goes to Blocked, and the owner moves it back by hand. The sweep's comments are factory comments whose heading starts `## Sweep:`.

## Comments

Every factory comment starts with the `[alves-factory]` marker, which `linear.py comment` adds. Every other comment is the owner's.

**Round comment**, one per Council round:

````markdown
[alves-factory]

## Council round <N>: <decision>

<the round's summary.md>

**Raw decision**

```json
<the round's decision.json>
```
````

Linear renders no HTML, so the raw decision is a plain fenced block, never a `<details>` wrapper.

**Escalation comment**: what the owner must decide, then how to resume:

```markdown
[alves-factory]

## Needs your decision

❓ **Q1**: <Blocker question, with the options and the factory's recommendation>
   _Why only you:_ <why_owner> · _Evidence:_ <evidence>

<for an Escalation without Blockers: the rule that fired and its reasons, e.g. each Risk flag>

**To continue:** reply here, then move the ticket to **Ready** to re-plan with your answers,
or move it to **Plan Approved** to implement the current Plan as it stands.
```

**Blocked comment**: the step that failed, the exact error, and what would unblock it.

**Triage comment**, on a ticket triage parked in Backlog:

```markdown
[alves-factory]

## Triage: unsure

<the reason, citing the ticket text and the repo evidence on each side>

**To continue:** move the ticket to **Ready** to plan it, or to **Canceled** if it holds no work for this repo.
```

## Owner answers

Every comment without the marker is an **owner answer**. A planning run copies all of them, oldest first, into `ticket.md`'s **Owner answers** section ([trackers.md](trackers.md)); they settle the questions they answer.

An answer that follows an escalation comment usually points into it ("Q1: follow your recommendation"), so copy each one under the escalation comment it answers (the latest one posted before it), quoting that comment's **Needs your decision** questions verbatim. The planner then sees the question, the options, the recommendation and the answer together, and settles the question with the option the owner chose.
