# Resolving ambiguity without the owner

Adapted from the facts-versus-decisions split in Matt Pocock's `grilling`: an agent finds facts itself and puts decisions to the human. Here the human is absent, so reversible decisions move to the agent and only material ones wait for the owner.

Every open question the ticket leaves falls in exactly one class:

| Class | Test | Resolution |
|---|---|---|
| **Fact** | The answer exists somewhere you can look: the repo, its history, its docs, a dependency's docs, the ticket's comments. | Investigate until answered. Cite where you found it. A fact you could not find becomes a reversible decision or a Blocker, never a guess stated as fact. |
| **Reversible decision** | A choice an engineer on the team would make without asking, that a later PR could change without migrating data, breaking a contract or changing what users already rely on. | Choose the most conservative option that matches the repo's existing patterns, and record it in `ASSUMPTIONS.md`. |
| **Material decision** | A choice that decides what the user sees or can do, what the business accepts, or what is expensive to undo, and that the ticket does not settle. | Record it as a **Blocker**. Never decide it. |

Owner answers in `ticket.md` settle the questions they answer; follow them even where you would have chosen differently.

## Scope

How much work the ticket asks for is a question like any other, and the same classes settle it:

- **Leaving out optional work** the ticket does not require (wiring a new module into the app, a follow-up refactor) is a **reversible decision**: list it under **Out of scope** with the reason, and in `ASSUMPTIONS.md`.
- **Adding work** the ticket does not ask for is invented scope: leave it out, or justify it with ticket text or the parent ticket's stated decisions.
- **A Blocker** is a product choice the ticket cannot be called done without, never a question of how much to build.
- **The parent ticket** is context only: it explains why the work exists and which decisions to respect, and its scope is not this ticket's scope.

## Examples

- Which test framework, where the new file goes, what a private function is called: **reversible**, follow the repo.
- Whether a retry helper already exists: **fact**.
- Whether a failed export shows an error or silently retries: **material**, it decides what the user sees.
- Whether to add a nullable column or a new table for an optional field: **reversible** while nothing reads it yet; **material** if it migrates existing data (and a `data-migration` Risk flag either way).
- What error message copy to show, when the ticket gives none and the product has a style guide: **reversible**, follow the guide; with no guide and user-facing copy: **material**.
- The ticket's acceptance criteria contradict each other: **material**.

## Writing them down

**`ASSUMPTIONS.md`**: one entry per reversible decision:

```markdown
## <the decision, as a short statement>
- **Chose:** <option>
- **Over:** <the alternatives considered>
- **Because:** <the repo pattern or evidence behind it>
- **To reverse:** <what a later change would do>
```

**Blocker**: one entry per material decision, in `PLAN.md`'s frontmatter `blockers` list:

- `question`: answerable by the owner in one reply; offer the options you see and your recommendation, the way `grilling` frames a question.
- `why_owner`: why investigation cannot settle it.
- `evidence`: the ticket text or code that raises it.
