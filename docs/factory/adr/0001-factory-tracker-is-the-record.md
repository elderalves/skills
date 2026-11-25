# The Factory tracker is the factory's record

Every plan, review, decision and escalation lives on the Factory ticket in the owner's Linear, never in the project's repo or Upstream tracker. Runners are disposable and the factory works in projects it does not own, so each run rebuilds its state from the Factory ticket, and a project receives only the implementation (a draft PR) plus one concluding comment on its Upstream ticket.

## Considered Options

- Committing `.factory/<ticket>/` artifacts to a branch in the project repo: rejected because client repos would carry factory internals and audit trails would be split across many repos.
- A separate artifacts repo owned by the factory's owner: rejected for v1 because the Factory tracker already gives the owner a human interface, triggers and history in one place.
