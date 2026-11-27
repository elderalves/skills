# An approved Discovered ticket is filed upstream before planning

**Discovery** files improvements the factory found as **Discovered tickets** in the Factory tracker's Backlog, where they have no Upstream ticket. The owner approves one by moving it to Ready. On a project with an Upstream tracker, the planning run that claims it first files its Upstream ticket, then plans as for any other ticket: the branch, the Upstream link, triage's duplicate check, the sweep and the concluding comment all key on an Upstream ticket, so filing first keeps every later stage unchanged. This amends ADR 0001: the Upstream tracker now also receives a ticket the owner approved, and nothing the owner has not.

The Upstream ticket is written in the owner's voice (problem, why, acceptance criteria) with one line saying automated analysis found it, and carries no factory internals: no Factory URL, label or score. So filing is made idempotent from the factory's own record. Before creating, the run posts a factory comment naming the exact title and time; it creates the ticket **unassigned**, attaches the Upstream link, and only then assigns it to the owner. A restarted run looks for a ticket the owner reported with that title since that time before creating one, and the owner's Jira "assigned" rule fires only once the link exists, so triage finds the Factory ticket and exits. A failed filing ends the run Blocked. A canceled Factory ticket leaves its Upstream ticket for the owner to tidy.

## Considered Options

- Filing only at promotion, so the team never sees work that ends Blocked: rejected because every stage before it would have to run without an upstream ref.
- A separate sync task with a "Syncing Upstream" status: rejected because it adds a trigger and a status for one step the planning run can take after its claim.
- The Factory URL, or an opaque `af-` label, on the Upstream ticket as the deduplication key: rejected because the owner wants nothing of the factory on the team's tracker, and GitHub labels need rights the factory may not have.
- Filing every Discovered ticket upstream as it is found: rejected because the team's tracker would fill with work nobody approved.
