# Triage criteria

A ticket is **work** when it asks for a change that one PR to the matched repo can deliver: code, tests, configuration or docs in that repo. The test is the deliverable, not the wording: "investigate why the chart flickers" is work when its natural outcome is a fix in this repo, and not work when its outcome is a written answer.

| Decision | When |
|---|---|
| **work** | The ticket names a change in this repo, and the repo evidence confirms the change is still needed (the code it touches exists, the behaviour it asks for is absent). |
| **not work** | The evidence clearly shows one of the cases below. |
| **unsure** | Anything else: it may belong to another repo, it bundles repo work with work elsewhere, or the evidence points both ways. |

**Not work**, each needing evidence:

- the deliverable is not a change: a question, a review, a meeting, a decision, an estimate, an investigation that ends in a written answer;
- the change belongs to another repo: the components, services or files it names are absent here and present in a repo it names;
- the change already exists on `origin/<base_branch>`: cite the commit or the code;
- the Upstream ticket is closed (Done, Resolved, Won't Do, or its tracker's equivalent);
- the ticket is a container (an epic, or a ticket whose work lives in its subtasks): the subtasks are triaged when they are assigned.

## Leaning

The costs are uneven. A wrong **work** costs one planning run whose record the owner sees on Linear; a wrong **not work** drops the ticket silently. So choose **not work** only on clear evidence, and **unsure** whenever you would have to guess. A ticket too vague to plan is still **work** when it plainly concerns this repo: planning turns its open questions into Blockers for the owner.
