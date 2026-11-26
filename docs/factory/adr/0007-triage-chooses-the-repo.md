# Triage chooses the repo when one Upstream prefix feeds several

A ticket key's prefix used to name exactly one repo: `projects.json` matched `RTP-` to one checkout, and every stage resolved the repo from the ref alone. GridX's `RTP` Jira project holds work for at least eight repos (empower-widgets, explore-frontend, advise-frontend, metronome and more), and nothing on the ticket says which: none of the 4,585 `RTP` tickets updated in the last 60 days had a component, labels are not used for it, and summary prefixes ("Exelon - Explore - …") are inconsistent. With one repo per prefix, triage could only call an Explore ticket "not work" for Empower and drop it.

So several `projects.json` entries may share one `match`, each with a distinct `linear_project`. **Triage** searches every candidate repo's `origin/<base_branch>` for what the ticket names and files the Factory ticket in the chosen entry's Linear project; a ticket that spans repos goes to the owner as **unsure**, because one Factory ticket covers one repo. From then on the **Factory ticket's Linear project names the repo**: planning, implementation, the Council resolver and the sweep resolve the entry from the upstream ref *and* that Linear project, and `project.py --ref` alone refuses to guess between shared entries. Moving a Factory ticket to another Linear project moves its work to that repo.

Triage no longer plans inline: it files a **work** ticket in Backlog and moves it to Ready, so the chosen repo's own planning trigger plans it in a worktree of that repo. Triage and the sweep belong to the prefix, not to a repo, so they live in a T3 project of their own (`alves-factory`, no worktree), and each repo keeps its own planning and implementation tasks, filtered by its Linear project.

## Considered Options

- Point the prefix at its busiest repo: what Empower did first. Rejected as the end state because every other repo's tickets are silently dropped.
- Route on a Jira field (component or label): rejected because the field is unused on this board and the factory cannot make the team fill it.
- One entry with a `repos` list: rejected because repos differ in what each entry already carries (`base_branch`, `github_account`, `pr_ready`, Council), and a repo then looks the same in config whether it shares a prefix or not.
- One Factory ticket per touched repo for cross-repo work: rejected because it breaks "each Upstream ticket has exactly one Factory ticket", and both runs would report on the same Upstream ticket.

## Consequences

- A repo added to a shared prefix needs its own Linear project and its own planning and implementation tasks; until then its tickets are triaged **not work**, naming the repo, so the owner sees what to add.
- A prefix with one entry behaves as before, except that its Factory tickets must sit in its `linear_project`.
