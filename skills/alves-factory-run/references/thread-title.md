# Thread title

Every factory task starts its threads with the same name (`factory: sweep (RTP-)`, `factory: plan`), so a run renames its own thread to say which ticket it worked on and how it ended. That is the only way the owner can tell runs apart in T3's sidebar. The title is cosmetic: the Factory ticket stays the record.

## Who renames

Only the skill that the scheduled prompt names renames the thread. The prompt says so in its "A Linear webhook / Jira automation / schedule started this run" line. So:

- A run started by hand (`/alves-factory-run RTP-412` in the owner's own thread) leaves the title alone.
- A skill that another skill invokes leaves it alone: the triage the sweep starts, and the plan and review stages of a planning run. The skill that invoked it owns the title.

## How

Call `t3_thread_update` with `action: "rename"` and `title`, and no `threadId`, so it renames the current thread. When the tool is missing or the call fails, skip it and say nothing about it. A failed rename is not a Process deviation and never changes the run's result or its final reply.

Rename twice:

1. **Start**, as soon as the run knows its ticket: `<stage> <ref> …`. When a run dies, its title stays at this stage, which shows which run died.
2. **End**, on every way the run ends, including an exit with no writes: `<stage> <ref> → <outcome>`.

`<ref>` is the Upstream ref (`RTP-412`), or the Factory ticket identifier for a Native ticket. Until the run has resolved it, use the argument it was given. A dry run adds ` (dry run)` at the end.

## Titles

| Stage | Start | End outcomes |
|---|---|---|
| Planning (`alves-factory-run`) | `plan RTP-412 …` | `Plan Approved`, `Needs Human`, `Blocked`, `skipped` (exit with no writes) |
| Implementation (`alves-factory-implement`) | `implement RTP-412 …` | `PR #57 ready`, `PR #57 draft`, `Blocked`, `skipped` |
| Promotion (`--promote`) | `promote RTP-412 …` | `PR #57 ready`, `back to In Review`, `skipped` |
| Triage (`alves-factory-triage`) | `triage RTP-412 …` | `Work`, `Unsure`, `Not work`, `skipped` (a Factory ticket already exists), `failed` |

The **sweep** runs in one thread per prefix, so its title shows the latest pass and its start time (the runner's local time, 24-hour clock):

- Start: `sweep RTP- · 14:30 …`
- End: `sweep RTP- · 14:30 · <summary>`, where the summary names the triage it started and counts every other action by kind: `triaged RTP-412 → Work · restarted 1 · closed 2`. `closed` counts `done` actions, and `pinned`, `retriggered`, `blocked` and `noted` count the rest. A pass with no action and no triage is `quiet`, a dry run is `dry run`, and a failed pass is `failed`.
- Keep the title under about 60 characters. When it is longer, drop the counts before the triage.

When a sweep covers several matches, `<prefix>` lists them joined by `+` (`PCS-+linear-project:Gerador de Escala` is long, so use `Gerador de Escala` for a `linear-project:` match).
