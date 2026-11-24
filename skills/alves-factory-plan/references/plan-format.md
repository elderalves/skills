# Factory Plan format

A factory Plan is a `writing-plans` plan with factory frontmatter, a factory header, three extra sections and a revision log. Where this file and `writing-plans` disagree, this file wins.

## Overrides to `writing-plans`

- **Save to** `<work-dir>/PLAN.md`, never `docs/superpowers/plans/`.
- **Skip Execution Handoff.** No one reviews the Plan in this session and no execution method is chosen: the Council judges it and `alves-factory-implement` executes it.
- **Replace the header's "For agentic workers" line** with the one below; the plan names no `superpowers:` sub-skill.
- **Spec** in the header is `ticket.md`: the Plan argues from the Upstream ticket.

## Frontmatter and header

```markdown
---
ticket: PROJ-123
revision: 0
risk_flags: []
blockers: []
---

# [Feature Name] Implementation Plan

> **For agentic workers:** implement with `alves-factory-implement`, task by task, test first. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [one sentence]

**Architecture:** [2-3 sentences]

**Tech Stack:** [key technologies]

**Spec:** `ticket.md` (Upstream ticket PROJ-123)
```

- `ticket`: the Upstream ticket key.
- `revision`: `0` for the first Plan; each Revise increments it.
- `risk_flags`: policy flag ids the work carries (`data-migration`, `auth`, `public-contract`, `infrastructure`, `large-change`, `dependency`).
- `blockers`: each `{question, why_owner, evidence}`, per [ambiguity.md](ambiguity.md). Empty in a Plan ready for the Council.

## Sections

In this order: the `writing-plans` header, **Global Constraints** and **Review Focus**, then:

1. **Requirements**: a table mapping every requirement and acceptance criterion in `ticket.md` to the task(s) that deliver it, quoting the ticket's words.

   | Requirement (from ticket.md) | Task(s) |
   |---|---|
   | "Export retries up to 3 times" | 2, 3 |

2. **Approach**: the chosen approach in a paragraph, the alternatives considered and why each lost, or one line saying the change has one obvious shape.
3. The `writing-plans` **tasks**.
4. **Risks and rollback**: what could go wrong in production, how each risk is detected, and how the change is undone. A change that cannot be undone by a revert says what else it takes.
5. **Out of scope**: work a reader might expect that this Plan deliberately leaves out, each with a reason.
6. **Revision log**: absent at revision 0; each Revise appends one line per Issue: `r<N> · <criterion> · fixed|rebutted · <reason>`.

## Blocked form

When Blockers remain after resolving ambiguity, `PLAN.md` holds only what the owner needs to answer them:

- the frontmatter, with `blockers` filled;
- the header's **Goal** line;
- **Context**: what you established in Discover, briefly, so the owner sees the questions in the light of the repo;
- **Approach**: the approach you would take, and how each Blocker's answer would change it.

No tasks: they wait for the answers. A Blocker found during a Revise keeps the existing tasks and adds the blockers to the frontmatter.
